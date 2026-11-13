"""把 ms14gen 包成 MCP 服务（stdio）。只用标准库，不依赖 mcp 包。

它不遥控 Multisim 界面：生成、编解码直接改文件；网表、截图、元件列表经 32 位 PowerShell 调
Multisim 自动化接口，脚本结束时只关自己启动的 Multisim 进程。

注册示例（Claude Code）：
    claude mcp add ms14gen -- python D:/路径/ms14gen/mcp_server.py
"""
import json
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ms14  # noqa: E402
import figure  # noqa: E402
import netcheck  # noqa: E402

PS32 = netcheck.PS32

TOOLS = [
    {"name": "build_circuit",
     "description": "按 spec JSON 生成 ms14：放好元件；spec 里写了 nets 时自动布局并连好线（A 纸）。"
                    "需要本机 Multisim 14，约 30～60 秒。",
     "inputSchema": {"type": "object", "required": ["spec", "output"], "properties": {
         "spec": {"type": "string", "description": "spec JSON 文件路径"},
         "output": {"type": "string", "description": "输出 .ms14 路径"},
         "overwrite": {"type": "boolean", "description": "输出已存在时是否覆盖，默认 false"}}}},
    {"name": "check_connectivity",
     "description": "用 Multisim 导出网表，与 spec 的 nets 逐个网络比对，返回缺少和多出的网络。",
     "inputSchema": {"type": "object", "required": ["ms14", "spec"], "properties": {
         "ms14": {"type": "string"}, "spec": {"type": "string"}}}},
    {"name": "export_netlist",
     "description": "用 Multisim 导出网表，返回 {网络名: [元件.引脚]}，地元件记为 0。",
     "inputSchema": {"type": "object", "required": ["ms14"], "properties": {"ms14": {"type": "string"}}}},
    {"name": "export_image",
     "description": "用 Multisim 把整页电路图导出成 PNG。",
     "inputSchema": {"type": "object", "required": ["ms14", "output"], "properties": {
         "ms14": {"type": "string"},
         "output": {"type": "string", "description": "输出路径，不带扩展名时自动补 .png"}}}},
    {"name": "export_figure",
     "description": "导出报告用电路图：整页导出后裁到电路范围（留一格白边），放大 3 倍存为 PNG。",
     "inputSchema": {"type": "object", "required": ["ms14", "output"], "properties": {
         "ms14": {"type": "string"}, "output": {"type": "string", "description": "输出 .png 路径"}}}},
    {"name": "insert_figure",
     "description": "用 Microsoft Word 把图片放进实验报告某道题的“电路图”小节，宽度等于版心宽。"
                    "那里已有图就原位替换，没有就新插图片和居中图注。会直接保存报告，调用前先备份。",
     "inputSchema": {"type": "object", "required": ["docx", "png", "section"], "properties": {
         "docx": {"type": "string"}, "png": {"type": "string"},
         "section": {"type": "string", "description": "题目标题开头，如“（五）”"},
         "nth": {"type": "integer", "description": "该题目之后第几个“电路图”小节，默认 1"},
         "caption": {"type": "string", "description": "新插图时的图注；替换旧图时不用"},
         "anchor": {"type": "string", "description": "报告还没有“电路图”小节时，改找包含这段文字的段落，如“画出所设计的逻辑电路图”"}}}},
    {"name": "list_components",
     "description": "用 Multisim 打开文件，列出元件名。",
     "inputSchema": {"type": "object", "required": ["ms14"], "properties": {"ms14": {"type": "string"}}}},
    {"name": "decode_ms14",
     "description": "把 ms14 解压成 XML 文本文件，不需要 Multisim。",
     "inputSchema": {"type": "object", "required": ["ms14", "output"], "properties": {
         "ms14": {"type": "string"}, "output": {"type": "string"}}}},
    {"name": "encode_ms14",
     "description": "把 XML 压回 ms14，不需要 Multisim。",
     "inputSchema": {"type": "object", "required": ["xml", "output"], "properties": {
         "xml": {"type": "string"}, "output": {"type": "string"},
         "overwrite": {"type": "boolean", "description": "输出已存在时是否覆盖，默认 false"}}}},
]


def _no_clobber(path, args):
    if os.path.exists(path) and not args.get("overwrite"):
        raise ValueError("%s 已存在。先确认用户没在 Multisim 里改过它，再传 overwrite=true" % path)


def call(name, a):
    if name == "build_circuit":
        _no_clobber(a["output"], a)
        res = subprocess.run([sys.executable, os.path.join(HERE, "build.py"), a["spec"], a["output"]],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=600, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if res.returncode or not os.path.exists(a["output"]):
            raise RuntimeError((res.stdout + res.stderr)[-3000:])
        return res.stdout[-3000:]
    if name == "check_connectivity":
        spec = json.load(open(a["spec"], encoding="utf-8"))
        return netcheck.compare(netcheck.netlist(a["ms14"]), spec["nets"])
    if name == "export_netlist":
        return {k: sorted(v) for k, v in netcheck.netlist(a["ms14"]).items()}
    if name == "export_image":
        out = os.path.abspath(a["output"])
        stem = out[:-4] if out.lower().endswith(".png") else out
        netcheck.run_report(a["ms14"], "image", stem)
        if not os.path.exists(stem + ".png"):
            raise RuntimeError("Multisim 没有导出图片")
        return stem + ".png"
    if name == "export_figure":
        return figure.image(a["ms14"], a["output"])
    if name == "insert_figure":
        return figure.insert(a["docx"], a["png"], a["section"], a.get("nth", 1), a.get("caption"), a.get("anchor"))
    if name == "list_components":
        res = subprocess.run([PS32, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                              os.path.join(HERE, "check.ps1"), os.path.abspath(a["ms14"])],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        return res.stdout or res.stderr
    if name == "decode_ms14":
        open(a["output"], "wb").write(ms14.decode(open(a["ms14"], "rb").read()))
        return a["output"]
    if name == "encode_ms14":
        _no_clobber(a["output"], a)
        open(a["output"], "wb").write(ms14.encode(open(a["xml"], "rb").read()))
        return a["output"]
    raise ValueError("未知工具 " + name)


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        ver = msg.get("params", {}).get("protocolVersion", "2025-06-18")
        return {"protocolVersion": ver, "capabilities": {"tools": {}},
                "serverInfo": {"name": "ms14gen", "version": "1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        p = msg["params"]
        try:
            r = call(p["name"], p.get("arguments", {}))
            text = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, indent=1)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:
            return {"content": [{"type": "text", "text": "%s: %s" % (type(e).__name__, e)}], "isError": True}
    if mid is None:
        return None  # 通知（如 notifications/initialized）不回
    raise LookupError(method)


def main():
    out = sys.stdout.buffer
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        msg = json.loads(line)
        try:
            result = handle(msg)
            if msg.get("id") is None:
                continue
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        except LookupError as e:
            reply = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32601, "message": "未知方法 %s" % e}}
        except Exception:
            reply = {"jsonrpc": "2.0", "id": msg.get("id"),
                     "error": {"code": -32603, "message": traceback.format_exc()[-2000:]}}
        out.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
        out.flush()


if __name__ == "__main__":
    main()
