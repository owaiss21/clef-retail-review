"""Review every downloaded clip and compare what the model found with the dataset's labels.

    python scripts/evaluate.py               # all collections, writes data/eval.json
    python scripts/evaluate.py real picks    # some of them

For each clip it prints the flag next to the label, and how the timeline lines up with the
labelled moments:
  theft clips   does the strongest "Hiding" window overlap a labelled theft?
  shelf picks   how many labelled reaches have a "Taking" window at 50% or more over them, and
                how many "Taking" windows at 50% or more sit on a labelled reach
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retailreview.model import make_backend  # noqa: E402
from retailreview.review import review  # noqa: E402
from retailreview.video import read_clip  # noqa: E402

THRESHOLD = 0.5


def overlaps(a, b, labels):
    return any(a < lab["end"] and b > lab["start"] for lab in labels)


def main():
    wanted = sys.argv[1:]
    manifest = json.loads((ROOT / "clips" / "clips.json").read_text())
    backend = make_backend()
    print(backend.info())
    warm = read_clip(next((ROOT / "data" / "clips").glob("*.mp4")))
    backend.ask([(warm.frames, warm.rate)], {"warm": {"type": "noul", "instructions": "warm"}})

    rows = []
    for collection in manifest["collections"]:
        if wanted and collection["id"] not in wanted:
            continue
        print(f"\n{collection['name']}")
        for clip in collection["clips"]:
            path = ROOT / "data" / "clips" / f"{clip['id']}.mp4"
            if not path.exists():
                continue
            events = list(review(backend, read_clip(path)))
            meta, checks, done = events[0], events[1], events[-1]
            moments = [e for e in events if e["event"] == "moment"]
            spans = meta["windows"]
            row = {"collection": collection["id"], "clip": clip["id"], "label": clip["flag"],
                   "flag": checks["flag"], "checks": checks["answers"], "seconds": done["seconds"]}

            thefts = [lab for lab in clip["labels"] if lab["kind"] == "theft"]
            reaches = [lab for lab in clip["labels"] if lab["kind"] == "reach"]
            timing = ""
            if thefts:
                best = max(moments, key=lambda e: e["answers"]["hiding"])
                a, b = spans[best["i"]]
                row["hiding_peak"] = [a, b, best["answers"]["hiding"]]
                row["hiding_on_label"] = overlaps(a, b, thefts)
                timing = f"hiding peak {a:.1f}-{b:.1f}s ({best['answers']['hiding']:.2f}) " \
                         f"{'on' if row['hiding_on_label'] else 'OFF'} label"
            if reaches:
                hot = [spans[m["i"]] for m in moments if m["answers"]["taking"] >= THRESHOLD]
                found = sum(any(a < r["end"] and b > r["start"] for a, b in hot) for r in reaches)
                on = sum(overlaps(a, b, reaches) for a, b in hot)
                row["reaches_found"] = [found, len(reaches)]
                row["taking_on_label"] = [on, len(hot)]
                timing = f"reaches found {found}/{len(reaches)}, taking windows on a reach {on}/{len(hot)}"

            ok = (checks["flag"] >= THRESHOLD) == clip["flag"]
            row["correct"] = ok
            rows.append(row)
            answers = " ".join(f"{k}={v:.2f}" for k, v in checks["answers"].items())
            print(f"  {clip['id']:15} {'flag' if clip['flag'] else 'ok  '} -> {checks['flag']:.2f} "
                  f"{'right' if ok else 'WRONG'}  {answers}  {timing}  [{done['seconds']:.1f}s]")

    for cid in dict.fromkeys(r["collection"] for r in rows):
        subset = [r for r in rows if r["collection"] == cid]
        print(f"{cid}: {sum(r['correct'] for r in subset)}/{len(subset)} flags match the labels")
    (ROOT / "data" / "eval.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
