# 更新日志

本项目按「2.0 一次性重写」发布：中间迭代过的版本号（2.1、2.2.x 等）已合并，不再单独列出。

---

## 2.0.0 —— 相对最初版本（1.x）的重写

### 一句话

最初版本（1.1）能做到「注入 + 换壳」，但在 Android 11 及以上**装不上**，装上后**打开就闪退**，MSF 会话**连上就断**；
2.0 把这条链路从头到尾修通，并在 Android 13 / Android 17 真机上逐模式验证。

### 安装期（装不上 → 能装）

| 问题（1.x） | 2.0 的处理 |
|---|---|
| 所有条目都用 DEFLATE 打包，`resources.arsc` 被压缩 → Android 11+ 直接拒装 | `resources.arsc` 强制 STORE 并 4 字节对齐 |
| `.so` 按 4KB 页对齐 → Android 15+ 16KB 页设备拒装/崩溃 | `ElfAlign` 重排 ELF：所有段 `p_offset` 同步平移、`p_align` 抬到 16KB、section 偏移与 `e_shoff` 一致（`PT_DYNAMIC` 与 `.dynamic` 必须相等，否则 linker 拒载） |
| `targetSdk` 沿用原值，`≤22` 在 Android 14+ 拒装、`<24` 在 Android 15+ 拒装 | 低于 24 自动抬到 24，`--target-sdk` 可显式指定；`targetSdk ≥ 31` 时给带 `intent-filter` 的组件补 `android:exported` |
| 签名用旧 apksigner，只有 v1 | v1/v2/v3 全开（`--no-v1/2/3` 可关） |
| Windows/macOS 解包时**大小写重名条目**互相覆盖（混淆资源名的包有 300+ 组）→ 重打包丢条目、资源错乱、启动崩 | 冲突条目隔离到 `_apkhook_dup/<序号>/` + `namemap.json` 还原原名；逐条 CRC 校验到 0 差异 |
| 解包无路径校验（zip slip） | `safe_extract()` 校验 CRC、拒绝 `..`/绝对路径/加密条目 |

### 运行期（装上但起不来 → 能跑）

| 问题（1.x） | 2.0 的处理 |
|---|---|
| 壳里 12 处判断写反（`isBindReal`、`isEmpty(app_name)`、`hiddenApiExempted`、`getPackageName`、`delegate` 判空、`isEmpty(dex列表)`…），导致 dex 永不加载、delegate 永不绑定 | 全部改正为 `if-nez`/`if-eqz` 正确方向，并在真机 logcat 上逐条验证 |
| 解密只走 native `decrypt([B)[B`，`libsteady-lib.so` 加载失败就整包崩 | 新增纯 Java `CryptoUtils.decryptAes`（AES/ECB/PKCS5，与打包端同 key），native 仅作兜底 |
| dex 加载只有一条路，失败就白屏/闪退 | 三级兜底：`makePathElements` 4 参 → 3 参 → 自建 `PathClassLoader` 取 `dexElements` 合并回写 |
| 解密目标目录未 `mkdirs`、旧版本 dex 残留 → 首次启动必失败 / 版本升级后加载陈旧 dex | 先清目录再建，解密产物固定写 `dexDir/classesN.dex` |
| 加密 dex 仍叫 `classesN.dex` 放 APK 根目录 → ART 打开 APK 时把密文当真 dex，进程起来之前就失败 | 加密产物改名 `*.bin` 放 `assets/apkhook/dex/`，壳自己解出来（**这是「打开就闪退」的根因之一**） |
| 崩了没有任何日志 | 壳日志落 `Android/data/<包名>/files/steady.log`（含栈）；provider 注入路径另写 `apkhook_probe.log`；`--log` 落全量运行日志 |
| 切后台就被回收，会话断 | 模式 1/2/5/6 注入前台服务保活：清单加 `foregroundServiceType=dataSync`（并修正 AXML resource-map，否则平台把该属性读成 0）+ 通知渠道 + `startForeground(id, n, type)` |
| `getApplication()` 在注入后返回壳，`(MyApp) getApplication()` 抛 `ClassCastException` | 壳覆写 `getApplication()/getApplicationContext()` 返回 delegate |

### 注入逻辑（必坏 → 可用）

| 问题（1.x） | 2.0 的处理 |
|---|---|
| 生成的 smali 带字面 `{p0}` 当类描述符、`invoke-static` 插在 `.locals` 之前 → 汇编必失败 | 类描述符按 `com/a/b/c` 正确生成；指令统一插在 `.locals/.registers` 后 |
| payload 与宿主同一个 dex，方法数一超 64K 就汇编失败 | payload 独立成新 dex；多 dex 场景按编号倒序整体 `+1` 改名，槽位顺序严格 |
| 目标 dex 用字符串排序取（`classes2` > `classes`），常选错 | 在 dex 字节里按类描述符定位目标 dex；只处理命中的那一个 |
| 用 baksmali→smali 往返宿主 dex（**遇到 ktor 等库必崩**：`IncompatibleClassChangeError: Found interface ..., but class was expected`，零改动往返也能复现） | **宿主 dex 一律逐字节保留**（模式 2/4/5/6）；改为 ContentProvider 注入 / 壳反射启动 payload |
| 注入点只认 Activity | 优先 Application，其次 launcher Activity；都找不到再全量兜底 |
| payload 类名固定，静态特征明显 | 包名/类名随机化（`--seed` 可复现），并生成 try/catch guard，payload 抛异常不会带崩宿主 |

### MSF 链路（连上就断 → 会话建立）

| 问题（1.x） | 2.0 的处理 |
|---|---|
| stage 落在可写目录再 `DexClassLoader` → Android 14+ 拒绝加载动态代码，会话立刻 `Reason: Died` | 写入后 `File.setReadOnly()` 再加载 |
| payload 配置是 2021 年的定长布局，现代 meterpreter stage 用 `ConfigParser`/`TLVPacket` 解析 → `NegativeArraySizeException` | 按上游格式生成完整 meterpreter packet（xor key + guid + `PACKET_TYPE_CONFIG` + TLV：`SESSION_EXPIRY`/`UUID`/`SESSION_GUID`/`SESSION_FLAGS`/`C2` 组），并用上游 `ConfigParser` 验证 `PARSE_OK`；URL 另写 `0x1000` 偏移，供内置 stager 直读，避免在 smali 里复刻 TLV 解析 |
| stager 异常被吞，msfconsole 只有「not valid」 | `:catch` 无条件打 `Log.e("apkhook", "stager: stage load or exec failed", e)` |
| 没法脱离真 msf 自测 | `tools/fake_handler.py`：本地假 handler + stub stage，验证 stager 连接、只读落盘、`DexClassLoader` 加载执行 |

### 功能（1.x 没有的）

- 六种模式：`-m 1` 加固+注入 / `2` 只注入明文 / `3` 只加固 / `4` 只整备 / `5` 零改 dex 注入 / `6` 零改 dex + 加密 payload（推荐，Android 8+）；
- `--analyze` 体检：zip 完整性、对齐、每个 `.so` 的页对齐、dex 明文/密文、签名、**Android 5.0~17 兼容矩阵**与处置建议（有兼容问题退出码 2，可挂 CI）；
- `--dry-run` 计划预览；`--mode-help` 模式说明；`--about` 版本与归属；
- `--rename-package` / `--label` 马甲包；`--debuggable`；`--jobs` 并行；`--log` / `--quiet`；
- `--strict-compat` 兼容严格模式（默认策略是「能降级就降级」，例如 `minSdk < 26` 时 `-m 6` 自动改明文 payload）；
- 一键安装：`install.py` / `install.sh` / `install.bat`（体检、装 pip 依赖、下载 Temurin JDK 17、生成 `tools/env.*`、容器/CI 友好）；
- 产物报告 `report.json` + `handler.rc`，以及 `utils/ApkVerifier.py`、`utils/ElfAlign.py` 两个可直接调用的校验器。

### 已验证

- `tests/test_e2e.py`：**41 组全 PASS**（5 种 APK 形态 × 模式 1/2/3/5/6 + 12 组回归：模式 4、`--analyze`、`--dry-run`、马甲包、`--jobs/--log`、`--quiet`、安装器体检、大小写重名条目、模式说明、兼容降级/严格、MSF 配置 TLV、stager URL 偏移、stager 补丁、保活服务）；
- 真机矩阵（Android 13 / SDK 33 与 Android 17 / SDK 37）：`-m 2 / 4 / 5 / 6` 全部正常打开且 payload 连上；`-m 1 / 3` 仅 Android 5.0~9（Android 10+ 隐藏 API 全部 denied，实测必崩）；
- 后台保活：切桌面 90 秒后进程存活、`startForegroundCount=1`、TCP 连接仍在。

### 已知限制

- `-m 1` / `-m 3` 依赖隐藏 API（`VMRuntime.setHiddenApiExemptions`、`DexPathList.makePathElements`），Android 10 及以上不可用，请改用 `-m 6`；
- `-m 6` 需要 Android 8.0+（`InMemoryDexClassLoader`），低版本自动降级为明文 payload；
- 重签后签名必然变化：若原 App 有签名校验/加固壳自校验，需要额外处理；
- 只修安装期/运行期兼容性，不负责对抗目标 App 的完整性校验（native 层校验、服务端校验）。

### 原始版本（1.1）的已知问题（仅存档）

`resources.arsc` 压缩、`.so` 4KB 页对齐、签名仅 v1、壳里 12 处判断反转、加密 dex 放根目录、baksmali→smali 往返宿主 dex、payload 与宿主同 dex、MSF stage 落在可写目录且配置格式过时 —— 这些在 2.0 均已修复，详见上面各表。
