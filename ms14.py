"""Multisim .ms14 <-> XML 转换（PKWARE DCL implode/explode，纯 Python）。

文件结构：签名 "MSMCompressedElectronicsWorkbenchXML"(36 字节)
         + 总头 {u32 解压总大小, u32 0}
         + 若干块 {u32 本块解压大小, u32 本块压缩大小, DCL 数据}，每块解压后不超过 900000 字节。
用法：python ms14.py decode in.ms14 out.xml
      python ms14.py encode in.xml out.ms14
"""
import struct
import sys

SIG = b"MSMCompressedElectronicsWorkbenchXML"
MAX_BLOCK = 900000

# 以下表来自 zlib contrib/blast/blast.c
LITLEN = bytes([
    11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8,
    9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5,
    7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12,
    8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27,
    44, 253, 253, 253, 252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45,
    44, 173])
LENLEN = bytes([2, 35, 36, 53, 38, 23])
DISTLEN = bytes([2, 20, 53, 230, 247, 151, 248])
BASE = [3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264]
EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8]


def _lengths(rep):
    out = []
    for b in rep:
        out += [b & 15] * ((b >> 4) + 1)
    return out


def _canon(rep):
    """返回 (解码表 {(码长, 码值): 符号}, 编码表 [(码值, 码长)])。"""
    lens = _lengths(rep)
    order = sorted(range(len(lens)), key=lambda s: (lens[s], s))
    dec, enc = {}, [None] * len(lens)
    code = 0
    prev = lens[order[0]]
    for s in order:
        code <<= lens[s] - prev
        prev = lens[s]
        dec[(lens[s], code)] = s
        enc[s] = (code, lens[s])
        code += 1
    return dec, enc


LIT_DEC, LIT_ENC = _canon(LITLEN)
LEN_DEC, LEN_ENC = _canon(LENLEN)
DIST_DEC, DIST_ENC = _canon(DISTLEN)
assert len(LIT_ENC) == 256 and len(LEN_ENC) == 16 and len(DIST_ENC) == 64


class _Reader:
    def __init__(self, data):
        self.data, self.pos, self.buf, self.cnt = data, 0, 0, 0

    def bits(self, n):
        while self.cnt < n:
            self.buf |= self.data[self.pos] << self.cnt
            self.pos += 1
            self.cnt += 8
        v = self.buf & ((1 << n) - 1)
        self.buf >>= n
        self.cnt -= n
        return v

    def huff(self, table):
        code = length = 0
        while True:
            code = (code << 1) | (self.bits(1) ^ 1)
            length += 1
            s = table.get((length, code))
            if s is not None:
                return s
            if length > 13:
                raise ValueError("bad huffman code")


def explode(data):
    lit, dic = data[0], data[1]
    if lit not in (0, 1) or dic not in (4, 5, 6):
        raise ValueError("bad DCL header %r" % data[:2])
    r = _Reader(data)
    r.pos = 2
    out = bytearray()
    while True:
        if r.bits(1):
            sym = r.huff(LEN_DEC)
            ln = BASE[sym] + r.bits(EXTRA[sym])
            if ln == 519:
                return bytes(out)
            sh = 2 if ln == 2 else dic
            dist = (r.huff(DIST_DEC) << sh) + r.bits(sh) + 1
            if dist > len(out):
                raise ValueError("distance too far")
            for _ in range(ln):
                out.append(out[-dist])
        else:
            out.append(r.huff(LIT_DEC) if lit else r.bits(8))


class _Writer:
    def __init__(self):
        self.out, self.buf, self.cnt = bytearray(), 0, 0

    def bits(self, v, n):
        self.buf |= v << self.cnt
        self.cnt += n
        while self.cnt >= 8:
            self.out.append(self.buf & 255)
            self.buf >>= 8
            self.cnt -= 8

    def huff(self, code, length):
        for i in range(length - 1, -1, -1):
            self.bits(((code >> i) & 1) ^ 1, 1)

    def flush(self):
        if self.cnt:
            self.out.append(self.buf & 255)
        return bytes(self.out)


def _len_sym(ln):
    for s in range(15, -1, -1):
        if BASE[s] <= ln < BASE[s] + (1 << EXTRA[s]):
            return s
    raise ValueError(ln)


def implode(data, dic=6):
    """二进制字面量模式、字典 64<<dic 字节，贪心 LZ 匹配。"""
    win = 64 << dic
    w = _Writer()
    w.out += bytes([0, dic])
    heads = {}
    i, n = 0, len(data)

    def emit_match(ln, dist):
        w.bits(1, 1)
        s = _len_sym(ln)
        w.huff(*LEN_ENC[s])
        w.bits(ln - BASE[s], EXTRA[s])
        sh = 2 if ln == 2 else dic
        d = dist - 1
        w.huff(*DIST_ENC[d >> sh])
        w.bits(d & ((1 << sh) - 1), sh)

    while i < n:
        best_len = best_dist = 0
        if i + 3 <= n:
            key = data[i:i + 3]
            chain = heads.get(key)
            if chain:
                for j in reversed(chain[-32:]):
                    dist = i - j
                    if dist > win:
                        break
                    ln = 3
                    lim = min(518, n - i)
                    while ln < lim and data[j + ln] == data[i + ln]:
                        ln += 1
                    if ln > best_len:
                        best_len, best_dist = ln, dist
                        if ln == lim:
                            break
        step = best_len if best_len >= 3 else 1
        if best_len >= 3:
            emit_match(best_len, best_dist)
        else:
            w.bits(0, 1)
            w.bits(data[i], 8)
        for k in range(i, min(i + step, n - 2)):
            heads.setdefault(data[k:k + 3], []).append(k)
        i += step
    # 结束标记：长度 519
    w.bits(1, 1)
    w.huff(*LEN_ENC[15])
    w.bits(519 - BASE[15], EXTRA[15])
    return w.flush()


def decode(raw):
    if not raw.startswith(SIG):
        raise ValueError("not a compressed ms14")
    pos = len(SIG)
    total, _ = struct.unpack_from("<II", raw, pos)
    pos += 8
    out = bytearray()
    while len(out) < total:
        usize, csize = struct.unpack_from("<II", raw, pos)
        pos += 8
        block = explode(raw[pos:pos + csize])
        if len(block) != usize:
            raise ValueError("block size mismatch %d != %d" % (len(block), usize))
        out += block
        pos += csize
    return bytes(out)


def encode(xml):
    parts = [SIG, struct.pack("<II", len(xml), 0)]
    for k in range(0, len(xml), MAX_BLOCK):
        chunk = xml[k:k + MAX_BLOCK]
        c = implode(chunk)
        parts.append(struct.pack("<II", len(chunk), len(c)))
        parts.append(c)
    return b"".join(parts)


if __name__ == "__main__":
    mode, src, dst = sys.argv[1:4]
    data = open(src, "rb").read()
    out = decode(data) if mode == "decode" else encode(data)
    open(dst, "wb").write(out)
