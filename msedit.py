"""在解压后的 Multisim XML 上复制、移动、删除元件。"""
import copy
import os
import random
import uuid
import xml.etree.ElementTree as ET

ID_ATTRS = ("ID", "CiID")
REF_ATTRS = ("SymCompID", "CiComponent", "Component", "PortID")


class Circuit:
    def __init__(self, xml_bytes):
        self.root = ET.fromstring(xml_bytes)
        self.dg = self.root.find(".//CIITDiagram")
        self.elements = self.dg.find("Elements")
        self.graphics = self.dg.find("Components/CODComposite/Objects")
        self.ccircuit = self.elements.find("Item[@Class='CiCircuit']/CiCircuit")
        self.used = {int(v) for e in self.root.iter() for k in ID_ATTRS
                     if (v := e.attrib.get(k)) and v.isdigit()}

    def new_id(self):
        while True:
            v = random.randint(100_000_000, 2_000_000_000)
            if v not in self.used:
                self.used.add(v)
                return v

    # ---------- 查询 ----------
    def components(self):
        out = {}
        for it in self.elements.findall("Item[@Class='CiComponent']"):
            c = it[0]
            out[c.attrib["LocalName"].replace("&ASC", "")] = it
        return out

    def ports_of(self, comp_item):
        cid = comp_item.attrib["CiID"]
        return [it for it in self.elements.findall("Item[@Class='CiPort']")
                if it[0].attrib.get("Component") == cid]

    def graphic_of(self, comp_item):
        sid = comp_item[0].attrib["SymCompID"]
        g = self.graphics.find(f"Item[@ID='{sid}']")
        if g is None:
            cid = comp_item.attrib["CiID"]
            g = next((it for it in self.graphics if it[0].attrib.get("CiComponent") == cid), None)
        return g

    # ---------- 操作 ----------
    def clone(self, name, new_name, dx=0, dy=0):
        src = self.components()[name]
        parts = [src] + self.ports_of(src) + [self.graphic_of(src)]
        clones = [copy.deepcopy(p) for p in parts]
        remap = {}
        for c in clones:
            for e in c.iter():
                for k in ID_ATTRS:
                    v = e.attrib.get(k)
                    if v and v.isdigit() and e.tag == "Item" and e.attrib.get("Class"):
                        remap.setdefault(v, str(self.new_id()))
        for c in clones:
            for e in c.iter():
                for k in ID_ATTRS + REF_ATTRS:
                    v = e.attrib.get(k)
                    if v in remap:
                        e.attrib[k] = remap[v]
        comp, *ports, gfx = clones
        comp[0].attrib["LocalName"] = "&ASC" + new_name
        comp[0].attrib["InstanceID"] = "{%s}" % str(uuid.uuid4()).upper()
        for e in gfx.iter("CIITSymTextCompName"):
            if e.attrib.get("Output") == "&ASC" + name:
                e.attrib["Output"] = "&ASC" + new_name
        self.elements.append(comp)
        for p in ports:
            self.elements.append(p)
        self.graphics.append(gfx)
        ET.SubElement(self.ccircuit.find("Components"), "Item", CiID=comp.attrib["CiID"])
        self.move(new_name, dx, dy)
        return comp

    def delete(self, name):
        comp = self.components()[name]
        ports = self.ports_of(comp)
        port_ids = {p.attrib["CiID"] for p in ports}
        self.graphics.remove(self.graphic_of(comp))
        for p in ports:
            self.elements.remove(p)
        self.elements.remove(comp)
        lst = self.ccircuit.find("Components")
        for it in list(lst):
            if it.attrib.get("CiID") == comp.attrib["CiID"]:
                lst.remove(it)
        for node in self.elements.findall("Item[@Class='CiNode']/CiNode"):
            nports = node.find("Ports")
            if nports is None:
                continue
            for it in list(nports):
                if it.attrib.get("CiID") in port_ids:
                    nports.remove(it)

    def rotate180(self, name):
        """把开关类（子对象用绝对坐标）符号绕边框原点转 180°，用于把占位扶正。"""
        gfx = self.graphic_of(self.components()[name])
        br = next(e for e in gfx.iter("CIITSymbolBorderRect"))
        cx, cy = float(br.attrib["Transformer-M20"]), float(br.attrib["Transformer-M21"])
        for e in gfx.iter():
            a = e.attrib
            if "Transformer-M20" not in a:
                continue
            for k in ("Transformer-M00", "Transformer-M01", "Transformer-M10", "Transformer-M11"):
                a[k] = _fmt(-float(a[k]) + 0.0)
            a["Transformer-M20"] = _fmt(2 * cx - float(a["Transformer-M20"]))
            a["Transformer-M21"] = _fmt(2 * cy - float(a["Transformer-M21"]))

    def size(self, name):
        """普通元件符号的宽高（取边框矩形）。"""
        g = self.graphic_of(self.components()[name])
        br = next(e for e in g.iter("CIITSymbolBorderRect"))
        a = br.attrib
        return abs(float(a["pt1X"]) - float(a["pt0X"])), abs(float(a["pt1Y"]) - float(a["pt0Y"]))

    def move(self, name, dx, dy):
        gfx = self.graphic_of(self.components()[name])
        # 普通元件的位置在符号自身的变换上；开关这类动画符号没有自身变换，子对象用绝对坐标
        # 引脚符号内部（连接器、引脚文字）是相对引脚符号的坐标，不能跟着平移
        targets = [gfx[0]] if "Transformer-M20" in gfx[0].attrib else list(_iter_abs(gfx))
        for e in targets:
            if "Transformer-M20" in e.attrib:
                e.attrib["Transformer-M20"] = _fmt(float(e.attrib["Transformer-M20"]) + dx)
                e.attrib["Transformer-M21"] = _fmt(float(e.attrib["Transformer-M21"]) + dy)

    def bbox(self, name):
        gfx = self.graphic_of(self.components()[name])
        xs = [float(e.attrib["Transformer-M20"]) for e in gfx.iter() if "Transformer-M20" in e.attrib]
        ys = [float(e.attrib["Transformer-M21"]) for e in gfx.iter() if "Transformer-M21" in e.attrib]
        return min(xs), min(ys), max(xs), max(ys)

    # ---------- 连线 ----------
    def _tpl(self, name):
        if not hasattr(self, "_tpls"):
            t = ET.parse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wire_templates.xml"))
            self._tpls = {e.get("name"): e[0] for e in t.getroot()}
        return copy.deepcopy(self._tpls[name])

    def _ref(self, item_id, cls):
        refs = self.dg.find("Components/CODComposite/ReferencedComponents")
        ET.SubElement(refs, "Item", ID=item_id, Class=cls)

    def wire_net(self, net, pins, links, junctions):
        """画一个网络。pins: {(x, y): (PortID, 引脚连接器 Item)}；links: [[(x, y), ...]] 每条线的点列，
        两端必须是引脚或结点；junctions: [(x, y)] 结点位置。"""
        refs = self.dg.find("Components/CODComposite/ReferencedComponents")
        circ_id = self.elements.find("Item[@Class='CiCircuit']").get("CiID")
        # 网络：一棵走线树对应一个 CiNode，端口从原来的网络里移过来
        node = self._tpl("node")
        node.set("CiID", str(self.new_id()))
        node[0].set("LocalName", "&ASC" + net)
        node[0].set("Circuit", circ_id)
        self.elements.append(node)
        ET.SubElement(self.ccircuit.find("Nodes"), "Item", CiID=node.get("CiID"))
        port_ids = {pid for pid, _ in pins.values()}
        for old in self.elements.findall("Item[@Class='CiNode']"):
            if old is node:
                continue
            ps = old[0].find("Ports")
            for it in list(ps):
                if it.get("CiID") in port_ids:
                    ps.remove(it)
            if len(ps) == 0:
                self.elements.remove(old)
                lst = self.ccircuit.find("Nodes")
                for it in list(lst):
                    if it.get("CiID") == old.get("CiID"):
                        lst.remove(it)
        for it in self.elements.findall("Item[@Class='CiPort']"):
            if it.get("CiID") in port_ids:
                ET.SubElement(node[0].find("Ports"), "Item", CiID=it.get("CiID"))
                ns = it[0].find("Nodes")
                if ns is None:
                    ns = ET.SubElement(it[0], "Nodes")
                ns.clear()
                ET.SubElement(ns, "Item", CiID=node.get("CiID"))
        # 网标
        text = self._tpl("nodetext")
        text.set("ID", str(self.new_id()))
        text[0].set("Transformer-M20", _fmt(links[0][0][0]))
        text[0].set("Transformer-M21", _fmt(links[0][0][1]))
        self.graphics.append(text)
        self._ref(text.get("ID"), "CODNodeTextComp")
        # 结点
        juncs = {}
        for x, y in junctions:
            j = self._tpl("junction")
            j.set("ID", str(self.new_id()))
            j[0].set("CenterX", _fmt(x))
            j[0].set("CenterY", _fmt(y))
            self.graphics.append(j)
            self._ref(j.get("ID"), "CODPinComp")
            juncs[(x, y)] = j
        used_conn = set()

        def end(x, y):
            """在 (x, y) 放一个外部引脚，与那里的元件引脚或结点双向登记，返回其 ID。"""
            e = self._tpl("extpin")
            e.set("ID", str(self.new_id()))
            e[0].set("CenterX", _fmt(x))
            e[0].set("CenterY", _fmt(y))
            if (x, y) in juncs:
                tgt, cls = juncs[(x, y)], "CODPinComp"
            else:
                tgt, cls = pins[(x, y)][1], "CIITPinConnectorComp"
                if tgt.get("ID") not in used_conn:
                    used_conn.add(tgt.get("ID"))
                    self._ref(tgt.get("ID"), cls)
            ET.SubElement(e[0].find("ConnectList"), "Item", ID=tgt.get("ID"), Class=cls)
            ET.SubElement(tgt[0].find("ConnectList"), "Item", ID=e.get("ID"), Class="CODPinComp")
            refs.append(e)
            return e.get("ID")

        for pts in links:
            ln = self._tpl("link")
            ln.set("ID", str(self.new_id()))
            a = ln[0]
            a.set("Connect1", end(*pts[0]))
            a.set("Connect2", end(*pts[-1]))
            a.set("Node", node.get("CiID"))
            a.set("NodeText", text.get("ID"))
            for x, y in pts:
                ET.SubElement(a.find("Points"), "Item", X=_fmt(x), Y=_fmt(y))
            self.graphics.append(ln)
            self._ref(ln.get("ID"), "CIITLinkComp")
            ET.SubElement(text[0].find("Links"), "Item", ID=ln.get("ID"), Class="CIITLinkComp")

    def tobytes(self):
        body = ET.tostring(self.root, encoding="unicode")
        return ('<?xml version="1.0" encoding="ASCII"?>\n' + body).encode("ascii", "xmlcharrefreplace")


def _iter_abs(e):
    yield e
    if e.tag == "CIITPinSymbolComp":
        return
    for c in e:
        yield from _iter_abs(c)


def _fmt(v):
    return str(int(v)) if v == int(v) else repr(v)
