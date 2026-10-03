"""Reading clips into evenly spaced frames, and cutting those frames into windows."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# The vision encoder merges frames in pairs, so every slice we send has an even length.
FRAME_PAIR = 2


@dataclass
class Clip:
    frames: np.ndarray  # (T, H, W, 3) uint8 RGB
    times: list[float]  # seconds, one per frame
    duration: float

    @property
    def rate(self) -> float:
        return len(self.frames) / self.duration

    def window(self, start: int, stop: int) -> np.ndarray:
        return self.frames[start:stop]

    def blank(self, start: int, stop: int) -> np.ndarray:
        """All frames, with frames [start, stop) replaced by flat grey."""
        frames = self.frames.copy()
        frames[start:stop] = 128
        return frames


def read_clip(path, fps: float = 4.0, side: int = 448) -> Clip:
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = total / source_fps
    count = max(FRAME_PAIR, int(round(duration * fps / FRAME_PAIR)) * FRAME_PAIR)
    # sample the middle of each slot rather than its edge, so the last frame isn't the final one
    wanted = ((np.arange(count) + 0.5) * total / count).astype(int)
    frames, times = [], []
    index, next_wanted = 0, 0
    while next_wanted < count:
        ok, frame = cap.read()
        if not ok:
            break
        while next_wanted < count and wanted[next_wanted] == index:
            frames.append(_resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), side))
            times.append(index / source_fps)
            next_wanted += 1
        index += 1
    cap.release()
    if not frames:
        raise ValueError(f"could not read frames from {path}")
    if len(frames) % FRAME_PAIR:
        frames, times = frames[:-1], times[:-1]
    return Clip(np.stack(frames), times, duration)


def _resize(frame: np.ndarray, side: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = side / max(h, w)
    size = (max(32, round(w * scale / 32) * 32), max(32, round(h * scale / 32) * 32))
    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


def windows(clip: Clip, length: int, step: int) -> list[tuple[int, int]]:
    """Frame ranges [start, stop) of `length` frames every `step` frames, covering the whole clip."""
    n = len(clip.frames)
    starts = list(range(0, max(1, n - length + 1), step))
    if starts[-1] + length < n:
        starts.append(n - length)
    return [(s, min(n, s + length)) for s in starts]


def segments(clip: Clip, count: int) -> list[tuple[int, int]]:
    """`count` back-to-back frame ranges, each an even number of frames long."""
    n = len(clip.frames) // FRAME_PAIR
    bounds = np.linspace(0, n, count + 1).round().astype(int) * FRAME_PAIR
    return [(int(a), int(b)) for a, b in zip(bounds[:-1], bounds[1:]) if b > a]
