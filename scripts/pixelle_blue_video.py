#!/usr/bin/env python3
import argparse
import asyncio
import base64
import html
import json
import mimetypes
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import edge_tts
from PIL import Image, ImageDraw, ImageOps
from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = ROOT / "assets" / "image_ai_blue_wide.html"
CANVAS_SIZE = (1600, 900)
VIDEO_SIZE = (1080, 1920)
PAD_COLOR = (2, 50, 104)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    )
    return float(out.strip())


def load_scenes(path: Path) -> list[dict]:
    scenes = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("scenes JSON must be a non-empty list")
    for i, scene in enumerate(scenes):
        for key in ("subtitle", "narration"):
            if key not in scene:
                raise ValueError(f"scene {i} missing {key}")
        scene.setdefault("image", i)
    return scenes


def normalize_assets(source_dir: Path, dest_dir: Path, count: int, prefix: str) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(
        [p for p in source_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    )
    if len(candidates) < count:
        raise FileNotFoundError(f"need {count} images in {source_dir}, found {len(candidates)}")

    output_paths = []
    for i, src in enumerate(candidates[:count]):
        image = Image.open(src).convert("RGB")
        canvas = Image.new("RGB", CANVAS_SIZE, PAD_COLOR)
        fitted = ImageOps.contain(image, CANVAS_SIZE, Image.Resampling.LANCZOS)
        x = (CANVAS_SIZE[0] - fitted.width) // 2
        y = (CANVAS_SIZE[1] - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        out = dest_dir / f"{prefix}_{i:02d}.png"
        canvas.save(out, quality=95)
        output_paths.append(out)
    return output_paths


def render_html(template: str, values: dict) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", html.escape(str(value), quote=True))
    return rendered


def image_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def render_frames(
    scenes: list[dict],
    assets: list[Path],
    frame_dir: Path,
    template_path: Path,
    brand: str,
    author: str,
    describe: str,
    tag: str,
) -> list[Path]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    template = template_path.read_text(encoding="utf-8")
    frames = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": VIDEO_SIZE[0], "height": VIDEO_SIZE[1]}, device_scale_factor=1)
        for i, scene in enumerate(scenes):
            image_index = int(scene.get("image", i))
            image_path = assets[image_index].resolve()
            frame_path = frame_dir / f"frame_{i:02d}.png"
            html_text = render_html(
                template,
                {
                    "brand": brand,
                    "author": author,
                    "describe": describe,
                    "tag": tag,
                    "index": f"{i + 1:02d}",
                    "total": f"{len(scenes):02d}",
                    "subtitle": scene["subtitle"],
                    "caption": scene["narration"],
                    "image_uri": image_data_uri(image_path),
                },
            )
            await page.set_content(html_text, wait_until="networkidle")
            await page.screenshot(path=str(frame_path), full_page=False)
            frames.append(frame_path)
        await browser.close()

    return frames


async def synthesize_tts(text: str, output_path: Path, voice: str, speed: float) -> None:
    rate = int(round((speed - 1.0) * 100))
    communicate = edge_tts.Communicate(text, voice=voice, rate=f"{rate:+d}%")
    await communicate.save(str(output_path))


def make_segment(frame: Path, audio: Path, output: Path) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(frame),
            "-i",
            str(audio),
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(output),
        ]
    )


def concat_segments(segments: list[Path], output: Path) -> None:
    with TemporaryDirectory() as tmp:
        filelist = Path(tmp) / "filelist.txt"
        filelist.write_text("".join(f"file '{p.resolve()}'\n" for p in segments), encoding="utf-8")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(output)])


def add_bgm(input_video: Path, bgm: Path, output: Path, volume: float) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video),
            "-stream_loop",
            "-1",
            "-i",
            str(bgm),
            "-filter_complex",
            f"[1:a]volume={volume}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
    )


def make_default_bgm(output: Path, duration: float) -> None:
    fade_out_start = max(0.0, duration - 1.2)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:duration={duration:.3f}:sample_rate=44100",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=330:duration={duration:.3f}:sample_rate=44100",
            "-filter_complex",
            (
                "[0:a]volume=0.10[a0];"
                "[1:a]volume=0.06[a1];"
                "[a0][a1]amix=inputs=2:duration=shortest,"
                f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out_start:.3f}:d=1.0[a]"
            ),
            "-map",
            "[a]",
            "-c:a",
            "mp3",
            str(output),
        ]
    )


def make_contact_sheet(frame_dir: Path, output: Path) -> None:
    frames = sorted(frame_dir.glob("frame_*.png"))
    if not frames:
        return
    thumbs = []
    for i, frame in enumerate(frames):
        image = Image.open(frame).convert("RGB")
        image.thumbnail((180, 320), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (180, 320), (1, 25, 62))
        tile.paste(image, ((180 - image.width) // 2, 0))
        ImageDraw.Draw(tile).text((8, 300), f"{i:02d}", fill=(255, 255, 255))
        thumbs.append(tile)
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 180, rows * 320), (1, 25, 62))
    for i, tile in enumerate(thumbs):
        sheet.paste(tile, ((i % cols) * 180, (i // cols) * 320))
    sheet.save(output, quality=92)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build a blue explainer video from images and a storyboard JSON.")
    parser.add_argument("--scenes", required=True, type=Path, help="JSON list with subtitle/narration/image fields")
    parser.add_argument("--images", required=True, type=Path, help="Directory containing generated images")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--name", default="video", help="Output basename")
    parser.add_argument("--brand", required=True, help="Top-left series name")
    parser.add_argument("--author", required=True, help="Footer account name")
    parser.add_argument("--describe", default="通俗解释")
    parser.add_argument("--tag", default="AI")
    parser.add_argument("--voice", default="zh-CN-YunjianNeural")
    parser.add_argument("--speed", default=0.95, type=float)
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, type=Path)
    parser.add_argument("--bgm", type=Path)
    parser.add_argument("--bgm-volume", default=0.07, type=float)
    parser.add_argument("--no-bgm", action="store_true", help="Disable the default lightweight background music")
    args = parser.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe are required")

    scenes = load_scenes(args.scenes)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = args.out_dir / "assets_1600x900"
    frame_dir = args.out_dir / "frames"
    audio_dir = args.out_dir / "audio"
    segment_dir = args.out_dir / "segments"
    audio_dir.mkdir(parents=True, exist_ok=True)
    segment_dir.mkdir(parents=True, exist_ok=True)

    assets = normalize_assets(args.images, asset_dir, len(scenes), args.name)
    frames = await render_frames(
        scenes,
        assets,
        frame_dir,
        args.template,
        args.brand,
        args.author,
        args.describe,
        args.tag,
    )

    segments = []
    for i, (scene, frame) in enumerate(zip(scenes, frames)):
        audio_path = audio_dir / f"audio_{i:02d}.mp3"
        segment_path = segment_dir / f"segment_{i:02d}.mp4"
        await synthesize_tts(scene["narration"], audio_path, args.voice, args.speed)
        make_segment(frame, audio_path, segment_path)
        segments.append(segment_path)

    no_bgm = args.out_dir / f"{args.name}_no_bgm.mp4"
    final = args.out_dir / f"{args.name}.mp4"
    concat_segments(segments, no_bgm)
    if args.no_bgm:
        shutil.copyfile(no_bgm, final)
    else:
        bgm = args.bgm
        if bgm is None:
            bgm = args.out_dir / "default_bgm.mp3"
            make_default_bgm(bgm, ffprobe_duration(no_bgm))
        if not bgm.exists():
            raise FileNotFoundError(f"BGM not found: {bgm}")
        add_bgm(no_bgm, bgm, final, args.bgm_volume)

    contact_sheet = args.out_dir / "contact_sheet_frames.jpg"
    make_contact_sheet(frame_dir, contact_sheet)

    print(f"FINAL={final}")
    print(f"CONTACT_SHEET={contact_sheet}")
    print(f"DURATION={ffprobe_duration(final):.2f}")
    print(f"FRAMES={len(frames)}")


if __name__ == "__main__":
    asyncio.run(main())
