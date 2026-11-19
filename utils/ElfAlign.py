#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ElfAlign -- ELF PT_LOAD 16 KB page size 对齐修补工具（纯标准库）。

背景: Android 15/16/17 的 16 KB page size 设备要求可执行文件的所有 PT_LOAD
满足 ``p_align >= 0x4000`` 且 ``p_offset % 0x4000 == p_vaddr % 0x4000``。
预编译的 .so 壳库只有二进制，无法重新编译，只能在文件里插入填充并同步改写
偏移字段。

设计原则
--------
* 只改「位置」，不改「内容」：不修改 e_entry / p_vaddr / p_paddr / memsz /
  filesz / .dynamic，任何段与节的内容字节保持原样，仅为对齐插入 0x00。
* 插入点选在某个 PT_LOAD 的 p_offset 处，则该段及其后所有段整体后移。
* 同步 e_shoff 与所有实体节（sh_type != SHT_NOBITS）的 sh_offset。
* 幂等: 已对齐的文件再跑一次不会产生任何改动。

API
---
PAGE_4K / PAGE_16K
parse_elf(data) -> dict
check_alignment(path, page_size=PAGE_16K) -> dict
align_elf(path, page_size=PAGE_16K, dry_run=False) -> dict
align_dir(dirpath, page_size=PAGE_16K) -> list[dict]

CLI
---
python utils/ElfAlign.py check <path_or_dir>...
python utils/ElfAlign.py align <path_or_dir>... [--page-size 16384] [--dry-run]
"""

import argparse
import os
import struct
import sys

PAGE_4K = 0x1000
PAGE_16K = 0x4000

PT_LOAD = 1
SHT_NOBITS = 8

_ELF_MAGIC = b"\x7fELF"

__all__ = [
    "PAGE_4K",
    "PAGE_16K",
    "parse_elf",
    "check_alignment",
    "align_elf",
    "align_dir",
    "PT_LOAD",
    "SHT_NOBITS",
]


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
def _u(fmt, endian, data, off):
    return struct.unpack_from(endian + fmt, data, off)[0]


def parse_elf(data):
    """解析 ELF 头 / 程序头 / 节头。

    返回::

        {'bits':32|64, 'endian':'<'|'>', 'e_shoff':int, 'e_shentsize':int,
         'e_shnum':int,
         'segments':[{'index','type','offset','vaddr','filesz','memsz',
                      'align','phdr_off'}...],
         'sections':[{'index','name_off','type','offset','size','shdr_off'}...]}

    另外附带 'e_phoff' / 'e_phentsize' / 'e_phnum' 便于上层使用。
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("parse_elf() expects bytes")
    if len(data) < 52:
        raise ValueError("file too small to be an ELF")
    if bytes(data[:4]) != _ELF_MAGIC:
        raise ValueError("bad ELF magic")

    ei_class = data[4]
    ei_data = data[5]
    if ei_class == 1:
        bits = 32
    elif ei_class == 2:
        bits = 64
    else:
        raise ValueError("bad EI_CLASS: %r" % (ei_class,))

    if ei_data == 1:
        endian = "<"
    elif ei_data == 2:
        endian = ">"
    else:
        raise ValueError("bad EI_DATA: %r" % (ei_data,))

    if bits == 64:
        if len(data) < 64:
            raise ValueError("truncated ELF64 header")
        e_phoff = _u("Q", endian, data, 0x20)
        e_shoff = _u("Q", endian, data, 0x28)
        e_phentsize = _u("H", endian, data, 0x36)
        e_phnum = _u("H", endian, data, 0x38)
        e_shentsize = _u("H", endian, data, 0x3A)
        e_shnum = _u("H", endian, data, 0x3C)
    else:
        e_phoff = _u("I", endian, data, 0x1C)
        e_shoff = _u("I", endian, data, 0x20)
        e_phentsize = _u("H", endian, data, 0x2A)
        e_phnum = _u("H", endian, data, 0x2C)
        e_shentsize = _u("H", endian, data, 0x2E)
        e_shnum = _u("H", endian, data, 0x30)

    segments = []
    for i in range(e_phnum):
        if not e_phentsize:
            break
        off = e_phoff + i * e_phentsize
        if off + e_phentsize > len(data) or e_phentsize < (56 if bits == 64 else 32):
            break
        p_type = _u("I", endian, data, off)
        phdr_off = off
        if bits == 64:
            p_offset = _u("Q", endian, data, off + 8)
            p_vaddr = _u("Q", endian, data, off + 16)
            p_filesz = _u("Q", endian, data, off + 32)
            p_memsz = _u("Q", endian, data, off + 40)
            p_align = _u("Q", endian, data, off + 48)
        else:
            p_offset = _u("I", endian, data, off + 4)
            p_vaddr = _u("I", endian, data, off + 8)
            p_filesz = _u("I", endian, data, off + 16)
            p_memsz = _u("I", endian, data, off + 20)
            p_align = _u("I", endian, data, off + 28)
        segments.append({
            "index": i,
            "type": p_type,
            "offset": p_offset,
            "vaddr": p_vaddr,
            "filesz": p_filesz,
            "memsz": p_memsz,
            "align": p_align,
            "phdr_off": phdr_off,
        })

    sections = []
    for i in range(e_shnum):
        if not e_shentsize:
            break
        off = e_shoff + i * e_shentsize
        if off + e_shentsize > len(data) or e_shentsize < (64 if bits == 64 else 40):
            break
        sh_name = _u("I", endian, data, off)
        sh_type = _u("I", endian, data, off + 4)
        if bits == 64:
            sh_offset = _u("Q", endian, data, off + 24)
            sh_size = _u("Q", endian, data, off + 32)
        else:
            sh_offset = _u("I", endian, data, off + 16)
            sh_size = _u("I", endian, data, off + 20)
        sections.append({
            "index": i,
            "name_off": sh_name,
            "type": sh_type,
            "offset": sh_offset,
            "size": sh_size,
            "shdr_off": off,
        })

    return {
        "bits": bits,
        "endian": endian,
        "e_shoff": e_shoff,
        "e_shentsize": e_shentsize,
        "e_shnum": e_shnum,
        "e_phoff": e_phoff,
        "e_phentsize": e_phentsize,
        "e_phnum": e_phnum,
        "segments": segments,
        "sections": sections,
    }


# --------------------------------------------------------------------------
# 对齐检查
# --------------------------------------------------------------------------
def _check_bytes(data, page_size=PAGE_16K):
    """对内存中的 ELF 做检查，返回 (ok, issues, loads, bits)."""
    info = parse_elf(data)
    loads = [s for s in info["segments"] if s["type"] == PT_LOAD]
    issues = []
    if not loads:
        issues.append("no PT_LOAD segment found")
    for s in loads:
        if s["align"] < page_size:
            issues.append(
                "LOAD%d: p_align=0x%x < 0x%x" % (s["index"], s["align"], page_size)
            )
        if s["offset"] % page_size != s["vaddr"] % page_size:
            issues.append(
                "LOAD%d: p_offset(0x%x) %% 0x%x != p_vaddr(0x%x) %% 0x%x"
                % (s["index"], s["offset"], page_size, s["vaddr"], page_size)
            )
        if s["offset"] + s["filesz"] > len(data):
            issues.append(
                "LOAD%d: offset+filesz exceeds file size" % (s["index"],)
            )
    return (not issues), issues, loads, info["bits"]


def check_alignment(path, page_size=PAGE_16K):
    """检查单个 ELF 文件是否满足 page_size 对齐要求。

    返回 {'ok':bool, 'bits':.., 'issues':[str,...], 'segments':[...]}
    """
    with open(path, "rb") as f:
        data = f.read()
    ok, issues, loads, bits = _check_bytes(data, page_size)
    return {
        "ok": ok,
        "bits": bits,
        "path": path,
        "page_size": page_size,
        "issues": issues,
        "segments": loads,
    }


# --------------------------------------------------------------------------
# 对齐修补
# --------------------------------------------------------------------------
def align_elf(path, page_size=PAGE_16K, dry_run=False):
    """就地修补单个 ELF 文件，使其 PT_LOAD 满足 page_size 对齐。

    算法（不改 vaddr / 段内容，只插入 0x00 填充并把其后偏移整体后移）:
      1. 按文件顺序遍历 PT_LOAD，计算 pad = (vaddr - cur_offset) % page_size，
         pad ∈ [0, page_size)，通常落在 {0, 0x1000, 0x2000, 0x3000}；
         p_offset == 0 的段 pad 必须为 0（EFI/ELF 头段无法前移）。
      2. 在该段 p_offset 处插入 pad 个 0x00。
      3. 该段及其后所有段 p_offset += 累计 pad；所有 PT_LOAD 的 p_align
         置为 max(原值, page_size)。
      4. e_shoff 与所有实体节 sh_offset 按插入点同步后移。
      5. e_entry / vaddr / p_paddr / memsz / filesz / 段内容 / .dynamic 不动。
    """
    with open(path, "rb") as f:
        data = f.read()
    size_before = len(data)

    info = parse_elf(data)
    bits = info["bits"]
    endian = info["endian"]
    loads = [s for s in info["segments"] if s["type"] == PT_LOAD]
    before = [dict(s) for s in loads]
    errors = []

    # ---- 1. 计算每个段的 pad（按原 p_offset 升序处理） ----
    plan = []            # [(orig_offset, pad)]，与 loads 的 index 对应
    inserts = []         # [(中间缓冲坐标, pad)]，供真实插入使用
    shift = 0
    for s in sorted(loads, key=lambda x: (x["offset"], x["index"])):
        cur = s["offset"] + shift
        if cur == 0:
            pad = 0
        else:
            pad = (s["vaddr"] - cur) % page_size
        plan.append((s["index"], s["offset"], pad))
        if pad:
            inserts.append((cur, pad))
            shift += pad

    pad_total = shift

    # 原文件坐标 -> 位移量的映射：该位置上/之后的内容会被 p_offset<=X 的所有插桩推后
    def shift_at(pos):
        total = 0
        for _idx, orig_off, pad in plan:
            if pad and orig_off <= pos:
                total += pad
        return total

    # ---- 2/3. 重建文件字节（插入填充） ----
    if pad_total:
        buf = bytearray()
        prev = 0
        for pos, pad in sorted(inserts, key=lambda x: x[0]):
            buf += data[prev:pos]
            buf += b"\x00" * pad
            prev = pos
        buf += data[prev:]
    else:
        buf = bytearray(data)

    # ---- 3. 改写程序头 ----
    # 注意：插桩点之后的所有 PT_* 的 p_offset 都必须跟着位移，
    # 不只是 PT_LOAD —— 否则 linker 会比对 PT_DYNAMIC.p_offset 与 .dynamic 节的
    # sh_offset，一旦不一致就直接拒载：
    #   ".dynamic section has invalid offset: 0x369e0, expected to match PT_DYNAMIC offset: 0x359e0"
    phoff = info["e_phoff"]
    phentsize = info["e_phentsize"]
    load_ids = set(s["index"] for s in loads)
    for s in info["segments"]:
        h = phoff + s["index"] * phentsize
        new_off = s["offset"] + shift_at(s["offset"])
        if new_off == s["offset"] and s["index"] not in load_ids:
            continue
        if bits == 64:
            struct.pack_into(endian + "Q", buf, h + 8, new_off)
            if s["index"] in load_ids:
                struct.pack_into(endian + "Q", buf, h + 48,
                                 max(s["align"], page_size))
        else:
            struct.pack_into(endian + "I", buf, h + 4, new_off)
            if s["index"] in load_ids:
                struct.pack_into(endian + "I", buf, h + 28,
                                 max(s["align"], page_size))

    # ---- 4. 改写节头表位置与各节 sh_offset ----
    new_shoff = info["e_shoff"] + shift_at(info["e_shoff"]) if info["e_shoff"] else 0
    if info["e_shoff"]:
        if bits == 64:
            struct.pack_into(endian + "Q", buf, 0x28, new_shoff)
        else:
            struct.pack_into(endian + "I", buf, 0x20, new_shoff)

    shdr_base = new_shoff
    shentsize = info["e_shentsize"]
    for sec in info["sections"]:
        if sec["type"] == SHT_NOBITS:
            continue
        if not sec["offset"]:
            continue
        new_sec_off = sec["offset"] + shift_at(sec["offset"])
        if new_sec_off == sec["offset"]:
            continue
        pos = shdr_base + sec["index"] * shentsize
        if bits == 64:
            struct.pack_into(endian + "Q", buf, pos + 24, new_sec_off)
        else:
            struct.pack_into(endian + "I", buf, pos + 16, new_sec_off)

    size_after = len(buf)

    # ---- 5. 写回 + 复检 ----
    if not dry_run and bytes(buf) != data:
        tmp = path + ".elfalign.tmp"
        with open(tmp, "wb") as f:
            f.write(buf)
        os.replace(tmp, path)

    ok_bytes, issues, after_loads, _ = _check_bytes(bytes(buf), page_size)
    if len(buf) != len(data):
        pass
    errors.extend(issues)

    after = [dict(s) for s in after_loads]
    changed = (not dry_run and bytes(buf) != data) or (dry_run and bytes(buf) != data)

    return {
        "path": path,
        "changed": bool(bytes(buf) != data),
        "applied": bool(not dry_run and bytes(buf) != data),
        "bits": bits,
        "pad": pad_total,
        "before": before,
        "after": after,
        "size_before": size_before,
        "size_after": size_after,
        "ok": ok_bytes,
        "errors": errors,
    }


def align_dir(dirpath, page_size=PAGE_16K):
    """递归对目录下所有 *.so 执行 align_elf，返回结果列表。"""
    results = []
    for root, dirs, files in os.walk(dirpath):
        dirs.sort()
        for name in sorted(files):
            if not name.lower().endswith(".so"):
                continue
            p = os.path.join(root, name)
            try:
                results.append(align_elf(p, page_size=page_size))
            except Exception as exc:  # 单个文件失败不影响其它文件
                results.append({
                    "path": p,
                    "changed": False,
                    "bits": 0,
                    "pad": 0,
                    "before": [],
                    "after": [],
                    "size_before": os.path.getsize(p) if os.path.exists(p) else 0,
                    "size_after": 0,
                    "ok": False,
                    "errors": ["%s: %s" % (type(exc).__name__, exc)],
                })
    return results


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _fmt_seg(s):
    return "LOAD%d off=0x%-6x vaddr=0x%-8x align=0x%-5x filesz=0x%x" % (
        s["index"], s["offset"], s["vaddr"], s["align"], s["filesz"],
    )


def _collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                for name in sorted(files):
                    if name.lower().endswith(".so"):
                        out.append(os.path.join(root, name))
        else:
            out.append(p)
    return out


def _print_check(res):
    state = "OK  " if res["ok"] else "FAIL"
    print("[%s] %s  (ELF%d)" % (state, os.path.abspath(res["path"]), res["bits"]))
    for s in res["segments"]:
        mark = "  " if (s["align"] >= res["page_size"]
                       and s["offset"] % res["page_size"] == s["vaddr"] % res["page_size"]) else "! "
        print("   %s%s" % (mark, _fmt_seg(s)))
    for issue in res["issues"]:
        print("       - %s" % issue)


def _print_align(res):
    state = "OK  " if res["ok"] else "FAIL"
    print("[%s] %s  (ELF%d) changed=%s pad=0x%x size %d -> %d" % (
        state, os.path.abspath(res["path"]), res["bits"],
        "yes" if res["changed"] else "no", res["pad"],
        res["size_before"], res["size_after"]))
    for s in res["before"]:
        print("   before  %s" % _fmt_seg(s))
    for s in res["after"]:
        print("   after   %s" % _fmt_seg(s))
    for err in res["errors"]:
        print("       - %s" % err)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        prog="ElfAlign.py",
        description="ELF PT_LOAD page-size alignment checker / patcher "
                    "(Android 16KB page size).")
    ap.add_argument("action", choices=["check", "align"])
    ap.add_argument("paths", nargs="+", help="ELF file(s) or directory(ies) (*.so)")
    ap.add_argument("--page-size", type=lambda v: int(v, 0), default=PAGE_16K,
                    help="page size in bytes, default 16384 (0x4000)")
    ap.add_argument("--dry-run", action="store_true",
                    help="align only: compute and report, do not write files")
    args = ap.parse_args(argv)

    targets = _collect(args.paths)
    if not targets:
        print("no ELF target found")
        return 1

    failures = 0
    for p in targets:
        try:
            if args.action == "check":
                res = check_alignment(p, page_size=args.page_size)
                _print_check(res)
                if not res["ok"]:
                    failures += 1
            else:
                res = align_elf(p, page_size=args.page_size, dry_run=args.dry_run)
                _print_align(res)
                if args.dry_run and res["changed"]:
                    print("       (dry-run: no bytes written)")
                if not res["ok"]:
                    failures += 1
        except Exception as exc:
            print("[FAIL] %s: %s: %s" % (os.path.abspath(p), type(exc).__name__, exc))
            failures += 1

    print("")
    print("checked %d file(s), %d failure(s)" % (len(targets), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
