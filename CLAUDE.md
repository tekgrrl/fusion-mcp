# agentic-cad

MCP server + Fusion add-in that lets Claude drive Autodesk Fusion locally.

```
Claude ──stdio──▶ server/server.py ──TCP 127.0.0.1:9876──▶ addin/FusionMCP (in Fusion) ──▶ Fusion API
```

- `addin/FusionMCP/` — runs inside Fusion (its embedded Python, stdlib only). Socket thread queues
  requests; a CustomEvent runs them on Fusion's main thread. Symlinked into Fusion's AddIns dir by `install.sh`,
  so edits take effect after stopping/re-running the add-in in Fusion (Shift+S), no reinstall.
- `server/server.py` — stdio MCP server (FastMCP; `mcp<2` is pinned because 2.x renamed it).
- Tools: `fusion_ping`, `fusion_design_info`, `fusion_execute` (arbitrary Fusion API Python), `fusion_screenshot`.

## Working in Fusion

- **Before any change, `fusion_ping` and confirm the active document is the one the user intends.**
  Never modify a document the user hasn't pointed at; `mcp-test` is the scratch doc.
- `fusion_execute` does NOT roll back on failure. Keep each call small enough to reason about, and
  if one fails partway, inspect `design.timeline` and clean up before retrying.
- **Verify numerically after every feature**, not just by screenshot: compare `body.volume`, face/body
  counts, and bounding boxes with hand-computed expectations. A wrong result often looks plausible.

## API gotchas (verified in Fusion 2705.1.25)

- Internal units are **cm and radians**. Convert mm inputs (`mm / 10`) explicitly.
- A sketch created on a **face** contains the projected face outline, so `sketch.profiles.item(0)` is
  usually the wrong region. Select profiles by area, e.g. `min(sketch.profiles, key=lambda p: p.areaProperties().area)`,
  or by a point inside them.
- Sketch-space to world mapping on origin planes:
  - XY: (x, y) → world (x, y, 0)
  - XZ: (x, y) → world (x, 0, **-y**)
  - YZ: (x, y) → world (0, y, **-x**)  (sketch x → -Z, sketch y → Y)
  Use `sketch.modelToSketchSpace()` / `point.worldGeometry` instead of doing this by hand.
- `execute` namespace: `adsk, app, ui, design, root`; set `result` to return JSON; `print()` is captured.
  `design` is None if the active product isn't a Design workspace.
