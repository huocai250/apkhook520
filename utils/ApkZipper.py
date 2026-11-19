#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
ApkZipper —— 具备 zipalign 语义的 APK 打包器。

为什么不能直接用 zipfile 全量 ZIP_DEFLATED（原 ZipApkFile 的做法）：

1. Android 11 (API 30) 起，targetSdk >= 30 的 APK 中 `resources.arsc` 必须
   **不压缩（STORED）** 且 **4 字节对齐**，否则安装时报：
   `Targeting R+ (version 30 and above) requires the resources.arsc of installed
    APKs to be stored uncompressed and aligned on a 4-byte boundary`
2. Android 15 (API 35) 起，设备可能使用 16KB 内存页（arm64 16K page size）。
   当 `android:extractNativeLibs="false"` 时，`lib/<abi>/*.so` 必须 **STORED**
   且 **16KB(16384) 对齐**，否则安装/加载失败：
   `Failed to load native library ... not page aligned`
   即使 extractNativeLibs=true，Android 15+ 的 16KB 设备仍要求 .so 的 ELF
   PT_LOAD 段按 16KB 对齐（见 utils/ElfAlign.py）。
3. 旧签名文件（META-INF/*.SF/*.RSA/*.MF）必须剔除，否则 apksigner 报
   `META-INF/xxx.SF` 与 v2/v3 签名冲突。

对齐实现走 zip local header 的 extra field（和 zipalign 一样用 0xD935 这个
"Android zipalign" 私有 extra id），把文件数据起点补齐到目标边界。
"""
import json
import os
import struct
import zipfile

from . import FsSafe

# zipalign 使用的 extra field id（"Android zipalign"）。
ALIGN_EXTRA_ID = 0xD935

DEFAULT_PAGE_ALIGN = 0x4000      # 16KB，Android 15+/16KB page size 设备
ARSC_ALIGN = 0x4                 # resources.arsc 需要 4 字节对齐

# 需要剔除的旧签名文件（大小写不敏感）
_SIG_SUFFIX = ('.sf', '.rsa', '.dsa', '.ec', '.mf')

# 这些后缀按 STORED 写入（本来就不压缩，可避免二次膨胀 + 保持对齐）
_STORED_EXT = ('.arsc', '.so')

# 解包时大小写冲突条目的落盘目录（不会出现在最终 APK 里）
DUP_DIR = '_apkhook_dup'
NAMEMAP_FILE = DUP_DIR + '/namemap.json'


def dup_dir(srcdir):
    return os.path.join(srcdir, DUP_DIR)


def _load_namemap(srcdir):
    """读取 safe_extract 写下的 {磁盘相对路径: APK 内路径} 映射。"""
    path = os.path.join(srcdir, NAMEMAP_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as fp:
            items = json.load(fp)
    except (OSError, ValueError):
        return {}
    out = {}
    for item in items:
        try:
            out[item['disk']] = item['arc']
        except (KeyError, TypeError):
            continue
    return out


def is_signature_entry(arcname):
    """判断是否是旧签名相关条目，必须从 APK 中剔除。"""
    upper = arcname.upper()
    if not upper.startswith('META-INF/'):
        return False
    name = upper.split('/')[-1]
    return name.endswith(_SIG_SUFFIX)


def _sorted_entries(srcdir):
    """遍历目录，返回 [(arcname, fullpath)]，顺序确定（可复现打包）。

    Windows/macOS 的文件系统大小写不敏感，而 APK 里经常有 `res/-B.png` 与
    `res/-b.png` 这种只差大小写的条目（AndResGuard 混淆后的资源名）。直接
    extractall 会让后者覆盖前者，重打包后资源就少了/串了 —— App 一启动就
    崩。所以 `safe_extract` 把冲突项落到 `_apkhook_dup/<序号>/<原路径>`，
    并写一份 namemap.json；这里按映射还原成真正的 APK 内路径。
    """
    namemap = _load_namemap(srcdir)
    result = []
    for root, dirs, files in os.walk(srcdir):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            arc = os.path.relpath(full, srcdir).replace(os.sep, '/')
            if arc == NAMEMAP_FILE:
                continue
            arc = namemap.get(arc, arc)
            if is_signature_entry(arc):
                continue
            result.append((arc, full))

    # 排序策略：resources.arsc 最前（4 对齐最省 padding），AndroidManifest.xml
    # 次之，lib/** 靠前（16KB 对齐在文件头部附近更省空间），其余按名字。
    def key(item):
        arc = item[0]
        if arc == 'resources.arsc':
            return (0, arc)
        if arc == 'AndroidManifest.xml':
            return (1, arc)
        if arc.startswith('lib/'):
            return (2, arc)
        if arc.startswith('classes') and arc.endswith('.dex'):
            return (3, arc)
        return (4, arc)

    result.sort(key=key)
    return result


def _entry_policy(arcname, store_libs=True):
    """返回 (是否 STORED, 对齐字节数或 0)。"""
    lower = arcname.lower()
    if lower == 'resources.arsc':
        return True, ARSC_ALIGN
    if lower.endswith('.so'):
        # .so 对齐到 16KB；是否压缩由 store_libs 决定
        return bool(store_libs), DEFAULT_PAGE_ALIGN
    if lower.endswith(_STORED_EXT):
        return True, 0
    return False, 0


def alignment_extra(current_offset, name, align):
    """
    计算让 (current_offset + 30 + len(name) + len(extra)) % align == 0 的 extra。

    zip local file header 固定 30 字节，随后是文件名，随后是 extra field。
    extra field 必须是 [id(2) size(2) data(size)] 的序列，所以最小 4 字节。
    """
    if not align:
        return b''
    name_len = len(name.encode('utf-8'))
    base = current_offset + 30 + name_len
    # base + 4 + pad ≡ 0 (mod align)
    pad = (-(base + 4)) % align
    return struct.pack('<HH', ALIGN_EXTRA_ID, pad) + b'\x00' * pad


class ApkZipper:
    """把解包目录重新打成 zipalign 过的 APK。"""

    def __init__(self, srcdir, outpath, page_align=DEFAULT_PAGE_ALIGN,
                 store_libs=True, timestamp=(1980, 1, 1, 0, 0, 0), on_entry=None):
        self.SrcDir = os.path.abspath(srcdir)
        self.OutPath = os.path.abspath(outpath)
        self.PageAlign = int(page_align)
        self.StoreLibs = bool(store_libs)
        self.Timestamp = tuple(timestamp)
        self.OnEntry = on_entry

    # ------------------------------------------------------------------ build
    def Build(self, **kwargs):
        """
        打包含 log 的包。返回 report dict。
        :return: {'outpath','entries','stored','aligned','size','skipped_signatures'}
        """
        entries = _sorted_entries(self.SrcDir)
        if not entries:
            raise RuntimeError(f'打包目录为空: {self.SrcDir}')

        out_dir = os.path.dirname(self.OutPath)
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        if os.path.exists(self.OutPath):
            os.remove(self.OutPath)

        report = {
            'outpath': self.OutPath,
            'entries': 0,
            'stored': 0,
            'deflated': 0,
            'aligned': [],
            'skipped_signatures': [],
            'warnings': [],
            'size': 0,
        }

        with zipfile.ZipFile(self.OutPath, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for arcname, full in entries:
                store, align = _entry_policy(arcname, self.StoreLibs)
                if align:
                    # .so 必须按 16KB 对齐；page_align 可被 --page-align 覆盖
                    align = self.PageAlign if arcname.lower().endswith('.so') else align

                zinfo = zipfile.ZipInfo(arcname, date_time=self.Timestamp)
                zinfo.compress_type = zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED
                zinfo.create_system = 0
                # 0755 for .so / dex? APK 内不需要权限位，统一 0644 即可
                zinfo.external_attr = 0o644 << 16

                current = zf.fp.tell()
                zinfo.extra = alignment_extra(current, arcname, align)

                # 读源文件走退避重试：Windows 杀软可能临时锁住刚写好的 .dex
                data = FsSafe.read_bytes(full)
                with zf.open(zinfo, 'w') as dst:
                    dst.write(data)

                data_offset = current + 30 + len(arcname.encode('utf-8')) + len(zinfo.extra)
                if align and data_offset % align:
                    report['warnings'].append(
                        f'{arcname}: 对齐失败 offset={data_offset} align={align}')

                report['entries'] += 1
                report['stored' if store else 'deflated'] += 1
                if align:
                    report['aligned'].append({
                        'name': arcname,
                        'offset': data_offset,
                        'align': align,
                        'aligned': data_offset % align == 0,
                    })
                if self.OnEntry:
                    self.OnEntry(arcname, report['entries'], len(entries))

        report['size'] = os.path.getsize(self.OutPath)
        return report

    # 兼容旧调用名
    def ZipApk(self, **kwargs):
        return self.Build(**kwargs)


def safe_extract(apkpath, destdir):
    """
    安全解包 APK：拒绝 ../ 穿越、绝对路径、盘符条目、被 zip 加密的条目，
    并先跑一遍 CRC 校验。

    恶意 APK 用 `../../` 条目可以把文件写到目录外，所以这里不能直接用
    `ZipFile.extractall`。

    **大小写冲突**：APK 里常见 `res/-B.png` 与 `res/-b.png`（AndResGuard 混淆
    出的资源名），而 Windows/macOS 的文件系统大小写不敏感，直接落盘会互相
    覆盖 —— 重打包后资源条目变少、内容串位，App 一启动就崩。这里的处理是：
    第一个照常落盘，之后冲突的落到 `_apkhook_dup/<序号>/<原路径>`，并写一份
    `_apkhook_dup/namemap.json` 记录「磁盘路径 → APK 内路径」，打包时还原。

    返回 {'files': 解出的文件数, 'collisions': 冲突条目数, 'namemap': [...]}
    """
    destdir = os.path.abspath(destdir)
    dup_root = os.path.join(destdir, DUP_DIR)
    used = {}          # 小写路径 -> 首次落盘的真实路径（仅用于判重）
    collisions = []
    count = 0

    with zipfile.ZipFile(apkpath, 'r') as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f'APK zip 已损坏（CRC 校验失败）: {bad}')
        for info in zf.infolist():
            name = info.filename
            if name.endswith('/'):
                continue
            parts = name.replace('\\', '/').split('/')
            if not name or name.startswith('/') or '..' in parts or (parts and ':' in parts[0]):
                raise RuntimeError(f'APK 内含非法路径条目: {name}')
            if info.flag_bits & 0x1:
                raise RuntimeError(f'APK 条目被 zip 加密，无法处理: {name}')

            key = '/'.join(parts).lower()
            clash = key in used
            if clash:
                # 落到 _apkhook_dup/<序号>/<原路径>，避开大小写不敏感文件系统
                disk_rel = f'{DUP_DIR}/{len(collisions) + 1:04d}/' + '/'.join(parts)
                collisions.append({'disk': disk_rel, 'arc': '/'.join(parts)})
            else:
                used[key] = '/'.join(parts)
                disk_rel = '/'.join(parts)

            target = os.path.join(destdir, *disk_rel.split('/'))
            if not os.path.abspath(target).startswith(destdir + os.sep):
                raise RuntimeError(f'APK 条目越界: {name}')
            os.makedirs(os.path.dirname(target) or destdir, exist_ok=True)
            with zf.open(info) as src, open(target, 'wb') as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
            count += 1

    os.makedirs(dup_root, exist_ok=True)
    with open(os.path.join(destdir, NAMEMAP_FILE), 'w', encoding='utf-8') as fp:
        json.dump(collisions, fp, ensure_ascii=False, indent=1)

    return {'files': count, 'collisions': len(collisions), 'namemap': collisions}


def verify_alignment(apkpath, page_align=DEFAULT_PAGE_ALIGN):
    """
    校验 APK 的 zip 结构（不用 Android SDK 的 zipalign）。

    返回 {'ok':bool,'resources_arsc':{...},'libs':[{...}],'issues':[...]}
    """
    result = {
        'ok': True,
        'resources_arsc': None,
        'libs': [],
        'dexes': [],
        'issues': [],
        'entry_count': 0,
    }
    with zipfile.ZipFile(apkpath, 'r') as zf:
        infos = zf.infolist()
        result['entry_count'] = len(infos)
        with open(apkpath, 'rb') as fp:
            for info in infos:
                fp.seek(info.header_offset)
                local = fp.read(30)
                if len(local) < 30 or local[:4] != b'PK\x03\x04':
                    result['issues'].append(f'{info.filename}: local header 损坏')
                    result['ok'] = False
                    continue
                name_len, extra_len = struct.unpack('<HH', local[26:30])
                data_offset = info.header_offset + 30 + name_len + extra_len
                stored = info.compress_type == zipfile.ZIP_STORED

                if info.filename == 'resources.arsc':
                    item = {
                        'name': info.filename,
                        'offset': data_offset,
                        'stored': stored,
                        'aligned4': data_offset % ARSC_ALIGN == 0,
                    }
                    result['resources_arsc'] = item
                    if not stored:
                        result['issues'].append('resources.arsc 未 STORED（Android 11+ 会安装失败）')
                        result['ok'] = False
                    if not item['aligned4']:
                        result['issues'].append('resources.arsc 未 4 字节对齐')
                        result['ok'] = False

                elif info.filename.lower().endswith('.so'):
                    item = {
                        'name': info.filename,
                        'offset': data_offset,
                        'stored': stored,
                        'align': page_align,
                        'aligned': data_offset % page_align == 0,
                    }
                    result['libs'].append(item)
                    if not item['aligned']:
                        result['issues'].append(
                            f'{info.filename} 未按 0x{page_align:x} 对齐（offset={data_offset}）')
                        result['ok'] = False

                elif info.filename.startswith('classes') and info.filename.endswith('.dex'):
                    result['dexes'].append(info.filename)

                if is_signature_entry(info.filename):
                    result['issues'].append(f'残留旧签名文件: {info.filename}')
                    result['ok'] = False

    result['dexes'].sort()
    return result


def check_zip_integrity(apkpath):
    """zip 自身完整性检查（CRC）。返回 {'ok':bool,'bad':[...]}"""
    bad = []
    with zipfile.ZipFile(apkpath, 'r') as zf:
        for info in zf.infolist():
            try:
                with zf.open(info) as fp:
                    while fp.read(1 << 20):
                        pass
            except Exception as exc:  # noqa: BLE001
                bad.append(f'{info.filename}: {exc}')
    return {'ok': not bad, 'bad': bad}


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print('usage: ApkZipper.py <src_apk_dir> <out.apk> [--page-align 16384] [--deflate-libs]')
        print('       ApkZipper.py verify <apk>')
        raise SystemExit(0)

    if sys.argv[1] == 'verify':
        print(verify_alignment(sys.argv[2]))
        print(check_zip_integrity(sys.argv[2]))
        raise SystemExit(0)

    page = DEFAULT_PAGE_ALIGN
    store_libs = True
    if '--page-align' in sys.argv:
        page = int(sys.argv[sys.argv.index('--page-align') + 1], 0)
    if '--deflate-libs' in sys.argv:
        store_libs = False

    zipper = ApkZipper(sys.argv[1], sys.argv[2], page_align=page, store_libs=store_libs)
    print(zipper.Build())
    print(verify_alignment(sys.argv[2], page))
