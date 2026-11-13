"""按 JSON 描述生成放好元件的 ms14，坐标按固定规则自动计算；写了 nets 时自动布局并连线。

用法：python build.py spec.json 输出.ms14
spec.json 只写有哪些元件，不写坐标：
{
  "switches": 3,                      # 输入开关个数，最多 26，切换键依次为 A、B、C……
  "parts": [
    {"name": "U1", "role": "chip",  "lib": ["TTL", "74LS", "74LS153N"]},
    {"name": "U2", "role": "gate",  "lib": ["TTL", "74LS", "74LS00N"]},
    {"name": "D",  "role": "probe", "lib": ["Indicators", "PROBE", "PROBE_DIG_RED"]}
  ],
  "nets": {"A": ["S1.2", "U1.A"], ...}   # 可选，每个网络列出全部引脚，写法见 AGENTS.md 3.2
}
role：chip 主芯片（从左到右排一行），gate 门电路（排在芯片下方一行），probe 指示灯（最右一列）。
布局常量见下方 LAYOUT，规则写在项目说明文档的“文件构建规范”里；有 nets 时改用 arrange_wired 的 A 纸布局。
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
import route  # noqa: E402

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


def geometry(c):
    """{元件名: ({引脚名: (PortID, 连接器 Item, x, y)}, 本体矩形)}"""
    ports = {it.get("CiID"): it[0].get("LocalName").replace("&ASC", "")
             for it in c.elements.findall("Item[@Class='CiPort']")}
    geo = {}
    for name, it in c.components().items():
        pins, rect = route.symbol_geometry(c.graphic_of(it))
        geo[name] = ({ports[pid]: (pid, conn, x, y) for pid, conn, x, y in pins if pid in ports}, rect)
    return geo


def put_pin(c, name, pin, x, y):
    """移动元件，使它的引脚 pin 落在 (x, y)。"""
    _, _, px, py = geometry_of(c, name)[0][pin]
    c.move(name, snap(x - px), snap(y - py))


def geometry_of(c, name):
    ports = {it.get("CiID"): it[0].get("LocalName").replace("&ASC", "")
             for it in c.ports_of(c.components()[name])}
    pins, rect = route.symbol_geometry(c.graphic_of(c.components()[name]))
    return {ports[pid]: (pid, conn, x, y) for pid, conn, x, y in pins if pid in ports}, rect


def display_extent(c, name):
    """元件连同名字、数值、切换键标签在内的显示范围。"""
    g = c.graphic_of(c.components()[name])
    return route.extent(geometry_of(c, name)[1], route.label_boxes(g))


SHEET = (20, 20, 940, 700)      # A 纸（960×720）图框内边界


def arrange_wired(c, spec):
    """要连线时的布局（必须放进默认 A 纸）：
    开关一列放不下就分两列，第二列下错 3 格，让第一列的输出线从第二列两个开关之间穿过；
    芯片和门竖排一列；指示灯在芯片右侧，放不下一行就分上下两行。"""
    G, L = LAYOUT["grid"], LAYOUT
    parts, nets = spec["parts"], spec["nets"]
    switches = ["S%d" % (i + 1) for i in range(spec["switches"])]
    x0, y0, x1, y1 = SHEET
    place(c, "VCC", *L["vcc"])
    vx, vy = geometry_of(c, "VCC")[0]["VCC"][2:]
    # 开关：引脚 3 在上（接 VCC）、引脚 1 在下（接地）、引脚 2 是输出
    pitch, shift = 9 * G, 3 * G
    top = vy + 2 * G
    cap = int((y1 - 9 * G - top) // pitch) + 1        # 最下面还要放接地符号
    n = len(switches)
    cols = [switches] if n <= cap else [switches[:(n + 1) // 2], switches[(n + 1) // 2:]]
    if len(cols[-1]) > cap:
        sys.exit("开关太多，A 纸放不下：%d 个" % n)
    px = vx + 4 * G
    for ci, col in enumerate(cols):
        for i, s in enumerate(col):
            put_pin(c, s, "3", px, top + ci * shift + i * pitch)
        px = geometry_of(c, col[0])[0]["2"][2] + 6 * G
    last = geometry_of(c, cols[0][-1])[0]["1"][3]
    put_pin(c, "0", "1", vx + G, last + 3 * G)
    # 芯片和门按信号流向分列：吃芯片输出的门放在芯片右边一列，其余的门（如给芯片供反变量的反相器）
    # 放在开关和芯片之间一列；有芯片时芯片一列，各列竖直居中，列与列之间留走线通道
    sw_right = max(geometry_of(c, s)[0]["2"][2] for s in switches)
    chips = [p["name"] for p in parts if p["role"] == "chip"]
    gates = [p["name"] for p in parts if p["role"] == "gate"]
    chip_out = set()
    for ch in chips:
        pins, rect = geometry_of(c, ch)
        chip_out |= {(ch, n) for n, v in pins.items() if v[2] >= rect[2]}
    post = [g for g in gates if any(
        any((o, q) in chip_out for o, q in (r.split(".", 1) for r in refs)) and any(r.startswith(g + ".") for r in refs)
        for refs in nets.values())] if chips else []
    pre = [g for g in gates if g not in post]

    def links(a, b):
        """a、b 两组元件之间直接相连的网络数，决定中间走线通道的宽度。"""
        return sum(1 for refs in nets.values()
                   if any(r.split(".", 1)[0] in a for r in refs) and any(r.split(".", 1)[0] in b for r in refs))

    def channel(n):
        # 每根线一条竖道，再加芯片引脚门口保留的 2 格；线少时也至少留 8 格，否则拐不开
        return max(n + 2, 8) * G

    n_sig = sum(1 for refs in nets.values() if any(r.split(".", 1)[1] == "2" and r.startswith("S") for r in refs))
    right = sw_right
    for col, n in ((pre, n_sig), (chips, n_sig + links(pre, chips)), (post, links(chips, post))):
        if not col:
            continue
        cx = right + channel(n)
        exts = {s: display_extent(c, s) for s in col}
        total = sum(e[3] - e[1] for e in exts.values()) + 2 * G * (len(col) - 1)
        y = max(y0 + 2 * G, (y0 + y1 - total) / 2)
        for s in col:
            e, rect = exts[s], geometry_of(c, s)[1]
            c.move(s, snap(cx - rect[0]), snap(y - e[1]))
            e = display_extent(c, s)
            right = max(right, e[2])
            y = e[3] + 2 * G
    # 指示灯：按驱动线从上到下排序；上面一行引脚朝下、线从下方直上接入；下面一行线从侧面接入
    probes = [p["name"] for p in parts if p["role"] == "probe"]
    if not probes:
        return
    drive = {}
    for refs in nets.values():
        names = [r.split(".", 1) for r in refs]
        for comp, pin in names:
            if comp in probes:
                ys = [geometry_of(c, o)[0][p][3] for o, p in names if o != comp]
                drive[comp] = min(ys) if ys else 0
    order = sorted(probes, key=lambda p: drive.get(p, 0))
    e = display_extent(c, probes[0])
    ppx, ppy = geometry_of(c, probes[0])[0]["1"][2:]
    w, off_x = e[2] - e[0], ppx - e[0]
    step = -(-(w + G) // G) * G
    start = right + 2 * G
    per_row = int((x1 - start - w) // step) + 1
    if len(order) <= per_row:
        rows = [order]
    else:
        half = (len(order) + 1) // 2
        rows = [order[:half], order[half:][::-1]]
        if len(rows[0]) > per_row:
            sys.exit("指示灯太多，A 纸放不下：%d 个" % len(order))
    ys = [drive[p] for p in order]
    for k, p in enumerate(rows[0]):
        put_pin(c, p, "1", start + off_x + k * step, min(ys) - 3 * G)
    if len(rows) > 1:
        low = max(ys) + 2 * G + (ppy - e[1])
        for k, p in enumerate(rows[1]):
            put_pin(c, p, "1", start + off_x + k * step, low)


def wire_all(c, nets):
    """按 spec 的 nets 自动连线。nets: {网络名: ["元件.引脚", ...]}，引脚名用 Multisim 端口名。"""
    geo = geometry(c)
    labels = [b for it in c.components().values() for b in route.label_boxes(c.graphic_of(it))]
    r = route.Router([g[1] for g in geo.values()], labels)
    resolved = {}
    for net, refs in nets.items():
        lst = []
        for ref in refs:
            comp, pin = ref.split(".", 1)
            if comp not in geo or pin not in geo[comp][0]:
                sys.exit("找不到引脚 %s（%s 的引脚有：%s）" % (ref, comp, sorted(geo.get(comp, ({},))[0])))
            pid, conn, x, y = geo[comp][0][pin]
            lst.append((x, y, pid, conn, r.add_pin(x, y, geo[comp][1], net, reserve=comp.startswith("U")), comp))
        lst.sort(key=lambda p: (p[0], p[1]))      # 从最左边的引脚开始长
        resolved[net] = lst

    def span(net):
        xs = [p[0] for p in resolved[net]]
        ys = [p[1] for p in resolved[net]]
        return max(xs) - min(xs) + max(ys) - min(ys)

    # 先走电源和地（在开关左侧形成竖干线），再走芯片之间的线（最难绕），最后走开关出来的线；同类按跨度从短到长
    def order(n):
        if n.upper() in ("VCC", "0", "GND"):
            return 0
        return 2 if any(p[5].startswith("S") for p in resolved[n]) else 1

    # 电源干线：每列开关一根，先把所有网络、所有列的干线都画好，再把其余各列的干线接回第一列
    rails = {}
    for net in nets:
        lst = resolved[net]
        src = next((p[4] for p in lst if p[5] in ("VCC", "0")), None)
        taps = [p[4] for p in lst if p[5].startswith("S") and r.pin_dir[p[4]] == (-1, 0)]
        if not (src and taps):
            continue
        groups = {}
        for t in taps:
            groups.setdefault(t[0], []).append(t)
        xs = sorted(groups)
        off = xs[0] - src[0]
        pre = route.rail(r, net, src[0], groups[xs[0]], src)
        if not pre:
            continue
        tree, ends = {q for e in pre for q in e}, []
        for gx in xs[1:]:
            e2 = route.rail(r, net, gx - off, groups[gx])
            if e2:
                pre |= e2
                trunk = sorted({q for e in e2 for q in e if q[0] == gx - off}, key=lambda q: q[1])
                ends.append((trunk[0], (0, -1)) if src[1] < trunk[0][1] else (trunk[-1], (0, 1)))
        rails[net] = (src, pre, tree, ends)

    # 开关出来的线跨度大的先走，先占通道外侧，短线在里面
    for net in sorted(nets, key=lambda n: (order(n), -span(n) if order(n) == 2 else span(n))):
        lst = resolved[net]
        cells = [p[4] for p in lst]
        pre = None
        if net in rails:
            src, pre, tree, ends = rails[net]
            cells.remove(src)
            cells.insert(0, src)
            for end, d in ends:
                r.pin_dir[end] = d
                path = r.connect(net, end, tree)
                del r.pin_dir[end]
                r.commit(net, path)
                pre |= set(zip(path, path[1:]))
                tree |= set(path)
            tree |= {q for e in pre for q in e}
        edges = route.route_net(r, net, cells, pre)
        links, juncs = route.tree_to_links(edges, {p[4] for p in lst})
        c.wire_net(net, {(p[0], p[1]): (p[2], p[3]) for p in lst}, links, juncs)


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
        set_key(c, n, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i])
    mapping, c = replace_parts(c, parts)
    names = {}
    for i, p in enumerate(parts):
        n = mapping["P%d" % (i + 1)]
        if n != p["name"]:
            rename(c, n, p["name"])
        names[p["name"]] = p
    arrange(c, spec)
    open(out_path, "wb").write(ms14.encode(c.tobytes()))
    print("written", out_path, list(c.components()))


def arrange(c, spec):
    """摆位置（位置是绝对计算的，可对已摆好的电路重复调用），有 nets 时再连线。"""
    if spec.get("nets"):
        arrange_wired(c, spec)
        wire_all(c, spec["nets"])
        return
    parts = spec["parts"]
    switches = ["S%d" % (i + 1) for i in range(spec["switches"])]
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


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
