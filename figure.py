"""电路截图：导出 → 裁到电路范围 → 插进实验报告的“电路图”小节。

用法：
    python figure.py image 电路.ms14 输出.png
    python figure.py insert 报告.docx 图.png --section "（五）" --nth 2 --caption "8 选 1 数据选择器分析电路仿真电路"

image：用 Multisim 导出整页（A 纸固定 960×720，1 坐标单位 = 1 像素，接口没有更高分辨率），
在图框内侧找出所有不是白底、不是网格点的像素，取外接矩形，四周留一格白边裁下，
再按最近邻放大 3 倍，Word 缩放时文字边缘不发虚。
insert：在 --section 标题之后的第 --nth 个“电路图”小节下放图，宽度等于版心宽、等比缩放。
还没细化的报告没有“电路图”小节，用 --anchor 指定题目下的提示句（如“画出所设计的逻辑电路图”），图放在这句后面。
那里已有图片就原位替换（保留段落格式和图注）；没有就新插图片段和居中图注。只用 Microsoft Word。
"""
import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import netcheck  # noqa: E402

WHITE, GRID = (255, 255, 255), (150, 150, 150)   # 白底、网格点
INNER = (21, 21, 940, 700)                       # A 纸图框线（20、940 / 20、700）内侧
PAD, SCALE = 9, 3


def crop(src, dst):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    px = im.load()
    x0, y0, x1, y1 = INNER
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[x, y] not in (WHITE, GRID):
                xs.append(x)
                ys.append(y)
    if not xs:
        raise RuntimeError("截图里没有电路")
    box = (max(min(xs) - PAD, x0), max(min(ys) - PAD, y0), min(max(xs) + PAD + 1, x1), min(max(ys) + PAD + 1, y1))
    out = im.crop(box)
    out = out.resize((out.width * SCALE, out.height * SCALE), Image.NEAREST)
    out.save(dst, dpi=(96 * SCALE, 96 * SCALE))
    return dst


def image(ms14_path, out_png):
    stem = os.path.join(tempfile.mkdtemp(), "page")
    netcheck.run_report(ms14_path, "image", stem)
    if not os.path.exists(stem + ".png"):
        raise RuntimeError("Multisim 没有导出图片")
    return crop(stem + ".png", os.path.abspath(out_png))


def insert(docx, png, section, nth=1, caption=None, anchor=None):
    import win32com.client as wc
    w = wc.DispatchEx("Word.Application")   # 独立实例，不碰用户开着的 Word
    w.Visible = False
    try:
        d = w.Documents.Open(os.path.abspath(docx))
        ps = d.Paragraphs
        n = ps.Count
        i = next((k for k in range(1, n + 1) if ps(k).Range.Text.strip().startswith(section)), None)
        if i is None:
            raise ValueError("找不到小节 " + section)
        hits = 0
        while i < n:
            i += 1
            t = ps(i).Range.Text.strip()
            if (anchor in t) if anchor else t.endswith("电路图"):
                hits += 1
                if hits == nth:
                    break
        else:
            raise ValueError("%s 之后没有第 %d 个“%s”" % (section, nth, anchor or "电路图"))
        head = ps(i)
        ps_ = head.Range.Sections(1).PageSetup
        width = ps_.PageWidth - ps_.LeftMargin - ps_.RightMargin
        nxt = ps(i + 1) if i < n else None
        if nxt is not None and nxt.Range.InlineShapes.Count:
            # 原位替换：删掉旧图，在同一段落里插新图
            r = nxt.Range.InlineShapes(1).Range
            nxt.Range.InlineShapes(1).Delete()
            # 图片段可能带着首行缩进（如紧跟在缩进的提示句后面），不清掉的话铺满版心的图会超出右边距
            nxt.CharacterUnitLeftIndent = nxt.CharacterUnitRightIndent = nxt.CharacterUnitFirstLineIndent = 0
            nxt.LeftIndent = nxt.RightIndent = nxt.FirstLineIndent = 0   # 先清字符单位，再清磅值，反过来字符单位会把磅值带回来
            nxt.Alignment = 1
            shp = d.InlineShapes.AddPicture(os.path.abspath(png), False, True, r)
            done = "替换"
        else:
            # 新段落只往段内插内容，绝不改写整段文字，否则段落标记被删，会和下一段并成一段
            head.Range.InsertParagraphAfter()
            pic = ps(i + 1)
            pic.Alignment = 1
            pic.SpaceBefore = pic.SpaceAfter = 0
            pic.CharacterUnitLeftIndent = pic.CharacterUnitRightIndent = pic.CharacterUnitFirstLineIndent = 0
            pic.LeftIndent = pic.RightIndent = pic.FirstLineIndent = 0   # 先清字符单位，再清磅值，反过来字符单位会把磅值带回来
            pic.KeepWithNext = True
            at = pic.Range
            at.Collapse(1)
            shp = d.InlineShapes.AddPicture(os.path.abspath(png), False, True, at)
            if caption:
                pic.Range.InsertParagraphAfter()
                cap = ps(i + 2)
                cap.Alignment = 1
                cap.SpaceBefore, cap.SpaceAfter = 3, 6
                cap.CharacterUnitLeftIndent = cap.CharacterUnitRightIndent = cap.CharacterUnitFirstLineIndent = 0
                cap.LeftIndent = cap.RightIndent = cap.FirstLineIndent = 0   # 先清字符单位，再清磅值，反过来字符单位会把磅值带回来
                cap.KeepWithNext = False
                at = cap.Range
                at.Collapse(1)
                at.InsertAfter(caption)
                # 新段落会继承小节标题的字体，改成报告里已有图注的字体：中文宋体、西文 Times New Roman、五号不加粗
                f = cap.Range.Font
                f.NameFarEast, f.Name, f.Size, f.Bold = "宋体", "Times New Roman", 10.5, False
            done = "新插"
        shp.LockAspectRatio = True
        shp.Width = width
        d.Save()
        d.Close()
        return "%s：%s 之后第 %d 个“%s”，宽 %.1f 磅" % (done, section, nth, anchor or "电路图", width)
    finally:
        w.Quit()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("image")
    a.add_argument("ms14")
    a.add_argument("png")
    b = sub.add_parser("insert")
    b.add_argument("docx")
    b.add_argument("png")
    b.add_argument("--section", required=True)
    b.add_argument("--nth", type=int, default=1)
    b.add_argument("--caption")
    b.add_argument("--anchor", help="不按“电路图”小节找，改找包含这段文字的段落")
    args = ap.parse_args()
    if args.cmd == "image":
        print(image(args.ms14, args.png))
    else:
        print(insert(args.docx, args.png, args.section, args.nth, args.caption, args.anchor))
