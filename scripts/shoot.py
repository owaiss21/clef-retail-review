"""Screenshot the page after a clip's review finishes.

    python scripts/shoot.py grocery-hide out.png [--dark] [--at 4.0]
"""

import argparse

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("clip")
    parser.add_argument("out")
    parser.add_argument("--url", default="http://127.0.0.1:8000/")
    parser.add_argument("--dark", action="store_true")
    parser.add_argument("--at", type=float, help="pause the video at this second")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": args.width, "height": args.height},
                                color_scheme="dark" if args.dark else "light", device_scale_factor=1)
        page.goto(f"{args.url}#{args.clip}")
        page.wait_for_function("document.body.dataset.state === 'done'", timeout=120_000)
        if args.at is not None:
            page.evaluate(f"(() => {{ const v = document.getElementById('video'); v.pause(); v.currentTime = {args.at}; }})()")
            page.wait_for_timeout(500)
        page.screenshot(path=args.out)
        browser.close()


if __name__ == "__main__":
    main()
