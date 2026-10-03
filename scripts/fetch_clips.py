"""Download the clips listed in clips/clips.json into data/clips/.

    python scripts/fetch_clips.py                         # every collection
    python scripts/fetch_clips.py synthetic               # just one
    python scripts/fetch_clips.py synthetic --zip x.zip   # use a Simuletic archive you already have

Real CCTV comes from the DCSASS split of UCF-Crime, which stores each video as short numbered
segments; the segments covering a clip are joined and trimmed. Shelf picks are cut from MERL
Shopping videos. Both are for research use only. Synthetic clips come from Simuletic's CC BY 4.0
sample (about 500 MB to download, 12 MB kept).
"""

import argparse
import json
import math
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "clips"
SIMULETIC = "https://www.kaggle.com/api/v1/datasets/download/simuletic/cctv-shoplifting-detection-dataset-yolo-and-vlm"
DCSASS = "https://huggingface.co/datasets/Centrique/tcc-shoplifting/resolve/main/DCSASS_Dataset"
MERL = "https://huggingface.co/datasets/Voxel51/MERL_Shopping_Dataset/resolve/main/data"


def download(url: str, path: Path) -> Path:
    if not path.exists() or path.stat().st_size == 0:
        urllib.request.urlretrieve(url, path)
    return path


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out)


def trim(src: Path, start: float, end: float, dst: Path) -> None:
    ffmpeg("-ss", f"{start}", "-to", f"{end}", "-i", str(src), "-an", "-c:v", "libx264", "-crf", "18",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst))


def fetch_synthetic(clips, archive: Path | None, tmp: Path) -> None:
    archive = archive or download(SIMULETIC, tmp / "simuletic.zip")
    with zipfile.ZipFile(archive) as zf:
        names = {Path(n).name: n for n in zf.namelist() if "/videos/" in n}
        for clip in clips:
            with zf.open(names[clip["file"]]) as src, open(OUT / f"{clip['id']}.mp4", "wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"  {clip['id']}.mp4")


def fetch_real(clips, tmp: Path) -> None:
    for clip in clips:
        video = f"{clip['video']}_x264"
        first = download(f"{DCSASS}/{video}.mp4/{video}_0.mp4", tmp / f"{video}_0.mp4")
        length = duration(first)  # every segment of a video has the same length
        wanted = range(int(clip["start"] // length), math.ceil(clip["end"] / length))
        listing = tmp / f"{clip['id']}.txt"
        listing.write_text("".join(
            f"file '{download(f'{DCSASS}/{video}.mp4/{video}_{i}.mp4', tmp / f'{video}_{i}.mp4')}'\n" for i in wanted))
        joined = tmp / f"{clip['id']}-joined.mp4"
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined))
        offset = wanted[0] * length
        trim(joined, clip["start"] - offset, clip["end"] - offset, OUT / f"{clip['id']}.mp4")
        print(f"  {clip['id']}.mp4")


def fetch_picks(clips, tmp: Path) -> None:
    for clip in clips:
        src = download(f"{MERL}/{clip['video']}_crop.mp4", tmp / f"{clip['video']}.mp4")
        trim(src, clip["start"], clip["end"], OUT / f"{clip['id']}.mp4")
        print(f"  {clip['id']}.mp4")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("collections", nargs="*")
    parser.add_argument("--zip", type=Path, help="Simuletic archive already on disk")
    args = parser.parse_args()

    manifest = json.loads((ROOT / "clips" / "clips.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for collection in manifest["collections"]:
            if args.collections and collection["id"] not in args.collections:
                continue
            print(f"{collection['name']} ({collection['source']['license']})")
            if collection["id"] == "synthetic":
                fetch_synthetic(collection["clips"], args.zip, tmp)
            elif collection["id"] == "real":
                fetch_real(collection["clips"], tmp)
            elif collection["id"] == "picks":
                fetch_picks(collection["clips"], tmp)


if __name__ == "__main__":
    main()
