---
name: pixelle-blue-explainer-video
description: Use this Codex-only skill when creating short vertical explainer videos with the established blue-white stick-figure/chalkboard style: generate images with Codex imagegen, render them with the bundled TikTok-safe blue template, synthesize narration with Edge TTS, and compose the final MP4 with the bundled script. Trigger when the user asks for this blue explainer video style, imagegen-based storyboard videos, or similar one-image-per-scene narrated videos.
metadata:
  short-description: Make blue imagegen explainer videos with Pixelle-Video
---

# Pixelle Blue Explainer Video

Use this for a portable lightweight video pipeline:

1. Generate storyboard images with `imagegen`.
2. Normalize images to consistent landscape `1600x900`.
3. Render vertical `1080x1920` frames with the bundled TikTok-safe blue template.
4. Synthesize narration with local Edge TTS.
5. Trim leading/trailing TTS silence, keep a short tail pad, then compose scene clips and final MP4 with the bundled Python script and ffmpeg.
6. Add the bundled default background music unless the user disables it.

This skill is intended for Codex. The video composer is portable Python, but image creation relies on Codex `imagegen`; non-Codex users must provide their own images.

## Required Check

Before producing a video, make sure the user has provided:

- `series name`: top-left brand text, for example `漫解人工智能`.
- `account name`: footer author text, for example `@智元`.

If either is missing and the user has not clearly said to reuse the previous values, ask for both before generating. Keep the question short.

## Bundled Files

This skill is self-contained for composition after images are generated:

- `requirements.txt`: Python dependencies.
- `assets/default_bgm.mp3`: bundled default BGM used when `--bgm` is not provided.
- `assets/image_ai_blue_wide.html`: centered TikTok-safe blue template.
- `assets/scenes.sample.json`: minimal storyboard shape.
- `scripts/setup.sh`: creates a virtualenv and installs Python/browser dependencies.
- `scripts/pixelle_blue_video.py`: normalizes images, renders frames, runs Edge TTS, builds MP4, and creates a contact sheet.

It does not bundle an image generation model. Use the `imagegen` tool to create images first, then pass the image directory to the script.

## Setup

When using this skill in a fresh environment, install the bundled dependencies:

```bash
bash /Users/robin/.codex/skills/pixelle-blue-explainer-video/scripts/setup.sh .venv
source .venv/bin/activate
```

Also require `ffmpeg` and `ffprobe` on PATH.

If working inside the existing Pixelle-Video repo, its `uv` environment can still be used, but prefer the bundled script for portability.

## Image Generation

Use `imagegen` for new images unless the user provides finished assets. Keep prompts consistent:

- blue background, white line art
- simple stick-figure / chalkboard explainer style
- landscape composition
- no readable text inside the image unless necessary
- leave comfortable margins around important objects
- one clear concept per image

After imagegen finishes, collect the generated PNGs into one directory. The bundled script will normalize them automatically into `1600x900` with contain/pad behavior, not crop.

Keep image filenames sorted in scene order, or rename them before running.

Use the same deep-blue background for padding.

## Storyboard

Prefer 8-12 scenes for a concise explainer. Each scene should have:

- `subtitle`: short, fits on one line when possible.
- `narration`: conversational spoken text, usually 1-3 Chinese sentences.
- `image`: matching asset index.

Open with a hook, not a flat topic statement. Good pattern:

`你有没有想过，X 为什么能做到 Y？今天用几分钟拆开它的底层原理。`

## Voice

Use Edge TTS through the bundled Python script:

- default voice: `zh-CN-YunjianNeural`
- common female option: `zh-CN-XiaoxiaoNeural`
- default speed: `0.95`
- default pause after each narration line: about `0.5s`
- no API key is required
- it needs network access, but does not use RunningHub or OpenAI billing

## Script Pattern

Create a `scenes.json` list with fields:

- `image`: index of sorted generated image.
- `subtitle`: short title above the image.
- `narration`: spoken caption and TTS text.

Run:

```bash
python /Users/robin/.codex/skills/pixelle-blue-explainer-video/scripts/pixelle_blue_video.py \
  --scenes /path/to/scenes.json \
  --images /path/to/generated_images \
  --out-dir /path/to/output_dir \
  --name topic_name \
  --brand "漫解人工智能" \
  --author "@智元" \
  --describe "大语言模型 · 通俗解释" \
  --tag "GPT / LLM"
```

Optional:

- `--voice zh-CN-XiaoxiaoNeural`
- `--speed 0.95`
- `--bgm /path/to/bgm.mp3` to override the bundled default BGM
- `--bgm-volume 0.07`
- `--tail-pad 0.35`
- `--end-silence-keep 0.20`
- `--silence-threshold -55dB`
- `--no-bgm`

## Verification

The bundled script prints:

- `FINAL`
- `CONTACT_SHEET`
- `DURATION`
- `FRAMES`

Always view the contact sheet before final response. For deeper inspection, run:

```bash
ffprobe -v error -show_entries format=duration,size -show_entries stream=width,height,codec_name -of json output/<topic>/<topic>.mp4
```

View the contact sheet. Check:

- frames are `1080x1920`
- content is centered, not awkwardly left/right biased
- top title avoids the app top bar
- main image and caption are readable
- footer is not too high, but avoids bottom controls
- no important content is cropped
- narration does not leave long silent gaps between scenes and does not clip the last syllables

Final response should link the MP4, the contact sheet, and any script/template changed.
