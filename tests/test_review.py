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
    checks = next(e for e in events if e["event"] == "checks")
    assert kinds[0] == "clip" and kinds[-1] == "done"
    before = kinds[1 : kinds.index("checks")]
    assert sorted(before) == sorted(["moment"] * len(meta["windows"]) + ["progress"] * len(meta["cuts"]))
    assert set(kinds[kinds.index("checks") + 1 : -1]) == {"xray"}
    assert kinds.count("moment") == len(meta["windows"])
    assert kinds.count("xray") == len(meta["segments"])
    assert events[-1]["calls"] == len(meta["cuts"]) + 1 + len(meta["windows"]) + len(meta["segments"])
    assert checks["flag"] == pytest.approx(flag(checks["answers"]), abs=1e-3)
    progress = [e["t"] for e in events if e["event"] == "progress"]
    assert progress == sorted(progress) and progress[-1] < meta["duration"]


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
    assert [c["id"] for c in listed] == ["synthetic"]  # collections with nothing downloaded are left out
    assert [c["id"] for c in listed[0]["clips"]] == ["phones-hide"]
    assert listed[0]["source"]["license"] == "CC BY 4.0"

    first = [json.loads(line) for line in client.post("/api/review/phones-hide").text.splitlines()]
    again = [json.loads(line) for line in client.post("/api/review/phones-hide").text.splitlines()]
    assert first[-1]["event"] == "done" and "replay" not in first[-1]
    assert again[-1]["replay"] is True
    assert [e for e in again[:-1]] == first[:-1]

    assert client.post("/api/review/nope").status_code == 404
    assert client.post("/api/review/jacket").status_code == 404  # listed, not downloaded


def test_every_clip_has_labels_inside_its_length():
    manifest = json.loads((server.MANIFEST).read_text())
    ids = [c["id"] for col in manifest["collections"] for c in col["clips"]]
    assert len(ids) == len(set(ids))
    for collection in manifest["collections"]:
        assert collection["source"]["license"]
        for clip in collection["clips"]:
            length = clip["end"] - clip["start"] if "end" in clip else 10.1
            for label in clip["labels"]:
                assert 0 <= label["start"] < label["end"] <= length + 0.01, clip["id"]
            assert clip["flag"] == any(lab["kind"] == "theft" for lab in clip["labels"]), clip["id"]


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MEDIA", tmp_path / "media")
    monkeypatch.setattr(server, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(server, "UPLOADS", tmp_path / "uploads")
    return TestClient(server.create_app(FakeBackend()))


def test_uploaded_photo_gets_checks_but_no_timeline(app_client, tmp_path):
    photo = tmp_path / "shop.png"
    cv2.imwrite(str(photo), np.full((120, 160, 3), 90, np.uint8))
    entry = app_client.post("/api/upload", content=photo.read_bytes(), headers={"X-Filename": "shop%20floor.png"}).json()
    assert entry["kind"] == "image" and entry["scene"] == "shop floor"
    assert app_client.get(entry["media"]).status_code == 200

    events = [json.loads(line) for line in app_client.post(f"/api/review/{entry['id']}").text.splitlines()]
    assert [e["event"] for e in events] == ["clip", "checks", "done"]
    assert events[0]["still"] is True and events[0]["windows"] == []

    listed = app_client.get("/api/clips").json()
    assert listed[-1]["id"] == "uploads" and listed[-1]["clips"][0]["id"] == entry["id"]


def test_uploaded_video_is_reencoded_and_reviewed(app_client, clip_file):
    entry = app_client.post("/api/upload", content=clip_file.read_bytes(), headers={"X-Filename": "door.mov"}).json()
    assert entry["kind"] == "video" and entry["media"].endswith(".mp4")
    again = app_client.post("/api/upload", content=clip_file.read_bytes(), headers={"X-Filename": "door.mov"}).json()
    assert again["id"] == entry["id"]  # same file, same id
    kinds = [json.loads(line)["event"] for line in app_client.post(f"/api/review/{entry['id']}").text.splitlines()]
    assert "moment" in kinds and "xray" in kinds and kinds[-1] == "done"


def test_upload_rejects_what_it_cannot_read(app_client):
    assert app_client.post("/api/upload", content=b"hello", headers={"X-Filename": "notes.txt"}).status_code == 415
    assert app_client.post("/api/upload", content=b"not a png", headers={"X-Filename": "x.png"}).status_code == 422
    assert app_client.post("/api/upload", content=b"not a video", headers={"X-Filename": "x.mp4"}).status_code == 422


def test_long_clips_are_thinned_for_the_whole_clip_question():
    from retailreview.video import overview

    frames = np.zeros((241, 8, 8, 3), np.uint8)
    picked = overview(frames, 80)
    assert len(picked) <= 80 and len(picked) % 2 == 0
    assert len(overview(frames[:40], 80)) == 40
