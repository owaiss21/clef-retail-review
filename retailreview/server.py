"""HTTP API and the static page.

A review streams newline-delimited JSON so the timeline fills in while the model works. Finished
reviews are kept on disk; asking again replays them at the speed they were measured.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .checks import CLIP_CHECKS, MOMENT_CHECKS, STATE
from .model import MODEL_ID, Backend, make_backend
from .review import OVERVIEW_FRAMES, PROGRESS_STEP, WINDOW_FRAMES, WINDOW_STEP, XRAY_SEGMENTS, review
from .video import read_clip, read_image

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MEDIA = ROOT / "data" / "clips"
CACHE = ROOT / "data" / "cache"
UPLOADS = ROOT / "data" / "uploads"
MANIFEST = ROOT / "clips" / "clips.json"

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
MAX_UPLOAD_SECONDS = 120


def settings_key() -> str:
    """Anything that changes the answers changes this, so old recordings are never replayed by mistake."""
    blob = json.dumps(
        [MODEL_ID, STATE, CLIP_CHECKS, MOMENT_CHECKS, WINDOW_FRAMES, WINDOW_STEP, XRAY_SEGMENTS,
         OVERVIEW_FRAMES, PROGRESS_STEP, read_clip.__defaults__, read_image.__defaults__],
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def save_upload(data: bytes, filename: str) -> dict:
    """Store an uploaded photo or video under data/uploads and return its clip entry.

    Videos are re-encoded to H.264 MP4 (and cut at MAX_UPLOAD_SECONDS) so every browser can play
    them; photos are re-saved as JPEG. Uploading the same file twice gives the same id.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_TYPES | VIDEO_TYPES:
        raise HTTPException(415, "Upload a video (mp4, mov, webm) or a photo (jpg, png).")
    clip_id = "upload-" + hashlib.sha256(data).hexdigest()[:12]
    kind = "image" if suffix in IMAGE_TYPES else "video"
    target = UPLOADS / f"{clip_id}.{'jpg' if kind == 'image' else 'mp4'}"
    UPLOADS.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / f"raw{suffix}"
            raw.write_bytes(data)
            if kind == "image":
                import cv2

                image = cv2.imread(str(raw), cv2.IMREAD_COLOR)
                if image is None:
                    raise HTTPException(422, "That file isn't a photo this server can read.")
                cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
            else:
                if shutil.which("ffmpeg") is None:
                    raise HTTPException(500, "ffmpeg is needed to accept video uploads.")
                result = subprocess.run(
                    ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(raw), "-t", str(MAX_UPLOAD_SECONDS),
                     "-an", "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-crf", "20",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)],
                    capture_output=True,
                )
                if result.returncode != 0 or not target.exists():
                    target.unlink(missing_ok=True)
                    raise HTTPException(422, "That file isn't a video this server can read.")

    entry = {
        "id": clip_id,
        "kind": kind,
        "media": f"/uploads/{target.name}",
        "scene": Path(filename).stem[:40] or "Upload",
        "short": Path(filename).stem[:16] or "Upload",
        "camera": "UPLOAD",
        "flag": None,
        "labels": [],
        "summary": filename,
    }
    (UPLOADS / f"{clip_id}.json").write_text(json.dumps(entry))
    return entry


def list_uploads() -> list[dict]:
    entries = [json.loads(p.read_text()) for p in UPLOADS.glob("upload-*.json")]
    return sorted(entries, key=lambda e: (UPLOADS / f"{e['id']}.json").stat().st_mtime)


def ndjson(events: Iterator[dict]) -> StreamingResponse:
    def lines():
        try:
            for event in events:
                yield json.dumps(event) + "\n"
        except Exception as exc:  # show model errors on the page instead of a dead socket
            yield json.dumps({"event": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


def create_app(backend: Backend | None = None) -> FastAPI:
    app = FastAPI(title="clef-retail-review")
    model = backend or make_backend()
    manifest = json.loads(MANIFEST.read_text())
    clips = {c["id"]: c for collection in manifest["collections"] for c in collection["clips"]}

    @app.get("/api/health")
    def health():
        return model.info()

    @app.get("/api/clips")
    def list_clips():
        """Collections with the clips that have been downloaded; empty collections are left out."""
        out = []
        for collection in manifest["collections"]:
            ready = [{**c, "kind": "video", "media": f"/media/{c['id']}.mp4"}
                     for c in collection["clips"] if (MEDIA / f"{c['id']}.mp4").exists()]
            if ready:
                out.append({**collection, "clips": ready})
        uploads = list_uploads()
        if uploads:
            out.append({"id": "uploads", "name": "Uploads", "public": False, "clips": uploads,
                        "source": {"name": "uploads", "author": "Your", "url": None,
                                   "license": "kept in data/uploads on this machine", "note": "no labels"}})
        return out

    @app.post("/api/upload")
    async def upload(request: Request):
        """The raw file is the request body; its name comes in the X-Filename header."""
        size = int(request.headers.get("content-length") or 0)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Keep uploads under {MAX_UPLOAD_BYTES // 2**20} MB.")
        data = await request.body()
        if not data:
            raise HTTPException(422, "The upload was empty.")
        return save_upload(data, unquote(request.headers.get("x-filename", "upload.mp4")))

    @app.post("/api/review/{clip_id}")
    def run_review(clip_id: str, fresh: bool = False):
        if clip_id.startswith("upload-") and (UPLOADS / f"{clip_id}.json").exists():
            entry = json.loads((UPLOADS / f"{clip_id}.json").read_text())
            path = UPLOADS / Path(entry["media"]).name
            reader = read_image if entry["kind"] == "image" else read_clip
        elif clip_id in clips:
            path, reader = MEDIA / f"{clip_id}.mp4", read_clip
            if not path.exists():
                raise HTTPException(404, "clip not downloaded; run scripts/fetch_clips.py")
        else:
            raise HTTPException(404, "unknown clip")
        saved = CACHE / f"{clip_id}.{model.name}.{settings_key()}.json"

        def live():
            events = []
            for event in review(model, reader(path)):
                events.append(event)
                yield event
            CACHE.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps(events))

        def replay():
            for event in json.loads(saved.read_text()):
                time.sleep(event.get("seconds", 0) if event["event"] != "done" else 0)
                yield {**event, "replay": True} if event["event"] == "done" else event

        return ndjson(replay() if saved.exists() and not fresh else live())

    app.mount("/media", StaticFiles(directory=MEDIA, check_dir=False), name="media")
    app.mount("/uploads", StaticFiles(directory=UPLOADS, check_dir=False), name="uploads")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=WEB), name="web")
    return app
