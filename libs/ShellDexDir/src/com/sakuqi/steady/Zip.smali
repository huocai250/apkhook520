.class public Lcom/sakuqi/steady/Zip;
.super Ljava/lang/Object;
.source "Zip.java"


# direct methods
.method public constructor <init>()V
    .registers 1

    .prologue
    .line 15
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

.method private static compress(Ljava/io/File;Ljava/util/zip/ZipOutputStream;Ljava/lang/String;)V
    .registers 9
    .param p0, "srcFile"    # Ljava/io/File;
    .param p1, "zos"    # Ljava/util/zip/ZipOutputStream;
    .param p2, "basePath"    # Ljava/lang/String;
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/lang/Exception;
        }
    .end annotation

    .prologue
    .line 102
    invoke-virtual {p0}, Ljava/io/File;->isDirectory()Z

    move-result v2

    if-eqz v2, :cond_31

    .line 103
    invoke-virtual {p0}, Ljava/io/File;->listFiles()[Ljava/io/File;

    move-result-object v1

    .line 104
    .local v1, "files":[Ljava/io/File;
    array-length v3, v1

    const/4 v2, 0x0

    :goto_c
    if-ge v2, v3, :cond_34

    aget-object v0, v1, v2

    .line 106
    .local v0, "file":Ljava/io/File;
    new-instance v4, Ljava/lang/StringBuilder;

    invoke-direct {v4}, Ljava/lang/StringBuilder;-><init>()V

    invoke-virtual {v4, p2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v4

    invoke-virtual {p0}, Ljava/io/File;->getName()Ljava/lang/String;

    move-result-object v5

    invoke-virtual {v4, v5}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v4

    const-string v5, "/"

    invoke-virtual {v4, v5}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v4

    invoke-virtual {v4}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v4

    invoke-static {v0, p1, v4}, Lcom/sakuqi/steady/Zip;->compress(Ljava/io/File;Ljava/util/zip/ZipOutputStream;Ljava/lang/String;)V

    .line 104
    add-int/lit8 v2, v2, 0x1

    goto :goto_c

    .line 109
    .end local v0    # "file":Ljava/io/File;
    .end local v1    # "files":[Ljava/io/File;
    :cond_31
    invoke-static {p0, p1, p2}, Lcom/sakuqi/steady/Zip;->compressFile(Ljava/io/File;Ljava/util/zip/ZipOutputStream;Ljava/lang/String;)V

    .line 111
    :cond_34
    return-void
.end method

.method private static compressFile(Ljava/io/File;Ljava/util/zip/ZipOutputStream;Ljava/lang/String;)V
    .registers 16
    .param p0, "file"    # Ljava/io/File;
    .param p1, "zos"    # Ljava/util/zip/ZipOutputStream;
    .param p2, "dir"    # Ljava/lang/String;
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/lang/Exception;
        }
    .end annotation

    .prologue
    const/16 v12, 0x800

    const/4 v11, 0x1

    const/4 v10, 0x0

    .line 116
    new-instance v8, Ljava/lang/StringBuilder;

    invoke-direct {v8}, Ljava/lang/StringBuilder;-><init>()V

    invoke-virtual {v8, p2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v8

    invoke-virtual {p0}, Ljava/io/File;->getName()Ljava/lang/String;

    move-result-object v9

    invoke-virtual {v8, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    move-result-object v8

    invoke-virtual {v8}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v4

    .line 118
    .local v4, "fullName":Ljava/lang/String;
    const-string v8, "/"

    invoke-virtual {v4, v8}, Ljava/lang/String;->split(Ljava/lang/String;)[Ljava/lang/String;

    move-result-object v2

    .line 120
    .local v2, "fileNames":[Ljava/lang/String;
    new-instance v7, Ljava/lang/StringBuffer;

    invoke-direct {v7}, Ljava/lang/StringBuffer;-><init>()V

    .line 121
    .local v7, "sb":Ljava/lang/StringBuffer;
    array-length v8, v2

    if-le v8, v11, :cond_38

    .line 122
    const/4 v5, 0x1

    .local v5, "i":I
    :goto_28
    array-length v8, v2

    if-ge v5, v8, :cond_3d

    .line 123
    const-string v8, "/"

    invoke-virtual {v7, v8}, Ljava/lang/StringBuffer;->append(Ljava/lang/String;)Ljava/lang/StringBuffer;

    .line 124
    aget-object v8, v2, v5

    invoke-virtual {v7, v8}, Ljava/lang/StringBuffer;->append(Ljava/lang/String;)Ljava/lang/StringBuffer;

    .line 122
    add-int/lit8 v5, v5, 0x1

    goto :goto_28

    .line 127
    .end local v5    # "i":I
    :cond_38
    const-string v8, "/"

    invoke-virtual {v7, v8}, Ljava/lang/StringBuffer;->append(Ljava/lang/String;)Ljava/lang/StringBuffer;

    .line 130
    :cond_3d
    new-instance v1, Ljava/util/zip/ZipEntry;

    invoke-virtual {v7, v11}, Ljava/lang/StringBuffer;->substring(I)Ljava/lang/String;

    move-result-object v8

    invoke-direct {v1, v8}, Ljava/util/zip/ZipEntry;-><init>(Ljava/lang/String;)V

    .line 131
    .local v1, "entry":Ljava/util/zip/ZipEntry;
    invoke-virtual {p1, v1}, Ljava/util/zip/ZipOutputStream;->putNextEntry(Ljava/util/zip/ZipEntry;)V

    .line 133
    new-instance v3, Ljava/io/FileInputStream;

    invoke-direct {v3, p0}, Ljava/io/FileInputStream;-><init>(Ljava/io/File;)V

    .line 135
    .local v3, "fis":Ljava/io/FileInputStream;
    new-array v0, v12, [B

    .line 136
    .local v0, "data":[B
    :goto_50
    invoke-virtual {v3, v0, v10, v12}, Ljava/io/FileInputStream;->read([BII)I

    move-result v6

    .local v6, "len":I
    const/4 v8, -0x1

    if-eq v6, v8, :cond_5b

    .line 137
    invoke-virtual {p1, v0, v10, v6}, Ljava/util/zip/ZipOutputStream;->write([BII)V

    goto :goto_50

    .line 139
    :cond_5b
    invoke-virtual {v3}, Ljava/io/FileInputStream;->close()V

    .line 140
    invoke-virtual {p1}, Ljava/util/zip/ZipOutputStream;->closeEntry()V

    .line 141
    return-void
.end method

.method public static deleteFile(Ljava/io/File;)V
    .registers 5
    .param p0, "file"    # Ljava/io/File;

    .prologue
    .line 18
    invoke-virtual {p0}, Ljava/io/File;->isDirectory()Z

    move-result v2

    if-eqz v2, :cond_16

    .line 19
    invoke-virtual {p0}, Ljava/io/File;->listFiles()[Ljava/io/File;

    move-result-object v1

    .line 20
    .local v1, "files":[Ljava/io/File;
    array-length v3, v1

    const/4 v2, 0x0

    :goto_c
    # 循环结束后要去 :cond_16 删掉目录自身（原来跳 :cond_19 直接 return，目录永远留着）
    if-ge v2, v3, :cond_16

    aget-object v0, v1, v2

    .line 21
    .local v0, "f":Ljava/io/File;
    invoke-static {v0}, Lcom/sakuqi/steady/Zip;->deleteFile(Ljava/io/File;)V

    .line 20
    add-int/lit8 v2, v2, 0x1

    goto :goto_c

    .line 24
    .end local v0    # "f":Ljava/io/File;
    .end local v1    # "files":[Ljava/io/File;
    :cond_16
    invoke-virtual {p0}, Ljava/io/File;->delete()Z

    .line 26
    :cond_19
    return-void
.end method

# 重写版 unZip：只解根目录 classes*.dex（壳自己的 classes.dex 不要），
# 每个条目独立 try/catch，单条失败不影响其它条目；64KB buffer。
.method public static unZip(Ljava/io/File;Ljava/io/File;)V
    # 注意：invoke-* 是 35c 格式，寄存器只能编码 v0..v15（4 bit）。
    # 本方法有 2 个参数，locals 必须 ≤14，否则 p0/p1 落到 v16/v17 装不进指令。
    .locals 14
    .param p0, "apk"    # Ljava/io/File;
    .param p1, "destDir"    # Ljava/io/File;

    const/4 v0, 0x0

    const/4 v1, 0x0

    :try_start_open
    # 先清掉上一次留下的旧 dex，避免新旧混装
    invoke-static {p1}, Lcom/sakuqi/steady/Zip;->deleteFile(Ljava/io/File;)V

    invoke-virtual {p1}, Ljava/io/File;->mkdirs()Z

    move-result v2

    new-instance v0, Ljava/util/zip/ZipFile;

    invoke-direct {v0, p0}, Ljava/util/zip/ZipFile;-><init>(Ljava/io/File;)V

    invoke-virtual {v0}, Ljava/util/zip/ZipFile;->entries()Ljava/util/Enumeration;

    move-result-object v1
    :try_end_open
    .catch Ljava/lang/Throwable; {:try_start_open .. :try_end_open} :catch_open

    :loop
    :try_start_next
    invoke-interface {v1}, Ljava/util/Enumeration;->hasMoreElements()Z

    move-result v2

    if-eqz v2, :close_and_ret

    invoke-interface {v1}, Ljava/util/Enumeration;->nextElement()Ljava/lang/Object;

    move-result-object v2

    check-cast v2, Ljava/util/zip/ZipEntry;

    invoke-virtual {v2}, Ljava/util/zip/ZipEntry;->isDirectory()Z

    move-result v3

    # 目录条目直接跳过（true 才跳），之前写成 if-eqz 导致所有文件条目被跳过
    if-nez v3, :loop

    invoke-virtual {v2}, Ljava/util/zip/ZipEntry;->getName()Ljava/lang/String;

    move-result-object v3

    # 加密 dex 放在 assets/apkhook/dex/ 下（不能叫 classesN.dex，
    # 否则 ART 打开 APK 时会把它们当成真 dex，直接整包加载失败）。
    const-string v4, "assets/apkhook/dex/"

    invoke-virtual {v3, v4}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z

    move-result v4

    if-eqz v4, :loop

    const-string v4, ".bin"

    invoke-virtual {v3, v4}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z

    move-result v4

    if-eqz v4, :loop

    # 取出 basename：从最后一个 '/' 之后开始
    const/16 v4, 0x2f

    invoke-virtual {v3, v4}, Ljava/lang/String;->lastIndexOf(I)I

    move-result v4

    add-int/lit8 v4, v4, 0x1

    invoke-virtual {v3, v4}, Ljava/lang/String;->substring(I)Ljava/lang/String;

    move-result-object v3

    new-instance v4, Ljava/io/File;

    invoke-direct {v4, p1, v3}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    invoke-virtual {v0, v2}, Ljava/util/zip/ZipFile;->getInputStream(Ljava/util/zip/ZipEntry;)Ljava/io/InputStream;

    move-result-object v5

    new-instance v6, Ljava/io/FileOutputStream;

    invoke-direct {v6, v4}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;)V

    const/16 v7, 0x4000

    new-array v7, v7, [B

    :copy
    invoke-virtual {v5, v7}, Ljava/io/InputStream;->read([B)I

    move-result v8

    const/4 v9, -0x1

    if-ne v8, v9, :copy_done

    const/4 v9, 0x0

    invoke-virtual {v6, v7, v9, v8}, Ljava/io/FileOutputStream;->write([BII)V

    goto :copy

    :copy_done
    invoke-virtual {v6}, Ljava/io/FileOutputStream;->flush()V

    invoke-virtual {v6}, Ljava/io/FileOutputStream;->close()V

    invoke-virtual {v5}, Ljava/io/InputStream;->close()V
    :try_end_next
    .catch Ljava/lang/Throwable; {:try_start_next .. :try_end_next} :catch_entry

    goto :loop

    :catch_entry
    move-exception v10

    const-string v11, "unZip: one entry failed, skipped"

    invoke-static {v11, v10}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    goto :loop

    :close_and_ret
    :try_start_close
    invoke-virtual {v0}, Ljava/util/zip/ZipFile;->close()V
    :try_end_close
    .catch Ljava/lang/Throwable; {:try_start_close .. :try_end_close} :catch_close

    return-void

    :catch_close
    move-exception v10

    const-string v11, "unZip: close failed"

    invoke-static {v11, v10}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void

    :catch_open
    move-exception v10

    const-string v11, "unZip: open apk failed"

    invoke-static {v11, v10}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    return-void
.end method

.method public static zip(Ljava/io/File;Ljava/io/File;)V
    .registers 6
    .param p0, "dir"    # Ljava/io/File;
    .param p1, "zip"    # Ljava/io/File;
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/lang/Exception;
        }
    .end annotation

    .prologue
    .line 82
    invoke-virtual {p1}, Ljava/io/File;->delete()Z

    .line 84
    new-instance v0, Ljava/util/zip/CheckedOutputStream;

    new-instance v2, Ljava/io/FileOutputStream;

    invoke-direct {v2, p1}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;)V

    new-instance v3, Ljava/util/zip/CRC32;

    invoke-direct {v3}, Ljava/util/zip/CRC32;-><init>()V

    invoke-direct {v0, v2, v3}, Ljava/util/zip/CheckedOutputStream;-><init>(Ljava/io/OutputStream;Ljava/util/zip/Checksum;)V

    .line 86
    .local v0, "cos":Ljava/util/zip/CheckedOutputStream;
    new-instance v1, Ljava/util/zip/ZipOutputStream;

    invoke-direct {v1, v0}, Ljava/util/zip/ZipOutputStream;-><init>(Ljava/io/OutputStream;)V

    .line 88
    .local v1, "zos":Ljava/util/zip/ZipOutputStream;
    const-string v2, ""

    invoke-static {p0, v1, v2}, Lcom/sakuqi/steady/Zip;->compress(Ljava/io/File;Ljava/util/zip/ZipOutputStream;Ljava/lang/String;)V

    .line 89
    invoke-virtual {v1}, Ljava/util/zip/ZipOutputStream;->flush()V

    .line 90
    invoke-virtual {v1}, Ljava/util/zip/ZipOutputStream;->close()V

    .line 91
    return-void
.end method
