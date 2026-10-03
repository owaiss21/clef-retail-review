"""One review of one clip, streamed as events.

1. `clip`     the clip's length and how it will be cut up
2. `checks`   whole-clip answers and the flag they add up to
3. `moment`   one per window: what is happening at that point in the clip
4. `xray`     one per segment: the flag again with that segment greyed out
5. `done`     totals
"""

from __future__ import annotations

from typing import Iterator

from .checks import CLIP_CHECKS, MOMENT_CHECKS, flag
from .model import Backend
from .video import Clip, segments, windows

WINDOW_FRAMES = 6  # 1.5 s at 4 fps
WINDOW_STEP = 2  # every 0.5 s
XRAY_SEGMENTS = 6


def review(backend: Backend, clip: Clip) -> Iterator[dict]:
    spans = windows(clip, WINDOW_FRAMES, WINDOW_STEP)
    parts = segments(clip, XRAY_SEGMENTS)

    def at(i: int) -> float:
        return round(min(clip.duration, i / clip.rate), 3)

    yield {
        "event": "clip",
        "duration": round(clip.duration, 3),
        "frames": len(clip.frames),
        "size": [int(clip.frames.shape[2]), int(clip.frames.shape[1])],
        "checks": {k: q["label"] for k, q in CLIP_CHECKS.items()},
        "moments": {k: q["label"] for k, q in MOMENT_CHECKS.items()},
        "windows": [[at(a), at(b)] for a, b in spans],
        "segments": [[at(a), at(b)] for a, b in parts],
    }

    [answers], seconds = backend.ask([(clip.frames, clip.rate)], CLIP_CHECKS)
    base = flag(answers)
    total = seconds
    yield {"event": "checks", "answers": _round(answers), "flag": round(base, 4), "seconds": round(seconds, 3)}

    for i, (a, b) in enumerate(spans):
        [moment], seconds = backend.ask([(clip.window(a, b), clip.rate)], MOMENT_CHECKS)
        total += seconds
        yield {"event": "moment", "i": i, "answers": _round(moment), "seconds": round(seconds, 3)}

    for k, (a, b) in enumerate(parts):
        [masked], seconds = backend.ask([(clip.blank(a, b), clip.rate)], CLIP_CHECKS)
        total += seconds
        without = flag(masked)
        yield {
            "event": "xray",
            "k": k,
            "flag": round(without, 4),
            # positive: this part of the clip was pushing towards a flag
            "effect": round(base - without, 4),
            "answers": _round(masked),
            "seconds": round(seconds, 3),
        }

    yield {"event": "done", "calls": 1 + len(spans) + len(parts), "seconds": round(total, 3)}


def _round(answers: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 4) for k, v in answers.items()}
