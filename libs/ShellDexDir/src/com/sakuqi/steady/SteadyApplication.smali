.class public Lcom/sakuqi/steady/SteadyApplication;
.super Landroid/app/Application;
.source "SteadyApplication.java"


# static fields
.field public static final TAG:Ljava/lang/String; = "steady"

# static 字段：hidden API 豁免只做一次（失败也只做一次，避免反复触发异常）
.field private static hiddenApiExempted:Z


# instance fields
.field public app_name:Ljava/lang/String;

# 模式 1：payload 的启动类（点号全名，来自 meta-data apkhook_payload）
.field public payload_name:Ljava/lang/String;

.field public keep_name:Ljava/lang/String;

.field delegate:Landroid/app/Application;

.field isBindReal:Z


# direct methods
.method static constructor <clinit>()V
    .locals 3

    :try_start_0
    const-string v0, "steady-lib"

    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    return-void

    :catch_0
    move-exception v0

    const-string v1, "clinit: loadLibrary steady-lib failed"

    invoke-static {v1, v0}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method

.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Landroid/app/Application;-><init>()V

    return-void
.end method

# JNI 按名绑定 libsteady-lib.so：方法名与签名不可改
.method public native decrypt([B)[B
.end method


# ------------------------------------------------------------------
# hidden API 豁免：Android 9+ 反射 hidden 成员会被拦，先申请全豁免。
# 任何失败只 log，不抛。静态方法 invoke 时 obj 传 null。
# ------------------------------------------------------------------
.method private static exemptHiddenApi()V
    .locals 9

    sget-boolean v0, Lcom/sakuqi/steady/SteadyApplication;->hiddenApiExempted:Z

    # 已经豁免过（true）才返回；null 首次进来必须继续往下走。
    # 原写法 if-eqz 会在「未豁免」时直接 return，等于豁免永远不生效。
    if-nez v0, :ret

    const/4 v0, 0x1

    sput-boolean v0, Lcom/sakuqi/steady/SteadyApplication;->hiddenApiExempted:Z

    :try_start_0
    const-string v0, "dalvik.system.VMRuntime"

    invoke-static {v0}, Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;

    move-result-object v0

    const-string v1, "getRuntime"

    const/4 v2, 0x0

    new-array v2, v2, [Ljava/lang/Class;

    invoke-virtual {v0, v1, v2}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v1

    const/4 v2, 0x1

    invoke-virtual {v1, v2}, Ljava/lang/reflect/Method;->setAccessible(Z)V

    const/4 v2, 0x0

    new-array v2, v2, [Ljava/lang/Object;

    const/4 v3, 0x0

    invoke-virtual {v1, v3, v2}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v1

    if-eqz v1, :ret

    const/4 v2, 0x1

    new-array v2, v2, [Ljava/lang/Class;

    const/4 v3, 0x0

    const-class v4, [Ljava/lang/String;

    aput-object v4, v2, v3

    const-string v3, "setHiddenApiExemptions"

    invoke-virtual {v0, v3, v2}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v0

    const/4 v2, 0x1

    invoke-virtual {v0, v2}, Ljava/lang/reflect/Method;->setAccessible(Z)V

    const/4 v2, 0x1

    new-array v2, v2, [Ljava/lang/Object;

    const/4 v3, 0x1

    new-array v3, v3, [Ljava/lang/String;

    const/4 v4, 0x0

    const-string v5, "L"

    aput-object v5, v3, v4

    const/4 v4, 0x0

    aput-object v3, v2, v4

    invoke-virtual {v0, v1, v2}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :ret
    return-void

    :catch_0
    move-exception v6

    const-string v7, "exemptHiddenApi failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method


# ------------------------------------------------------------------
# 读取 app_name：PackageManager(带 GET_META_DATA) -> getApplicationInfo().metaData
# -> getApplicationInfo().className 兜底（且不能等于壳自己）。
# ------------------------------------------------------------------
.method private readAppName()V
    .locals 8

    const/4 v4, 0x0

    :try_start_0
    invoke-virtual {p0}, Landroid/content/Context;->getPackageManager()Landroid/content/pm/PackageManager;

    move-result-object v0

    invoke-super {p0}, Landroid/content/ContextWrapper;->getPackageName()Ljava/lang/String;

    move-result-object v1

    const/16 v2, 0x80

    invoke-virtual {v0, v1, v2}, Landroid/content/pm/PackageManager;->getApplicationInfo(Ljava/lang/String;I)Landroid/content/pm/ApplicationInfo;

    move-result-object v0

    if-eqz v0, :s1

    iget-object v1, v0, Landroid/content/pm/ApplicationInfo;->metaData:Landroid/os/Bundle;

    if-eqz v1, :s1

    const-string v2, "app_name"

    invoke-virtual {v1, v2}, Landroid/os/Bundle;->getString(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v2

    invoke-static {v2}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v3

    if-nez v3, :s1

    move-object v4, v2
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s1
    if-nez v4, :store

    :try_start_1
    invoke-virtual {p0}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;

    move-result-object v0

    if-eqz v0, :s2

    iget-object v1, v0, Landroid/content/pm/ApplicationInfo;->metaData:Landroid/os/Bundle;

    if-eqz v1, :s2

    const-string v2, "app_name"

    invoke-virtual {v1, v2}, Landroid/os/Bundle;->getString(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v2

    invoke-static {v2}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v3

    if-nez v3, :s2

    move-object v4, v2
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :s2
    if-nez v4, :store

    :try_start_2
    invoke-virtual {p0}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;

    move-result-object v0

    if-eqz v0, :s3

    iget-object v1, v0, Landroid/content/pm/ApplicationInfo;->className:Ljava/lang/String;

    invoke-static {v1}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v2

    if-nez v2, :s3

    move-object v4, v1
    :try_end_2
    .catch Ljava/lang/Throwable; {:try_start_2 .. :try_end_2} :catch_2

    :s3

    :store
    invoke-static {v4}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v0

    if-nez v0, :ret

    const-string v0, "com.sakuqi.steady.SteadyApplication"

    invoke-virtual {v0, v4}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-nez v0, :ret

    iput-object v4, p0, Lcom/sakuqi/steady/SteadyApplication;->app_name:Ljava/lang/String;

    :ret
    return-void

    :catch_0
    move-exception v6

    const-string v7, "readAppName: pm meta-data failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s1

    :catch_1
    move-exception v6

    const-string v7, "readAppName: applicationInfo meta-data failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s2

    :catch_2
    move-exception v6

    const-string v7, "readAppName: className fallback failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s3
.end method


# ------------------------------------------------------------------
# 解压 / 解密 / 加载，任何一步失败都只 log。
# ------------------------------------------------------------------
.method private static isCacheValid(Ljava/io/File;Ljava/io/File;Ljava/io/File;)Z
    .locals 6
    .param p0, "apk"    # Ljava/io/File;
    .param p1, "appDir"    # Ljava/io/File;
    .param p2, "dexDir"    # Ljava/io/File;

    :try_start_0
    invoke-virtual {p2}, Ljava/io/File;->exists()Z

    move-result v0

    if-eqz v0, :no

    invoke-virtual {p2}, Ljava/io/File;->list()[Ljava/lang/String;

    move-result-object v0

    if-eqz v0, :no

    array-length v0, v0

    if-eqz v0, :no

    new-instance v0, Ljava/io/File;

    const-string v1, ".stamp"

    invoke-direct {v0, p1, v1}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    invoke-static {v0}, Lcom/sakuqi/steady/ProxyUtils;->getBytes(Ljava/io/File;)[B

    move-result-object v0

    new-instance v1, Ljava/lang/String;

    invoke-direct {v1, v0}, Ljava/lang/String;-><init>([B)V

    invoke-static {p0}, Lcom/sakuqi/steady/SteadyApplication;->buildStamp(Ljava/io/File;)Ljava/lang/String;

    move-result-object v2

    invoke-virtual {v2, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    return v0

    :no
    const/4 v0, 0x0

    return v0

    :catch_0
    move-exception v3

    const-string v4, "isCacheValid failed"

    invoke-static {v4, v3}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    const/4 v0, 0x0

    return v0
.end method

.method private static buildStamp(Ljava/io/File;)Ljava/lang/String;
    .locals 3
    .param p0, "apk"    # Ljava/io/File;

    new-instance v0, Ljava/lang/StringBuilder;

    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V

    invoke-virtual {p0}, Ljava/io/File;->getAbsolutePath()Ljava/lang/String;

    move-result-object v1

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v0

    const-string v1, "|"

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v0

    invoke-virtual {p0}, Ljava/io/File;->length()J

    move-result-wide v1

    invoke-virtual {v0, v1, v2}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;

    move-result-object v0

    const-string v1, "|"

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v0

    invoke-virtual {p0}, Ljava/io/File;->lastModified()J

    move-result-wide v1

    invoke-virtual {v0, v1, v2}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;

    move-result-object v0

    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    return-object v0
.end method

.method private static writeStamp(Ljava/io/File;Ljava/io/File;)V
    .locals 6
    .param p0, "apk"    # Ljava/io/File;
    .param p1, "appDir"    # Ljava/io/File;

    :try_start_0
    new-instance v0, Ljava/io/File;

    const-string v1, ".stamp"

    invoke-direct {v0, p1, v1}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    invoke-static {p0}, Lcom/sakuqi/steady/SteadyApplication;->buildStamp(Ljava/io/File;)Ljava/lang/String;

    move-result-object v1

    invoke-virtual {v1}, Ljava/lang/String;->getBytes()[B

    move-result-object v1

    new-instance v2, Ljava/io/FileOutputStream;

    invoke-direct {v2, v0}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;)V

    invoke-virtual {v2, v1}, Ljava/io/FileOutputStream;->write([B)V

    invoke-virtual {v2}, Ljava/io/FileOutputStream;->flush()V

    invoke-virtual {v2}, Ljava/io/FileOutputStream;->close()V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    return-void

    :catch_0
    move-exception v3

    const-string v4, "writeStamp failed"

    invoke-static {v4, v3}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method

# 遍历 classes2..classes199，跳过 classes.dex（壳自身）
.method private decryptDexes(Ljava/io/File;Ljava/io/File;)V
    .locals 12
    .param p1, "appDir"    # Ljava/io/File;
    .param p2, "dexDir"    # Ljava/io/File;

    # 先清空 dexDir：版本升级后 dex 数量可能变少，残留的旧 classesN.dex
    # 会被 addDexFiles 一并加载，导致新旧混淆。
    invoke-static {p2}, Lcom/sakuqi/steady/Zip;->deleteFile(Ljava/io/File;)V

    invoke-virtual {p2}, Ljava/io/File;->mkdirs()Z

    move-result v1

    const/4 v0, 0x2

    :loop
    const/16 v1, 0xc8

    if-ge v0, v1, :done

    new-instance v1, Ljava/lang/StringBuilder;

    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V

    const-string v2, "classes"

    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v1

    invoke-virtual {v1, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    move-result-object v1

    # 源文件：appDir/classesN.bin（unZip 解出来的密文，不是 .dex 后缀）
    const-string v2, ".bin"

    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v1

    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v1

    # 目标文件名：dexDir/classesN.dex
    new-instance v9, Ljava/lang/StringBuilder;

    invoke-direct {v9}, Ljava/lang/StringBuilder;-><init>()V

    const-string v2, "classes"

    invoke-virtual {v9, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v9, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    move-result-object v9

    const-string v2, ".dex"

    invoke-virtual {v9, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v9

    invoke-virtual {v9}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v9

    new-instance v2, Ljava/io/File;

    invoke-direct {v2, p1, v1}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    invoke-virtual {v2}, Ljava/io/File;->exists()Z

    move-result v3

    if-eqz v3, :next

    :try_start_0
    invoke-static {v2}, Lcom/sakuqi/steady/ProxyUtils;->getBytes(Ljava/io/File;)[B

    move-result-object v4

    # 先走纯 Java AES（与打包端 EncryptFile.py 同 key 同模式），
    # 失败再退回 native decrypt：老壳只依赖 so，so 一挂就全崩。
    invoke-static {v4}, Lcom/sakuqi/steady/CryptoUtils;->decryptAes([B)[B

    move-result-object v5

    if-nez v5, :have

    invoke-virtual {p0, v4}, Lcom/sakuqi/steady/SteadyApplication;->decrypt([B)[B

    move-result-object v5

    :have
    if-nez v5, :have5

    const-string v6, "decryptDexes: decrypt returned null"

    invoke-static {v6}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    goto :next

    :have5
    if-eqz v5, :next

    # 目标目录可能还不存在（首次启动），mkdirs() 幂等：存在时返回 false，不会抛异常。
    # 原写法 `if-nez v8, :mkdir` 会把「目录不存在」直接跳到 mkdirs 之后，
    # 导致 FileOutputStream 抛 FileNotFoundException、整只 dex 解密失败。
    invoke-virtual {p2}, Ljava/io/File;->mkdirs()Z

    move-result v8
    new-instance v6, Ljava/io/File;

    invoke-direct {v6, p2, v9}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v7, Ljava/io/FileOutputStream;

    invoke-direct {v7, v6}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;)V

    invoke-virtual {v7, v5}, Ljava/io/FileOutputStream;->write([B)V

    invoke-virtual {v7}, Ljava/io/FileOutputStream;->flush()V

    invoke-virtual {v7}, Ljava/io/FileOutputStream;->close()V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :next
    add-int/lit8 v0, v0, 0x1

    goto :loop

    :done
    return-void

    :catch_0
    move-exception v10

    const-string v11, "decryptDexes: one dex failed"

    invoke-static {v11, v10}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :next
.end method

.method private installDex()V
    .locals 8

    const/4 v0, 0x0

    :try_start_0
    invoke-virtual {p0}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;

    move-result-object v2

    if-eqz v2, :s1

    iget-object v2, v2, Landroid/content/pm/ApplicationInfo;->sourceDir:Ljava/lang/String;

    new-instance v0, Ljava/io/File;

    invoke-direct {v0, v2}, Ljava/io/File;-><init>(Ljava/lang/String;)V

    invoke-virtual {v0}, Ljava/io/File;->exists()Z

    move-result v2

    if-nez v2, :s1

    const/4 v0, 0x0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s1
    if-nez v0, :s2

    const-string v2, "installDex: apk not found"

    invoke-static {v2}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    return-void

    :s2
    const/4 v1, 0x0

    :try_start_1
    const-string v2, "SteadyDir"

    const/4 v3, 0x0

    invoke-virtual {p0, v2, v3}, Landroid/content/Context;->getDir(Ljava/lang/String;I)Ljava/io/File;

    move-result-object v1
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :s3
    if-eqz v1, :ret

    new-instance v2, Ljava/io/File;

    const-string v3, "app"

    invoke-direct {v2, v1, v3}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v3, Ljava/io/File;

    const-string v4, "dexDir"

    invoke-direct {v3, v2, v4}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v4, Ljava/util/ArrayList;

    invoke-direct {v4}, Ljava/util/ArrayList;-><init>()V

    invoke-static {v0, v2, v3}, Lcom/sakuqi/steady/SteadyApplication;->isCacheValid(Ljava/io/File;Ljava/io/File;Ljava/io/File;)Z

    move-result v5

    if-eqz v5, :fresh
    const-string v6, "installDex: step1 unzip start"

    invoke-static {v6}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V


    invoke-static {v3, v4}, Lcom/sakuqi/steady/ClassLoaderUtils;->addDexFiles(Ljava/io/File;Ljava/util/List;)V

    goto :load

    :fresh
    :try_start_2
    invoke-static {v0, v2}, Lcom/sakuqi/steady/Zip;->unZip(Ljava/io/File;Ljava/io/File;)V
    :try_end_2
    .catch Ljava/lang/Throwable; {:try_start_2 .. :try_end_2} :catch_2

    :s4
    const-string v6, "installDex: step2 decrypt start"

    invoke-static {v6}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    invoke-direct {p0, v2, v3}, Lcom/sakuqi/steady/SteadyApplication;->decryptDexes(Ljava/io/File;Ljava/io/File;)V

    const-string v6, "installDex: step2 decrypt done"

    invoke-static {v6}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    invoke-static {v0, v2}, Lcom/sakuqi/steady/SteadyApplication;->writeStamp(Ljava/io/File;Ljava/io/File;)V

    const-string v6, "installDex: step3 addDexFiles"

    invoke-static {v6}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    invoke-static {v3, v4}, Lcom/sakuqi/steady/ClassLoaderUtils;->addDexFiles(Ljava/io/File;Ljava/util/List;)V

    :load
    invoke-interface {v4}, Ljava/util/List;->isEmpty()Z

    move-result v5

    # isEmpty() 为 true(1) 表示没有任何 dex 可加载 → 直接返回；
    # 为 false(0) 表示有待加载 dex → 跳到 :have 调 loadDex。
    if-eqz v5, :have

    const-string v5, "installDex: nothing to load"

    invoke-static {v5}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    return-void

    :have
    :try_start_3
    invoke-static {p0, v4, v3}, Lcom/sakuqi/steady/ClassLoaderUtils;->loadDex(Landroid/app/Application;Ljava/util/List;Ljava/io/File;)V
    :try_end_3
    .catch Ljava/lang/Throwable; {:try_start_3 .. :try_end_3} :catch_3

    const-string v6, "installDex: step4 loadDex done"

    invoke-static {v6}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    :ret
    return-void

    :catch_0
    move-exception v6

    const-string v7, "installDex: resolve apk failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void

    :catch_1
    move-exception v6

    const-string v7, "installDex: getDir failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void

    :catch_2
    move-exception v6

    const-string v7, "installDex: unzip failed, fall back to dex cache"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    # 解压失败也要尽力加载上次留下的 dex（老版本升级上来时通常是有效的）
    invoke-static {v3, v4}, Lcom/sakuqi/steady/ClassLoaderUtils;->addDexFiles(Ljava/io/File;Ljava/util/List;)V

    goto :load

    :catch_3
    move-exception v6

    const-string v7, "installDex: loadDex failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :ret
.end method


# ------------------------------------------------------------------
# attachBaseContext：super 最前，随后每一步独立 try/catch(Throwable)
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# 模式 1：不注入宿主 dex，改为由壳自己反射启动 payload。
# 宿主 dex 一旦过 baksmali/smali 往返就会被改坏（实测 ktor 的接口调用
# 会变成 ART 认为 class/interface 不匹配，抛 IncompatibleClassChangeError），
# 所以启动点必须在壳里，而不是插进宿主 Application。
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# 保活：读 meta-data apkhook_keep，起前台服务（2.0）
# ------------------------------------------------------------------
.method private readKeepName()V
    .locals 6

    const/4 v0, 0x0

    :try_start_0
    invoke-virtual {p0}, Landroid/content/Context;->getPackageManager()Landroid/content/pm/PackageManager;

    move-result-object v1

    invoke-super {p0}, Landroid/content/ContextWrapper;->getPackageName()Ljava/lang/String;

    move-result-object v2

    const/16 v3, 0x80

    invoke-virtual {v1, v2, v3}, Landroid/content/pm/PackageManager;->getApplicationInfo(Ljava/lang/String;I)Landroid/content/pm/ApplicationInfo;

    move-result-object v1

    if-eqz v1, :done

    iget-object v1, v1, Landroid/content/pm/ApplicationInfo;->metaData:Landroid/os/Bundle;

    if-eqz v1, :done

    const-string v2, "apkhook_keep"

    invoke-virtual {v1, v2}, Landroid/os/Bundle;->getString(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :done
    invoke-static {v0}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v1

    if-nez v1, :ret

    iput-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->keep_name:Ljava/lang/String;

    :ret
    return-void

    :catch_0
    move-exception v1

    const-string v2, "readKeepName: meta-data failed"

    invoke-static {v2, v1}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method


.method private startKeep(Landroid/content/Context;)V
    .locals 5

    iget-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->keep_name:Ljava/lang/String;

    invoke-static {v0}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v1

    if-nez v1, :ret

    :try_start_0
    new-instance v1, Landroid/content/Intent;

    invoke-direct {v1}, Landroid/content/Intent;-><init>()V

    invoke-virtual {v1, p0, v0}, Landroid/content/Intent;->setClassName(Landroid/content/Context;Ljava/lang/String;)Landroid/content/Intent;

    sget v2, Landroid/os/Build$VERSION;->SDK_INT:I

    const/16 v3, 0x1a

    if-lt v2, v3, :legacy

    invoke-virtual {p0, v1}, Landroid/content/Context;->startForegroundService(Landroid/content/Intent;)Landroid/content/ComponentName;

    goto :ok

    :legacy
    invoke-virtual {p0, v1}, Landroid/content/Context;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;

    :ok
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    const-string v2, "startKeep: foreground service started"

    invoke-static {v2}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V

    return-void

    :catch_0
    move-exception v0

    const-string v1, "startKeep: failed"

    invoke-static {v1, v0}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    :ret
    return-void
.end method


.method private readPayloadName()V
    .locals 6

    const/4 v0, 0x0

    :try_start_0
    invoke-virtual {p0}, Landroid/content/Context;->getPackageManager()Landroid/content/pm/PackageManager;

    move-result-object v1

    invoke-super {p0}, Landroid/content/ContextWrapper;->getPackageName()Ljava/lang/String;

    move-result-object v2

    const/16 v3, 0x80

    invoke-virtual {v1, v2, v3}, Landroid/content/pm/PackageManager;->getApplicationInfo(Ljava/lang/String;I)Landroid/content/pm/ApplicationInfo;

    move-result-object v1

    if-eqz v1, :done

    iget-object v1, v1, Landroid/content/pm/ApplicationInfo;->metaData:Landroid/os/Bundle;

    if-eqz v1, :done

    const-string v2, "apkhook_payload"

    invoke-virtual {v1, v2}, Landroid/os/Bundle;->getString(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :done
    invoke-static {v0}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v1

    if-nez v1, :ret

    iput-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->payload_name:Ljava/lang/String;

    :ret
    return-void

    :catch_0
    move-exception v1

    const-string v2, "readPayloadName: meta-data failed"

    invoke-static {v2, v1}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method


.method private static startPayload(Landroid/content/Context;Ljava/lang/String;)V
    .locals 6

    invoke-static {p1}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v0

    if-nez v0, :ret

    :try_start_0
    invoke-virtual {p0}, Landroid/content/Context;->getClassLoader()Ljava/lang/ClassLoader;

    move-result-object v0

    const/4 v1, 0x1

    invoke-static {p1, v1, v0}, Ljava/lang/Class;->forName(Ljava/lang/String;ZLjava/lang/ClassLoader;)Ljava/lang/Class;

    move-result-object v0

    const-string v1, "start"

    const/4 v2, 0x1

    new-array v2, v2, [Ljava/lang/Class;

    const/4 v3, 0x0

    const-string v4, "android.content.Context"

    invoke-static {v4}, Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;

    move-result-object v4

    aput-object v4, v2, v3

    invoke-virtual {v0, v1, v2}, Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v0

    const/4 v1, 0x0

    const/4 v2, 0x1

    new-array v2, v2, [Ljava/lang/Object;

    const/4 v3, 0x0

    aput-object p0, v2, v3

    invoke-virtual {v0, v1, v2}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;

    const-string v0, "startPayload: payload started"

    invoke-static {v0}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :ret
    return-void

    :catch_0
    move-exception v1

    const-string v2, "startPayload: payload start failed"

    invoke-static {v2, v1}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method


.method protected attachBaseContext(Landroid/content/Context;)V
    .locals 4
    .param p1, "base"    # Landroid/content/Context;

    # 最先做：把 Context 交给 ProxyUtils，之后所有日志都会同时落到
    # Android/data/<包名>/files/steady.log（没电脑也能取证）。
    :try_start_ctx
    invoke-static {p1}, Lcom/sakuqi/steady/ProxyUtils;->setContext(Landroid/content/Context;)V

    const-string v0, "attachBaseContext: enter"

    invoke-static {v0}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V
    :try_end_ctx
    .catch Ljava/lang/Throwable; {:try_start_ctx .. :try_end_ctx} :catch_ctx

    :ctx_ok
    invoke-super {p0, p1}, Landroid/app/Application;->attachBaseContext(Landroid/content/Context;)V

    :try_start_0
    invoke-static {}, Lcom/sakuqi/steady/SteadyApplication;->exemptHiddenApi()V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s1
    :try_start_1
    invoke-direct {p0}, Lcom/sakuqi/steady/SteadyApplication;->readAppName()V
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :s2
    :try_start_2
    invoke-direct {p0}, Lcom/sakuqi/steady/SteadyApplication;->installDex()V
    :try_end_2
    .catch Ljava/lang/Throwable; {:try_start_2 .. :try_end_2} :catch_2

    :s3
    return-void

    :catch_0
    move-exception v2

    const-string v3, "attachBaseContext: exemptHiddenApi failed"

    invoke-static {v3, v2}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s1

    :catch_1
    move-exception v2

    const-string v3, "attachBaseContext: readAppName failed"

    invoke-static {v3, v2}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s2

    :catch_2
    move-exception v2

    const-string v3, "attachBaseContext: installDex failed"

    invoke-static {v3, v2}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void

    :catch_ctx
    move-exception v0

    goto :ctx_ok
.end method

.method public onCreate()V
    .locals 2

    invoke-super {p0}, Landroid/app/Application;->onCreate()V

    :try_start_0
    invoke-direct {p0}, Lcom/sakuqi/steady/SteadyApplication;->bindRealApplication()V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :try_start_1
    invoke-direct {p0}, Lcom/sakuqi/steady/SteadyApplication;->readPayloadName()V

    iget-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->payload_name:Ljava/lang/String;

    invoke-static {p0, v0}, Lcom/sakuqi/steady/SteadyApplication;->startPayload(Landroid/content/Context;Ljava/lang/String;)V
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :try_start_2
    invoke-direct {p0}, Lcom/sakuqi/steady/SteadyApplication;->readKeepName()V

    invoke-direct {p0, p0}, Lcom/sakuqi/steady/SteadyApplication;->startKeep(Landroid/content/Context;)V
    :try_end_2
    .catch Ljava/lang/Throwable; {:try_start_2 .. :try_end_2} :catch_2

    return-void

    :catch_1
    move-exception v0

    const-string v1, "onCreate: startPayload failed"

    invoke-static {v1, v0}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void

    :catch_2
    move-exception v0

    const-string v1, "onCreate: startKeep failed"

    invoke-static {v1, v0}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void

    :catch_0
    move-exception v0

    const-string v1, "onCreate: bindRealApplication failed"

    invoke-static {v1, v0}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method


# ------------------------------------------------------------------
# 委派绑定：每一步单独 try/catch，失败不中断后续步骤
# ------------------------------------------------------------------
.method private attachDelegate(Landroid/app/Application;Landroid/content/Context;)V
    .locals 8
    .param p1, "app"    # Landroid/app/Application;
    .param p2, "base"    # Landroid/content/Context;

    # 1) Application.attach(Context)：填 mBase / mLoadedApk / mResources 等
    :try_start_0
    const-class v0, Landroid/app/Application;

    const-string v1, "attach"

    const/4 v2, 0x1

    new-array v2, v2, [Ljava/lang/Class;

    const/4 v3, 0x0

    const-class v4, Landroid/content/Context;

    aput-object v4, v2, v3

    invoke-virtual {v0, v1, v2}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v0

    const/4 v1, 0x1

    invoke-virtual {v0, v1}, Ljava/lang/reflect/Method;->setAccessible(Z)V

    const/4 v1, 0x1

    new-array v1, v1, [Ljava/lang/Object;

    const/4 v2, 0x0

    aput-object p2, v1, v2

    invoke-virtual {v0, p1, v1}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s0
    # 2) 说明：Application.attach(Context) 内部会 `attachBaseContext(context)`，
    #    所以被代理 Application 的 attachBaseContext 已经执行过了（Tinker 的
    #    ApplicationLike 就是在那里面建的）。这里**不能**再调一次，否则 Tinker
    #    会二次初始化 ApplicationLike。
    :s1
    # 3) 兜底：attach(Context) 走不通时 mLoadedApk 还是空，很多 SDK 会 NPE
    :try_start_2
    invoke-static {p2}, Lcom/sakuqi/steady/SteadyApplication;->getPackageInfo(Landroid/content/Context;)Ljava/lang/Object;

    move-result-object v0

    if-eqz v0, :s2

    const-string v1, "mLoadedApk"

    invoke-static {p1, v1}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v1

    invoke-virtual {v1, p1, v0}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :try_end_2
    .catch Ljava/lang/Throwable; {:try_start_2 .. :try_end_2} :catch_2

    :s2
    return-void

    :catch_0
    move-exception v6

    const-string v7, "attachDelegate: attach(Context) failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s0

    :catch_1
    move-exception v6

    const-string v7, "attachDelegate: attachBaseContext failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s1

    :catch_2
    move-exception v6

    const-string v7, "attachDelegate: mLoadedApk fixup failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s2
.end method


.method private static getMainThread(Landroid/content/Context;)Ljava/lang/Object;
    .locals 8
    .param p0, "base"    # Landroid/content/Context;

    const/4 v1, 0x0

    :try_start_0
    const-string v0, "mMainThread"

    invoke-static {p0, v0}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v0

    invoke-virtual {v0, p0}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v1
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s1
    if-nez v1, :ret

    :try_start_1
    const-string v0, "android.app.ActivityThread"

    invoke-static {v0}, Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;

    move-result-object v0

    const-string v2, "currentActivityThread"

    const/4 v3, 0x0

    new-array v3, v3, [Ljava/lang/Class;

    invoke-virtual {v0, v2, v3}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v0

    const/4 v2, 0x1

    invoke-virtual {v0, v2}, Ljava/lang/reflect/Method;->setAccessible(Z)V

    const/4 v2, 0x0

    new-array v2, v2, [Ljava/lang/Object;

    const/4 v3, 0x0

    invoke-virtual {v0, v3, v2}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v1
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :ret
    return-object v1

    :catch_0
    move-exception v6

    const-string v7, "getMainThread: mMainThread failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s1

    :catch_1
    move-exception v6

    const-string v7, "getMainThread: currentActivityThread failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :ret
.end method

.method private static getPackageInfo(Landroid/content/Context;)Ljava/lang/Object;
    .locals 8
    .param p0, "base"    # Landroid/content/Context;

    const/4 v1, 0x0

    # Android 10 之前 ContextImpl 用 mPackageInfo；
    # 新版部分分支改用 mLoadedApk，两个都试，取到即返回
    :try_start_0
    const-string v0, "mPackageInfo"

    invoke-static {p0, v0}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v0

    invoke-virtual {v0, p0}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v1
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    if-nez v1, :ret

    :mloaded
    :try_start_1
    const-string v0, "mLoadedApk"

    invoke-static {p0, v0}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v0

    invoke-virtual {v0, p0}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v1
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :ret
    return-object v1

    :catch_0
    move-exception v6

    const-string v7, "getPackageInfo: mPackageInfo missing, try mLoadedApk"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :mloaded

    :catch_1
    move-exception v6

    const-string v7, "getPackageInfo: mLoadedApk missing"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :ret
.end method

.method private bindRealApplication()V
    .locals 12

    iget-boolean v0, p0, Lcom/sakuqi/steady/SteadyApplication;->isBindReal:Z

    # 已经绑定过（true）才返回；false 是首次，必须往下执行。
    if-nez v0, :ret

    const/4 v0, 0x1

    iput-boolean v0, p0, Lcom/sakuqi/steady/SteadyApplication;->isBindReal:Z

    iget-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->app_name:Ljava/lang/String;

    invoke-static {v0}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v0

    # app_name 为空（isEmpty==true）才放弃绑定。
    if-nez v0, :ret

    const/4 v1, 0x0

    :try_start_0
    invoke-virtual {p0}, Landroid/content/ContextWrapper;->getBaseContext()Landroid/content/Context;

    move-result-object v1
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s1
    if-nez v1, :s2

    move-object v1, p0

    :s2
    const/4 v0, 0x0

    :try_start_1
    iget-object v2, p0, Lcom/sakuqi/steady/SteadyApplication;->app_name:Ljava/lang/String;

    invoke-static {v2}, Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;

    move-result-object v2

    invoke-virtual {v2}, Ljava/lang/Class;->newInstance()Ljava/lang/Object;

    move-result-object v2

    check-cast v2, Landroid/app/Application;

    move-object v0, v2

    iput-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->delegate:Landroid/app/Application;
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :s3
    if-eqz v0, :ret

    :try_start_2
    invoke-direct {p0, v0, v1}, Lcom/sakuqi/steady/SteadyApplication;->attachDelegate(Landroid/app/Application;Landroid/content/Context;)V
    :try_end_2
    .catch Ljava/lang/Throwable; {:try_start_2 .. :try_end_2} :catch_2

    :s4
    :try_start_3
    invoke-virtual {p0}, Landroid/content/Context;->getApplicationInfo()Landroid/content/pm/ApplicationInfo;

    move-result-object v2

    if-eqz v2, :s5

    iget-object v3, p0, Lcom/sakuqi/steady/SteadyApplication;->app_name:Ljava/lang/String;

    iput-object v3, v2, Landroid/content/pm/ApplicationInfo;->className:Ljava/lang/String;
    :try_end_3
    .catch Ljava/lang/Throwable; {:try_start_3 .. :try_end_3} :catch_3

    :s5
    :try_start_4
    const-string v2, "mOuterContext"

    invoke-static {v1, v2}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v2

    invoke-virtual {v2, v1, v0}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :try_end_4
    .catch Ljava/lang/Throwable; {:try_start_4 .. :try_end_4} :catch_4

    :s6
    const/4 v6, 0x0

    :try_start_5
    invoke-static {v1}, Lcom/sakuqi/steady/SteadyApplication;->getMainThread(Landroid/content/Context;)Ljava/lang/Object;

    move-result-object v6
    :try_end_5
    .catch Ljava/lang/Throwable; {:try_start_5 .. :try_end_5} :catch_5

    :s7
    :try_start_6
    if-eqz v6, :s8

    const-string v2, "mInitialApplication"

    invoke-static {v6, v2}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v2

    invoke-virtual {v2, v6, v0}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :try_end_6
    .catch Ljava/lang/Throwable; {:try_start_6 .. :try_end_6} :catch_6

    :s8
    :try_start_7
    if-eqz v6, :s9

    const-string v2, "mAllApplications"

    invoke-static {v6, v2}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v2

    invoke-virtual {v2, v6}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Ljava/util/ArrayList;

    if-eqz v3, :s9

    invoke-virtual {v3, p0}, Ljava/util/ArrayList;->remove(Ljava/lang/Object;)Z

    invoke-virtual {v3, v0}, Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z
    :try_end_7
    .catch Ljava/lang/Throwable; {:try_start_7 .. :try_end_7} :catch_7

    :s9
    :try_start_8
    invoke-static {v1}, Lcom/sakuqi/steady/SteadyApplication;->getPackageInfo(Landroid/content/Context;)Ljava/lang/Object;

    move-result-object v7

    if-eqz v7, :s10

    const-string v2, "mApplication"

    invoke-static {v7, v2}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v2

    invoke-virtual {v2, v7, v0}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :try_end_8
    .catch Ljava/lang/Throwable; {:try_start_8 .. :try_end_8} :catch_8

    :s10
    :try_start_9
    invoke-virtual {v0}, Landroid/app/Application;->onCreate()V
    :try_end_9
    .catch Ljava/lang/Throwable; {:try_start_9 .. :try_end_9} :catch_9

    :ret
    return-void

    :catch_0
    move-exception v8

    const-string v9, "bindRealApplication: getBaseContext failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s1

    :catch_1
    move-exception v8

    const-string v9, "bindRealApplication: newInstance failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s3

    :catch_2
    move-exception v8

    const-string v9, "bindRealApplication: attach failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s4

    :catch_3
    move-exception v8

    const-string v9, "bindRealApplication: set ApplicationInfo.className failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s5

    :catch_4
    move-exception v8

    const-string v9, "bindRealApplication: ContextImpl.mOuterContext failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s6

    :catch_5
    move-exception v8

    const-string v9, "bindRealApplication: getMainThread failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s7

    :catch_6
    move-exception v8

    const-string v9, "bindRealApplication: mInitialApplication failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s8

    :catch_7
    move-exception v8

    const-string v9, "bindRealApplication: mAllApplications failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s9

    :catch_8
    move-exception v8

    const-string v9, "bindRealApplication: LoadedApk.mApplication failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s10

    :catch_9
    move-exception v8

    const-string v9, "bindRealApplication: delegate onCreate failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :ret
.end method


# ------------------------------------------------------------------
# 公共方法：有 delegate 就委托，否则走真实实现（不再返回空串）
# ------------------------------------------------------------------
.method public getPackageName()Ljava/lang/String;
    .locals 1

    :try_start_0
    iget-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->delegate:Landroid/app/Application;

    # delegate 为空（还没绑定）才回退到 super。
    if-eqz v0, :super

    invoke-virtual {v0}, Landroid/app/Application;->getPackageName()Ljava/lang/String;

    move-result-object v0

    if-eqz v0, :super

    return-object v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :super
    invoke-super {p0}, Landroid/app/Application;->getPackageName()Ljava/lang/String;

    move-result-object v0

    return-object v0

    :catch_0
    move-exception v0

    invoke-super {p0}, Landroid/app/Application;->getPackageName()Ljava/lang/String;

    move-result-object v0

    return-object v0
.end method

# ------------------------------------------------------------------
# getApplication / getApplicationContext 委派
# 现代 App（尤其 Tinker 系）会写 (MyApplication) getApplication()，
# 而 framework 的 ContextImpl.mOuterContext 指向本壳，隐藏 API 被拦时改不动，
# 于是这里直接重写这两个公开方法返回 delegate，避免 ClassCastException。
# ------------------------------------------------------------------
.method public getApplication()Landroid/content/Context;
    .locals 1

    iget-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->delegate:Landroid/app/Application;

    if-eqz v0, :super

    return-object v0

    :super
    invoke-super {p0}, Landroid/content/ContextWrapper;->getApplication()Landroid/content/Context;

    move-result-object v0

    return-object v0
.end method

.method public getApplicationContext()Landroid/content/Context;
    .locals 1

    iget-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->delegate:Landroid/app/Application;

    if-eqz v0, :super

    return-object v0

    :super
    invoke-super {p0}, Landroid/content/ContextWrapper;->getApplicationContext()Landroid/content/Context;

    move-result-object v0

    return-object v0
.end method

.method public createPackageContext(Ljava/lang/String;I)Landroid/content/Context;
    .locals 1
    .param p1, "packageName"    # Ljava/lang/String;
    .param p2, "flags"    # I

    :try_start_0
    iget-object v0, p0, Lcom/sakuqi/steady/SteadyApplication;->delegate:Landroid/app/Application;

    # delegate 为空（还没绑定）才回退到 super。
    if-eqz v0, :super

    invoke-virtual {v0, p1, p2}, Landroid/content/Context;->createPackageContext(Ljava/lang/String;I)Landroid/content/Context;

    move-result-object v0

    if-eqz v0, :super

    return-object v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :super
    invoke-super {p0, p1, p2}, Landroid/content/ContextWrapper;->createPackageContext(Ljava/lang/String;I)Landroid/content/Context;

    move-result-object v0

    return-object v0

    :catch_0
    move-exception v0

    invoke-super {p0, p1, p2}, Landroid/content/ContextWrapper;->createPackageContext(Ljava/lang/String;I)Landroid/content/Context;

    move-result-object v0

    return-object v0
.end method
