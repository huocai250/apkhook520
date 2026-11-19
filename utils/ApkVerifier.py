#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
ApkVerifier —— 产物自检与兼容性报告（2.0 新增）

加固/注入类工具最容易出的问题不是"生成失败"，而是"生成成功但装不上"：
  * resources.arsc 被 deflate 或没 4 字节对齐  -> Android 11+ 直接拒装；
  * lib/*/*.so 没按 16KB 对齐                  -> Android 15+ 16KB 页设备崩溃/拒装；
  * dex 命名错位 / 只剩 classes.dex            -> 壳加载不到原始 dex；
  * 签名残留旧 META-INF                        -> 安装报 INSTALL_PARSE_FAILED。
所以打完包必须跑一遍这里的检查，把结论写进 report.json 一起交付。
"""
import os
import shutil
import tempfile
import zipfile

try:
    from utils import ApkZipper, ElfAlign, ManifestTools, MultiDex, Tools
except Exception:  # noqa: BLE001
    import ApkZipper  # type: ignore
    import ElfAlign  # type: ignore
    import ManifestTools  # type: ignore
    import MultiDex  # type: ignore
    import Tools  # type: ignore

# (API level, Android 版本, 该版本新增的强制要求)
ANDROID_LEVELS = [
    (21, '5.0 Lollipop', None),
    (23, '6.0 Marshmallow', None),
    (26, '8.0 Oreo', None),
    (29, '10', None),
    (30, '11', 'resources.arsc 必须 STORED 且 4 字节对齐'),
    (31, '12', '带 intent-filter 的组件必须显式 android:exported'),
    (33, '13', '通知需要 POST_NOTIFICATIONS 运行时权限'),
    (34, '14', 'targetSdk < 23 的系统级拒装'),
    (35, '15', 'targetSdk < 24 的系统级拒装；16KB 页设备要求 .so 16KB 对齐'),
    (36, '16', '16KB 页设备成为主流，非对齐 .so 会被拒绝加载'),
    (37, '17', 'targetSdk < 24 拒装 + 16KB 页强制'),
]


def _read_manifest_from_apk(apkpath):
    """从 APK 里读 AndroidManifest.xml（二进制）并解析。"""
    tmpdir = tempfile.mkdtemp(prefix='apkverify_')
    target = os.path.join(tmpdir, 'AndroidManifest.xml')
    try:
        with zipfile.ZipFile(apkpath) as zf:
            try:
                data = zf.read('AndroidManifest.xml')
            except KeyError:
                return None, 'APK 内缺少 AndroidManifest.xml'
        with open(target, 'wb') as fp:
            fp.write(data)
        return ManifestTools.ReadInfo(target), None
    except Exception as exc:  # noqa: BLE001
        return None, f'解析清单失败: {exc}'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _check_elfs(apkpath, page_align):
    """从 APK 里取出所有 lib/**/*.so 做 16KB 对齐检查。"""
    results = []
    tmpdir = tempfile.mkdtemp(prefix='apkelf_')
    try:
        with zipfile.ZipFile(apkpath) as zf:
            for info in zf.infolist():
                name = info.filename
                if not name.lower().endswith('.so'):
                    continue
                out = os.path.join(tmpdir, name.replace('/', '_'))
                with zf.open(info) as src, open(out, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                res = ElfAlign.check_alignment(out, page_size=page_align)
                results.append({
                    'name': name,
                    'ok': res['ok'],
                    'bits': res['bits'],
                    'issues': res['issues'],
                    'segments': [
                        {'index': s['index'], 'offset': s['offset'],
                         'vaddr': s['vaddr'], 'filesz': s['filesz'],
                         'align': s['align']} for s in res['segments']
                    ],
                })
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return results


def _dex_listing(apkpath):
    """列出 APK 里所有 dex 载体：根目录 classes*.dex + assets/apkhook/dex/*.bin。

    加密 dex 必须放在 assets 下（名字不能是 classesN.dex），否则 ART 打开
    APK 时会把它当成真 dex，整包加载失败 → 打开即闪退。
    """
    out = []
    with zipfile.ZipFile(apkpath) as zf:
        for info in zf.infolist():
            name = info.filename
            low = name.lower()
            if low.endswith('.dex'):
                kind = 'root'
            elif low.startswith('assets/apkhook/dex/') and low.endswith('.bin'):
                kind = 'asset'
            else:
                continue
            with zf.open(info) as fp:
                magic = fp.read(8)
            out.append({
                'name': name,
                'kind': kind,
                'size': info.file_size,
                'compressed': info.compress_type != zipfile.ZIP_STORED,
                'plaintext': magic[:3] == b'dex',
                'magic': magic[:8].hex(),
            })
    out.sort(key=lambda x: (x['kind'] != 'root', MultiDex.parse_dex_name(x['name']) or 0, x['name']))
    return out


def Verify(apkpath, page_align=ApkZipper.DEFAULT_PAGE_ALIGN, java=None,
           check_signature=True):
    """对最终 APK 做完整自检，返回 report dict（可 JSON 序列化）。"""
    report = {
        'apk': os.path.abspath(apkpath),
        'size': os.path.getsize(apkpath) if os.path.isfile(apkpath) else 0,
        'page_align': page_align,
        'ok': False,
        'problems': [],
        'warnings': [],
    }
    if not os.path.isfile(apkpath):
        report['problems'].append('APK 文件不存在')
        return report

    report['size_human'] = Tools.human_size(report['size'])
    report['sha256'] = Tools.sha256_file(apkpath)
    report['md5'] = Tools.md5_file(apkpath)

    # 1. zip 完整性
    try:
        report['zip_integrity'] = ApkZipper.check_zip_integrity(apkpath)
        if not report['zip_integrity'].get('ok', False):
            report['problems'].append('zip 完整性检查未通过')
    except Exception as exc:  # noqa: BLE001
        report['problems'].append(f'zip 完整性检查异常: {exc}')

    # 2. 对齐
    try:
        align = ApkZipper.verify_alignment(apkpath, page_align=page_align)
        report['alignment'] = align
        if not align.get('ok', False):
            for issue in align.get('issues', []):
                report['problems'].append(f'对齐: {issue}')
    except Exception as exc:  # noqa: BLE001
        report['problems'].append(f'对齐检查异常: {exc}')

    # 3. manifest
    info, err = _read_manifest_from_apk(apkpath)
    if err:
        report['problems'].append(err)
        info = None
    else:
        _pkg = info['package']
        report['manifest'] = {
            'package': _pkg,
            # 清单里常写 `.DemoApp`，报告统一输出全限定名
            'application': ManifestTools.NormalizeClassName(_pkg, info['application']),
            'launcher_activity': ManifestTools.NormalizeClassName(_pkg, info['launcher_activity']),
            'target_sdk': info['target_sdk'],
            'min_sdk': info['min_sdk'],
            'extract_native_libs': info['extract_native_libs'],
            'permission_count': len(info['permissions']),
        }
        report['components'] = info.get('components', [])

    # 4. ELF 对齐
    try:
        elfs = _check_elfs(apkpath, page_align)
        report['elfs'] = elfs
        for item in elfs:
            if not item['ok']:
                report['problems'].append(f"{item['name']} 未满足 16KB 段对齐")
    except Exception as exc:  # noqa: BLE001
        report['problems'].append(f'ELF 检查异常: {exc}')

    # 5. dex 布局
    try:
        dexes = _dex_listing(apkpath)
        report['dexes'] = dexes
        names = [d['name'] for d in dexes]
        if 'classes.dex' not in names:
            report['problems'].append('APK 内没有 classes.dex')
        dup = len(names) != len(set(names))
        if dup:
            report['problems'].append('存在重名 dex')
    except Exception as exc:  # noqa: BLE001
        report['problems'].append(f'dex 检查异常: {exc}')

    # 6. 旧签名残留
    try:
        with zipfile.ZipFile(apkpath) as zf:
            stale = [n for n in zf.namelist()
                     if n.upper().startswith('META-INF/')
                     and n.upper().endswith(('.RSA', '.DSA', '.EC', '.SF'))]
        report['signature_files'] = stale
        if not stale:
            report['warnings'].append('未发现 v1 签名文件（仅 v2/v3 签名）')
    except Exception as exc:  # noqa: BLE001
        report['problems'].append(f'签名文件检查异常: {exc}')

    # 7. apksigner verify
    if check_signature:
        try:
            rc, out = Tools.apksigner_verify(apkpath, java=java)
            report['signature_verified'] = (rc == 0)
            report['signature_output'] = out.strip()[-2000:]
            if rc != 0:
                report['problems'].append('apksigner verify 未通过')
        except Exception as exc:  # noqa: BLE001
            report['warnings'].append(f'apksigner verify 未能执行: {exc}')

    # 8. 版本兼容矩阵
    target = (report.get('manifest') or {}).get('target_sdk') or 0
    minsdk = (report.get('manifest') or {}).get('min_sdk') or 0
    matrix = []
    for api, name, note in ANDROID_LEVELS:
        if api < (minsdk or 0):
            state = 'skip'
            reason = f'minSdk={minsdk} > API {api}'
        elif api >= 34 and target < 24:
            state = 'fail'
            reason = f'targetSdk={target} < 24，Android {name} 拒装'
        else:
            state = 'ok'
            reason = note or ''
        matrix.append({'api': api, 'android': name, 'state': state, 'note': reason})
    report['android_matrix'] = matrix

    report['ok'] = not report['problems']
    return report


def PrintReport(report, printer=None):
    """把报告打印成人话。"""
    say = printer or print
    say(f"APK      : {report['apk']}")
    say(f"大小     : {report.get('size_human', '?')}")
    say(f"SHA256   : {report.get('sha256', '?')}")
    align = report.get('alignment') or {}
    say(f"对齐     : {'OK' if align.get('ok') else 'FAIL'} "
        f"(entries={align.get('entry_count', '?')}, "
        f"page=0x{report.get('page_align', 0):x})")
    man = report.get('manifest') or {}
    say(f"包名     : {man.get('package')}  targetSdk={man.get('target_sdk')} "
        f"minSdk={man.get('min_sdk')}")
    say(f"启动组件 : {man.get('application')} / {man.get('launcher_activity')}")
    for dex in report.get('dexes', []):
        flag = 'plain' if dex['plaintext'] else 'encrypted'
        say(f"dex      : {dex['name']} ({dex['size']} B, {flag})")
    for elf in report.get('elfs', []):
        say(f"so       : {elf['name']} {'OK' if elf['ok'] else 'FAIL'}")
    for warn in report.get('warnings', []):
        say(f"警告     : {warn}")
    for problem in report.get('problems', []):
        say(f"问题     : {problem}")
    say('兼容性   : ' + ', '.join(
        f"{row['android'].split()[0]}={row['state']}"
        for row in report.get('android_matrix', [])))


if __name__ == '__main__':
    import json
    import sys
    if len(sys.argv) < 2:
        print('usage: ApkVerifier.py <apk>')
        raise SystemExit(0)
    result = Verify(sys.argv[1])
    PrintReport(result)
    print(json.dumps({'ok': result['ok'], 'problems': result['problems']},
                     ensure_ascii=False, indent=2))
