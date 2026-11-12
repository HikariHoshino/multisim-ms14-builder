# AGENTS.md — 给自动化 Agent 的操作手册

本文件写给 Codex、Claude Code、DeepSeek 等自动化编程 Agent。按顺序一步步执行，不要跳步，不要凭感觉改流程。每一步都写了“怎么判断成功”，没成功就停下来报告，不要继续往下做。

## 0. 这个项目是干什么的

输入：一份 JSON，列出一道电路题需要的元件（芯片、门、指示灯）和输入开关个数。
输出：一个 Multisim 14 的 `.ms14` 文件，元件已经放好、摆整齐、改好名字，**没有连线**。

你不需要理解电路原理。你只需要：写 JSON → 运行 `build.py` → 检查结果。

## 1. 先检查环境（每次开始任务时做一次）

逐条执行，全部通过才能继续。

1. 操作系统必须是 Windows。不是就停止，告诉用户本工具只能在 Windows 上运行。
2. 确认 Multisim 已安装且自动化接口已注册。在 PowerShell 里运行：
   ```powershell
   Test-Path 'Registry::HKEY_CLASSES_ROOT\MultisimInterface.MultisimApp'
   ```
   输出 `True` 才算通过。输出 `False` 就停止，告诉用户需要安装 Multisim 14.3。
3. 确认 32 位 PowerShell 存在：
   ```powershell
   Test-Path 'C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
   ```
   必须是 `True`。原因：Multisim 的自动化接口是 32 位 COM 组件，64 位 PowerShell 和 64 位 Python 都调不动它，只能通过这个 32 位 PowerShell。
4. 确认有 Python 3（64 位、32 位都可以），只用标准库，不需要 `pip install` 任何东西：
   ```bash
   python --version
   ```

## 2. 文件说明（先读，别乱改）

| 文件 | 作用 | 你需要改吗 |
|---|---|---|
| `build.py` | 主程序：读 JSON，生成 `.ms14` | 一般不改。只有用户要求调整布局时，才改里面的 `LAYOUT` 常量 |
| `ms14.py` | `.ms14` 和 XML 互相转换 | 不改 |
| `msedit.py` | 在 XML 里复制、删除、移动、旋转元件 | 不改 |
| `msapi.ps1` | 调 Multisim 接口把占位换成真实元件 | 不改 |
| `check.ps1` | 用 Multisim 打开一个文件，列出里面的元件 | 不改 |
| `base.ms14` | 底板：含 1 个开关、VCC、GROUND 等，所有元件都从这里派生 | **绝对不改** |
| `specs/*.json` | 每道题的元件描述 | 你新建的 JSON 放这里 |

## 3. 写 JSON 描述

在 `specs/` 下新建一个文件，例如 `specs/my_circuit.json`。格式：

```json
{
  "switches": 3,
  "parts": [
    {"name": "U1", "role": "chip",  "lib": ["TTL", "74LS", "74LS153N"]},
    {"name": "U2", "role": "gate",  "lib": ["TTL", "74LS", "74LS00N"]},
    {"name": "D",  "role": "probe", "lib": ["Indicators", "PROBE", "PROBE_DIG_RED"]}
  ]
}
```

字段逐个解释：

- `switches`：整数，输入开关（单刀双掷 SPDT）的个数。生成后名字依次是 S1、S2、S3……，切换键依次是 A、B、C……。
- `parts`：列表，除开关、VCC、GROUND 以外的所有元件。**顺序有意义**：同一种 role 的元件按列表顺序从左到右（芯片、门）或从上到下（指示灯）排列。
- `name`：生成后元件在 Multisim 里显示的名字。芯片和门用 U1、U2……；指示灯可以直接写题目里的输出名，如 `D`、`Bo`、`Y`。名字不能重复。
- `role`：只能是下面三个之一：
  - `chip`：主芯片，如 74LS138N、74LS151N、74LS153N。排在开关右侧一行。
  - `gate`：门电路，如 74LS00N（与非门）、74LS20N。排在芯片下方一行。
  - `probe`：指示灯。排在最右边一列。
- `lib`：三个字符串，依次是 Multisim 元件库的 **组（Group）/ 系列（Family）/ 型号（Component）**。

### 3.1 `lib` 怎么填（最容易出错的地方）

常用元件直接抄下表，不要自己编：

| 元件 | lib |
|---|---|
| 74LS00N 四二输入与非门 | `["TTL", "74LS", "74LS00N"]` |
| 74LS04N 六反相器 | `["TTL", "74LS", "74LS04N"]` |
| 74LS20N 双四输入与非门 | `["TTL", "74LS", "74LS20N"]` |
| 74LS86N 四异或门 | `["TTL", "74LS", "74LS86N"]` |
| 74LS138N 3-8 线译码器 | `["TTL", "74LS", "74LS138N"]` |
| 74LS151N 8 选 1 数据选择器 | `["TTL", "74LS", "74LS151N"]` |
| 74LS153N 双 4 选 1 数据选择器 | `["TTL", "74LS", "74LS153N"]` |
| 红色数字指示灯 | `["Indicators", "PROBE", "PROBE_DIG_RED"]` |

规则：
- 74LS 系列一律用带 `N` 后缀的型号（DIP 封装、简化符号），除非用户另有要求。
- 表里没有的元件：让用户在 Multisim 的“放置元件”对话框里查到 组 / 系列 / 元件 三栏的名字告诉你，不要猜。
- 写错名字时 `build.py` 会报 Multisim 替换失败，见第 6 节。

## 4. 生成文件

在本仓库目录下运行：

```bash
python build.py specs/my_circuit.json 输出路径/my_circuit.ms14
```

运行大约 30～60 秒，因为要在后台启动一次 Multisim。

**怎么判断成功**：
1. 标准输出里每个占位都有一行 `P1 -> U1`、`P2 -> U2`……，箭头右边是 Multisim 分配的名字，不是空的。
2. 最后一行是 `written <输出路径> [...]`，方括号里的名字列表包含你在 JSON 里写的所有 `name`，以及 S1…Sn、VCC、0（0 就是 GROUND）。
3. 输出文件确实存在。

三条都满足才算成功。

## 5. 检查生成结果（可选，但第一次用时建议做）

```powershell
C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File check.ps1 "完整路径\my_circuit.ms14"
```

输出第一行是 `name: my_circuit`，后面逐行列出元件名。和 JSON 对得上就说明 Multisim 能正常打开这个文件。

画面布局（方向、标签、间距）脚本检查不了，交给用户用 Multisim 打开看。

## 6. 出错了怎么办

| 现象 | 原因 | 处理 |
|---|---|---|
| `Multisim 替换失败` | `lib` 名字写错，或 Multisim 没装好 | 核对 `lib` 三个名字；还不行就把报错原文给用户 |
| 某行 `P3 -> ` 箭头右边是空的 | 这个占位的 `lib` 在库里找不到 | 只改这一个元件的 `lib`，重跑 |
| PowerShell 报 `AccessViolationException` | 调 COM 方法的写法不对（见第 7 节） | 不要改 `msapi.ps1`；如果是你自己写的脚本，按第 7 节改 |
| 生成的文件里元件倒置、标签错位 | 你绕过了 `build.py` 自己拼流程 | 回到用 `build.py` 生成 |

## 7. 绝对不要做的事

1. **不要用 `ReplaceComponent` 直接替换芯片**。只能替换开关类占位，替换芯片会让接口崩溃。`build.py` 已经按这个规矩做了，不要自己另写。
2. **不要把 COM 方法的返回值直接拼进字符串**。在 PowerShell 里必须先赋值给变量再用：
   ```powershell
   $r = $c.ReplaceComponent(...)   # 对
   "结果 " + $c.ReplaceComponent(...)   # 错，会崩溃
   ```
3. **不要强制结束用户自己开着的 Multisim**。脚本只会关掉自己启动的进程（启动前记下已有进程号，结束时只关新增的），你也照这个规矩做。
4. **不要覆盖用户正在 Multisim 里编辑的文件**。覆盖前先确认磁盘上的文件自你上次生成后没被用户保存过；用户开着它的话，提醒对方不保存关闭后再重新打开。
5. **不要修改 `base.ms14`**。所有元件都从它派生，改坏了整个工具就不能用了。
6. **不要在 JSON 里写坐标**。位置由 `build.py` 按规则计算；要调布局，只改 `build.py` 里的 `LAYOUT` 常量，并告诉用户你改了哪个值。
7. **不要尝试让本工具连线**。当前版本只放元件。

## 8. 原理速览（排查疑难问题时再读）

1. `.ms14` = 签名 `MSMCompressedElectronicsWorkbenchXML` + 总大小头 + 若干块；每块是 PKWARE DCL implode 压缩的 XML，块头写着解压/压缩大小。`python ms14.py decode a.ms14 a.xml` 可以解出来看。
2. 每个元件在 XML 里由三部分组成：`Elements` 下的 `CiComponent`（逻辑元件）、若干 `CiPort`（引脚），以及 `Components/CODComposite/Objects` 下的符号图形（`CIITSymbolComp` 或开关用的 `CIITAnimationSymbolComp`），彼此用数字 ID 互相引用。`msedit.clone` 复制元件时会把这些 ID 全部换新。
3. 元件的符号、引脚、仿真模型都来自 Multisim 的元件库，手写不现实，所以由 Multisim 的 `ReplaceComponent` 填进来。
4. 开关符号带 `OrientationFlip=2`，替换出来的元件会继承这个翻转，所以占位在替换前先扶正、把该标志清零。开关自己保留 `OrientationFlip=2`，那是它的正常朝向。
5. 普通元件的位置写在符号自身的 `Transformer-M20/M21` 上；开关符号没有自身变换，位置分散在各子对象上，以 `CIITSymbolBorderRect` 为基准移动。
