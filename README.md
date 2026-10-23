# Infinite MCP

Drive [Infinite](https://infinitedevices.org), the node-based audio and visual instrument, from Claude. This plugin exposes every headless command of the local Infinite app as a tool: discover the 327 node types, write and validate `.inf` patches, author Field kernels and 2D JavaScript sketches, and render stills, frame sequences, video and audio measurements. Everything runs on your machine.

## Tools

| Tool | What it does |
|---|---|
| `infinite_docs` | Bundled patch format, connection rules, headless guide, Field language and example patches |
| `infinite_describe` | List or search node types; full parameters, ranges, options and slots for one node |
| `infinite_write_patch` | Write a `.inf` patch (from text, a Field kernel or a 2D sketch) and validate it |
| `infinite_validate_patch` | Strict validation with code, line, node and hint per issue |
| `infinite_explain_patch` | The graph the engine actually built, to compare with intent |
| `infinite_canonicalize_patch` | Rewrite a patch in canonical form |
| `infinite_render_frame` | PNG frames at chosen times, contact sheet, per-frame luma stats, per-node render, `--set` overrides |
| `infinite_render_frames_dir` | Numbered PNG sequence (8 or 16 bit, optional alpha) |
| `infinite_render_video` | mp4 (h264) or mov (prores4444) with synced audio |
| `infinite_audio_summary` | Loudness and spectrum measurements, WAV, stems, notes, timeline |
| `infinite_version` | Installed version and binary path |

## Requirements

- Infinite installed (macOS, Windows or Linux). The plugin looks in the usual install locations, or set `INFINITE_BIN` to the executable.
- Python 3.
- On Linux without a display, `xvfb-run` is used automatically.

## Example prompts

- "List the Effects nodes, then build a patch with a kaleidoscope driven by an LFO and render three frames."
- "Write a Field pixel kernel that reacts to bass and render a 6 second video."
- "Validate ~/patches/live.inf and explain why the output is black."
- "Measure the loudness of this patch and export the stems."

## Privacy Policy

This plugin runs entirely on your computer. It starts the local Infinite app, reads the patch files you point it at, and writes the outputs you ask for. It collects no data, makes no network requests and sends nothing anywhere.

## License

MIT. Every tool result carries the note: generated with infinite, by naman soni (https://infinitedevices.org).
