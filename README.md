# clef-retail-review

**Ask an open decision model what happens in a store camera clip, and when.**

![Same shopper, same aisle: one clip gets flagged, the other doesn't](docs/img/demo.gif)

[Clef-flash](https://huggingface.co/Cloudflare/clef-flash) is a 9B open-weight model from Cloudflare that answers typed questions (yes/no, pick one, score) with a probability for every option. It doesn't write text. It reads images and video too, and it runs on one consumer GPU.

A model like that gets filed under "classifier". I wanted to see if it could do something a classifier can't: watch a clip, answer several separate questions about it, and point at the moment that mattered. Nothing here is trained or fine-tuned. Every number below comes from asking questions in plain English.

This is meant to **flag clips for a person to look at**. It doesn't catch anyone. A flag means "someone should watch these few seconds", nothing more.

## What's on the screen

- **The camera.** The clip plays on a loop. When the model thinks something is happening at that moment, a tag shows up on the video (`Hiding 93%`).
- **The timeline.** The clip is cut into 1.5-second windows every half second, and each window is asked three things: is a product in their hand, are they hiding it, are they putting it back? The darker the cell, the more sure the model is. This is the part that answers *when*.
- **Drove the flag.** Each sixth of the clip is greyed out in turn and the whole clip is asked again. A segment lights up when hiding it makes the flag drop.
- **The flag.** Three questions about the whole clip: did they pick something up, did they put it back, did they hide it. The flag is `hid it × (1 − put it back)`, so taking something and returning it never gets flagged, however suspicious it looks.

Click the timeline to jump to that moment.

## Results

Eight clips: four scenes, each with one take where the shopper hides the item and one where they put it back. Same person, same camera, same product in each pair. That makes them a fair test, because the only thing that changes is what the person does.

| Clip | Should flag | Flag | Hid it | Put it back | Hiding peaks at | Labelled action |
|---|---|---:|---:|---:|---|---|
| Phones A | yes | **32%** ✗ | 40% | 20% | 2.3 s (52%) | 2.0–4.0 s |
| Phones B | no | 0% | 1% | 81% | — | 2.0–4.0 s |
| Hardware A | yes | 66% | 74% | 11% | 3.8 s (70%) | 2.0–4.0 s |
| Hardware B | no | 1% | 9% | 87% | — | 2.0–4.0 s |
| Grocery A | yes | 59% | 71% | 17% | 3.8 s (82%) | 3.3–6.7 s |
| Grocery B | no | 1% | 4% | 84% | — | 2.0–4.0 s |
| Clothing A | yes | 81% | 88% | 8% | 3.3 s (94%) | 3.3–6.7 s |
| Clothing B | no | 2% | 6% | 74% | — | 2.0–4.0 s |

- **7 of 8 flags are right** at a 50% cutoff. None of the put-back clips got above 2%.
- **The miss is Phones A.** A woman tucks a phone box under her jacket while facing the camera. The timeline does catch it (hiding at 52%, right where it happens), but the whole-clip question only gives 40%. I left it in because it's the honest result, and it's a good reminder that one question isn't enough.
- **Timing.** In every hiding clip the strongest "hiding" window falls inside the part of the clip the dataset labels as the action. In the put-back clips the "putting back" peak lands inside the labelled part for three of four. The fourth (Phones B) peaks at 5.3 s, just after it.
- **Drove the flag** points at the hiding moment for Hardware, Grocery and Clothing. Greying out that stretch drops the flag by 32 to 51 points. For Phones A, nothing moves it much, which fits the low flag.

Eight clips is a demo, not a benchmark. Don't read these as accuracy figures.

### Speed

On an RTX 4090, in bfloat16:

| | |
|---|---|
| Whole clip, 3 questions (6 s clip, 24 frames) | 0.52 s |
| Whole clip, 3 questions (10 s clip, 40 frames) | 0.86–0.90 s |
| One 1.5 s window, 3 questions | 0.16 s |
| Full review of a 6 s clip (17 calls) | 5.3 s |
| GPU memory | about 20 GB |

These are with `flash-linear-attention` installed but without `causal-conv1d`, which needs a CUDA compiler I didn't have. It should be a little faster with it.

## The footage

The clips come from the free sample of Simuletic's [CCTV Shoplifting Detection Dataset](https://www.kaggle.com/datasets/simuletic/cctv-shoplifting-detection-dataset-yolo-and-vlm), released under CC BY 4.0. They're computer-generated: high-angle store cameras, but no real shoppers. I used them for two reasons. They look like an actual camera feed, and nobody in them is a real person being accused of anything.

The "labelled action" column above comes from the timestamped descriptions that ship with the dataset.

## Running it

You need Python 3.10+, an NVIDIA GPU with about 22 GB free, and ffmpeg for the demo GIF.

```bash
git clone https://github.com/owaiss21/clef-retail-review
cd clef-retail-review
pip install -e ".[model]"
python scripts/fetch_clips.py         # about 500 MB download, keeps 8 clips (12 MB)
retail-review serve                   # http://127.0.0.1:8000
```

The first start downloads Clef-flash from Hugging Face (19 GB). `torch` 2.11 or newer and `transformers` 5.10.2 or newer are required.

Finished reviews are saved under `data/cache`. Opening a clip again replays the saved run at the speed it was measured, and the stats panel says "recorded". Add `?fresh=1` to the page URL to ask the model again.

To work on the page without a GPU, `RETAIL_BACKEND=fake retail-review serve` returns made-up numbers.

Other scripts:

```bash
python scripts/evaluate.py                                        # the results table, from scratch
python scripts/record_demo.py docs/img/demo.gif hardware-hide hardware-return
python scripts/shoot.py clothing-hide shot.png --at 4.0 --dark
pytest
```

## How it fits together

```
retailreview/
  video.py     read a clip into frames at 4 fps, cut windows and segments
  checks.py    the questions, and how they combine into a flag
  model.py     Clef-flash on the GPU, or a fake backend for tests
  review.py    one review as a stream of events: clip, checks, moments, x-ray, done
  server.py    FastAPI; streams newline-delimited JSON and saves finished runs
web/           plain HTML, CSS and JavaScript, no build step
clips/         which clips to use, their labels and where they came from
scripts/       fetch the clips, evaluate, screenshot, record the GIF
```

## License

Code is MIT. The footage belongs to Simuletic and is CC BY 4.0. Clef-flash is Apache-2.0.
