"""Display a Bible passage full-screen while Ezra reads it."""

from pathlib import Path
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

import speech_playback

_display_lock = threading.Lock()
_active_display = None


def split_passage_response(response):
    """Return a display title and passage text for a spoken Bible response."""

    match = re.match(
        r"^(?P<title>.+?(?:from the World English Bible|from the NIV))\.\s+"
        r"(?P<text>.+)$",
        response,
        flags=re.DOTALL,
    )
    if match is None:
        return None
    return (
        match.group("title"),
        match.group("text"),
        getattr(response, "verses", ()),
    )


def render_passage_html(title, passage_text, verses=()):
    if verses:
        passage_html = " ".join(
            '<span class="verse">'
            f"<sup>{html.escape(str(number))}</sup>{html.escape(text)}"
            "</span>"
            for number, text in verses
        )
    else:
        passage_html = html.escape(passage_text)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:100%;min-height:100%;background:#101722;color:#f7f1df}}
body{{font-family:Georgia,serif}}
main{{box-sizing:border-box;width:min(92vw,1400px);margin:0 auto;padding:6vh 5vw 50vh}}
h1{{margin:0 0 3vh;color:#d8b66c;font-size:clamp(34px,4.5vw,72px);line-height:1.1}}
p{{margin:0;font-size:clamp(25px,3vw,48px);line-height:1.42;white-space:pre-wrap}}
sup{{color:#d8b66c;font-size:.52em;font-weight:bold;line-height:0;margin-right:.18em;vertical-align:super}}
.verse{{display:inline}}
</style></head><body><main>
<h1>{html.escape(title)}</h1><p>{passage_html}</p>
</main><script>
const passage=document.querySelector('p');
const readingPosition=0.5;
let readingSession=null;
let manualScroll=false;
addEventListener('keydown',event=>{{
    if(event.key==='ArrowUp'||event.key==='ArrowDown'){{
        event.preventDefault();
        manualScroll=true;
        const lineHeight=parseFloat(getComputedStyle(passage).lineHeight);
        scrollBy({{top:(event.key==='ArrowDown'?1:-1)*lineHeight,behavior:'smooth'}});
        return;
    }}
    if(event.key===' '){{
        event.preventDefault();
        if(!event.repeat)fetch('/pause',{{method:'POST'}}).catch(()=>{{}});
    }}
}});
async function followReading(){{
  try{{
    const response=await fetch('/state',{{cache:'no-store'}});
    const state=await response.json();
        if(readingSession!==state.reading_session){{
            readingSession=state.reading_session;
            manualScroll=false;
        }}
        if(state.scrolls.length){{
            manualScroll=true;
            for(const direction of state.scrolls){{
                scrollBy(0,direction*innerHeight);
            }}
        }}
        if(!state.auto_follow||manualScroll){{
            setTimeout(followReading,100);
            return;
        }}
    const bounds=passage.getBoundingClientRect();
    const lineHeight=parseFloat(getComputedStyle(passage).lineHeight);
    const readingY=bounds.top+scrollY+lineHeight/2+
      Math.max(0,bounds.height-lineHeight)*state.progress;
        if(readingY<=innerHeight*readingPosition){{
            setTimeout(followReading,100);
            return;
        }}
    const maximum=Math.max(0,document.documentElement.scrollHeight-innerHeight);
    scrollTo(0,Math.min(maximum,Math.max(0,readingY-innerHeight*readingPosition)));
  }}catch(error){{}}
  setTimeout(followReading,100);
}}
followReading();
</script></body></html>"""


class BibleDisplay:
    def __init__(self, title, passage_text, verses=(), read_along=True):
        self.title = title
        self.passage_text = passage_text
        self.verses = tuple(verses)
        self.process = None
        self.profile_directory = None
        self.browser_log = None
        self.server = None
        self.server_thread = None
        self.reading_started_at = None
        self.read_along = read_along
        self.reading_session = 0
        self.scroll_requests = []
        self.scroll_lock = threading.Lock()
        self.reading_duration = max(5.0, len(passage_text.split()) / 2.6)
        self.reading_complete = False
        self.reading_stopped_progress = None
        self.reading_paused_progress = None

    def reading_progress(self):
        if self.reading_complete:
            return 1.0
        if self.reading_stopped_progress is not None:
            return self.reading_stopped_progress
        if self.reading_paused_progress is not None:
            return self.reading_paused_progress
        if self.reading_started_at is None:
            return 0.0
        elapsed = time.monotonic() - self.reading_started_at
        return min(1.0, max(0.0, elapsed / self.reading_duration))

    def begin_reading(self):
        self.reading_started_at = time.monotonic()
        self.reading_session += 1
        self.reading_complete = False
        self.reading_stopped_progress = None

    def queue_scroll(self, direction):
        if direction not in ("up", "down"):
            raise ValueError("Scroll direction must be 'up' or 'down'")
        with self.scroll_lock:
            self.scroll_requests.append(-1 if direction == "up" else 1)

    def take_scroll_requests(self):
        with self.scroll_lock:
            requests = self.scroll_requests
            self.scroll_requests = []
        return requests

    def stop_reading(self):
        """Freeze the passage at its current position when playback ends."""
        self.reading_stopped_progress = self.reading_progress()

    def toggle_reading(self):
        """Pause or resume the visual reading position with speech."""
        if self.reading_started_at is None or self.reading_complete:
            return
        if self.reading_paused_progress is None:
            self.reading_paused_progress = self.reading_progress()
        else:
            self.reading_started_at = (
                time.monotonic() - self.reading_paused_progress * self.reading_duration
            )
            self.reading_paused_progress = None

    def finish_reading(self):
        self.reading_complete = True

    def start(self):
        if shutil.which("chromium") is None:
            raise RuntimeError("Chromium is not installed")

        passage_display = self
        rendered_page = render_passage_html(
            self.title,
            self.passage_text,
            self.verses,
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/state"):
                    content = json.dumps(
                        {
                            "progress": passage_display.reading_progress(),
                            "auto_follow": (
                                passage_display.read_along
                                and passage_display.reading_started_at is not None
                            ),
                            "reading_session": passage_display.reading_session,
                            "scrolls": passage_display.take_scroll_requests(),
                        }
                    ).encode()
                    content_type = "application/json"
                else:
                    content = rendered_page
                    content_type = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

            def do_POST(self):
                if self.path == "/pause":
                    speech_playback.toggle()
                    passage_display.toggle_reading()
                    self.send_response(204)
                    self.end_headers()
                    return
                if self.path in ("/scroll-up", "/scroll-down"):
                    direction = "up" if self.path == "/scroll-up" else "down"
                    passage_display.queue_scroll(direction)
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()
        self.profile_directory = tempfile.TemporaryDirectory(
            prefix="ezra-bible-profile-"
        )

        environment = os.environ.copy()
        defaults = {
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
            "XAUTHORITY": str(Path.home() / ".Xauthority"),
        }
        for variable, value in defaults.items():
            environment.setdefault(variable, value)

        self.browser_log = tempfile.TemporaryFile(mode="w+t")
        self.process = subprocess.Popen(
            [
                "chromium",
                "--kiosk",
                "--ozone-platform=wayland",
                "--password-store=basic",
                "--no-first-run",
                "--no-default-browser-check",
                "--noerrdialogs",
                "--disable-session-crashed-bubble",
                f"--user-data-dir={self.profile_directory.name}",
                f"http://127.0.0.1:{self.server.server_port}/",
            ],
            env=environment,
            stdout=self.browser_log,
            stderr=self.browser_log,
        )
        time.sleep(1.0)
        if self.process.poll() is not None:
            self.browser_log.seek(0)
            details = self.browser_log.read().strip().splitlines()
            self.close()
            suffix = f": {details[-1]}" if details else ""
            raise RuntimeError(f"Chromium could not display the passage{suffix}")

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.server_thread is not None:
            self.server_thread.join(timeout=1.0)
        self.server = None
        self.server_thread = None
        if self.profile_directory is not None:
            self.profile_directory.cleanup()
        self.profile_directory = None
        if self.browser_log is not None:
            self.browser_log.close()
        self.browser_log = None


def show_bible_passage(title, passage_text, verses=(), read_along=True):
    """Show a passage until another visual replaces it or Ezra shuts down."""

    global _active_display

    new_display = BibleDisplay(title, passage_text, verses, read_along)
    new_display.start()

    with _display_lock:
        previous_display = _active_display
        _active_display = new_display

    if previous_display is not None:
        previous_display.close()

    return new_display


def scroll_active_bible_display(direction):
    """Queue a screen-sized scroll for the currently displayed passage."""

    with _display_lock:
        display = _active_display
    if display is None:
        return False
    display.queue_scroll(direction)
    return True


def close_bible_display():
    """Close the currently displayed passage, if any."""

    global _active_display

    with _display_lock:
        display = _active_display
        _active_display = None

    if display is not None:
        display.close()
