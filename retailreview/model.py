"""Backends that answer yes/no checks about video frames.

`ClefBackend` runs Clef-flash on the local GPU. `FakeBackend` returns stable made-up numbers so
the server and page can be worked on without a GPU.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import time

import numpy as np

from .checks import STATE, wire

MODEL_ID = "Cloudflare/clef-flash"


class Backend:
    name = "base"
    device = ""

    def ask(self, clips: list[tuple[np.ndarray, float]], checks: dict) -> tuple[list[dict[str, float]], float]:
        """Answer `checks` for each (frames, frames_per_second) item.

        Returns the probability of "yes" per check for every item, and the seconds it took.
        """
        raise NotImplementedError

    def info(self) -> dict:
        return {"backend": self.name, "model": MODEL_ID, "device": self.device}


class ClefBackend(Backend):
    name = "clef"

    def __init__(self, path: str | None = None, batch: int = 4) -> None:
        import torch
        from huggingface_hub import snapshot_download

        self.torch = torch
        self.path = path or snapshot_download(MODEL_ID)
        sys.path.insert(0, self.path)
        from joint_schema_model import collate_records, encode_record, load_release_model

        self._encode, self._collate = encode_record, collate_records
        self.model, self.processor = load_release_model(self.path, device="cuda")
        self.device = torch.cuda.get_device_name(0)
        self.batch = batch
        self._lock = threading.Lock()

    def _record(self, frames: np.ndarray, fps: float, schema: dict):
        n = len(frames)
        metadata = {"fps": fps, "total_num_frames": n, "duration": n / fps, "frames_indices": list(range(n))}
        record = {
            "state": STATE,
            "videos": [frames],
            "media_kwargs": {"do_sample_frames": False, "video_metadata": [metadata]},
            "questions": schema,
        }
        return self._encode(self.processor.tokenizer, record, processor=self.processor)

    def ask(self, clips, checks):
        torch = self.torch
        schema = wire(checks)
        out: list[dict[str, float]] = []
        with self._lock, torch.inference_mode():
            torch.cuda.synchronize()
            started = time.perf_counter()
            for i in range(0, len(clips), self.batch):
                encoded = [self._record(frames, fps, schema) for frames, fps in clips[i : i + self.batch]]
                batch = self._collate(encoded, self.processor.tokenizer.pad_token_id, torch.device("cuda"))
                for record, logits in zip(encoded, self.model(batch)):
                    answers = {}
                    for question, question_logits in zip(record.questions, logits):
                        probs = dict(zip(question.option_ids, question_logits.float().softmax(-1).tolist()))
                        answers[question.question_id] = probs["true"]
                    out.append(answers)
            torch.cuda.synchronize()
            seconds = time.perf_counter() - started
        return out, seconds


class FakeBackend(Backend):
    """Deterministic numbers derived from the pixels, so the same input always gives the same answer."""

    name = "fake"
    device = "cpu"

    def ask(self, clips, checks):
        out = []
        for frames, _fps in clips:
            digest = hashlib.sha256(np.ascontiguousarray(frames[:, ::32, ::32]).tobytes()).digest()
            out.append({key: digest[i] / 255 for i, key in enumerate(checks)})
        return out, 0.001 * len(clips)


def make_backend() -> Backend:
    if os.environ.get("RETAIL_BACKEND", "clef") == "fake":
        return FakeBackend()
    return ClefBackend()
