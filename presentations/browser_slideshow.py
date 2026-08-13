"""Convert simple pptx vector slides to HTML and display them in Chromium."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import html
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

from .powerpoint import PresentationError


A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
STAGE_WIDTH = 1600
STAGE_HEIGHT = 900


def _first(parent, path):
    return parent.find(path) if parent is not None else None


def _color(parent, default="transparent"):
    solid = _first(parent, f"{A}solidFill")
    rgb = _first(solid, f"{A}srgbClr")
    if rgb is not None and rgb.get("val"):
        return f"#{rgb.get('val')}"
    return default


def _number(element, name, default=0):
    try:
        return int(element.get(name, default))
    except (AttributeError, TypeError, ValueError):
        return default


def _shape_html(shape, slide_width, slide_height):
    props = _first(shape, f"{P}spPr")
    transform = _first(props, f"{A}xfrm")
    offset = _first(transform, f"{A}off")
    extent = _first(transform, f"{A}ext")
    if offset is None or extent is None:
        return ""

    x = _number(offset, "x") / slide_width * STAGE_WIDTH
    y = _number(offset, "y") / slide_height * STAGE_HEIGHT
    width = _number(extent, "cx") / slide_width * STAGE_WIDTH
    height = _number(extent, "cy") / slide_height * STAGE_HEIGHT

    identity = _first(_first(shape, f"{P}nvSpPr"), f"{P}cNvPr")
    name = identity.get("name", "") if identity is not None else ""
    geometry = _first(props, f"{A}prstGeom")
    geometry_name = geometry.get("prst", "rect") if geometry is not None else "rect"

    fill = _color(props)
    line = _first(props, f"{A}ln")
    border_color = _color(line)
    border_width = _number(line, "w") / 12700 if line is not None else 0
    if _first(line, f"{A}noFill") is not None:
        border_width = 0

    styles = [
        f"left:{x:.3f}px",
        f"top:{y:.3f}px",
        f"width:{width:.3f}px",
        f"height:{height:.3f}px",
        f"background:{fill}",
        f"border:{border_width:.2f}px solid {border_color}",
    ]
    if geometry_name in ("roundRect", "round1Rect", "round2SameRect"):
        styles.append("border-radius:18px")
    elif geometry_name in ("ellipse", "arc"):
        styles.append("border-radius:50%")
    elif geometry_name in ("chevron", "rightArrow"):
        styles.append("clip-path:polygon(0 0,60% 0,100% 50%,60% 100%,0 100%,40% 50%)")

    body = _first(shape, f"{P}txBody")
    body_props = _first(body, f"{A}bodyPr")
    anchor = body_props.get("anchor", "t") if body_props is not None else "t"
    vertical = {"ctr": "center", "b": "flex-end"}.get(anchor, "flex-start")
    styles.extend(("display:flex", "flex-direction:column", f"justify-content:{vertical}"))

    paragraphs = []
    if body is not None:
        for paragraph in body.findall(f"{A}p"):
            p_props = _first(paragraph, f"{A}pPr")
            alignment = {
                "ctr": "center",
                "r": "right",
                "just": "justify",
            }.get(p_props.get("algn") if p_props is not None else None, "left")
            default_run = _first(p_props, f"{A}defRPr")
            runs = []
            for run in paragraph.findall(f"{A}r"):
                run_props = _first(run, f"{A}rPr")
                props_for_run = run_props if run_props is not None else default_run
                size = _number(props_for_run, "sz", _number(default_run, "sz", 1800)) / 100
                color = _color(props_for_run, _color(default_run, "#172C2B"))
                weight = "700" if props_for_run is not None and props_for_run.get("b") == "1" else "400"
                italic = "italic" if props_for_run is not None and props_for_run.get("i") == "1" else "normal"
                text_node = _first(run, f"{A}t")
                text = html.escape(text_node.text or "") if text_node is not None else ""
                runs.append(
                    f'<span style="font-size:{size * 96 / 72:.2f}px;color:{color};'
                    f'font-weight:{weight};font-style:{italic}">{text}</span>'
                )
            if runs:
                paragraphs.append(
                    f'<div class="paragraph" style="text-align:{alignment}">'
                    + "".join(runs)
                    + "</div>"
                )

    reveal = name.startswith("answer-")
    classes = "shape reveal" if reveal else "shape"
    return (
        f'<div class="{classes}" data-name="{html.escape(name)}" '
        f'style="{";".join(styles)}">{"".join(paragraphs)}</div>'
    )


def render_pptx_html(deck_path):
    """Return one self-contained HTML document rendered from a pptx."""

    with zipfile.ZipFile(deck_path) as package:
        presentation = ET.fromstring(package.read("ppt/presentation.xml"))
        size = _first(presentation, f"{P}sldSz")
        slide_width = _number(size, "cx")
        slide_height = _number(size, "cy")
        if not slide_width or not slide_height:
            raise PresentationError("The PowerPoint file has no slide dimensions")

        slide_names = sorted(
            (
                name
                for name in package.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ),
            key=lambda name: int(Path(name).stem.removeprefix("slide")),
        )
        slides = []
        for index, name in enumerate(slide_names):
            root = ET.fromstring(package.read(name))
            background = _color(_first(_first(root, f"{P}cSld/{P}bg"), f"{P}bgPr"), "#fff")
            tree = _first(root, f"{P}cSld/{P}spTree")
            shapes = "".join(
                _shape_html(shape, slide_width, slide_height)
                for shape in tree.findall(f"{P}sp")
            )
            slides.append(
                f'<section class="slide" data-slide="{index}" style="background:{background}">{shapes}</section>'
            )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Ezra Presentation</title>
<style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#000;font-family:Calibri,Aptos,Arial,sans-serif}}
#viewport{{position:absolute;left:50%;top:50%;width:{STAGE_WIDTH}px;height:{STAGE_HEIGHT}px;transform-origin:center center}}
.slide{{display:none;position:absolute;inset:0;overflow:hidden}}
.slide.active{{display:block}}
.shape{{position:absolute;box-sizing:border-box;overflow:hidden}}
.paragraph{{width:100%;line-height:1.15;white-space:pre-wrap}}
.reveal{{opacity:0;transform:translateY(10px);transition:opacity .35s ease,transform .35s ease}}
body.revealed .reveal{{opacity:1;transform:none}}
</style></head><body><main id="viewport">{"".join(slides)}</main>
<script>
const viewport=document.getElementById('viewport');
function fit(){{const scale=Math.min(innerWidth/{STAGE_WIDTH},innerHeight/{STAGE_HEIGHT});viewport.style.transform=`translate(-50%,-50%) scale(${{scale}})`;}}
addEventListener('resize',fit);fit();
let last='';
async function update(){{try{{const response=await fetch('/state',{{cache:'no-store'}});const state=await response.json();const key=JSON.stringify(state);if(key!==last){{document.querySelectorAll('.slide').forEach((s,i)=>s.classList.toggle('active',i===state.slide));document.body.classList.toggle('revealed',state.revealed);last=key;}}}}catch(e){{}}setTimeout(update,100);}}
update();
</script></body></html>"""


class BrowserSlideshow:
    """Serve rendered slides locally and show them in Chromium kiosk mode."""

    def __init__(self, deck_path):
        self.deck_path = Path(deck_path).resolve()
        self.slide = 0
        self.revealed = False
        self.process = None
        self.server = None
        self.server_thread = None
        self.profile_directory = None
        self.browser_log = None
        self._html = ""

    @staticmethod
    def missing_commands():
        return () if shutil.which("chromium") else ("chromium",)

    def start(self):
        if self.missing_commands():
            raise PresentationError("Missing presentation software: chromium")
        self._html = render_pptx_html(self.deck_path)
        slideshow = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/state"):
                    content = json.dumps(
                        {"slide": slideshow.slide, "revealed": slideshow.revealed}
                    ).encode()
                    content_type = "application/json"
                else:
                    content = slideshow._html.encode()
                    content_type = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.profile_directory = tempfile.TemporaryDirectory(prefix="ezra-slides-")
        url = f"http://127.0.0.1:{self.server.server_port}/"
        browser_environment = os.environ.copy()
        # Ezra is commonly started over SSH, where GUI session variables are
        # absent even though the Pi desktop is active on the attached display.
        gui_defaults = {
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
            "XAUTHORITY": str(Path.home() / ".Xauthority"),
        }
        for variable, value in gui_defaults.items():
            if not browser_environment.get(variable):
                browser_environment[variable] = value
        self.browser_log = tempfile.TemporaryFile(mode="w+t")
        self.process = subprocess.Popen(
            [
                "chromium",
                "--kiosk",
                "--ozone-platform=wayland",
                "--noerrdialogs",
                "--disable-session-crashed-bubble",
                f"--user-data-dir={self.profile_directory.name}",
                url,
            ],
            env=browser_environment,
            stdout=self.browser_log,
            stderr=self.browser_log,
        )
        time.sleep(1.0)
        if self.process.poll() is not None:
            self.browser_log.seek(0)
            details = self.browser_log.read().strip()
            self.close()
            if details:
                details = details.splitlines()[-1]
            raise PresentationError(
                "Chromium exited before displaying the slides"
                + (f": {details}" if details else "")
            )

    def next(self):
        self.slide += 1
        self.revealed = False

    def previous(self):
        self.slide = max(0, self.slide - 1)
        self.revealed = False

    def reveal(self):
        self.revealed = True

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.server_thread is not None:
            self.server_thread.join(timeout=1)
        self.server = None
        self.server_thread = None
        if self.profile_directory is not None:
            self.profile_directory.cleanup()
        self.profile_directory = None
        if self.browser_log is not None:
            self.browser_log.close()
        self.browser_log = None
