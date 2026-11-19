#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
MultiDex —— APK 内 classes*.dex 的编号管理。

原 main.py/CopyDexJniFile 的做法：
    ReSearch = re.search(r'classes(\\d)', DexName)   # classes10.dex 匹配不到
    NewDexFile = classes{NewNum}.dex                 # 直接覆盖已存在的 dex
它会：
  * 用 listdir 顺序决定编号，结果不可预测；
  * 把加密后的 classes.dex 写成 classes2.dex，覆盖 App 原有的 classes2.dex；
  * 原地留下 App 原有未加密的 classes3/classes4.dex，壳运行时解密失败；
  * >9 个 dex 时编号算错。

本模块的做法：
  1. scan() 把 APK 里所有 classes*.dex 按编号排好（classes.dex=0）；
  2. 直接清空旧 dex（新的 dex 集合完全由我方生成，不再原地改名，避免覆盖）；
  3. install_shell() 写壳 dex 到 slot 0（classes.dex）；
  4. install_app_dexes() 把 App 的 dex（加密或不加密）按原顺序写入 slot 1..N。
"""
import os

from . import FsSafe

DEX_HEADER_MAGIC = (b'dex\n035\x00', b'dex\n036\x00', b'dex\n037\x00',
                    b'dex\n038\x00', b'dex\n039\x00', b'dex\n040\x00')


def dex_name(index):
    """slot 0 -> classes.dex, slot 1 -> classes2.dex, ..."""
    if index < 0:
        raise ValueError(f'invalid dex slot: {index}')
    return 'classes.dex' if index == 0 else f'classes{index + 1}.dex'


def parse_dex_name(filename):
    """classes.dex -> 0, classes2.dex -> 1, assets/apkhook/dex/classes2.bin -> 1。

    加密 dex 用 .bin 后缀放在 assets 下（不能是 classesN.dex，否则 ART
    会把密文当真 dex 打开，整包加载失败）。这里统一按 basename 解析。
    """
    name = filename.lower().replace('\\', '/').rsplit('/', 1)[-1]
    suffix = None
    for ext in ('.dex', '.bin'):
        if name.startswith('classes') and name.endswith(ext):
            suffix = ext
            break
    if suffix is None:
        return None
    middle = name[len('classes'):-len(suffix)]
    if middle == '':
        return 0
    if middle.isdigit():
        value = int(middle)
        # classes1.dex 是非法的（等价于 classes.dex），归一化处理
        if value <= 1:
            return 0
        return value - 1
    return None


def scan(apkdir):
    """返回 [(slot, filename)]，按 slot 升序。忽略非 dex 文件与子目录。"""
    found = {}
    for entry in os.listdir(apkdir):
        path = os.path.join(apkdir, entry)
        if not os.path.isfile(path):
            continue
        slot = parse_dex_name(entry)
        if slot is None:
            continue
        found.setdefault(slot, entry)
    return sorted(found.items())


def next_slot(apkdir):
    """下一个可用的 dex slot（用于"追加一个新 dex、不动原有 dex"的模式）。"""
    slots = scan(apkdir)
    return (slots[-1][0] + 1) if slots else 0


def strip_all(apkdir):
    """删除 APK 目录内全部 classes*.dex，返回被删除的 [(slot, filename)]。"""
    removed = []
    for slot, name in scan(apkdir):
        os.remove(os.path.join(apkdir, name))
        removed.append((slot, name))
    return removed


def is_dex(path):
    """检查文件是否是以 dex\\n0xx\\0 开头的合法 dex（防止把加密块当 dex 写进去）。"""
    if not os.path.isfile(path):
        return False
    try:
        head = FsSafe.head(path, 8)
    except OSError:
        return False
    return head in DEX_HEADER_MAGIC


def _place(apkdir, slot, srcpath):
    name = dex_name(slot)
    dst = os.path.join(apkdir, name)
    if FsSafe.copyfile(srcpath, dst) != dst:      # 带退避重试的整文件拷贝
        raise OSError(f'写入 {dst} 失败')
    return name


def install_shell(apkdir, shell_dex_path):
    """把壳 dex 写到 slot 0（classes.dex）。返回写入的文件名。"""
    return _place(apkdir, 0, shell_dex_path)


def install_app_dexes(apkdir, ordered_dex_paths, start_slot=1, allow_encrypted=False):
    """
    把 App 的 dex 依次写到 slot start_slot, start_slot+1, ...

    :param ordered_dex_paths: 已按原 dex 顺序排好的 dex 文件路径
    :param start_slot: 起始 slot（有壳时传 1，无壳时传 0）
    :param allow_encrypted: True 表示这些文件是 AES 加密块，不做 dex 头校验
    :return: [{'slot','name','src'}]
    """
    placed = []
    for offset, src in enumerate(ordered_dex_paths):
        if not allow_encrypted and not is_dex(src):
            raise RuntimeError(f'不是合法 dex 文件: {src}')
        slot = start_slot + offset
        name = _place(apkdir, slot, src)
        placed.append({'slot': slot, 'name': name, 'src': src})
    return placed


def summary(apkdir):
    """返回当前 dex 布局，用于 report.json。"""
    return [{'slot': slot, 'name': name,
             'size': os.path.getsize(os.path.join(apkdir, name))}
            for slot, name in scan(apkdir)]


if __name__ == '__main__':
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else '.'
    for item in summary(target):
        print(item)
