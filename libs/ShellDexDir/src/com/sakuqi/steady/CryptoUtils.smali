# 纯 Java 的 AES/ECB/PKCS5 解密，和打包端 utils/EncryptFile.py 完全一致。
#
# 为什么需要它：原壳解密只走 native（libsteady-lib.so 的 JNI 方法）。
# 一旦 .so 在设备上加载失败（ABI 不匹配、16KB 页、抽走 so 的加固方案），
# 壳就彻底没法解密 dex，宿主类全部找不到 → 打开即闪退，而且日志里只有
# 一条 loadLibrary 失败。改成「先 Java、失败再 native」，壳就不再依赖 so。
.class public final Lcom/sakuqi/steady/CryptoUtils;
.super Ljava/lang/Object;


# 与 utils/config.py 的 AESCryptKey 保持同步
.method public static decryptAes([B)[B
    .locals 4

    if-nez p0, :null

    :try_start_0
    const-string v0, "AES/ECB/PKCS5Padding"

    invoke-static {v0}, Ljavax/crypto/Cipher;->getInstance(Ljava/lang/String;)Ljavax/crypto/Cipher;

    move-result-object v0

    const-string v1, "huangdh'l,.AMWK;"

    const-string v2, "UTF-8"

    invoke-virtual {v1, v2}, Ljava/lang/String;->getBytes(Ljava/lang/String;)[B

    move-result-object v1

    new-instance v2, Ljavax/crypto/spec/SecretKeySpec;

    const-string v3, "AES"

    invoke-direct {v2, v1, v3}, Ljavax/crypto/spec/SecretKeySpec;-><init>([BLjava/lang/String;)V

    # 2 = Cipher.DECRYPT_MODE
    const/4 v1, 0x2

    invoke-virtual {v0, v1, v2}, Ljavax/crypto/Cipher;->init(ILjava/security/Key;)V

    invoke-virtual {v0, p0}, Ljavax/crypto/Cipher;->doFinal([B)[B

    move-result-object v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    return-object v0

    :catch_0
    move-exception v0

    const-string v1, "CryptoUtils: aes decrypt failed"

    invoke-static {v1, v0}, Lcom/sakuqi/steady/ProxyUtils;->logE(Ljava/lang/String;Ljava/lang/Throwable;)V

    :null
    const/4 v0, 0x0

    return-object v0
.end method
