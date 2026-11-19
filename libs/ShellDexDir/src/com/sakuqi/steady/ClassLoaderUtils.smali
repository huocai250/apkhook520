.class public Lcom/sakuqi/steady/ClassLoaderUtils;
.super Ljava/lang/Object;
.source "ClassLoaderUtils.java"


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

# 把 dexDir 下所有 *.dex 加入 list（缓存命中时用）
.method public static addDexFiles(Ljava/io/File;Ljava/util/List;)V
    .locals 8
    .param p0, "dexDir"    # Ljava/io/File;
    .param p1, "out"    # Ljava/util/List;

    # 严格按 classes2 / classes3 / ... / classesN 的数字顺序收集，
    # 不能用 listFiles() 的返回顺序：文件系统顺序不可控，字典序会把
    # classes10.dex 排到 classes2.dex 前面，改变类解析优先级。
    :try_start_0
    const/4 v0, 0x2

    :loop
    const/16 v1, 0xc8

    if-lt v0, v1, :ret

    new-instance v3, Ljava/lang/StringBuilder;

    invoke-direct {v3}, Ljava/lang/StringBuilder;-><init>()V

    const-string v4, "classes"

    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v3, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    const-string v4, ".dex"

    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v3}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v3

    new-instance v2, Ljava/io/File;

    invoke-direct {v2, p0, v3}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    invoke-virtual {v2}, Ljava/io/File;->isFile()Z

    move-result v4

    if-nez v4, :skip

    invoke-interface {p1, v2}, Ljava/util/List;->add(Ljava/lang/Object;)Z

    :skip
    add-int/lit8 v0, v0, 0x1

    goto :loop
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :ret
    return-void

    :catch_0
    move-exception v6

    const-string v7, "addDexFiles failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method

    # 反射调用 DexPathList.makePathElements：先 3 参（API 23-25），再 4 参（API 26+）
    # p0 必须是 DexPathList 实例（不是 ClassLoader），否则 findMethod 沿类继承链永远找不到。
    .method private static makeDexElements(Ljava/lang/Object;Ljava/util/List;Ljava/io/File;)[Ljava/lang/Object;
    .locals 8
    .param p0, "pathList"    # Ljava/lang/Object;
    .param p1, "files"    # Ljava/util/List;
    .param p2, "optimizedDir"    # Ljava/io/File;

    const/4 v0, 0x0

    :try_start_0
    const/4 v1, 0x3

    new-array v1, v1, [Ljava/lang/Class;

    const/4 v2, 0x0

    const-class v3, Ljava/util/List;

    aput-object v3, v1, v2

    const/4 v2, 0x1

    const-class v3, Ljava/io/File;

    aput-object v3, v1, v2

    const/4 v2, 0x2

    const-class v3, Ljava/util/List;

    aput-object v3, v1, v2

    const-string v2, "makePathElements"

    invoke-static {p0, v2, v1}, Lcom/sakuqi/steady/ProxyUtils;->findMethod(Ljava/lang/Object;Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v1

    const/4 v2, 0x3

    new-array v2, v2, [Ljava/lang/Object;

    const/4 v3, 0x0

    aput-object p1, v2, v3

    const/4 v3, 0x1

    aput-object p2, v2, v3

    const/4 v3, 0x2

    new-instance v4, Ljava/util/ArrayList;

    invoke-direct {v4}, Ljava/util/ArrayList;-><init>()V

    aput-object v4, v2, v3

    invoke-virtual {v1, p0, v2}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s1
    if-nez v0, :done

    :try_start_1
    # 备用签名（API 26+）：makePathElements(List, File, List, ClassLoader)
    const/4 v1, 0x4

    new-array v1, v1, [Ljava/lang/Class;

    const/4 v2, 0x0

    const-class v3, Ljava/util/List;

    aput-object v3, v1, v2

    const/4 v2, 0x1

    const-class v3, Ljava/io/File;

    aput-object v3, v1, v2

    const/4 v2, 0x2

    const-class v3, Ljava/util/List;

    aput-object v3, v1, v2

    const/4 v2, 0x3

    const-class v3, Ljava/lang/ClassLoader;

    aput-object v3, v1, v2

    const-string v2, "makePathElements"

    invoke-static {p0, v2, v1}, Lcom/sakuqi/steady/ProxyUtils;->findMethod(Ljava/lang/Object;Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v1

    const/4 v2, 0x4

    new-array v2, v2, [Ljava/lang/Object;

    const/4 v3, 0x0

    aput-object p1, v2, v3

    const/4 v3, 0x1

    aput-object p2, v2, v3

    const/4 v3, 0x2

    new-instance v4, Ljava/util/ArrayList;

    invoke-direct {v4}, Ljava/util/ArrayList;-><init>()V

    aput-object v4, v2, v3

    const/4 v3, 0x3

    const/4 v4, 0x0

    aput-object v4, v2, v3

    invoke-virtual {v1, p0, v2}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v0
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    :s2
    :done
    check-cast v0, [Ljava/lang/Object;

    return-object v0

    :catch_0
    move-exception v6

    const-string v7, "makeDexElements: 3-arg makePathElements failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s1

    :catch_1
    move-exception v6

    const-string v7, "makeDexElements: 4-arg makePathElements failed"

    invoke-static {v7, v6}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :s2
.end method

# 合并 dexElements：新元素在前，保留原始组件类型
.method private static mergeElements([Ljava/lang/Object;[Ljava/lang/Object;)[Ljava/lang/Object;
    .locals 7
    .param p0, "oldArr"    # [Ljava/lang/Object;
    .param p1, "addArr"    # [Ljava/lang/Object;

    const/4 v0, 0x0

    if-eqz p0, :comp_from_add

    invoke-virtual {p0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    move-result-object v0

    invoke-virtual {v0}, Ljava/lang/Class;->getComponentType()Ljava/lang/Class;

    move-result-object v0

    goto :have_comp

    :comp_from_add
    if-eqz p1, :comp_object

    invoke-virtual {p1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    move-result-object v0

    invoke-virtual {v0}, Ljava/lang/Class;->getComponentType()Ljava/lang/Class;

    move-result-object v0

    goto :have_comp

    :comp_object
    const-class v0, Ljava/lang/Object;

    :have_comp
    const/4 v1, 0x0

    if-eqz p0, :len0

    array-length v1, p0

    :len0
    const/4 v2, 0x0

    if-eqz p1, :len1

    array-length v2, p1

    :len1
    add-int v3, v1, v2

    invoke-static {v0, v3}, Ljava/lang/reflect/Array;->newInstance(Ljava/lang/Class;I)Ljava/lang/Object;

    move-result-object v4

    check-cast v4, [Ljava/lang/Object;

    if-eqz p1, :copy_old

    const/4 v5, 0x0

    invoke-static {p1, v5, v4, v5, v2}, Ljava/lang/System;->arraycopy(Ljava/lang/Object;ILjava/lang/Object;II)V

    :copy_old
    if-eqz p0, :end

    const/4 v5, 0x0

    invoke-static {p0, v5, v4, v2, v1}, Ljava/lang/System;->arraycopy(Ljava/lang/Object;ILjava/lang/Object;II)V

    :end
    return-object v4
.end method

.method private static fallbackLoadDex(Landroid/app/Application;Ljava/lang/Object;Ljava/util/List;)V
    .locals 10
    .param p0, "app"    # Landroid/app/Application;
    .param p1, "pathList"    # Ljava/lang/Object;
    .param p2, "dexFiles"    # Ljava/util/List;

    :try_start_0
    new-instance v0, Ljava/lang/StringBuilder;

    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V

    const/4 v1, 0x0

    invoke-interface {p2}, Ljava/util/List;->size()I

    move-result v2

    :loop
    if-ge v1, v2, :built

    if-lez v1, :no_sep

    sget-object v3, Ljava/io/File;->pathSeparator:Ljava/lang/String;

    invoke-virtual {v0, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    :no_sep
    invoke-interface {p2, v1}, Ljava/util/List;->get(I)Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Ljava/io/File;

    invoke-virtual {v3}, Ljava/io/File;->getAbsolutePath()Ljava/lang/String;

    move-result-object v3

    invoke-virtual {v0, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    add-int/lit8 v1, v1, 0x1

    goto :loop

    :built
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    new-instance v1, Ldalvik/system/PathClassLoader;

    invoke-virtual {p0}, Landroid/app/Application;->getClassLoader()Ljava/lang/ClassLoader;

    move-result-object v2

    invoke-direct {v1, v0, v2}, Ldalvik/system/PathClassLoader;-><init>(Ljava/lang/String;Ljava/lang/ClassLoader;)V

    const-string v2, "pathList"

    invoke-static {v1, v2}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v2

    invoke-virtual {v2, v1}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v2

    if-eqz v2, :gave_up

    const-string v3, "dexElements"

    invoke-static {v2, v3}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v3

    invoke-virtual {v3, v2}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v3

    check-cast v3, [Ljava/lang/Object;

    if-eqz v3, :gave_up

    const-string v4, "dexElements"

    invoke-static {p1, v4}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v4

    invoke-virtual {v4, p1}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v5

    check-cast v5, [Ljava/lang/Object;

    invoke-static {v5, v3}, Lcom/sakuqi/steady/ClassLoaderUtils;->mergeElements([Ljava/lang/Object;[Ljava/lang/Object;)[Ljava/lang/Object;

    move-result-object v6

    if-eqz v6, :gave_up

    invoke-virtual {v4, p1, v6}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V

    const-string v7, "loadDex: fallback PathClassLoader injected"

    invoke-static {v7}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :gave_up
    return-void

    :catch_0
    move-exception v8

    const-string v9, "loadDex: fallback PathClassLoader failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method

.method public static loadDex(Landroid/app/Application;Ljava/util/List;Ljava/io/File;)V
    .locals 10
    .param p0, "app"    # Landroid/app/Application;
    .param p1, "dexFiles"    # Ljava/util/List;
    .param p2, "dexDir"    # Ljava/io/File;

    if-eqz p0, :ret

    if-eqz p1, :ret

    if-eqz p2, :ret

    invoke-interface {p1}, Ljava/util/List;->isEmpty()Z

    move-result v0

    if-nez v0, :body

    return-void

    :body
    const/4 v0, 0x0

    const/4 v2, 0x0

    :try_start_0
    invoke-virtual {p0}, Landroid/app/Application;->getClassLoader()Ljava/lang/ClassLoader;

    move-result-object v0

    const-string v1, "pathList"

    invoke-static {v0, v1}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v1

    invoke-virtual {v1, v0}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v2
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :s1
    if-eqz v2, :ret

    # 必须把 pathList（DexPathList 实例）传进去，不是 ClassLoader：
    # makePathElements 是 DexPathList 的静态方法，用 ClassLoader 找必然 NoSuchMethodException。
    invoke-static {v2, p1, p2}, Lcom/sakuqi/steady/ClassLoaderUtils;->makeDexElements(Ljava/lang/Object;Ljava/util/List;Ljava/io/File;)[Ljava/lang/Object;

    move-result-object v3

    if-eqz v3, :fallback

    :try_start_1
    const-string v4, "dexElements"

    invoke-static {v2, v4}, Lcom/sakuqi/steady/ProxyUtils;->findField(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/reflect/Field;

    move-result-object v4

    invoke-virtual {v4, v2}, Ljava/lang/reflect/Field;->get(Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v5

    check-cast v5, [Ljava/lang/Object;

    invoke-static {v5, v3}, Lcom/sakuqi/steady/ClassLoaderUtils;->mergeElements([Ljava/lang/Object;[Ljava/lang/Object;)[Ljava/lang/Object;

    move-result-object v6

    if-eqz v6, :fallback

    invoke-virtual {v4, v2, v6}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V

    const-string v7, "loadDex: dexElements injected"

    invoke-static {v7}, Lcom/sakuqi/steady/ProxyUtils;->logI(Ljava/lang/String;)V
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :catch_1

    return-void

    :fallback
    invoke-static {p0, v2, p1}, Lcom/sakuqi/steady/ClassLoaderUtils;->fallbackLoadDex(Landroid/app/Application;Ljava/lang/Object;Ljava/util/List;)V

    :ret
    return-void

    :catch_0
    move-exception v8

    const-string v9, "loadDex: pathList unavailable"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void

    :catch_1
    move-exception v8

    const-string v9, "loadDex: inject dexElements failed"

    invoke-static {v9, v8}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :fallback
.end method
