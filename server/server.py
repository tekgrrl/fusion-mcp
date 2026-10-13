"""MCP server (stdio) that forwards tool calls to the FusionMCP add-in over localhost TCP."""
import json
import os
import socket

from mcp.server.fastmcp import FastMCP, Image

HOST = os.environ.get("FUSION_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("FUSION_MCP_PORT", "9876"))

mcp = FastMCP("fusion")


def call(cmd: str, **params):
    try:
        with socket.create_connection((HOST, PORT), timeout=5) as s:
            s.settimeout(130)
            s.sendall((json.dumps({"cmd": cmd, "params": params}) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise RuntimeError(
            f"Cannot reach the Fusion add-in at {HOST}:{PORT} ({e}). "
            "Is Fusion running with the FusionMCP add-in started (Utilities > Add-Ins)?"
        )
    resp = json.loads(buf)
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["data"]


@mcp.tool()
def fusion_ping() -> dict:
    """Check the connection to Fusion; returns Fusion version and active document name."""
    return call("ping")


@mcp.tool()
def fusion_design_info() -> dict:
    """Summarise the active design: bodies, sketches, features, components, user parameters.
    Lengths are in cm (Fusion's internal unit)."""
    return call("design_info")


@mcp.tool()
def fusion_execute(code: str) -> dict:
    """Run Python inside Fusion with the full Fusion API (adsk.core / adsk.fusion).

    Predefined names: adsk, app, ui, design, root (root component). Set a variable named
    `result` to return a JSON-serialisable value; print() output is captured as stdout.
    The Fusion API uses centimetres and radians internally. Everything runs on Fusion's main
    thread in one call, so batch related steps (sketch + profile + extrude) together.
    On failure returns ok=false with a traceback; partial changes are NOT rolled back.
    """
    return call("execute", code=code)


@mcp.tool()
def fusion_screenshot(width: int = 1024, height: int = 768, fit: bool = True) -> Image:
    """Capture the active Fusion viewport as an image (optionally fit-to-view first)."""
    data = call("screenshot", width=width, height=height, fit=fit)
    if not data["ok"]:
        raise RuntimeError("Fusion failed to save the viewport image")
    try:
        with open(data["path"], "rb") as f:
            return Image(data=f.read(), format="png")
    finally:
        try:
            os.remove(data["path"])
        except OSError:
            pass


if __name__ == "__main__":
    mcp.run()
