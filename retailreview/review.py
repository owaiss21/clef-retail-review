"""One review of one clip, streamed as events.

1. `clip`     the clip's length and how it will be cut up (a photo is not cut up at all)
2. `moment`   one per window: what is happening at that point in the clip
3. `progress` one per cut point: the whole-clip questions asked about the clip up to that second,
              so the page can show the verdict as it would have stood while the clip played
4. `checks`   whole-clip answers and the flag they add up to
5. `xray`     one per segment: the flag again with that segment greyed out
6. `done`     totals

Moments and progress come interleaved in clip order, so a page playing the clip while the review
streams in stays ahead of the playhead.
"""

from __future__ import annotations

from typing import Iterator

from .checks import CLIP_CHECKS, MOMENT_CHECKS, flag
from .model import Backend
from .video import FRAME_PAIR, Clip, overview, segments, windows

WINDOW_FRAMES = 6  # 1.5 s at 4 fps
WINDOW_STEP = 2  # every 0.5 s
XRAY_SEGMENTS = 6
OVERVIEW_FRAMES = 80  # whole-clip questions; 160 frames ran out of memory on a 24 GB card
PROGRESS_STEP = 2.0  # seconds between "so far" verdicts


def review(backend: Backend, clip: Clip) -> Iterator[dict]:
    """A photo only gets the whole-clip checks: there is no "when" in a single frame."""
    spans = [] if clip.still else windows(clip, WINDOW_FRAMES, WINDOW_STEP)
    parts = [] if clip.still else segments(clip, XRAY_SEGMENTS)

    def whole(frames, duration=clip.duration):
        picked = overview(frames, OVERVIEW_FRAMES)
        return picked, len(picked) / duration

    cuts = []  # frame counts for the "so far" verdicts, even and short of the full clip
    t = PROGRESS_STEP
    while not clip.still and t < clip.duration - PROGRESS_STEP / 4:
        cuts.append(max(FRAME_PAIR, int(round(t * clip.rate / FRAME_PAIR)) * FRAME_PAIR))
        t += PROGRESS_STEP

    def at(i: int) -> float:
        return round(min(clip.duration, i / clip.rate), 3)

    yield {
        "event": "clip",
        "duration": round(clip.duration, 3),
        "still": clip.still,
        "frames": 1 if clip.still else len(clip.frames),
        "size": [int(clip.frames.shape[2]), int(clip.frames.shape[1])],
        "checks": {k: q["label"] for k, q in CLIP_CHECKS.items()},
        "moments": {k: q["label"] for k, q in MOMENT_CHECKS.items()},
        "windows": [[at(a), at(b)] for a, b in spans],
        "segments": [[at(a), at(b)] for a, b in parts],
        "cuts": [at(n) for n in cuts],
    }

    total = 0.0
    timeline = sorted([(b, 0, i) for i, (_, b) in enumerate(spans)] + [(n, 1, n) for n in cuts])
    for _, is_cut, key in timeline:
        if is_cut:
            [answers], seconds = backend.ask([whole(clip.frames[:key], key / clip.rate)], CLIP_CHECKS)
            yield {"event": "progress", "t": at(key), "answers": _round(answers),
                   "flag": round(flag(answers), 4), "seconds": round(seconds, 3)}
        else:
            a, b = spans[key]
            [moment], seconds = backend.ask([(clip.window(a, b), clip.rate)], MOMENT_CHECKS)
            yield {"event": "moment", "i": key, "answers": _round(moment), "seconds": round(seconds, 3)}
        total += seconds

    [answers], seconds = backend.ask([whole(clip.frames)], CLIP_CHECKS)
    base = flag(answers)
    total += seconds
    yield {"event": "checks", "answers": _round(answers), "flag": round(base, 4), "seconds": round(seconds, 3)}

    for k, (a, b) in enumerate(parts):
        [masked], seconds = backend.ask([whole(clip.blank(a, b))], CLIP_CHECKS)
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

    yield {"event": "done", "calls": len(cuts) + 1 + len(spans) + len(parts), "seconds": round(total, 3)}


def _round(answers: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 4) for k, v in answers.items()}
