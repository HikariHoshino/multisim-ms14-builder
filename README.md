# multisim-ms14-builder

按一份 JSON 描述，自动生成 NI Multisim 14 电路文件（`.ms14`）：元件从 Multisim 自己的元件库取出，按固定规则摆好位置、改好名字，不连线。适合数字电路实验课这类“每道题都要先放一堆芯片、开关、电源、指示灯”的场景。

Generate NI Multisim 14 schematic files (`.ms14`) from a small JSON description: parts are pulled from Multisim's own library, placed by layout rules and named, but left unwired.

> 本项目与 National Instruments 无关。Multisim 是 NI 的商标。

> 用 Codex、Claude Code、DeepSeek 等自动化 Agent 操作本工具时，先读 [AGENTS.md](AGENTS.md)，里面有逐步操作说明、常用元件的库名和禁止事项。

## 能做什么

- `ms14.py`：`.ms14` 与 XML 互相转换（纯 Python 实现 PKWARE DCL implode / explode，无第三方依赖）。
- `msedit.py`：在解压后的 XML 上复制、删除、移动、旋转元件。
- `build.py`：读 JSON 描述，一步生成放好元件的 `.ms14`。
- `msapi.ps1`、`check.ps1`：通过 Multisim 自带的自动化接口替换元件、打开文件列出元件；脚本结束时只关闭自己启动的 Multisim 进程。

## 环境

- Windows，已安装 Multisim 14.3（需要它注册的 `MultisimInterface.MultisimApp` 自动化接口，这是 32 位 COM 组件，脚本通过 `C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe` 调用）。
- Python 3（64 位即可），只用标准库。

## 用法

```bash
python build.py specs/实验三_3_数据选择器全减器.json 输出.ms14
```

JSON 只写有哪些元件，不写坐标：

```json
{
  "switches": 3,
  "parts": [
    {"name": "U1", "role": "chip",  "lib": ["TTL", "74LS", "74LS153N"]},
    {"name": "U2", "role": "gate",  "lib": ["TTL", "74LS", "74LS00N"]},
    {"name": "D",  "role": "probe", "lib": ["Indicators", "PROBE", "PROBE_DIG_RED"]},
    {"name": "Bo", "role": "probe", "lib": ["Indicators", "PROBE", "PROBE_DIG_RED"]}
  ]
}
```

- `switches`：输入开关（SPDT）个数，切换键依次为 A、B、C……
- `lib`：Multisim 元件库里的 组 / 系列 / 型号，与“放置元件”对话框里看到的一致。
- `role`：`chip` 主芯片、`gate` 门电路、`probe` 指示灯，决定摆放位置。
- `name`：生成后的元件编号（RefDes），指示灯可以直接写输出名。

单独转换文件：

```bash
python ms14.py decode 电路.ms14 电路.xml
python ms14.py encode 电路.xml 电路.ms14
```

## 布局规则

坐标单位与 Multisim XML 一致，全部对齐 9 的网格；常量在 `build.py` 的 `LAYOUT` 里。

| 元件 | 规则 |
|---|---|
| VCC | 左上角固定点 |
| 输入开关 | 左侧竖排一列，固定间距；全部由同一个开关克隆，标签相对位置一致 |
| GROUND | 与 VCC 同列，和最下面的开关齐平 |
| 主芯片 | 开关列右侧，多片从左到右排一行 |
| 门电路 | 芯片下方排一行 |
| 指示灯 | 最右元件右侧竖排一列，固定间距 |

## 工作原理

1. **文件格式**：`.ms14` = 签名 `MSMCompressedElectronicsWorkbenchXML` + 总大小头 + 若干块（每块不超过 900000 字节，块头为解压/压缩大小），每块是 PKWARE DCL implode 压缩的 XML。
2. **元件来源**：XML 里的每个元件都带着完整的符号图形、引脚、仿真模型，手写不现实。做法是从底板 `base.ms14` 克隆一个开关当占位，再调用自动化接口的 `ReplaceComponent` 让 Multisim 把占位换成库里的任意元件，符号和模型由 Multisim 自己填好。
3. **方向修正**：开关符号带 `OrientationFlip=2`，替换出来的元件会继承这个翻转，导致元件倒置、标签错位；占位在替换前先扶正并把该标志清零。
4. **摆放与命名**：替换完成后再解压，在 XML 里按规则改坐标，并同步修改元件名、符号上的名字文字和 RefDes 记录。

## 已知限制与坑

- 只能替换开关这类占位；直接用 `ReplaceComponent` 替换芯片会让接口崩溃。
- PowerShell 里 COM 方法的返回值要先赋给变量再使用，直接拼进字符串表达式也会崩溃。
- 生成的文件只放元件，不连线。

## 致谢

- [cinderblock/electronics-workbench-decoder](https://github.com/cinderblock/electronics-workbench-decoder) 与 [barncastle 的 MultiSimConverter](https://gist.github.com/barncastle/4277ac44aa47bf8c4389c7df0d160e56)：揭示了 `.ms14` 是 DCL 压缩的 XML 及其分块结构。
- DCL 解码所用的 Huffman 码表来自 zlib 的 `contrib/blast/blast.c`（Mark Adler，zlib 许可证）。

## 许可证

GPL-3.0，见 [LICENSE](LICENSE)。
