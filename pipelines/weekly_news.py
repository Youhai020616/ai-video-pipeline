#!/usr/bin/env python3
"""
AI Weekly News Video Generator 🎬
Generates a news recap video from headlines:
  FLUX illustrations + Ken Burns effect + TTS voiceover + Suno BGM + SRT subtitles
"""

import os
import sys

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    check_env, check_ffmpeg, log, with_retry,
    flux_generate, generate_tts, generate_bgm,
    get_duration, run_ffmpeg,
    generate_srt, add_voiceover, mix_bgm, burn_subtitles,
    cleanup_intermediates,
)

# ── Work directory ──
WORK = os.path.join(os.path.dirname(__file__), "work", "weekly-news")
os.makedirs(WORK, exist_ok=True)

# ── Ken Burns effect parameters ──
KB_ZOOM_STEP = 0.0008   # zoom increment per frame
KB_MAX_ZOOM = 1.3        # maximum zoom level
KB_PAN_ZOOM = 1.15       # static zoom for pan shots
KB_FPS = 30              # output framerate

# ── Audio mix levels ──
VOICE_VOLUME = 1.5
BGM_VOLUME = 0.08

# ═══════════════════════════════════════════
# Demo news content
# ═══════════════════════════════════════════

NEWS = [
    {
        "title": "GPT-5.4 重磅发布",
        "script": (
            "本周最大新闻，OpenAI 发布 GPT-5.4。百万 token 上下文窗口，原生电脑操控能力，"
            "这是 AI 第一次能自己操作你的电脑完成任务。编程、推理、智能体工作流全面升级。"
        ),
        "image_prompt": (
            "Futuristic digital brain with glowing neural connections, holographic computer "
            "screens floating around it, OpenAI logo style, dark blue background with gold "
            "accents, text 'GPT-5.4' glowing, cinematic sci-fi style, 9:16"
        ),
    },
    {
        "title": "Kling 3.0 AI视频革命",
        "script": (
            "快手发布可灵 3.0。原生 4K 60帧，多场景一次生成，角色一致性大幅提升。"
            "AI 短片从玩具变成了真正的生产力工具。"
        ),
        "image_prompt": (
            "A cinema film reel transforming into digital data streams, movie clapperboard "
            "with AI circuit patterns, neon blue and purple, dramatic lighting, futuristic "
            "movie production concept, 9:16"
        ),
    },
    {
        "title": "OpenAI融资1100亿美元",
        "script": (
            "OpenAI 宣布完成史上最大科技融资，1100 亿美元。不过实际到手只有 150 亿，"
            "剩下的是条件承诺。AI 军备竞赛的资金规模已经超过了大多数国家的 GDP。"
        ),
        "image_prompt": (
            "Mountain of gold coins and dollar bills with AI chip on top, digital rain of "
            "money falling, corporate skyscraper in background, dramatic cinematic lighting, "
            "wealth and technology fusion, 9:16"
        ),
    },
    {
        "title": "AI三巨头混战升级",
        "script": (
            "谷歌 Gemini 3.2、Anthropic Claude 新版本、OpenAI GPT-5.4。三巨头在同一周密集"
            "发布。大模型的门槛越来越高，但价格却在疯狂下降。普通开发者反而是最大赢家。"
        ),
        "image_prompt": (
            "Three giant robots facing each other in a futuristic arena, each representing "
            "different AI companies, dramatic battle scene with energy beams, cyberpunk style, "
            "epic scale, 9:16"
        ),
    },
    {
        "title": "AI短剧成新风口",
        "script": (
            "AI 短剧市场预计 2030 年达到 260 亿美元。ReelShort 去年收入 7 亿美元。"
            "传统短剧制作要 30 万，AI 只要几百块。一个人加几个 AI，就能做一个剧组的活。"
            "这不就是我们在做的事情吗？"
        ),
        "image_prompt": (
            "A single person sitting at a desk surrounded by holographic AI assistants, each "
            "doing different production tasks like filming directing editing, movie set "
            "atmosphere but futuristic, warm dramatic lighting, 9:16"
        ),
    },
]

OPENER_SCRIPT = "大家好，这里是 AI 自动化工具人，带你盘点本周 AI 圈最重要的五件大事。"
CLOSER_SCRIPT = "以上就是本周的 AI 大事盘点。如果觉得有用，记得点赞收藏。我们下周见。"

OPENER_IMAGE_PROMPT = (
    "Bold text '本周AI大事' in Chinese characters, futuristic holographic display, "
    "dark blue background with glowing grid lines, tech news broadcast style, "
    "date 'March 2026' visible, sleek modern design, 9:16"
)

BGM_PROMPT = (
    "upbeat tech news background music, modern electronic, "
    "podcast style, energetic but not overwhelming, "
    "suitable for a tech news video, clean and professional"
)


# ═══════════════════════════════════════════
# Ken Burns clip generation
# ═══════════════════════════════════════════

def make_ken_burns_clip(
    image_path: str,
    clip_path: str,
    duration: float,
    effect_index: int,
) -> bool:
    """Create a Ken Burns (zoom/pan) video clip from a static image.
    Returns True on success, False on failure.
    """
    frames = int(duration * KB_FPS)
    if frames <= 0:
        log(f"  ⚠️  Skipping clip: duration too short ({duration:.2f}s)")
        return False

    effect = effect_index % 3
    if effect == 0:
        # Zoom in
        vf = (f"zoompan=z='min(zoom+{KB_ZOOM_STEP},{KB_MAX_ZOOM})':"
              f"d={frames}:s=1080x1920:fps={KB_FPS},format=yuv420p")
    elif effect == 1:
        # Pan right
        vf = (f"zoompan=z='{KB_PAN_ZOOM}':"
              f"x='iw/2-(iw/zoom/2)+((iw/zoom)*on/{frames}/4)':"
              f"d={frames}:s=1080x1920:fps={KB_FPS},format=yuv420p")
    else:
        # Zoom out
        vf = (f"zoompan=z='if(lte(zoom,1.0),{KB_MAX_ZOOM},"
              f"max(1.001,zoom-{KB_ZOOM_STEP}))':"
              f"d={frames}:s=1080x1920:fps={KB_FPS},format=yuv420p")

    try:
        run_ffmpeg([
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-vf", vf, "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", clip_path,
        ], timeout=120)
        if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
            return True
    except RuntimeError as exc:
        log(f"  ⚠️  Ken Burns failed: {exc}")
    return False


# ═══════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════

def run():
    print("\n🎬 本周 AI 大事 — 视频生成")
    print("=" * 60)

    # ── Preflight checks ──
    env = check_env("DEERAPI_KEY", "HF_TOKEN")
    check_ffmpeg()
    deerapi_key = env["DEERAPI_KEY"]
    hf_token = env["HF_TOKEN"]

    # ── Step 1: Generate illustrations (sequential) ──
    print("\n📸 Step 1: 生成配图")
    for i, item in enumerate(NEWS):
        img_path = f"{WORK}/news_{i}.jpg"
        if os.path.exists(img_path) and os.path.getsize(img_path) > 1000:
            log(f"  Cached: news_{i}.jpg")
        else:
            with_retry(flux_generate, item["image_prompt"], img_path, hf_token)

    # Opener image
    opener_img = f"{WORK}/opener.jpg"
    if not os.path.exists(opener_img) or os.path.getsize(opener_img) < 1000:
        with_retry(flux_generate, OPENER_IMAGE_PROMPT, opener_img, hf_token)

    # ── Step 2: Voiceover (TTS) ──
    print("\n🔊 Step 2: 配音")
    full_script = OPENER_SCRIPT
    for item in NEWS:
        full_script += " " + item["title"] + "。" + item["script"]
    full_script += " " + CLOSER_SCRIPT

    voiceover_path = f"{WORK}/voiceover.mp3"
    with_retry(generate_tts, full_script, voiceover_path, deerapi_key, voice="nova")
    voiceover_dur = get_duration(voiceover_path)
    log(f"  ✅ Voiceover: {voiceover_dur:.1f}s")

    # ── Step 3: BGM ──
    print("\n🎵 Step 3: BGM")
    bgm_path = f"{WORK}/bgm.mp3"
    if os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 10000:
        log("  Cached BGM")
    else:
        with_retry(generate_bgm, BGM_PROMPT, bgm_path, deerapi_key)

    # ── Step 4: Subtitles ──
    print("\n📝 Step 4: 字幕")
    srt_path = f"{WORK}/subtitles.srt"
    segments = (
        [OPENER_SCRIPT]
        + [item["title"] + "。" + item["script"] for item in NEWS]
        + [CLOSER_SCRIPT]
    )
    generate_srt(segments, voiceover_dur, srt_path)

    # ── Step 5: Assemble video ──
    print("\n🎞️ Step 5: 组装视频")

    # Calculate per-image duration proportional to script length
    img_files = [f"{WORK}/opener.jpg"] + [f"{WORK}/news_{i}.jpg" for i in range(len(NEWS))]
    seg_durs = []
    total_chars = sum(len(s) for s in segments)
    char_rate = voiceover_dur / total_chars
    for seg in segments[:-1]:  # each image covers one segment
        seg_durs.append(len(seg) * char_rate)
    # Last image also covers the closer segment
    seg_durs[-1] += len(segments[-1]) * char_rate

    log(f"  Image durations: {[f'{d:.1f}s' for d in seg_durs]}")

    # Generate Ken Burns clips
    clips = []
    for i, (img, dur) in enumerate(zip(img_files, seg_durs)):
        clip_path = f"{WORK}/clip_{i}.mp4"
        if make_ken_burns_clip(img, clip_path, dur, effect_index=i):
            clips.append(clip_path)
            log(f"  Clip {i}: {dur:.1f}s ✅")
        else:
            log(f"  Clip {i}: FAILED ❌")

    if not clips:
        print("❌ No clips generated. Cannot produce video.")
        sys.exit(1)

    # Concatenate all clips
    concat_list_path = f"{WORK}/concat.txt"
    with open(concat_list_path, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    concat_path = f"{WORK}/concat.mp4"
    run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:v", "libx264", "-preset", "fast", concat_path,
    ], timeout=120)
    log(f"  Concat: {get_duration(concat_path):.1f}s")

    # Add voiceover
    voice_path = f"{WORK}/with_voice.mp4"
    add_voiceover(concat_path, voiceover_path, voice_path)

    # Mix in BGM
    bgm_mix_path = f"{WORK}/with_bgm.mp4"
    mix_bgm(voice_path, bgm_path, bgm_mix_path,
            voice_volume=VOICE_VOLUME, bgm_volume=BGM_VOLUME)

    # Burn subtitles
    output = f"{WORK}/final_weekly.mp4"
    burn_subtitles(bgm_mix_path, srt_path, output)

    # ── Done ──
    dur = get_duration(output)
    size_kb = os.path.getsize(output) // 1024
    print(f"\n{'=' * 60}")
    print(f"🎉 Weekly AI News Video Complete!")
    print(f"   📁 {output}")
    print(f"   📏 {size_kb}KB | {dur:.1f}s | {len(NEWS)} 条新闻")
    print(f"{'=' * 60}")

    # Optional: clean up intermediate files
    # cleanup_intermediates(WORK)


if __name__ == "__main__":
    run()
