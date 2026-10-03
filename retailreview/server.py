"""HTTP API and the static page.

A review streams newline-delimited JSON so the timeline fills in while the model works. Finished
reviews are kept on disk; asking again replays them at the speed they were measured.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import review as review_module
from .checks import CLIP_CHECKS, MOMENT_CHECKS, STATE
from .model import MODEL_ID, Backend, make_backend
from .review import review
from .video import read_clip

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MEDIA = ROOT / "data" / "clips"
CACHE = ROOT / "data" / "cache"
MANIFEST = ROOT / "clips" / "clips.json"


def settings_key() -> str:
    """Anything that changes the answers changes this, so old recordings are never replayed by mistake."""
    blob = json.dumps(
        [MODEL_ID, STATE, CLIP_CHECKS, MOMENT_CHECKS, review_module.WINDOW_FRAMES,
         review_module.WINDOW_STEP, review_module.XRAY_SEGMENTS, read_clip.__defaults__],
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


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
            ready = [c for c in collection["clips"] if (MEDIA / f"{c['id']}.mp4").exists()]
            if ready:
                out.append({**collection, "clips": ready})
        return out

    @app.post("/api/review/{clip_id}")
    def run_review(clip_id: str, fresh: bool = False):
        if clip_id not in clips:
            raise HTTPException(404, "unknown clip")
        path = MEDIA / f"{clip_id}.mp4"
        if not path.exists():
            raise HTTPException(404, "clip not downloaded; run scripts/fetch_clips.py")
        saved = CACHE / f"{clip_id}.{model.name}.{settings_key()}.json"

        def live():
            events = []
            for event in review(model, read_clip(path)):
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

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=WEB), name="web")
    return app
