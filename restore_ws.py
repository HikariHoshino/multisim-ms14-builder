"""还原 .ms14 里被 XML 规范化压平的多行属性值。

用法：python restore_ws.py 坏文件.ms14 输出.ms14 参考1.ms14 [参考2.ms14 ...]

元件仿真模型（.SUBCKT）、开关的交互模型（* !!!BEGIN-INTERACT）、仿真设置（list{... gminsteps ...}）
都是多行文本，原样写在属性值里。XML 解析会把属性里的每个换行、回车、制表符换成一个空格，
写回后 Multisim 仿真报 Invalid subckt definition、Unmatched ".ENDS"、gminsteps 等错误，开关拨不动。
规范化是一个字符换一个空格，可以精确还原：从参考文件（Multisim 自己保存、能正常仿真的电路）
收集含换行的属性值，按“规范化后的样子”建表，坏文件里与表中某项完全相同的属性值换回原文。
参考文件要含有同样的元件或同样的底板内容，否则找不到对应原文；末尾会列出仍像被压平的可疑值。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ms14  # noqa: E402


def norm(v):
    v = v.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return v.replace(b"\n", b" ").replace(b"\t", b" ")


def restore(target, out, refs):
    table = {}
    for r in refs:
        b = ms14.decode(open(r, "rb").read())
        for m in re.finditer(rb'="([^"]*)"', b):
            v = m.group(1)
            if b"\n" in v or b"\r" in v or b"\t" in v:
                table.setdefault(norm(v), v)
    b = ms14.decode(open(target, "rb").read())
    hit = 0

    def sub(m):
        nonlocal hit
        v = m.group(1)
        if v in table and table[v] != v:
            hit += 1
            return b'="' + table[v] + b'"'
        return m.group(0)

    b = re.sub(rb'="([^"]*)"', sub, b)
    left = [m.group(1)[:70] for m in re.finditer(rb'="([^"]*)"', b)
            if b"\n" not in m.group(1) and (b".ENDS" in m.group(1) or b"list{" in m.group(1))]
    open(out, "wb").write(ms14.encode(b))
    return len(table), hit, left


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    n, hit, left = restore(sys.argv[1], sys.argv[2], sys.argv[3:])
    print("参考值 %d，还原 %d，仍像被压平的 %d" % (n, hit, len(left)))
    for x in left[:10]:
        print("  ", x)
    sys.exit(1 if left else 0)
