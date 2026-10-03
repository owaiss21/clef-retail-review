"""Record the page as a GIF (and an MP4 next to it) while it reviews a few clips.

    python scripts/record_demo.py docs/img/demo.gif hardware-hide hardware-return

Needs the server running and ffmpeg on PATH. Each clip is filmed until its review is done,
plus a few seconds.
"""

import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("clips", nargs="+")
    parser.add_argument("--url", default="http://127.0.0.1:8000/")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=880)
    parser.add_argument("--hold", type=float, default=2.5, help="seconds to keep filming after a review is done")
    parser.add_argument("--dark", action="store_true")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp())
    stamps = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=1,
                                color_scheme="dark" if args.dark else "light")
        page.goto(f"{args.url}#{args.clips[0]}")
        page.wait_for_selector("#stats dt", timeout=120_000)  # fonts and thumbnails settled

        def film(until):
            while not until():
                path = tmp / f"{len(stamps):05d}.png"
                page.screenshot(path=path)
                stamps.append(time.perf_counter())

        for clip in args.clips:
            page.click(f".clip[data-id='{clip}']")
            page.evaluate("document.getElementById('video').currentTime = 0")
            film(lambda: page.query_selector("#stats dt") is not None)
            stop = time.perf_counter() + args.hold
            film(lambda: time.perf_counter() > stop)
        browser.close()

    # concat list with each frame shown for as long as it was really on screen
    listing = tmp / "frames.txt"
    lines = []
    for i, start in enumerate(stamps):
        end = stamps[i + 1] if i + 1 < len(stamps) else start + 1 / args.fps
        lines += [f"file '{tmp / f'{i:05d}.png'}'", f"duration {end - start:.4f}"]
    listing.write_text("\n".join(lines) + "\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    graph = (f"fps={args.fps},scale={args.width}:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-filter_complex", graph, "-loop", "0", str(args.out)], check=True)
    # same frames as an MP4 at full size, which LinkedIn and most sites play better than a GIF
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart",
                    str(args.out.with_suffix(".mp4"))], check=True)
    shutil.rmtree(tmp)
    print(f"{args.out}  {len(stamps)} frames over {stamps[-1] - stamps[0]:.1f}s, {args.out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
