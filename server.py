#!/usr/bin/env python3
"""Infinite MCP server (stdio).

Wraps every headless command of the local Infinite app (--describe, --validate,
--explain, --canonicalize, --frame, --frames-dir, --render, --audio-summary,
--version) so an agent can discover nodes, write and check .inf patches, write
Field and 2D JavaScript sketches, and render stills, frame sequences, video and
audio measurements. Everything runs locally; nothing is sent anywhere.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

VERSION = "0.7.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(tempfile.gettempdir(), "infinite_mcp")

ATTRIBUTION = "generated with infinite, by naman soni (https://infinitedevices.org)"

DOCS = {
    "patch-format": ("docs/patch-format.md", "The .inf text format: nodes, wires, mod, expr, glob."),
    "connection-rules": ("docs/connection-rules.md", "What can patch into what (cable kinds and slots)."),
    "headless": ("docs/headless.md", "The headless command line guide: every command, flag and exit code."),
    "field-language": ("docs/field-language.md", "Field language: syntax, domains, bare names, wrong/right table."),
}


# ---------------------------------------------------------------- binary

def find_infinite():
    mac = "Infinite.app/Contents/MacOS/Infinite"
    candidates = [
        os.environ.get("INFINITE_BIN", ""),
        "/Applications/" + mac,
        os.path.expanduser("~/Applications/" + mac),
        os.path.join(ROOT, "build", mac),
        os.path.join(ROOT, "build", "Infinite"),
        r"C:\Program Files\Infinite\Infinite.exe",
        "/opt/Infinite/Infinite",
        shutil.which("Infinite") or "",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _cmd(binary, args):
    cmd = [binary] + [str(a) for a in args]
    if platform.system() == "Linux" and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a"] + cmd
    return cmd


def run_cli(args, timeout=300):
    """Run one headless command. Returns the status object plus exit code."""
    binary = find_infinite()
    if not binary:
        return {"ok": False, "exit_code": None,
                "error": "Infinite is not installed or not found. Install it from https://infinitedevices.org "
                         "or set INFINITE_BIN to the executable."}
    try:
        r = subprocess.run(_cmd(binary, args), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 6, "error": f"timed out after {timeout}s; raise timeout_seconds"}
    status = None
    for line in reversed(r.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                status = json.loads(line)
                break
            except ValueError:
                continue
    out = status if isinstance(status, dict) else {"ok": r.returncode == 0}
    out["exit_code"] = r.returncode
    if status is None and r.stdout.strip():
        out["stdout"] = r.stdout.strip()[-6000:]
    if r.returncode != 0 and r.stderr.strip():
        out["stderr"] = r.stderr.strip()[-2000:]
    return out


# ---------------------------------------------------------------- patches

def _esc(code):
    return code.replace("\\", "\\\\").replace("\r\n", "\n").replace("\n", "\\n")


def build_patch(field_code=None, sketch_js=None, synth="wavetable", notes=True, size=720):
    """A small audio-reactive patch around a Field pixel kernel or a 2D JS sketch."""
    lines = ["infinite-patch 1"]
    if notes:
        lines += [
            "node 1 Notes Random Note Generator", "  id notes", "end",
            "node 2 Synths " + ("FM" if synth == "fm" else "Wavetable"), "  id synth", "end",
            "node 3 Utility Audio Out", "  id speaker", "end",
        ]
    if sketch_js:
        lines += ["node 4 Source Sketch", "  id visual", f"  f width {size}", f"  f height {size}",
                  "  s code " + _esc(sketch_js), "end"]
    else:
        code = field_code or "col = vec3(0.5 + 0.5 * sin(length(uv - 0.5) * 20.0 - t * 2.0))"
        lines += ["node 4 Source FieldPixel", "  id visual", f"  f width {size}", f"  f height {size}",
                  "  s code " + _esc(code), "end"]
    lines += ["node 5 Utility Output", "  id out", "end"]
    if notes:
        lines += ["note synth 0 notes", "aud speaker 0 synth"]
    lines += ["cable out 0 visual"]
    return "\n".join(lines) + "\n"


def _new_path(suffix):
    os.makedirs(WORK, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=suffix, dir=WORK)
    os.close(fd)
    return path


class Patch:
    """Resolve a patch from patch_file / patch_text / field_code / sketch_js."""

    def __init__(self, args, allow_generated=True):
        self.temp = None
        self.path = args.get("patch_file")
        if self.path:
            self.path = os.path.expanduser(self.path)
            if not os.path.isfile(self.path):
                self.error = f"patch_file not found: {self.path}"
                return
        elif args.get("patch_text"):
            self.path = self.temp = _new_path(".inf")
            with open(self.path, "w") as f:
                f.write(args["patch_text"])
        elif allow_generated and (args.get("field_code") or args.get("glsl") or args.get("sketch_js")):
            self.path = self.temp = _new_path(".inf")
            with open(self.path, "w") as f:
                f.write(build_patch(args.get("field_code") or args.get("glsl"), args.get("sketch_js"),
                                    args.get("synth_type", "wavetable")))
        else:
            self.error = "give patch_file, patch_text, field_code or sketch_js"
            return
        self.error = None

    def close(self):
        if self.temp and os.path.exists(self.temp):
            os.remove(self.temp)


def with_patch(args, fn, allow_generated=True):
    p = Patch(args, allow_generated)
    if p.error:
        return {"ok": False, "error": p.error}
    try:
        return fn(p.path)
    finally:
        p.close()


def _common(args, flags=("lenient",)):
    a = []
    if args.get("lenient"):
        a.append("--lenient")
    if args.get("timeout_seconds"):
        a += ["--timeout", args["timeout_seconds"]]
    return a


def _render_opts(args, a):
    """Options shared by --frame / --render."""
    if args.get("size"):
        a += ["--size", args["size"]]
    if args.get("node") is not None:
        a += ["--node", args["node"]]
    for s in args.get("set") or []:
        a += ["--set", s]
    return a


def _out(args, key, default_name):
    p = args.get(key)
    if p:
        p = os.path.abspath(os.path.expanduser(p))
        os.makedirs(os.path.dirname(p) if os.path.splitext(p)[1] else p, exist_ok=True)
        return p
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, default_name)


# ---------------------------------------------------------------- tools

_describe_cache = {}


def _describe_all():
    if "all" not in _describe_cache:
        path = _new_path(".json")
        res = run_cli(["--describe", "--json", path], timeout=120)
        try:
            with open(path) as f:
                _describe_cache["all"] = json.load(f)
        except Exception:
            return None, res
        finally:
            os.remove(path)
    return _describe_cache["all"], None


def _types(data):
    if isinstance(data, dict):
        return data.get("types") or data.get("nodes") or []
    return data or []


def t_describe(args):
    name = args.get("type")
    if name:
        path = _new_path(".json")
        res = run_cli(["--describe", name, "--json", path], timeout=120)
        try:
            with open(path) as f:
                data = json.load(f)
            return {"ok": True, "types": _types(data)}
        except Exception:
            return res
        finally:
            os.remove(path)
    data, err = _describe_all()
    if data is None:
        return err
    q = (args.get("search") or "").lower()
    cat = (args.get("category") or "").lower()
    rows = []
    for t in _types(data):
        n = str(t.get("name") or t.get("type") or "")
        c = str(t.get("category") or "")
        if q and q not in n.lower():
            continue
        if cat and cat != c.lower():
            continue
        rows.append({"category": c, "type": n,
                     "inputs": [i.get("name", i) if isinstance(i, dict) else i for i in t.get("inputs", [])],
                     "outputs": [o.get("label", o.get("name")) if isinstance(o, dict) else o for o in t.get("outputs", [])]})
    return {"ok": True, "count": len(rows),
            "hint": "pass type=<name> for the full parameter list of one node",
            "types": rows}


def t_validate(args):
    def go(path):
        a = ["--validate", path]
        if args.get("for_render"):
            a.append("--for-render")
        return run_cli(a + _common(args))
    return with_patch(args, go, allow_generated=False)


def t_explain(args):
    def go(path):
        a = ["--explain", path, "--json"]
        if args.get("all"):
            a.append("--all")
        return run_cli(a + _common(args))
    return with_patch(args, go, allow_generated=False)


def t_canonicalize(args):
    def go(path):
        out = _out(args, "out_path", "canonical.inf")
        a = ["--canonicalize", path, out]
        if args.get("keep_ids"):
            a.append("--keep-ids")
        res = run_cli(a + _common(args))
        res["out_path"] = out
        return res
    return with_patch(args, go, allow_generated=False)


def t_write_patch(args):
    if not (args.get("patch_text") or args.get("field_code") or args.get("glsl") or args.get("sketch_js")):
        return {"ok": False, "error": "give patch_text, field_code or sketch_js"}
    out = _out(args, "out_path", "patch.inf")
    text = args.get("patch_text") or build_patch(args.get("field_code") or args.get("glsl"),
                                                 args.get("sketch_js"), args.get("synth_type", "wavetable"))
    with open(out, "w") as f:
        f.write(text)
    res = {"ok": True, "patch_file": out}
    if args.get("validate", True):
        res["validation"] = run_cli(["--validate", out] + _common(args))
    return res


def t_frames(args):
    times = args.get("times", [1.0])
    if not isinstance(times, list):
        times = [times]
    tstr = ",".join(str(t) for t in times)

    def go(path):
        out = _out(args, "out_path", "frame.png" if len(times) == 1 else "frames")
        if len(times) > 1 and os.path.splitext(out)[1]:
            out = os.path.splitext(out)[0]
            os.makedirs(out, exist_ok=True)
        a = ["--frame", path, tstr, out]
        if args.get("contact_sheet"):
            a += ["--contact-sheet", _out(args, "contact_sheet", "sheet.png")]
        if args.get("repeat"):
            a += ["--repeat", args["repeat"]]
        if args.get("png_level") is not None:
            a += ["--png-level", args["png_level"]]
        res = run_cli(_render_opts(args, a) + _common(args))
        res["out_path"] = out
        return res
    return with_patch(args, go)


def t_frames_dir(args):
    def go(path):
        out = _out(args, "out_dir", "sequence")
        os.makedirs(out, exist_ok=True)
        a = ["--frames-dir", path, out, "--duration", args.get("duration", 2)]
        for k, f in (("start", "--start"), ("fps", "--fps"), ("depth", "--depth")):
            if args.get(k) is not None:
                a += [f, args[k]]
        if args.get("alpha"):
            a.append("--alpha")
        res = run_cli(a + _common(args), timeout=1800)
        res["out_dir"] = out
        return res
    return with_patch(args, go)


def t_render(args):
    def go(path):
        out = _out(args, "out_path", "render.mp4")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        a = ["--render", path, out, "--duration", args.get("duration", 4)]
        for k, f in (("start", "--start"), ("fps", "--fps"), ("bpm", "--bpm"), ("codec", "--codec")):
            if args.get(k) is not None:
                a += [f, args[k]]
        if args.get("no_audio"):
            a.append("--no-audio")
        if args.get("plugin_params"):
            a += ["--plugin-params", args["plugin_params"]]
        res = run_cli(_render_opts(args, a) + _common(args), timeout=3600)
        res["out_path"] = out
        res["attribution"] = ATTRIBUTION
        return res
    return with_patch(args, go)


def t_audio_summary(args):
    def go(path):
        js = _new_path(".json")
        a = ["--audio-summary", path, js]
        if args.get("wav_path"):
            a += ["--wav", _out(args, "wav_path", "audio.wav")]
        if args.get("output"):
            a += ["--output", args["output"]]
        if args.get("stems"):
            a += ["--stems", ",".join(args["stems"]) if isinstance(args["stems"], list) else args["stems"]]
            a += ["--stems-dir", _out(args, "stems_dir", "stems")]
        if args.get("notes"):
            a.append("--notes")
        if args.get("note_map"):
            a.append("--note-map")
        if args.get("timeline"):
            a.append("--timeline")
        for k, f in (("duration", "--duration"), ("start", "--start"), ("bpm", "--bpm"),
                     ("sample_rate", "--sample-rate")):
            if args.get(k) is not None:
                a += [f, args[k]]
        res = run_cli(a + _common(args), timeout=1800)
        try:
            with open(js) as f:
                res["summary_file"] = json.load(f)
        except Exception:
            pass
        finally:
            if os.path.exists(js):
                os.remove(js)
        return res
    return with_patch(args, go)


def t_version(args):
    res = run_cli(["--version", "--json"], timeout=30)
    res["plugin_version"] = VERSION
    res["binary"] = find_infinite()
    return res


def t_docs(args):
    topic = args.get("topic")
    if not topic:
        ex = sorted(os.listdir(os.path.join(HERE, "examples")))
        return {"ok": True, "topics": {k: v[1] for k, v in DOCS.items()}, "examples": ex,
                "hint": "topic=<name> for a doc; topic=example:<file> for an example patch"}
    if topic.startswith("example:"):
        name = os.path.basename(topic.split(":", 1)[1])
        path = os.path.join(HERE, "examples", name)
    elif topic in DOCS:
        path = os.path.join(HERE, DOCS[topic][0])
    else:
        return {"ok": False, "error": f"unknown topic {topic}", "topics": list(DOCS)}
    if not os.path.isfile(path):
        return {"ok": False, "error": "not found"}
    with open(path) as f:
        return {"ok": True, "topic": topic, "text": f.read()}


# ---------------------------------------------------------------- schemas

_PATCH_SRC = {
    "patch_file": {"type": "string", "description": "Path to an existing .inf patch."},
    "patch_text": {"type": "string", "description": "Full .inf patch text (written to a temp file for the call)."},
}
_GEN_SRC = {
    "field_code": {"type": "string", "description": "Field pixel kernel (bare names, no @; e.g. 'col = vec3(0.5+0.5*sin(length(uv-0.5)*20.0-t))'). Wrapped in a small audio-reactive patch."},
    "glsl": {"type": "string", "description": "Deprecated alias of field_code (the code is Field, not GLSL)."},
    "sketch_js": {"type": "string", "description": "2D JavaScript sketch (Source > Sketch): draw(t), circle(), rect(), hsl()."},
    "synth_type": {"type": "string", "enum": ["wavetable", "fm"], "default": "wavetable"},
}
_COMMON = {
    "lenient": {"type": "boolean", "description": "Treat warnings as non-fatal."},
    "timeout_seconds": {"type": "number", "description": "Engine timeout (--timeout)."},
}
_RENDER = {
    "size": {"type": "string", "description": "WxH, e.g. 1280x720."},
    "node": {"type": ["integer", "string"], "description": "Render this node (index or index:output) instead of the Output."},
    "set": {"type": "array", "items": {"type": "string"}, "description": "Overrides like 'node.param=value'."},
}


def schema(*parts, required=()):
    props = {}
    for p in parts:
        props.update(p)
    s = {"type": "object", "properties": props}
    if required:
        s["required"] = list(required)
    return s


def ann(title, read_only, destructive=False, idem=True):
    return {"title": title, "readOnlyHint": read_only, "destructiveHint": destructive,
            "idempotentHint": idem, "openWorldHint": False}


def tool(name, title, desc, sch, a, fn):
    return {"name": name, "title": title, "description": desc, "inputSchema": sch, "annotations": a, "_fn": fn}


TOOL_LIST = [
    tool("infinite_docs", "Read Infinite docs and examples",
         "Bundled reference: the .inf patch format, connection rules, headless CLI guide, Field language, and example patches. Call with no topic to list them. Read patch-format and field-language before writing a patch.",
         schema({"topic": {"type": "string", "description": "patch-format | connection-rules | headless | field-language | example:<file>"}}),
         ann("Read Infinite docs and examples", True), t_docs),
    tool("infinite_describe", "Describe Infinite nodes",
         "Discover the 327 node types: list/search by name or category, or pass type for one node's parameters (key, default, min, max, options), input slots and outputs. Always call this before using a node; never guess keys.",
         schema({"type": {"type": "string", "description": "Exact node type name for full detail."},
                 "search": {"type": "string", "description": "Substring filter on type name."},
                 "category": {"type": "string", "description": "3D, AudioEffects, Compositing, Effects, Macros, Modulators, Notes, Prediction, Source, Synths, Utility."}}),
         ann("Describe Infinite nodes", True), t_describe),
    tool("infinite_write_patch", "Write an Infinite patch file",
         "Write a .inf patch to disk from patch_text, or generate one from field_code / sketch_js, then validate it. Returns patch_file for the other tools.",
         schema(_PATCH_SRC, _GEN_SRC, _COMMON,
                {"out_path": {"type": "string", "description": "Where to write the .inf (default: temp folder)."},
                 "validate": {"type": "boolean", "default": True}}),
         ann("Write an Infinite patch file", False, True), t_write_patch),
    tool("infinite_validate_patch", "Validate Infinite patch",
         "Check a patch for syntax, wiring and graph errors (strict by default). Every issue has a code, line, node and hint. Fix until ok.",
         schema(_PATCH_SRC, _COMMON, {"for_render": {"type": "boolean", "description": "Also refuse hardware sources (--for-render)."}}),
         ann("Validate Infinite patch", True), t_validate),
    tool("infinite_explain_patch", "Explain Infinite patch",
         "Print the graph the engine actually built (nodes, wires, modulation, unreachable nodes) so you can compare it with intent.",
         schema(_PATCH_SRC, _COMMON, {"all": {"type": "boolean", "description": "Include every parameter, not just changed ones."}}),
         ann("Explain Infinite patch", True), t_explain),
    tool("infinite_canonicalize_patch", "Canonicalize Infinite patch",
         "Rewrite a patch in the app's canonical form (stable ids, normalized order) to a new file.",
         schema(_PATCH_SRC, _COMMON, {"out_path": {"type": "string"}, "keep_ids": {"type": "boolean"}}),
         ann("Canonicalize Infinite patch", False, True), t_canonicalize),
    tool("infinite_render_frame", "Render still frames",
         "Render one or more PNG frames at times (seconds) from a patch, Field kernel or 2D sketch. Returns per-frame stats (mean_luma etc.); optional contact sheet.",
         schema(_PATCH_SRC, _GEN_SRC, _COMMON, _RENDER,
                {"times": {"type": "array", "items": {"type": "number"}, "default": [1.0]},
                 "out_path": {"type": "string", "description": "PNG path (one time) or folder."},
                 "contact_sheet": {"type": "string", "description": "Path for a contact sheet PNG."},
                 "repeat": {"type": "integer", "minimum": 1, "maximum": 8},
                 "png_level": {"type": "integer", "minimum": 0, "maximum": 9}}),
         ann("Render still frames", False, True), t_frames),
    tool("infinite_render_frames_dir", "Render frame sequence",
         "Render a numbered PNG sequence for a duration (optionally 16-bit or with alpha).",
         schema(_PATCH_SRC, _GEN_SRC, _COMMON,
                {"out_dir": {"type": "string"}, "duration": {"type": "number", "default": 2},
                 "start": {"type": "number"}, "fps": {"type": "number"}, "alpha": {"type": "boolean"},
                 "depth": {"type": "integer", "enum": [8, 16]}}),
         ann("Render frame sequence", False, True), t_frames_dir),
    tool("infinite_render_video", "Render audio-reactive video",
         "Render a video with synced audio (mp4 h264, or mov prores4444) from a patch, Field kernel or 2D sketch.",
         schema(_PATCH_SRC, _GEN_SRC, _COMMON, _RENDER,
                {"out_path": {"type": "string", "description": "Output .mp4 or .mov path."},
                 "duration": {"type": "number", "default": 4}, "start": {"type": "number"},
                 "fps": {"type": "number"}, "bpm": {"type": "number"},
                 "codec": {"type": "string", "enum": ["h264", "prores4444"]},
                 "no_audio": {"type": "boolean"}, "plugin_params": {"type": "string"}}),
         ann("Render audio-reactive video", False, True), t_render),
    tool("infinite_audio_summary", "Measure patch audio",
         "Render the audio only and return measurements (levels, spectrum, silence), optionally a WAV, per-node stems, notes, note map and timeline.",
         schema(_PATCH_SRC, _GEN_SRC, _COMMON,
                {"wav_path": {"type": "string"}, "output": {"type": "string"},
                 "stems": {"type": "array", "items": {"type": "string"}, "description": "Node ids to export as stems."},
                 "stems_dir": {"type": "string"}, "notes": {"type": "boolean"}, "note_map": {"type": "boolean"},
                 "timeline": {"type": "boolean"}, "duration": {"type": "number"}, "start": {"type": "number"},
                 "bpm": {"type": "number"}, "sample_rate": {"type": "integer"}}),
         ann("Measure patch audio", False, True), t_audio_summary),
    tool("infinite_version", "Infinite version and install check",
         "Report the installed Infinite version and the binary path this plugin found.",
         schema(), ann("Infinite version and install check", True), t_version),
]
TOOLS = [{k: v for k, v in t.items() if k != "_fn"} for t in TOOL_LIST]
HANDLERS = {t["name"]: t["_fn"] for t in TOOL_LIST}
HANDLERS["infinite_render_frames"] = t_frames


def handle_tool_call(name, args):
    fn = HANDLERS.get(name)
    if not fn:
        return {"ok": False, "error": f"unknown tool {name}"}
    try:
        return fn(args or {})
    except Exception as e:  # keep the server alive
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- stdio

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def stdio_mcp_loop():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "serverInfo": {"name": "infinite-mcp", "version": VERSION},
                "capabilities": {"tools": {}}}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            out = handle_tool_call(params.get("name"), params.get("arguments"))
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, indent=2)}],
                "isError": out.get("ok") is False and "error" in out}})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        for n, a in (("infinite_version", {}),
                     ("infinite_write_patch", {"field_code": "col = vec3(0.5+0.5*sin(length(uv-0.5)*20.0-t))\ncol.r = 1.0"}),
                     ("infinite_render_frame", {"field_code": "col = vec3(uv.x, uv.y, 0.5)", "times": [0.5]})):
            print(n, json.dumps(handle_tool_call(n, a), indent=1)[:1500])
        return
    stdio_mcp_loop()


if __name__ == "__main__":
    main()
