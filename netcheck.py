"""用 Multisim 导出网表，与 spec 的 nets 逐个网络比对，确认自动连线的连通性。

用法：python netcheck.py 文件.ms14 spec.json
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PS32 = r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"


def run_report(ms14_path, *args):
    res = subprocess.run([PS32, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          os.path.join(HERE, "msreport.ps1"), os.path.abspath(ms14_path), *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return res.stdout, res.stderr


def netlist(ms14_path):
    """返回 {网络名: {"元件.引脚", ...}}。地元件在网表里是 _uc 开头的转义名，统一记为 0。"""
    out, err = run_report(ms14_path, "netlist")
    nets = {}
    for line in out.splitlines():
        f = line.split()
        # 第二列是单个字母，不同次导出可能是 w 或 t，不认具体字母
        if len(f) == 4 and len(f[1]) == 1:
            comp = "0" if f[2].startswith("_uc") else f[2]
            nets.setdefault(f[0], set()).add(comp + "." + f[3])
    if not nets:
        raise RuntimeError("没有读到网表：\n" + (err or out)[:2000])
    return nets


def compare(nets, spec_nets):
    """按引脚集合比对（不看网络名）。芯片隐藏电源脚会自动并入 VCC/地网络，比较时去掉。"""
    def strip(s):
        return frozenset(p for p in s if not re.match(r"U\d+\.(VCC|GND)$", p))
    got = {strip(s) for s in nets.values()} - {frozenset()}
    want = {frozenset(v) for v in spec_nets.values()}
    return {"netlist_nets": len(got), "spec_nets": len(want),
            "missing": [sorted(s) for s in want - got],
            "extra": [sorted(s) for s in got - want],
            "ok": got == want}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    spec = json.load(open(sys.argv[2], encoding="utf-8"))
    r = compare(netlist(sys.argv[1]), spec["nets"])
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["ok"] else 1)
