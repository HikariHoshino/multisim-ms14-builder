"""引脚几何与正交走线：在 9 单位网格上做带拐弯惩罚的 A*，得到每个网络的走线树。

走线规则（美观优先级从高到低）：
1. 元件本体是障碍，线不穿过元件；引脚只能从朝外的方向接入。
2. 拐弯代价远大于直走，能直走就直走，路径尽量简单。
3. 不同网络的线可以垂直交叉，但不能重叠在同一段上，也不能在别的线的拐点、结点、引脚上经过。
4. 多点网络从已画好的线上以 T 形分出支线，分支点放结点。
"""
import heapq
import re

G = 9                       # 网格，与 Multisim 坐标对齐
COST_STEP = 1
COST_BEND = 12              # 拐一次弯相当于多走 12 格
COST_CROSS = 3              # 与别的网络交叉
COST_NEAR = 0.5             # 紧贴元件本体或别的线平行走
COST_JOIN = 2               # 在已有线上分支
COST_LABEL = 15             # 压过元件标签
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


# ---------- 几何 ----------
def _m(a):
    if "Transformer-M20" not in a:
        return None
    return [float(a["Transformer-M" + k]) for k in ("00", "01", "10", "11", "20", "21")]


def _mul(p, m):
    """先做子变换 m，再做父变换 p。"""
    if p is None:
        return m
    a, b, c, d, e, f = m
    A, B, C, D, E, F = p
    return [a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F]


def _ap(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]) if m else (x, y)


def symbol_geometry(gfx):
    """返回 (pins, rect)。pins: [(PortID, 连接器 Item, x, y)]，rect: 边框 (x0, y0, x1, y1)。"""
    pins, corners = [], []

    def walk(e, m):
        mm = _m(e.attrib)
        if mm is not None:
            m = _mul(m, mm)
        if e.tag == "CIITPinSymbolComp":
            if e.get("Hidden") == "1":
                return
            item = next(it for it in e.iter("Item") if it.get("Class") == "CIITPinConnectorComp")
            con = item[0]
            x, y = _ap(_mul(m, _m(con.attrib)) if _m(con.attrib) else m,
                       float(con.get("ptCenterX")), float(con.get("ptCenterY")))
            pins.append((e.get("PortID"), item, round(x), round(y)))
            return
        if e.tag == "CIITSymbolBorderRect":
            for k in ("0", "1"):
                corners.append(_ap(m, float(e.get("pt%sX" % k)), float(e.get("pt%sY" % k))))
        for c in e:
            walk(c, m)

    walk(gfx[0], None)
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    # 边框不含引脚线：把引脚端点并进障碍区，线就不会从引脚线中间穿过。
    # 隐藏的电源脚落在符号外面很远的地方，不并入。
    near = [(x, y) for _, _, x, y in pins
            if x0 - 4 * G <= x <= x1 + 4 * G and y0 - 4 * G <= y <= y1 + 4 * G]
    xs += [p[0] for p in near]
    ys += [p[1] for p in near]
    return pins, (min(xs), min(ys), max(xs), max(ys))


def _text(s):
    """Multisim 文字编码转成字符串：&ASCxxx 或 &UNI 加 _ucXXXX 转义。"""
    if s.startswith("&ASC"):
        return s[4:]
    if s.startswith("&UNI"):
        return re.sub(r"_uc([0-9a-f]{4})", lambda m: chr(int(m.group(1), 16)), s[4:])
    return s


def label_boxes(gfx):
    """元件名字、数值/切换键等标签的显示框 [(x0, y0, x1, y1)]，按字号估算宽度（中文按一个字高，西文按 0.6 个字高）。"""
    boxes = []

    def walk(e, m):
        mm = _m(e.attrib)
        if mm is not None and e.tag not in ("CIITSymTextCompName", "CIITSymTextCompValue"):
            m = _mul(m, mm)
        if e.tag == "CIITPinSymbolComp":
            return
        if e.tag in ("CIITSymTextCompName", "CIITSymTextCompValue") and e.get("Hidden") != "1":
            t = _text(e.get("Output", "")).strip()
            if t:
                fh = abs(float(e.get("Font-Height", "-13")))
                w = sum(fh if ord(ch) > 0x2000 else 0.6 * fh for ch in t)
                x, y = _ap(m, float(e.get("Transformer-M20")), float(e.get("Transformer-M21")))
                if e.get("HorizontalAlign") == "1":
                    x -= w / 2
                elif e.get("HorizontalAlign") == "2":
                    x -= w
                boxes.append((x, y, x + w, y + fh))
            return
        for c in e:
            walk(c, m)

    walk(gfx[0], None)
    return boxes


def extent(rect, boxes):
    xs = [rect[0], rect[2]] + [b[0] for b in boxes] + [b[2] for b in boxes]
    ys = [rect[1], rect[3]] + [b[1] for b in boxes] + [b[3] for b in boxes]
    return min(xs), min(ys), max(xs), max(ys)


# ---------- 走线 ----------
class Router:
    def __init__(self, rects, labels=(), margin=6):
        """rects: [(x0, y0, x1, y1)] 元件本体；labels: 标签显示框，走线尽量绕开（单位为 Multisim 坐标）。"""
        self.block = set()
        self.near = set()
        self.label = set()
        # Multisim 写出的坐标带浮点噪声（如 143.99999 / 144.00001），不先去掉的话落在网格线上的边会随机差一格
        labels = [tuple(round(v, 3) for v in b) for b in labels]
        rects = [tuple(round(v, 3) for v in r) for r in rects]
        for x0, y0, x1, y1 in labels:
            # 恰好落在文字框右边、下边线上的格点不压字，不算
            for cx in range(int(x0 // G), -int(-x1 // G)):
                for cy in range(int(y0 // G), -int(-y1 // G)):
                    self.label.add((cx, cy))
        xs, ys = [], []
        for x0, y0, x1, y1 in rects:
            cx0, cy0, cx1, cy1 = int(x0 // G), int(y0 // G), -int(-x1 // G), -int(-y1 // G)
            xs += [cx0, cx1]
            ys += [cy0, cy1]
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    self.block.add((cx, cy))
            for cx in range(cx0 - 1, cx1 + 2):
                for cy in range(cy0 - 1, cy1 + 2):
                    self.near.add((cx, cy))
        self.bounds = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
        self.axis = {}          # 格子 -> {(网络, 轴)}，轴 0=水平 1=竖直
        self.solid = {}         # 格子 -> 网络：引脚、拐点、结点，别的网络不能经过
        self.pin_dir = {}       # 引脚格子 -> 朝外方向

    def add_pin(self, x, y, rect, net, reserve=False):
        c = (x // G, y // G)
        x0, y0, x1, y1 = rect
        if x <= x0:
            d = (-1, 0)
        elif x >= x1:
            d = (1, 0)
        elif y <= y0:
            d = (0, -1)
        else:
            d = (0, 1)
        self.pin_dir[c] = d
        self.solid[c] = net
        self.block.discard(c)
        # 芯片两侧的引脚间距只有 1 格，门口 2 格只留给本网络，别的线不能沿着引脚那一行走过来把入口堵死
        if reserve and d[1] == 0:
            for k in (1, 2):
                e = (c[0] + d[0] * k, c[1])
                if e not in self.block:
                    self.solid.setdefault(e, net)
        return c

    def _free(self, c, ax, net):
        if c in self.block:
            return False
        s = self.solid.get(c)
        if s is not None and s != net:
            return False
        return not any(n != net and a == ax for n, a in self.axis.get(c, ()))

    def _crossing(self, c, net):
        return any(n != net for n, _ in self.axis.get(c, ()))

    def connect(self, net, start, tree):
        """从引脚 start 出发连到本网络已有的树 tree（格子集合；树只有一个引脚时就是那个引脚）。"""
        bx0, by0, bx1, by1 = self.bounds
        d0 = self.pin_dir[start]
        own_axis = {c: {a for n, a in self.axis.get(c, ()) if n == net} for c in tree}
        tx = sum(c[0] for c in tree) / len(tree)
        ty = sum(c[1] for c in tree) / len(tree)

        def h(c):
            return min(abs(c[0] - t[0]) + abs(c[1] - t[1]) for t in tree) if len(tree) < 40 else \
                abs(c[0] - tx) + abs(c[1] - ty)

        # 朝上/朝下的引脚（指示灯、电源符号）允许从侧面接线，和手连时一样
        exits = [d0] + ([(1, 0), (-1, 0)] if d0[0] == 0 else [])
        openq = []
        for d in exits:
            first = (start[0] + d[0], start[1] + d[1])
            if first in tree or self._free(first, 0 if d[1] == 0 else 1, net):
                openq.append((h(first) + (0 if d == d0 else COST_BEND), 0, first, d, (start, None)))
        if not openq:
            raise RuntimeError("引脚出口被堵：%s %s" % (net, start))
        prev = {}
        best = {}
        while openq:
            f, g, c, d, back = heapq.heappop(openq)
            key = (c, d)
            if key in prev:
                continue
            prev[key] = back
            ax = 0 if d[1] == 0 else 1
            if c in tree:
                pd = self.pin_dir.get(c)
                if pd is not None:          # 到达对端引脚：从它朝外的方向进入；朝上/朝下的引脚也可从侧面接入
                    ok = ((d[0] == -pd[0] and d[1] == -pd[1]) or (pd[0] == 0 and d[1] == 0)) \
                        and not own_axis.get(c)
                else:                       # 在已有线上分支：只能垂直接入
                    ok = ax not in own_axis.get(c, set())
                if ok:
                    return self._trace(prev, key, start)
                continue
            for nd in DIRS:
                if nd == (-d[0], -d[1]):
                    continue
                n = (c[0] + nd[0], c[1] + nd[1])
                if not (bx0 <= n[0] <= bx1 and by0 <= n[1] <= by1):
                    continue
                nax = 0 if nd[1] == 0 else 1
                bend = nd != d
                if bend and (self.axis.get(c) and self._crossing(c, net)):
                    continue                # 不在别的线上拐弯
                if n not in tree and not self._free(n, nax, net):
                    continue
                if n in tree and n not in self.pin_dir and nax in own_axis.get(n, set()):
                    continue
                cost = COST_STEP + (COST_BEND if bend else 0)
                if n in self.near:
                    cost += COST_NEAR
                if n in self.label:
                    cost += COST_LABEL
                if n not in tree and self._crossing(n, net):
                    cost += COST_CROSS
                if n in tree:
                    cost += COST_JOIN
                ng = g + cost
                if best.get((n, nd), 1e18) <= ng:
                    continue
                best[(n, nd)] = ng
                heapq.heappush(openq, (ng + h(n), ng, n, nd, key))
        raise RuntimeError("走不通：网络 %s 引脚 %s" % (net, start))

    def _trace(self, prev, key, start):
        path = [key[0]]
        while True:
            back = prev[key]
            if back[1] is None:
                path.append(back[0])
                break
            key = back
            path.append(key[0])
        return path[::-1]           # 从 start 到树上的接入点

    def commit(self, net, path):
        for i, c in enumerate(path):
            axes = set()
            if i > 0:
                axes.add(0 if path[i - 1][1] == c[1] else 1)
            if i + 1 < len(path):
                axes.add(0 if path[i + 1][1] == c[1] else 1)
            s = self.axis.setdefault(c, set())
            for a in axes:
                s.add((net, a))
            if len(axes) == 2 or i == 0 or i == len(path) - 1:
                self.solid[c] = net


def rail(router, net, tx, taps, src=None):
    """电源干线：在 x=tx 拉一根竖直线（有 src 时从电源符号引脚 src 出发），taps 里朝左的引脚各水平接到干线上。
    走不通（被元件挡住）就返回 None，交给普通寻路。"""
    ys = [t[1] for t in taps] + ([src[1]] if src else [])
    trunk = [(tx, y) for y in range(min(ys), max(ys) + 1)]
    if src and src[1] == max(ys):
        trunk.reverse()
    stubs = []
    for t in taps:
        step = -1 if t[0] > tx else 1
        stubs.append([(x, t[1]) for x in range(t[0], tx + step, step)])
    # 干线与别的网络的横线可以交叉，但不能重叠，也不能压在别的网络的拐点、引脚上
    for c in trunk[1:]:
        if not router._free(c, 1, net):
            return None
    for c in [c for s in stubs for c in s[1:]]:
        if not router._free(c, 0, net):
            return None
    router.commit(net, trunk)
    for s in stubs:
        router.commit(net, s)
    edges = set(zip(trunk, trunk[1:]))
    for s in stubs:
        edges |= set(zip(s, s[1:]))
    return edges


def route_net(router, net, pins, edges=None):
    """pins: [格子]，第一个是起点；edges 是已经画好的部分（如电源干线）。返回边集合 {(格子a, 格子b)}。
    按默认起点走不通时（例如两个相邻引脚先连成死结，别的引脚无处分支），撤销后换别的引脚当起点重试。"""
    orders = [pins] + ([pins[i:i + 1] + pins[:i] + pins[i + 1:] for i in range(1, len(pins))] if not edges else [])
    err = None
    for order in orders:
        saved = ({k: set(v) for k, v in router.axis.items()}, dict(router.solid))
        try:
            return _route_net(router, net, order, edges)
        except RuntimeError as e:
            err = e
            router.axis, router.solid = saved
    raise err


def _route_net(router, net, pins, edges=None):
    edges = set(edges or ())
    tree = {pins[0]} | {c for e in edges for c in e}
    rest = [p for p in pins[1:] if p not in tree]
    while rest:
        rest.sort(key=lambda p: min(abs(p[0] - t[0]) + abs(p[1] - t[1]) for t in tree))
        p = rest.pop(0)
        path = router.connect(net, p, tree)
        router.commit(net, path)
        for a, b in zip(path, path[1:]):
            edges.add((a, b))
        tree |= set(path)
    return edges


def tree_to_links(edges, terminals):
    """把走线树拆成 Multisim 的连线：端点是引脚或结点（度 ≥ 3 的格子），中间只保留拐点。

    返回 (links, junctions)。links: [[(x, y), ...]]，junctions: [(x, y)]，坐标为 Multisim 单位。
    """
    adj = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    junctions = {c for c, n in adj.items() if len(n) >= 3 and c not in terminals}
    stops = junctions | set(terminals)
    links, seen = [], set()
    for s in stops:
        for n in adj.get(s, ()):
            if (s, n) in seen:
                continue
            path = [s, n]
            seen.add((s, n))
            while path[-1] not in stops:
                cur = path[-1]
                nxt = next(x for x in adj[cur] if x != path[-2])
                path.append(nxt)
            seen.add((path[-1], path[-2]))
            pts = [path[0]]
            for i in range(1, len(path) - 1):
                a, b, c = path[i - 1], path[i], path[i + 1]
                if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
                    pts.append(b)
            pts.append(path[-1])
            links.append([(x * G, y * G) for x, y in pts])
    return links, [(x * G, y * G) for x, y in junctions]
