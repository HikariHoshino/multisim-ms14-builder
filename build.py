"""按 JSON 描述生成放好元件、不连线的 ms14，坐标按固定规则自动计算。

用法：python build.py spec.json 输出.ms14
spec.json 只写有哪些元件，不写坐标：
{
  "switches": 3,                      # 输入开关个数，1～3，切换键依次为 A、B、C
  "parts": [
    {"name": "U1", "role": "chip",  "lib": ["TTL", "74LS", "74LS153N"]},
    {"name": "U2", "role": "gate",  "lib": ["TTL", "74LS", "74LS00N"]},
    {"name": "D",  "role": "probe", "lib": ["Indicators", "PROBE", "PROBE_DIG_RED"]}
  ]
}
role：chip 主芯片（从左到右排一行），gate 门电路（排在芯片下方一行），probe 指示灯（最右一列）。
布局常量见下方 LAYOUT，规则写在项目说明文档的“文件构建规范”里。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ms14  # noqa: E402
import msedit  # noqa: E402

PS32 = r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"

LAYOUT = {
    "grid": 9,
    "vcc": (54, 54),          # VCC 符号原点
    "sw_x": 243,              # 开关边框右下角 x
    "sw_y0": 252,             # 第一个开关边框右下角 y
    "sw_step": 99,            # 开关固定间距
    "col_gap": 36,            # 开关列到芯片列的水平间隔
    "chip_y": 153,            # 芯片顶部 y
    "chip_gap": 108,          # 芯片之间的水平间隔
    "row_gap": 54,            # 芯片底部到门电路行的垂直间隔
    "gate_gap": 36,           # 门电路之间的水平间隔
    "probe_gap": 117,         # 最右元件到指示灯列的水平间隔
    "probe_step": 81,         # 指示灯固定间距
}


def snap(v):
    g = LAYOUT["grid"]
    return int(round(v / g)) * g


def origin(c, name):
    t = c.graphic_of(c.components()[name])[0]
    if "Transformer-M20" in t.attrib:
        return float(t.attrib["Transformer-M20"]), float(t.attrib["Transformer-M21"])
    br = next(e for e in t.iter("CIITSymbolBorderRect"))
    return float(br.attrib["Transformer-M20"]), float(br.attrib["Transformer-M21"])


def place(c, name, x, y):
    x0, y0 = origin(c, name)
    c.move(name, snap(x) - x0, snap(y) - y0)


def rename(c, old, new):
    comp = c.components()[old][0]
    comp.attrib["LocalName"] = "&ASC" + new
    for e in c.root.iter():
        if e.attrib.get("Output") == "&ASC" + old:
            e.attrib["Output"] = "&ASC" + new
        rd = e.attrib.get("RefDes", "")
        tag = "!0" + old + "!0"
        if tag in rd:
            rd = rd.replace(tag, "!0" + new + "!0")
            e.attrib["RefDes"] = rd
            e.attrib["RefDesStrSize"] = str(len(rd.replace("&ASC", "")))
            e.attrib["Prefix"] = "&ASC" + new
            e.attrib["Number"] = "0"


def set_key(c, name, key):
    """开关切换键：CiComponent 参数表的第一个字符串，以及符号上“键 = X”的文字。"""
    it = c.components()[name]
    it[0].find(".//CiaParamList/strings/Item").attrib["Value"] = "&ASC" + key
    for e in c.graphic_of(it).iter("CIITSymTextCompValue"):
        e.attrib["Output"] = re.sub(r"= \w ", "= %s " % key, e.attrib["Output"])


def replace_parts(c, parts):
    """把扶正后的开关占位交给 Multisim 换成真实元件，返回 {占位名: 新名字} 和新电路。"""
    tmp = tempfile.mkdtemp()
    stage1, stage2, table = (os.path.join(tmp, f) for f in ("s1.ms14", "s2.ms14", "rep.txt"))
    open(stage1, "wb").write(ms14.encode(c.tobytes()))
    with open(table, "w", encoding="ascii") as f:
        for i, p in enumerate(parts):
            f.write("P%d|%s|%s\n" % (i + 1, p.get("section", ""), "|".join(p["lib"])))
    res = subprocess.run([PS32, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          os.path.join(HERE, "msapi.ps1"), stage1, stage2, table],
                         capture_output=True, text=True, timeout=300)
    print(res.stdout)
    if not os.path.exists(stage2):
        sys.exit("Multisim 替换失败：\n" + res.stderr[:2000])
    mapping = dict(re.findall(r"^(P\d+) -> (\S+)", res.stdout, re.M))
    return mapping, msedit.Circuit(ms14.decode(open(stage2, "rb").read()))


def main(spec_path, out_path):
    spec = json.load(open(spec_path, encoding="utf-8"))
    parts = spec["parts"]
    c = msedit.Circuit(ms14.decode(open(os.path.join(HERE, "base.ms14"), "rb").read()))
    for n in [n for n in c.components() if n.startswith("U")]:
        c.delete(n)
    # 占位从开关克隆后转正，替换出来的元件才是库里的原始朝向和默认标签位置
    for i in range(len(parts)):
        c.clone("S1", "P%d" % (i + 1))
        c.rotate180("P%d" % (i + 1))
        # 开关的 OrientationFlip=2，替换出来的元件会继承这个翻转，占位上必须清零
        c.graphic_of(c.components()["P%d" % (i + 1)])[0].attrib["OrientationFlip"] = "0"
    # 底板里 S2、S3 的内部结构和标签偏移与 S1 不一致，一律删掉，改由 S1 克隆
    c.delete("S2")
    c.delete("S3")
    switches = ["S%d" % (i + 1) for i in range(spec["switches"])]
    for i, n in enumerate(switches[1:], start=1):
        c.clone("S1", n)
        set_key(c, n, "ABCDEFGH"[i])
    mapping, c = replace_parts(c, parts)
    names = {}
    for i, p in enumerate(parts):
        n = mapping["P%d" % (i + 1)]
        if n != p["name"]:
            rename(c, n, p["name"])
        names[p["name"]] = p

    L = LAYOUT
    # 开关：固定列、固定间距；都由 S1 克隆，标签相对位置天然一致
    for i, n in enumerate(switches):
        place(c, n, L["sw_x"], L["sw_y0"] + i * L["sw_step"])
    last_sw_y = L["sw_y0"] + (len(switches) - 1) * L["sw_step"]
    place(c, "VCC", *L["vcc"])
    place(c, "0", L["vcc"][0], last_sw_y)
    # 芯片：开关列右侧，从左到右一行
    x = L["sw_x"] + L["col_gap"]
    right, bottom = x, L["chip_y"]
    for p in parts:
        if p["role"] == "chip":
            w, h = c.size(p["name"])
            place(c, p["name"], x, L["chip_y"])
            right, bottom = max(right, x + w), max(bottom, L["chip_y"] + h)
            x += w + L["chip_gap"]
    # 门电路：芯片下方一行
    x, gy = L["sw_x"] + L["col_gap"], bottom + L["row_gap"]
    for p in parts:
        if p["role"] == "gate":
            w, h = c.size(p["name"])
            place(c, p["name"], x, gy)
            right = max(right, x + w)
            x += w + L["gate_gap"]
    # 指示灯：最右一列，固定间距
    k = 0
    for p in parts:
        if p["role"] == "probe":
            place(c, p["name"], right + L["probe_gap"], L["chip_y"] + k * L["probe_step"])
            k += 1
    open(out_path, "wb").write(ms14.encode(c.tobytes()))
    print("written", out_path, list(c.components()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
