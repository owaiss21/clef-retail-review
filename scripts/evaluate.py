"""Review every clip in clips/clips.json and print what the model found next to the labels.

    python scripts/evaluate.py                 # writes data/eval.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retailreview.model import make_backend  # noqa: E402
from retailreview.review import review  # noqa: E402
from retailreview.video import read_clip  # noqa: E402


def main():
    manifest = json.loads((ROOT / "clips" / "clips.json").read_text())
    backend = make_backend()
    print(backend.info())
    rows = []
    for clip in manifest["clips"]:
        frames = read_clip(ROOT / "data" / "clips" / f"{clip['id']}.mp4")
        backend.ask([(frames.frames, frames.rate)], {"warm": {"type": "noul", "instructions": "warm"}})
        events = list(review(backend, frames))
        meta, checks = events[0], events[1]
        moments = [e for e in events if e["event"] == "moment"]
        xray = [e for e in events if e["event"] == "xray"]
        done = events[-1]

        def peak(key):
            best = max(moments, key=lambda e: e["answers"][key])
            a, b = meta["windows"][best["i"]]
            return round(best["answers"][key], 2), round((a + b) / 2, 1)

        top = max(xray, key=lambda e: e["effect"])
        row = {
            "clip": clip["id"],
            "label": clip["flag"],
            "flag": checks["flag"],
            "checks": checks["answers"],
            "checks_ms": round(checks["seconds"] * 1000),
            "window_ms": round(1000 * sum(e["seconds"] for e in moments) / len(moments)),
            "peaks": {k: peak(k) for k in meta["moments"]},
            "xray_top": [meta["segments"][top["k"]], top["effect"]],
            "action": clip["action"],
            "total_s": done["seconds"],
            "events": events,
        }
        rows.append(row)
        print(f"{clip['id']:16} label={'flag' if clip['flag'] else 'ok  '} flag={row['flag']:.2f} "
              f"{json.dumps({k: round(v, 2) for k, v in row['checks'].items()})}")
        print(f"{'':16} peaks {row['peaks']}  xray top {row['xray_top']}  action {clip['action']}  "
              f"clip {row['checks_ms']} ms, window {row['window_ms']} ms, total {done['seconds']:.1f}s")
    correct = sum((r["flag"] >= 0.5) == r["label"] for r in rows)
    print(f"\n{correct}/{len(rows)} flags match the labels at 0.5")
    out = ROOT / "data" / "eval.json"
    out.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
