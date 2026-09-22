"""Cutroom: a loopback video editor. Start with python3 server.py."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from intelligence import LiveSuggestions, fingerprint, keyword_select
from media import export_video, parse_subtitles, probe_video

ROOT = Path(__file__).resolve().parent
MAX_UPLOAD = 512 * 1024 * 1024
ID = re.compile(r"^[a-f0-9]{32}$")
EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}


class App:
    def __init__(self, storage: Path, live: LiveSuggestions | None = None):
        self.storage = storage.resolve()
        self.storage.mkdir(parents=True, exist_ok=True)
        self.live = live
        self.locks: dict[str, threading.Lock] = {}
        self.guard = threading.Lock()

    def directory(self, identifier: str) -> Path:
        if not ID.fullmatch(identifier):
            raise ValueError("Unknown project.")
        path = self.storage / identifier
        if not path.is_dir() or path.is_symlink():
            raise ValueError("Unknown project.")
        return path

    def read(self, identifier: str) -> dict:
        return json.loads((self.directory(identifier) / "project.json").read_text())

    def save(self, project: dict) -> None:
        path = self.directory(project["id"]) / "project.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(project, ensure_ascii=False, indent=2))
        temporary.replace(path)

    def lock(self, identifier: str) -> threading.Lock:
        with self.guard:
            return self.locks.setdefault(identifier, threading.Lock())

    def new(self) -> tuple[str, Path]:
        identifier = uuid.uuid4().hex
        path = self.storage / identifier
        path.mkdir(mode=0o700)
        return identifier, path

    def finish_import(self, identifier: str, source: Path, name: str, *, demo=False) -> dict:
        project = {
            "id": identifier,
            "name": name[:160],
            "video_url": f"/media/{identifier}/{source.name}",
            **probe_video(source),
            "cues": [],
            "is_demo": demo,
        }
        if project["duration"] > 7200:
            raise ValueError("Video source may be at most two hours.")
        self.save(project)
        return project

    def demo(self) -> dict:
        identifier, path = self.new()
        try:
            shutil.copyfile(ROOT / "demo" / "walkthrough.mp4", path / "source.mp4")
            project = self.finish_import(
                identifier, path / "source.mp4", "The recovery walkthrough", demo=True
            )
            project["cues"] = parse_subtitles((ROOT / "demo" / "walkthrough.srt").read_text())
            project["suggested_goal"] = json.loads((ROOT / "demo" / "recorded.json").read_text())[
                "goal"
            ]
            self.save(project)
            return project
        except Exception:
            shutil.rmtree(path)
            raise

    def suggest(self, project: dict, payload: dict) -> dict:
        goal = payload.get("goal")
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 1000:
            raise ValueError("Enter a goal of 1–1000 characters.")
        goal = goal.strip()
        cues = project["cues"]
        if not cues:
            raise ValueError("Import subtitles first.")
        if payload.get("mode") == "keywords":
            return {
                "selected_ids": keyword_select(cues, goal),
                "judgments": [],
                "mode": "keywords",
                "measurement": {
                    "new_requests": 0,
                    "cached_decisions": 0,
                    "input_tokens": 0,
                    "call_ms": 0,
                },
                "note": "Literal word matches. No AI or network request.",
            }
        if payload.get("mode") != "jev":
            raise ValueError("Unknown suggestion mode.")
        recorded = json.loads((ROOT / "demo" / "recorded.json").read_text())
        if project["is_demo"] and fingerprint(cues, goal) == recorded["fingerprint"]:
            return {
                **recorded["result"],
                "mode": "recorded",
                "measurement": {
                    **recorded["result"]["measurement"],
                    "new_requests": 0,
                    "cached_decisions": len(cues),
                },
                "note": "Recorded Jev answers from the bundled synthetic demo. No new API calls.",
            }
        if self.live is None:
            raise ValueError(
                "This launch uses the recorded demo. Enable Jev in the terminal for custom goals."
            )
        if payload.get("consent") is not True:
            raise ValueError(
                "Confirm sending subtitle text and your goal to TypeSafe. Video stays local."
            )
        return self.live.suggest(cues, goal)


class Handler(BaseHTTPRequestHandler):
    server_version = "Cutroom/0.1"

    @property
    def app(self) -> App:
        return self.server.app

    def log_message(self, fmt, *args):
        # Do not log user filenames, subtitles, goals, or provider responses.
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        super().end_headers()

    def permitted(self, mutation=False) -> bool:
        authority = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != authority:
            self.reply({"error": "Use the printed loopback URL."}, 403)
            return False
        origin = self.headers.get("Origin")
        if mutation and origin is not None and origin != f"http://{authority}":
            self.reply({"error": "Cross-origin request refused."}, 403)
            return False
        if mutation and self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.reply({"error": "Cross-site request refused."}, 403)
            return False
        return True

    def reply(self, data: dict, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def file(self, path: Path):
        if not path.is_file() or path.is_symlink():
            self.reply({"error": "File not found."}, 404)
            return
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                self.reply({"error": "Unsupported byte range."}, 416)
                return
            left, right = match.groups()
            if left:
                start, end = int(left), min(int(right), size - 1) if right else size - 1
            else:
                start, end = max(0, size - int(right)), size - 1
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        content_type = {
            ".vtt": "text/vtt",
            ".srt": "application/x-subrip",
            ".js": "text/javascript",
        }.get(path.suffix, mimetypes.guess_type(path.name)[0])
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if path.suffix in {".zip", ".srt", ".json"}:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = source.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        if not self.permitted():
            return
        path = urlsplit(self.path).path
        try:
            if path in {"/", "/index.html", "/app.js", "/style.css"}:
                self.file(ROOT / ("index.html" if path == "/" else path[1:]))
            elif path == "/api/config":
                self.reply(
                    {
                        "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
                        "jev_available": True,
                        "jev_scope": "all" if self.app.live else "demo",
                        "max_upload_mb": 512,
                        "version": "0.1.0",
                    }
                )
            elif re.fullmatch(r"/api/project/[a-f0-9]{32}", path):
                self.reply(self.app.read(path.rsplit("/", 1)[1]))
            elif match := re.fullmatch(
                r"/media/([a-f0-9]{32})/(source\.(?:mp4|mov|webm|mkv))", path
            ):
                self.file(self.app.directory(match[1]) / match[2])
            elif match := re.fullmatch(
                r"/media/([a-f0-9]{32})/([a-f0-9]{32})/(clip\.(?:mp4|srt|vtt)|timeline.json|cutroom.zip)",
                path,
            ):
                self.file(self.app.directory(match[1]) / match[2] / match[3])
            else:
                self.reply({"error": "Not found."}, 404)
        except (ValueError, OSError):
            self.reply({"error": "Project or file could not be read."}, 404)

    def body_length(self, maximum: int) -> int:
        if (
            self.headers.get("Transfer-Encoding")
            or len(self.headers.get_all("Content-Length", [])) != 1
        ):
            raise ValueError("Supply one Content-Length header.")
        raw = self.headers["Content-Length"]
        if not raw.isdecimal() or not 0 < int(raw) <= maximum:
            raise ValueError("Request is empty or exceeds the size limit.")
        return int(raw)

    def do_POST(self):
        if not self.permitted(mutation=True):
            return
        self.connection.settimeout(60)
        path = urlsplit(self.path).path
        try:
            if path == "/api/upload":
                if self.headers.get_content_type() != "application/octet-stream":
                    raise ValueError("Upload the video as application/octet-stream.")
                length = self.body_length(MAX_UPLOAD)
                name = self.headers.get("X-Filename", "video.mp4")
                # UI sends percent-encoded names; storage never uses the provided name.
                from urllib.parse import unquote

                name = unquote(name)
                extension = Path(name).suffix.lower()
                if extension not in EXTENSIONS:
                    raise ValueError("Choose MP4, MOV, WebM, or MKV video.")
                identifier, directory = self.app.new()
                source = directory / f"source{extension}"
                try:
                    with source.open("wb") as destination:
                        while length:
                            chunk = self.rfile.read(min(65536, length))
                            if not chunk:
                                raise ValueError("Upload was interrupted.")
                            destination.write(chunk)
                            length -= len(chunk)
                    self.reply(self.app.finish_import(identifier, source, Path(name).name), 201)
                except Exception:
                    shutil.rmtree(directory)
                    raise
                return
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Use application/json.")
            length = self.body_length(512 * 1024)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Request was interrupted.")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
            if path == "/api/demo":
                self.reply(self.app.demo(), 201)
                return
            match = re.fullmatch(r"/api/project/([a-f0-9]{32})/(subtitles|suggest|export)", path)
            if not match:
                self.reply({"error": "Not found."}, 404)
                return
            identifier, operation = match.groups()
            lock = self.app.lock(identifier)
            if not lock.acquire(blocking=False):
                self.reply({"error": "This project is busy. Wait for the current operation."}, 409)
                return
            try:
                project = self.app.read(identifier)
                if operation == "subtitles":
                    text = payload.get("text")
                    if not isinstance(text, str):
                        raise ValueError("Choose an SRT or WebVTT subtitle file.")
                    cues = parse_subtitles(text)
                    if any(cue["end"] > project["duration"] + 0.15 for cue in cues):
                        raise ValueError(
                            "Subtitle timing extends beyond this video. Check the matching file."
                        )
                    project.update(cues=cues, is_demo=False)
                    project.pop("suggested_goal", None)
                    self.app.save(project)
                    self.reply(project)
                elif operation == "suggest":
                    self.reply(self.app.suggest(project, payload))
                else:
                    export_id = uuid.uuid4().hex
                    directory = self.app.directory(identifier)
                    output = directory / export_id
                    output.mkdir()
                    try:
                        result = export_video(
                            directory / project["video_url"].rsplit("/", 1)[1],
                            project["cues"],
                            payload.get("selected_ids"),
                            output,
                            payload.get("padding", 0.12),
                        )
                    except Exception:
                        shutil.rmtree(output)
                        raise
                    self.reply(
                        {
                            **{key: value for key, value in result.items() if key != "filenames"},
                            "urls": {
                                key: f"/media/{identifier}/{export_id}/{name}"
                                for key, name in result["filenames"].items()
                            },
                        }
                    )
            finally:
                lock.release()
        except (TimeoutError, ValueError, UnicodeError, OSError) as error:
            message = (
                str(error)
                if isinstance(error, ValueError)
                else "Could not finish the local operation."
            )
            self.reply({"error": message[:300]}, 400)
        except Exception:
            self.reply(
                {"error": "Unexpected local operation failure. Your source is unchanged."}, 500
            )


def make_server(app: App, port: int = 8771) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(
        description="Edit video by selecting transcript lines. Local by default."
    )
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--output", type=Path, default=Path.cwd() / ".cutroom")
    parser.add_argument(
        "--enable-jev", action="store_true", help="Allow consented subtitle-only API requests"
    )
    parser.add_argument(
        "--api-budget", type=int, default=30, help="1–30 new requests for this launch"
    )
    args = parser.parse_args()
    try:
        live = (
            LiveSuggestions(os.environ.get("TYPESAFE_API_KEY", ""), args.api_budget)
            if args.enable_jev
            else None
        )
        server = make_server(App(args.output, live), args.port)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Cutroom → http://127.0.0.1:{server.server_port}/", flush=True)
    print(
        "Jev: explicit subtitle consent required"
        if live
        else "Offline editing + recorded Jev demo",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
