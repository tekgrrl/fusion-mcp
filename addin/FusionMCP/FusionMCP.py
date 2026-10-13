"""Fusion add-in: exposes a localhost JSON-line RPC so an external MCP server can drive Fusion.

Threading: a background thread owns the socket server. Fusion's API is main-thread only,
so each request is queued and a CustomEvent is fired; the handler (main thread) runs it
and signals the waiting socket thread with the result.
"""
import contextlib
import io
import json
import os
import queue
import socket
import socketserver
import tempfile
import threading
import traceback
import uuid

import adsk.core
import adsk.fusion

HOST = "127.0.0.1"
PORT = int(os.environ.get("FUSION_MCP_PORT", "9876"))
EVENT_ID = "FusionMCP_dispatch"
REQUEST_TIMEOUT = 120

_app = None
_ui = None
_event = None
_handler = None
_server = None
_pending = queue.Queue()


class _Job:
    def __init__(self, request):
        self.request = request
        self.done = threading.Event()
        self.response = None


# ---------- commands (run on Fusion's main thread) ----------

def _design():
    return adsk.fusion.Design.cast(_app.activeProduct)


def _cmd_ping(_):
    return {"fusion_version": _app.version, "document": _app.activeDocument.name if _app.activeDocument else None}


def _cmd_design_info(_):
    design = _design()
    if not design:
        return {"error": "Active product is not a Design (switch to the Design workspace)."}
    root = design.rootComponent

    def comp_info(c):
        return {
            "name": c.name,
            "bodies": [{"name": b.name, "visible": b.isVisible, "volume_cm3": b.volume if b.isSolid else None,
                        "faces": b.faces.count} for b in c.bRepBodies],
            "sketches": [s.name for s in c.sketches],
            "features": [f.name for f in c.features],
            "occurrences": [o.name for o in c.occurrences],
        }

    return {
        "document": _app.activeDocument.name,
        "units": design.unitsManager.defaultLengthUnits,
        "root": comp_info(root),
        "components": [comp_info(c) for c in design.allComponents if c != root],
        "user_parameters": [{"name": p.name, "expression": p.expression, "value": p.value}
                            for p in design.userParameters],
    }


def _cmd_execute(params):
    code = params.get("code", "")
    design = _design()
    ns = {
        "adsk": adsk, "app": _app, "ui": _ui, "design": design,
        "root": design.rootComponent if design else None,
        "result": None,
    }
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(code, "<fusion_execute>", "exec"), ns)
        return {"ok": True, "stdout": buf.getvalue(), "result": _jsonable(ns.get("result"))}
    except Exception:
        return {"ok": False, "stdout": buf.getvalue(), "error": traceback.format_exc()}


def _cmd_screenshot(params):
    vp = _app.activeViewport
    if params.get("fit", True):
        vp.fit()
    path = os.path.join(tempfile.gettempdir(), f"fusion_mcp_{uuid.uuid4().hex[:8]}.png")
    ok = vp.saveAsImageFile(path, int(params.get("width", 1024)), int(params.get("height", 768)))
    return {"ok": bool(ok), "path": path}


def _jsonable(v):
    try:
        json.dumps(v)
        return v
    except TypeError:
        return repr(v)


COMMANDS = {
    "ping": _cmd_ping,
    "design_info": _cmd_design_info,
    "execute": _cmd_execute,
    "screenshot": _cmd_screenshot,
}


class _EventHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        while True:
            try:
                job = _pending.get_nowait()
            except queue.Empty:
                return
            try:
                fn = COMMANDS.get(job.request.get("cmd"))
                if fn is None:
                    job.response = {"error": f"unknown command {job.request.get('cmd')!r}"}
                else:
                    job.response = {"data": fn(job.request.get("params") or {})}
            except Exception:
                job.response = {"error": traceback.format_exc()}
            finally:
                job.done.set()


# ---------- socket server (background thread) ----------

class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            line = line.strip()
            if not line:
                continue
            try:
                job = _Job(json.loads(line))
                _pending.put(job)
                _app.fireCustomEvent(EVENT_ID)
                if not job.done.wait(REQUEST_TIMEOUT):
                    resp = {"error": "timed out waiting for Fusion main thread"}
                else:
                    resp = job.response
            except Exception:
                resp = {"error": traceback.format_exc()}
            self.wfile.write((json.dumps(resp) + "\n").encode())
            self.wfile.flush()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run(context):
    global _app, _ui, _event, _handler, _server
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        with contextlib.suppress(Exception):
            _app.unregisterCustomEvent(EVENT_ID)
        _event = _app.registerCustomEvent(EVENT_ID)
        _handler = _EventHandler()
        _event.add(_handler)
        _server = _Server((HOST, PORT), _Handler)
        threading.Thread(target=_server.serve_forever, daemon=True).start()
        _ui.messageBox(f"FusionMCP listening on {HOST}:{PORT}")
    except Exception:
        if _ui:
            _ui.messageBox("FusionMCP failed to start:\n" + traceback.format_exc())


def stop(context):
    global _server
    try:
        if _server:
            _server.shutdown()
            _server.server_close()
            _server = None
        if _event and _handler:
            _event.remove(_handler)
        _app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        if _ui:
            _ui.messageBox("FusionMCP failed to stop:\n" + traceback.format_exc())
