"""Download the Simuletic CCTV sample (CC BY 4.0) and copy the clips listed in clips/clips.json
into data/clips/.

    python scripts/fetch_clips.py              # downloads about 500 MB, keeps 8 videos (about 18 MB)
    python scripts/fetch_clips.py --zip x.zip  # use an archive you already have
"""

import argparse
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.kaggle.com/api/v1/datasets/download/simuletic/cctv-shoplifting-detection-dataset-yolo-and-vlm"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "clips")
    args = parser.parse_args()

    manifest = json.loads((ROOT / "clips" / "clips.json").read_text())
    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        archive = args.zip
        if archive is None:
            archive = Path(tmp) / "sample.zip"
            print(f"downloading {URL}")
            urllib.request.urlretrieve(URL, archive)
        with zipfile.ZipFile(archive) as zf:
            names = {Path(n).name: n for n in zf.namelist() if "/videos/" in n}
            for clip in manifest["clips"]:
                with zf.open(names[clip["file"]]) as src, open(args.out / f"{clip['id']}.mp4", "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"  {clip['id']}.mp4")


if __name__ == "__main__":
    main()
