# multisim-ms14-builder

按一份 JSON 描述，自动生成 NI Multisim 14 电路文件（`.ms14`）：元件从 Multisim 自己的元件库取出，按固定规则摆好位置、改好名字；描述里写了网络（`nets`）时，还会自动布局并用实线连好线，连通性可用 Multisim 网表自动核对，还能导出只含电路本身的截图。适合数字电路实验课这类“每道题都要先放一堆芯片、开关、电源、指示灯”的场景。也可作为 MCP 服务接入 Agent。

Generate NI Multisim 14 schematic files (`.ms14`) from a small JSON description: parts are pulled from Multisim's own library, placed by layout rules and named; if nets are given, they are also wired automatically (solid wires on the default A sheet) and checked against Multisim's own netlist. Also usable as an MCP server.

> 本项目与 National Instruments 无关。Multisim 是 NI 的商标。

> 用 Codex、Claude Code、DeepSeek 等自动化 Agent 操作本工具时，先读 [AGENTS.md](AGENTS.md)，里面有逐步操作说明、常用元件的库名和禁止事项。

## 能做什么

- `ms14.py`：`.ms14` 与 XML 互相转换（纯 Python 实现 PKWARE DCL implode / explode，无第三方依赖）。
- `msedit.py`：在解压后的 XML 上复制、删除、移动、旋转元件。
- `build.py`：读 JSON 描述，一步生成放好元件（有 `nets` 时连好线）的 `.ms14`。
- `route.py`：网格布线器（A* + 斯坦纳树），开关到 VCC/GND 走两条平行总线。
- `wire_templates.xml`：连线、外部引脚、结点、网标、网络的 XML 模板，取自手工连好的电路。
- `netcheck.py`、`msreport.ps1`：用 Multisim 导出网表与 spec 比对，或导出整页电路图 PNG。
- `figure.py`：导出电路图并裁到电路范围；可选地用 Microsoft Word 插进实验报告（见“可选：插进实验报告”）。
- `restore_ws.py`：以一份完好的电路为参考，还原被 XML 规范化压平的多行属性值（见“已知限制与坑”）。
- `mcp_server.py`：把上面这些包成 MCP 工具（只用标准库）。
- `msapi.ps1`、`check.ps1`：通过 Multisim 自带的自动化接口替换元件、打开文件列出元件；脚本结束时只关闭自己启动的 Multisim 进程。

## 环境

- Windows，已安装 Multisim 14.3（需要它注册的 `MultisimInterface.MultisimApp` 自动化接口，这是 32 位 COM 组件，脚本通过 `C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe` 调用）。
- Python 3（64 位即可）。生成、连线、网表核对只用标准库；裁图需要 Pillow；可选的插报告功能另需 pywin32 和 Microsoft Word。

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

### 自动连线

在 JSON 里加 `nets`，每个网络列出它连接的所有引脚，写成 `元件名.引脚名`：

```json
"nets": {
  "VCC": ["VCC.VCC", "S1.3", "S2.3", "U2.G1"],
  "0":   ["0.1", "S1.1", "S2.1", "U1.~G"],
  "A":   ["S1.2", "U1.A", "U2.A"],
  "Y0":  ["U2.Y0", "X1.1"]
}
```

- 开关（SPDT）：`3` 左上脚接 VCC，`1` 左下脚接地，`2` 右侧输出。
- `VCC.VCC` 是电源；地元件名是 `0`，引脚 `1`。
- 指示灯 PROBE 只有引脚 `1`。
- 芯片用符号上的引脚名，低电平有效的带 `~`，如 `U1.~G`、`U2.~G2A`；芯片隐藏的 VCC/GND 脚不用写。
- 完整示例见 `specs/实验二_5-2_8选1数据选择器分析.json`。

核对连通性（导出 Multisim 网表，与 `nets` 按引脚集合逐个比对，全部一致时退出码为 0）：

```bash
python netcheck.py 输出.ms14 spec.json
```

导出只含电路本身的截图（需要 Pillow）：

```bash
python figure.py image 输出.ms14 电路图.png
```

Multisim 接口只能按 A 纸 960×720 导出（1 坐标单位 = 1 像素，没有更高分辨率或矢量格式）。脚本在图框内找出电路的实际范围，留一格白边裁下，再按最近邻放大 3 倍，放进文档缩放后文字不发虚。

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

写了 `nets` 时改用另一套布局，保证整张图落在默认 A 纸内：

| 元件 | 规则 |
|---|---|
| VCC、GROUND | 左上角 VCC，地在最后一个开关下方，两者各引一条竖直总线，VCC 在外、GND 在内，每个开关水平接出 |
| 输入开关 | 竖排，一列放不下时分两列错开 |
| 芯片、门 | 按信号流向分列：吃芯片输出的门在芯片右边一列，其余的门（如给芯片供反变量的反相器）在开关和芯片之间一列；各列竖直居中，列间走线通道至少 8 格 |
| 指示灯 | 芯片右侧横排，按驱动引脚高低排序；一行放不下时分上下两行 |

走线规则：全部实线，尽量直、少拐弯，允许交叉；多引脚网络在中途用 T 形结点分叉；芯片引脚前两格只留给本引脚的网络。

## 可选：插进实验报告

不写报告可以跳过这一节。需要 pywin32 和 Microsoft Word（通过 COM 独立启动一个 Word 实例，不碰已打开的窗口）。

```bash
python figure.py insert 报告.docx 电路图.png --section "（五）" --nth 2 --caption "8 选 1 数据选择器分析电路仿真电路"
python figure.py insert 报告.docx 电路图.png --section "（三）" --anchor "画出所设计的逻辑电路图"
```

- 先找以 `--section` 开头的题目，再往后数第 `--nth` 个以“电路图”结尾的小节；报告还没有这种小节时，用 `--anchor` 改找包含指定文字的段落。
- 图放在该段之后，宽度等于版心宽、等比缩放。那里已有图片就原位替换（保留图注），没有就新插图片段；给了 `--caption` 时再加居中图注。
- 会直接保存报告，插图前先备份。

## MCP 服务

`mcp_server.py` 是一个 stdio MCP 服务，只用标准库。它不操作 Multisim 界面：生成和编解码直接改文件，网表、截图、元件列表经 32 位 PowerShell 调 Multisim 自动化接口。

```bash
claude mcp add ms14gen -- python D:/路径/ms14gen/mcp_server.py
```

| 工具 | 作用 |
|---|---|
| `build_circuit` | 按 spec 生成 `.ms14`（输出已存在时需 `overwrite=true`） |
| `check_connectivity` | 网表与 spec 的 `nets` 比对 |
| `export_netlist` | 导出网表 |
| `export_image` | 导出整页 PNG |
| `export_figure` | 导出只含电路本身的截图 |
| `insert_figure` | 可选：把截图插进实验报告 |
| `list_components` | 列出元件 |
| `decode_ms14` / `encode_ms14` | `.ms14` 与 XML 互转 |

## 工作原理

1. **文件格式**：`.ms14` = 签名 `MSMCompressedElectronicsWorkbenchXML` + 总大小头 + 若干块（每块不超过 900000 字节，块头为解压/压缩大小），每块是 PKWARE DCL implode 压缩的 XML。
2. **元件来源**：XML 里的每个元件都带着完整的符号图形、引脚、仿真模型，手写不现实。做法是从底板 `base.ms14` 克隆一个开关当占位，再调用自动化接口的 `ReplaceComponent` 让 Multisim 把占位换成库里的任意元件，符号和模型由 Multisim 自己填好。
3. **方向修正**：开关符号带 `OrientationFlip=2`，替换出来的元件会继承这个翻转，导致元件倒置、标签错位；占位在替换前先扶正并把该标志清零。
4. **摆放与命名**：替换完成后再解压，在 XML 里按规则改坐标，并同步修改元件名、符号上的名字文字和 RefDes 记录。
5. **连线**：在网格上为每个网络布出一棵走线树，按 `wire_templates.xml` 写出连线（`CIITLinkComp`）、两端的外部引脚、分叉结点和网络（`CiNode`），并在引脚连接器与外部引脚的 `ConnectList` 里双向登记。

## 已知限制与坑

- 只能替换开关这类占位；直接用 `ReplaceComponent` 替换芯片会让接口崩溃。
- PowerShell 里 COM 方法的返回值要先赋给变量再使用，直接拼进字符串表达式也会崩溃。
- 自动连线只在默认 A 纸（960×720）内布局，放不下时直接报错退出，不会改图纸尺寸。
- 标签按 XML 坐标估算占位，开关切换键标签实际显示偏低，偶尔会被线压住，不影响连通性。
- 仿真模型、开关交互模型、仿真设置是写在属性值里的多行文本，XML 解析会把其中的换行换成空格，SPICE 随即报 `Invalid subckt definition`、`Unmatched ".ENDS"` 等错误，开关拨不动。`msedit.py` 现在读写时保留这些字符，`base.ms14` 里早先被压平的 83 处也已还原，新生成的文件不受影响。2026-11-13 之前生成的旧文件可以用 `restore_ws.py` 以一份能正常仿真的电路为参考还原（`python restore_ws.py 旧文件.ms14 还原.ms14 参考.ms14`）。网表核对和接口的 `RunSimulation` 都查不出这个问题，最终以 Multisim 里实际仿真为准。
- 部分中文文件名会让 Multisim 接口抛 `AccessViolationException`，并留下无窗口的 `/SimServer` 进程；核对网表、导图前把文件复制成英文名。

## 致谢

- [cinderblock/electronics-workbench-decoder](https://github.com/cinderblock/electronics-workbench-decoder) 与 [barncastle 的 MultiSimConverter](https://gist.github.com/barncastle/4277ac44aa47bf8c4389c7df0d160e56)：揭示了 `.ms14` 是 DCL 压缩的 XML 及其分块结构。
- DCL 解码所用的 Huffman 码表来自 zlib 的 `contrib/blast/blast.c`（Mark Adler，zlib 许可证）。

## 许可证

GPL-3.0，见 [LICENSE](LICENSE)。
