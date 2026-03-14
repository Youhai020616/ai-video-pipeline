#!/usr/bin/env python3
"""
Shared utilities for AI Video Pipeline.
API wrappers, ffmpeg helpers, retry logic, and common constants.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests

# ═══════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════

DEERAPI_BASE = "https://api.deerapi.com"
FLUX_ENDPOINT = (
    "https://router.huggingface.co/hf-inference/models/"
    "black-forest-labs/FLUX.1-schnell"
)
NEGATIVE_PROMPT = (
    "morphing, flickering, distorted face, extra fingers, "
    "blurry, low quality, watermark, text overlay"
)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds, exponential backoff


# ═══════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════

def log(msg: str) -> None:
    """Print indented log message."""
    print(f"  {msg}")


# ═══════════════════════════════════════════
# Environment & preflight checks
# ═══════════════════════════════════════════

def check_env(*required_keys: str) -> Dict[str, str]:
    """Validate that required environment variables are set and non-empty.
    Returns a dict of {key: value}. Exits the process if any are missing.
    """
    env = {}
    missing = []
    for key in required_keys:
        val = os.environ.get(key, "").strip()
        if not val:
            missing.append(key)
        env[key] = val
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("   Run: cp .env.example .env  then fill in your API keys.")
        sys.exit(1)
    return env


def check_ffmpeg() -> None:
    """Verify that ffmpeg and ffprobe are installed."""
    for cmd in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run([cmd, "-version"], capture_output=True, timeout=5)
        except FileNotFoundError:
            print(f"❌ '{cmd}' not found. Please install ffmpeg first.")
            print("   macOS:  brew install ffmpeg")
            print("   Ubuntu: sudo apt install ffmpeg")
            sys.exit(1)


def detect_subtitle_font() -> str:
    """Detect best available CJK font for subtitle rendering (cross-platform)."""
    candidates = [
        "PingFang SC",           # macOS
        "Noto Sans CJK SC",     # Linux (common)
        "Microsoft YaHei",      # Windows
        "WenQuanYi Micro Hei",  # Linux fallback
        "Arial",                # universal fallback
    ]
    try:
        result = subprocess.run(
            ["fc-list", ":lang=zh", "family"],
            capture_output=True, text=True, timeout=5,
        )
        for font in candidates:
            if font in result.stdout:
                return font
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Arial"


def api_headers(api_key: str) -> Dict[str, str]:
    """Build authorization headers for DeerAPI requests."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ═══════════════════════════════════════════
# Retry
# ═══════════════════════════════════════════

def with_retry(fn, *args, max_retries: int = MAX_RETRIES, **kwargs):
    """Call fn(*args, **kwargs) with exponential-backoff retry on failure."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_err = exc
            if attempt < max_retries:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log(f"⚠️  Attempt {attempt}/{max_retries} failed: {exc}")
                log(f"    Retrying in {delay}s...")
                time.sleep(delay)
    raise RuntimeError(f"Failed after {max_retries} attempts: {last_err}")


# ═══════════════════════════════════════════
# ffmpeg / ffprobe helpers
# ═══════════════════════════════════════════

def run_ffmpeg(
    args: List[str],
    timeout: int = 120,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run an ffmpeg/ffprobe command. Raises RuntimeError on non-zero exit."""
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, cwd=cwd,
    )
    if result.returncode != 0:
        cmd_preview = " ".join(args[:6])
        stderr_tail = (result.stderr or "")[-500:]
        raise RuntimeError(
            f"Command failed (rc={result.returncode}): {cmd_preview}...\n"
            f"stderr: {stderr_tail}"
        )
    return result


def get_duration(filepath: str) -> float:
    """Get media file duration in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", filepath],
        capture_output=True, text=True, timeout=10,
    )
    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError(f"Cannot read duration of '{filepath}' (empty ffprobe output)")
    return float(raw)


def get_resolution(filepath: str) -> Tuple[int, int]:
    """Get video resolution as (width, height)."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "default=noprint_wrappers=1:nokey=1", filepath],
        capture_output=True, text=True, timeout=10,
    )
    lines = result.stdout.strip().split("\n")
    if len(lines) < 2:
        raise RuntimeError(f"Cannot read resolution of '{filepath}'")
    return int(lines[0]), int(lines[1])


def convert_to_jpg(image_path: str) -> str:
    """Convert any image to JPG using ffmpeg (cross-platform replacement for sips)."""
    jpg_path = os.path.splitext(image_path)[0] + ".jpg"
    if image_path == jpg_path:
        return image_path
    run_ffmpeg(["ffmpeg", "-y", "-i", image_path, "-q:v", "2", jpg_path], timeout=10)
    return jpg_path


def extract_last_frame(video_path: str, output_path: str) -> str:
    """Extract the last frame from a video file."""
    duration = get_duration(video_path)
    run_ffmpeg([
        "ffmpeg", "-y", "-ss", str(max(0, duration - 0.1)),
        "-i", video_path, "-frames:v", "1", "-q:v", "2", output_path,
    ], timeout=15)
    return output_path


# ═══════════════════════════════════════════
# FLUX image generation (HuggingFace)
# ═══════════════════════════════════════════

def flux_generate(prompt: str, output_path: str, hf_token: str) -> str:
    """Generate an image with FLUX.1-schnell via HuggingFace Inference API.
    Returns the output file path.
    """
    log(f"🎨 FLUX: {prompt[:60]}...")
    resp = requests.post(
        FLUX_ENDPOINT,
        headers={
            "Authorization": f"Bearer {hf_token}",
            "Content-Type": "application/json",
        },
        json={"inputs": prompt},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"FLUX HTTP {resp.status_code}: {resp.text[:200]}")
    if len(resp.content) < 1000:
        raise RuntimeError(
            f"FLUX returned suspiciously small response ({len(resp.content)} bytes)"
        )
    with open(output_path, "wb") as f:
        f.write(resp.content)
    log(f"  ✅ {os.path.basename(output_path)} ({os.path.getsize(output_path) // 1024}KB)")
    return output_path


# ═══════════════════════════════════════════
# TTS (OpenAI-compatible via DeerAPI)
# ═══════════════════════════════════════════

def generate_tts(
    text: str,
    output_path: str,
    api_key: str,
    voice: str = "nova",
) -> str:
    """Generate speech audio via OpenAI TTS. Returns output path."""
    resp = requests.post(
        f"{DEERAPI_BASE}/v1/audio/speech",
        headers=api_headers(api_key),
        json={
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"TTS HTTP {resp.status_code}: {resp.text[:200]}")
    if len(resp.content) < 500:
        raise RuntimeError(f"TTS returned too-small audio ({len(resp.content)} bytes)")
    with open(output_path, "wb") as f:
        f.write(resp.content)
    log(f"  ✅ TTS → {os.path.basename(output_path)} ({os.path.getsize(output_path) // 1024}KB)")
    return output_path


# ═══════════════════════════════════════════
# Suno BGM generation
# ═══════════════════════════════════════════

def generate_bgm(
    prompt: str,
    output_path: str,
    api_key: str,
    max_wait: int = 300,
) -> str:
    """Generate instrumental background music via Suno API. Returns output path."""
    log(f"🎵 Suno: {prompt[:50]}...")
    headers = api_headers(api_key)
    resp = requests.post(
        f"{DEERAPI_BASE}/suno/submit/music",
        headers=headers,
        json={
            "prompt": prompt,
            "make_instrumental": True,
            "model": "chirp-v3-5",
            "wait_audio": False,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Suno submit HTTP {resp.status_code}: {resp.text[:200]}")
    task_id = resp.json().get("data")
    if not task_id:
        raise RuntimeError(f"Suno returned no task ID: {resp.json()}")

    for _ in range(max_wait // 15):
        time.sleep(15)
        poll = requests.get(
            f"{DEERAPI_BASE}/suno/fetch/{task_id}",
            headers=headers, timeout=15,
        )
        clips = poll.json().get("data", {}).get("data", [])
        for clip in clips:
            if (clip.get("status") == "complete"
                    and clip.get("audio_url", "").startswith("https://cdn")):
                download_file(clip["audio_url"], output_path)
                log(f"  ✅ BGM ready ({os.path.getsize(output_path) // 1024}KB)")
                return output_path
    raise RuntimeError(f"Suno BGM timed out after {max_wait}s")


# ═══════════════════════════════════════════
# Image upload (freeimage.host)
# ═══════════════════════════════════════════

def upload_image(filepath: str, freeimage_key: str) -> str:
    """Upload an image to freeimage.host and return its public URL.
    Converts PNG→JPG automatically (cross-platform, using ffmpeg).
    """
    if filepath.lower().endswith(".png"):
        filepath = convert_to_jpg(filepath)
    with open(filepath, "rb") as f:
        resp = requests.post(
            "https://freeimage.host/api/1/upload",
            data={"key": freeimage_key},
            files={"source": f},
            timeout=30,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Upload HTTP {resp.status_code}: {resp.text[:200]}")
    url = resp.json().get("image", {}).get("url", "")
    if not url:
        raise RuntimeError(f"Upload returned no URL: {resp.json()}")
    return url


# ═══════════════════════════════════════════
# File download
# ═══════════════════════════════════════════

def download_file(url: str, output_path: str) -> str:
    """Download a file from URL to local path. Returns output path."""
    resp = requests.get(url, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"Download HTTP {resp.status_code} from {url[:80]}")
    with open(output_path, "wb") as f:
        f.write(resp.content)
    log(f"  💾 {os.path.basename(output_path)} ({len(resp.content) // 1024}KB)")
    return output_path


# ═══════════════════════════════════════════
# SRT subtitle helpers
# ═══════════════════════════════════════════

def format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(
    segments: List[str],
    total_duration: float,
    output_path: str,
    delimiters: str = r'[。，！？]',
) -> str:
    """Generate SRT file from text segments, timed proportionally to total_duration.

    Each segment is split into sentences by delimiters, and timing is allocated
    proportionally based on character count.
    """
    all_sentences = []
    for seg in segments:
        parts = re.split(delimiters, seg)
        parts = [p.strip() for p in parts if p.strip()]
        all_sentences.extend(parts)

    if not all_sentences:
        raise ValueError("No sentences could be extracted from segments")

    total_chars = sum(len(s) for s in all_sentences)
    char_rate = total_duration / total_chars  # seconds per character

    entries = []
    current_time = 0.0
    for idx, sentence in enumerate(all_sentences, start=1):
        duration = len(sentence) * char_rate
        start = current_time
        end = current_time + duration
        entries.append(
            f"{idx}\n"
            f"{format_srt_time(start)} --> {format_srt_time(end)}\n"
            f"{sentence}\n"
        )
        current_time = end

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))
    log(f"  ✅ {len(entries)} subtitle entries → {os.path.basename(output_path)}")
    return output_path


# ═══════════════════════════════════════════
# Audio & subtitle assembly helpers
# ═══════════════════════════════════════════

def add_voiceover(video_path: str, voice_path: str, output_path: str) -> str:
    """Mux voiceover audio onto a silent video. Uses shortest duration."""
    run_ffmpeg([
        "ffmpeg", "-y", "-i", video_path, "-i", voice_path,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v", "-map", "1:a", "-shortest", output_path,
    ], timeout=60)
    return output_path


def mix_bgm(
    video_path: str,
    bgm_path: str,
    output_path: str,
    voice_volume: float = 1.5,
    bgm_volume: float = 0.08,
) -> str:
    """Mix looped BGM under the existing voiceover track."""
    run_ffmpeg([
        "ffmpeg", "-y", "-i", video_path, "-i", bgm_path,
        "-filter_complex",
        f"[1:a]aloop=loop=-1:size=2e+09[bgm];"
        f"[bgm]volume={bgm_volume}[bv];"
        f"[0:a]volume={voice_volume}[voice];"
        f"[voice][bv]amix=inputs=2:duration=first:dropout_transition=3[out]",
        "-map", "0:v", "-map", "[out]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", output_path,
    ], timeout=60)
    return output_path


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    font_size: int = 20,
    margin_v: int = 40,
) -> str:
    """Burn SRT subtitles into video. Falls back to plain copy on failure."""
    font = detect_subtitle_font()
    video_path = os.path.abspath(video_path)
    output_path = os.path.abspath(output_path)
    srt_dir = os.path.dirname(os.path.abspath(srt_path))
    srt_name = os.path.basename(srt_path)
    vf = (
        f"subtitles={srt_name}:force_style="
        f"'Fontsize={font_size},PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,Outline=2,Shadow=1,"
        f"Alignment=2,MarginV={margin_v},FontName={font}'"
    )
    try:
        run_ffmpeg(
            ["ffmpeg", "-y", "-i", video_path, "-vf", vf, "-c:a", "copy", output_path],
            timeout=120, cwd=srt_dir,
        )
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            log(f"  ✅ Subtitles burned (font: {font})")
            return output_path
    except RuntimeError as exc:
        log(f"  ⚠️  Subtitle burn failed: {exc}")

    shutil.copy2(video_path, output_path)
    log("  ⚠️  Fallback: video copied without subtitles")
    return output_path


# ═══════════════════════════════════════════
# Kling video generation (DeerAPI)
# ═══════════════════════════════════════════

def kling_submit_image2video(
    image_url: str,
    prompt: str,
    api_key: str,
    duration: str = "5",
    aspect_ratio: str = "9:16",
) -> str:
    """Submit a Kling image-to-video generation task. Returns task_id."""
    resp = requests.post(
        f"{DEERAPI_BASE}/kling/v1/videos/image2video",
        headers=api_headers(api_key),
        json={
            "model_name": "kling-v2-master",
            "image": image_url,
            "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "mode": "std",
        },
        timeout=60,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Kling i2v submit failed: {data}")
    return data["data"]["task_id"]


def kling_submit_text2video(
    prompt: str,
    api_key: str,
    duration: str = "5",
    aspect_ratio: str = "9:16",
) -> str:
    """Submit a Kling text-to-video generation task. Returns task_id."""
    resp = requests.post(
        f"{DEERAPI_BASE}/kling/v1/videos/text2video",
        headers=api_headers(api_key),
        json={
            "model_name": "kling-v2-master",
            "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "mode": "std",
        },
        timeout=60,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Kling t2v submit failed: {data}")
    return data["data"]["task_id"]


def kling_poll(
    task_id: str,
    endpoint: str,
    api_key: str,
    max_wait: int = 600,
    poll_interval: int = 10,
) -> str:
    """Poll a Kling task until completion.
    Args:
        endpoint: 'image2video' or 'text2video'
    Returns:
        Video URL on success.
    """
    headers = api_headers(api_key)
    url = f"{DEERAPI_BASE}/kling/v1/videos/{endpoint}/{task_id}"

    iterations = max_wait // poll_interval
    for i in range(iterations):
        time.sleep(poll_interval)
        resp = requests.get(url, headers=headers, timeout=30)
        status = resp.json().get("data", {}).get("task_status", "")
        if i % 3 == 0:
            log(f"    [{i * poll_interval}s] {status}")
        if status == "succeed":
            return resp.json()["data"]["task_result"]["videos"][0]["url"]
        if status == "failed":
            msg = resp.json()["data"].get("task_status_msg", "unknown error")
            raise RuntimeError(f"Kling task failed: {msg}")
    raise RuntimeError(f"Kling task timed out after {max_wait}s")


# ═══════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════

def cleanup_intermediates(work_dir: str, patterns: Optional[List[str]] = None) -> None:
    """Remove intermediate files from work directory."""
    import glob
    if patterns is None:
        patterns = [
            "norm_*.mp4", "clip_*.mp4", "concat.mp4", "concat.txt",
            "with_voice.mp4", "with_bgm.mp4",
        ]
    removed = 0
    for pattern in patterns:
        for filepath in glob.glob(os.path.join(work_dir, pattern)):
            try:
                os.remove(filepath)
                removed += 1
            except OSError:
                pass
    if removed:
        log(f"🧹 Cleaned up {removed} intermediate files")
