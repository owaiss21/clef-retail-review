import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from retailreview import server
from retailreview.checks import flag
from retailreview.model import FakeBackend
from retailreview.review import review
from retailreview.video import read_clip, segments, windows


@pytest.fixture
def clip_file(tmp_path):
    path = tmp_path / "clip.mp4"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (96, 96))
    for i in range(24 * 6):
        frame = np.full((96, 96, 3), i % 255, np.uint8)
        out.write(frame)
    out.release()
    return path


def test_read_clip_gives_even_frames_at_the_requested_rate(clip_file):
    clip = read_clip(clip_file, fps=4.0, side=64)
    assert len(clip.frames) % 2 == 0
    assert len(clip.frames) == 24
    assert clip.frames.shape[1:] == (64, 64, 3)
    assert clip.duration == pytest.approx(6.0)


def test_windows_cover_the_clip_and_segments_tile_it(clip_file):
    clip = read_clip(clip_file, side=64)
    spans = windows(clip, 6, 2)
    assert spans[0][0] == 0 and spans[-1][1] == len(clip.frames)
    parts = segments(clip, 6)
    assert parts[0][0] == 0 and parts[-1][1] == len(clip.frames)
    assert all(b == c for (_, b), (c, _) in zip(parts, parts[1:]))
    assert all((b - a) % 2 == 0 for a, b in parts)


def test_review_streams_every_stage_in_order(clip_file):
    events = list(review(FakeBackend(), read_clip(clip_file, side=64)))
    kinds = [e["event"] for e in events]
    meta = events[0]
    assert kinds[0] == "clip" and kinds[1] == "checks" and kinds[-1] == "done"
    assert kinds.count("moment") == len(meta["windows"])
    assert kinds.count("xray") == len(meta["segments"])
    assert events[-1]["calls"] == 1 + len(meta["windows"]) + len(meta["segments"])
    assert events[1]["flag"] == pytest.approx(flag(events[1]["answers"]), abs=1e-3)


def test_flag_needs_hidden_and_not_put_back():
    assert flag({"concealed": 0.9, "put_back": 0.1}) == pytest.approx(0.81)
    assert flag({"concealed": 0.9, "put_back": 0.9}) < 0.1
    assert flag({"concealed": 0.1, "put_back": 0.0}) == pytest.approx(0.1)


def test_server_reviews_then_replays_the_saved_run(clip_file, tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    (media / "phones-hide.mp4").write_bytes(clip_file.read_bytes())
    monkeypatch.setattr(server, "MEDIA", media)
    monkeypatch.setattr(server, "CACHE", tmp_path / "cache")
    client = TestClient(server.create_app(FakeBackend()))

    listed = client.get("/api/clips").json()
    assert [c["id"] for c in listed["clips"]] == ["phones-hide"]
    assert listed["source"]["license"] == "CC BY 4.0"

    first = [json.loads(line) for line in client.post("/api/review/phones-hide").text.splitlines()]
    again = [json.loads(line) for line in client.post("/api/review/phones-hide").text.splitlines()]
    assert first[-1]["event"] == "done" and "replay" not in first[-1]
    assert again[-1]["replay"] is True
    assert [e for e in again[:-1]] == first[:-1]

    assert client.post("/api/review/nope").status_code == 404
    assert client.post("/api/review/grocery-hide").status_code == 404
