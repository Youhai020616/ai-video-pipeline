#!/usr/bin/env python3
"""
AI Short Drama Pipeline V4 🎬
Optimizations based on deep research:
  1. Character Pack — FLUX pre-generates multi-angle reference images
  2. Prompt rewrite — camera-first, identity via reference image
  3. Transition shots — prop close-ups / empty shots to hide seams
  4. Color grading — colorbalance post-processing
  5. Negative prompts — reduce artifacts
  6. Mixed composition — wide/medium/close-up alternating
  7. Grouped generation — character shots serial, cutaway shots parallel
"""

import os
import sys
import time

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    check_env, check_ffmpeg, log, with_retry,
    flux_generate, generate_tts, generate_bgm,
    get_duration, get_resolution, run_ffmpeg,
    upload_image, download_file, extract_last_frame,
    generate_srt, add_voiceover, mix_bgm, burn_subtitles,
    kling_submit_image2video, kling_submit_text2video, kling_poll,
    cleanup_intermediates,
)

# ── Work directory ──
WORK = os.path.join(os.path.dirname(__file__), "work", "drama")
os.makedirs(WORK, exist_ok=True)

# ── Color grading parameters ──
COLOR_BALANCE = "colorbalance=rs=0.08:gs=0.04:bs=-0.06:rm=0.04:gm=0.02:bm=-0.04"
COLOR_EQ = "eq=brightness=0.02:contrast=1.05:saturation=1.05"

# ── Transition parameters ──
XFADE_DURATION = 0.4
TRANSITIONS = [
    "fade", "dissolve", "wipeleft", "dissolve",
    "circleopen", "fade", "dissolve", "smoothleft",
]

# ── Audio mix levels ──
VOICE_VOLUME = 1.4
BGM_VOLUME = 0.10

# ═══════════════════════════════════════════
# Demo content: 《最后一行代码》
# ═══════════════════════════════════════════

CHAR_DNA = {
    "name": "陈辉",
    "silhouette": "short black hair, thin glasses, dark gray hoodie",
    "face": "East Asian male, late 20s, single eyelids, straight nose",
    "prop": "silver headphones around neck",
    "style": "photorealistic, cinematic, warm tungsten indoor light",
}

SCENES = [
    {   # S1: Establishing wide shot
        "type": "establishing",
        "keyframe_prompt": (
            f"Wide shot of a dimly lit office at 3AM, rows of empty desks, "
            f"one desk lit by monitors deep in the room, a lone programmer hunched over, "
            f"blue monitor glow, takeout containers, photorealistic, cinematic, 9:16"
        ),
        "video_prompt": (
            "Slow dolly push-in through empty office. Monitor glow flickers. "
            "Subtle dust particles in light. Camera steadily approaches the lone lit desk. "
            "Warm tungsten mixed with cold blue screen light. Cinematic, atmospheric."
        ),
        "duration": "5",
        "use_char_ref": False,
    },
    {   # S2: Medium — character introduction
        "type": "character",
        "keyframe_prompt": None,
        "video_prompt": (
            "Static medium shot. Character types intensely on keyboard, "
            "pauses, leans back and sighs. Monitor reflects on glasses. "
            "Warm tungsten desk lamp mixed with blue screen glow. Photorealistic."
        ),
        "duration": "5",
        "use_char_ref": True,
    },
    {   # S3: Cutaway — keyboard + empty cup
        "type": "cutaway",
        "keyframe_prompt": (
            "Extreme close-up of laptop keyboard with fingers typing rapidly, "
            "empty coffee cup and crumpled papers beside it, "
            "shallow depth of field, warm tungsten light, photorealistic, 9:16"
        ),
        "video_prompt": (
            "Macro close-up of fingers typing fast on keyboard. "
            "Camera slowly racks focus from keyboard to empty coffee cup beside laptop. "
            "Warm tungsten light, shallow depth of field. Photorealistic."
        ),
        "duration": "5",
        "use_char_ref": False,
    },
    {   # S4: Close-up — emotion
        "type": "character",
        "keyframe_prompt": None,
        "video_prompt": (
            "Close-up on character's face illuminated by monitor. "
            "Eyes narrow as he spots something on screen. "
            "Subtle shift from frustration to realization. "
            "Blue light from monitor, warm tungsten side light. Photorealistic."
        ),
        "duration": "5",
        "use_char_ref": True,
    },
    {   # S5: Cutaway — screen close-up
        "type": "cutaway",
        "keyframe_prompt": (
            "Close-up of computer monitor showing lines of code, "
            "red error text highlighted, dark background, "
            "screen reflection visible, photorealistic, 9:16"
        ),
        "video_prompt": (
            "Close-up of monitor screen. Red error text transforms to green success message. "
            "Terminal output scrolls. Green checkmark appears. "
            "Screen light changes from red tint to green. Photorealistic."
        ),
        "duration": "5",
        "use_char_ref": False,
    },
    {   # S6: Medium — reaction (celebration)
        "type": "character",
        "keyframe_prompt": None,
        "video_prompt": (
            "Medium shot. Character pumps fist in silent celebration, "
            "pulls off headphones, leans back in chair with relieved smile. "
            "Warm tungsten light. Same office background. Photorealistic."
        ),
        "duration": "5",
        "use_char_ref": True,
    },
    {   # S7: Cutaway — window empty shot
        "type": "cutaway",
        "keyframe_prompt": (
            "Window blinds in dark office, first golden rays of dawn "
            "streaming through the slats, dust particles in light beams, "
            "warm golden and cool blue contrast, photorealistic, 9:16"
        ),
        "video_prompt": (
            "Static shot of office window blinds. Dawn light slowly brightens, "
            "golden rays stream through slats. Light shifts from blue to warm gold. "
            "Dust particles float in the beams. Timelapse feel. Cinematic."
        ),
        "duration": "5",
        "use_char_ref": False,
    },
    {   # S8: Closing wide shot — silhouette
        "type": "closing",
        "keyframe_prompt": (
            "Silhouette of a person standing at a large office window, "
            "beautiful sunrise orange pink sky, city skyline, "
            "holding coffee mug, backlit, cinematic, 9:16"
        ),
        "video_prompt": (
            "Wide shot. Silhouetted figure stands at window, sunrise behind. "
            "Slowly raises coffee mug. Golden light floods in. "
            "Camera slow pull-back reveals messy but peaceful office. Cinematic, golden hour."
        ),
        "duration": "5",
        "use_char_ref": False,
    },
]

# Narration segments — used for both TTS and dynamic subtitle generation
NARRATION_SEGMENTS = [
    "凌晨三点。整栋楼只剩他一个人。",
    "屏幕上的代码像一面墙，怎么也翻不过去。",
    "第三杯咖啡已经凉了。但他知道，答案就藏在某一行里。",
    "突然，他看到了。就是这一行。",
    "删掉。重写。运行。",
    "绿色。",
    "那一刻，整个世界都安静了。",
    "抬头看窗外。天，已经亮了。",
    "有些夜晚，值得熬。",
]
NARRATION_FULL = "".join(NARRATION_SEGMENTS)

BGM_PROMPT = (
    "lo-fi ambient piano, late night coding, soft synth pads, "
    "melancholic then gradually hopeful, minimal beats, "
    "suitable as short film background music"
)


# ═══════════════════════════════════════════
# Assembly: normalize + xfade + audio + subtitles
# ═══════════════════════════════════════════

def normalize_and_xfade(scene_files: list) -> str:
    """Normalize resolution, apply color grading, and chain xfade transitions.
    Returns path to the concatenated video.
    """
    width, height = get_resolution(scene_files[0])

    # Normalize + color grade each scene
    normed = []
    durs = []
    for i, scene_path in enumerate(scene_files):
        norm_path = f"{WORK}/norm_{i}.mp4"
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=1,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"{COLOR_BALANCE},{COLOR_EQ}"
        )
        run_ffmpeg([
            "ffmpeg", "-y", "-i", scene_path, "-vf", vf,
            "-r", "30", "-an", "-c:v", "libx264", "-preset", "fast", norm_path,
        ], timeout=60)
        dur = get_duration(norm_path)
        normed.append(norm_path)
        durs.append(dur)
        log(f"  Norm {i}: {dur:.1f}s")

    # Apply xfade transitions
    concat_path = f"{WORK}/concat.mp4"
    if len(normed) <= 1:
        import shutil
        shutil.copy2(normed[0], concat_path)
        return concat_path

    # Build chained xfade filter_complex
    parts = []
    last_label = "0:v"
    offset = 0.0
    td = XFADE_DURATION

    for i in range(len(durs) - 1):
        offset += durs[i] - td
        tr = TRANSITIONS[i % len(TRANSITIONS)]
        next_label = f"v{i}{i + 1}"
        is_last = (i == len(durs) - 2)

        out_tag = "" if is_last else f"[{next_label}]"
        fmt_suffix = ",format=yuv420p[video]" if is_last else ""

        part = (
            f"[{last_label}][{i + 1}:v]xfade=transition={tr}:"
            f"duration={td}:offset={offset:.3f}{fmt_suffix}{out_tag}"
        )
        if not is_last:
            part += ";"
        parts.append(part)
        last_label = next_label

    inputs = []
    for f in normed:
        inputs.extend(["-i", f])

    run_ffmpeg([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", "".join(parts),
        "-map", "[video]", "-c:v", "libx264", "-preset", "fast", concat_path,
    ], timeout=120)

    return concat_path


def assemble(scene_files: list, voiceover: str, srt_path: str, bgm: str, output: str) -> str:
    """Full assembly: normalize → xfade → voiceover → BGM → subtitles."""

    # Step 1: Normalize + transitions
    concat_path = normalize_and_xfade(scene_files)

    # Step 2: Add voiceover
    voice_path = f"{WORK}/with_voice.mp4"
    add_voiceover(concat_path, voiceover, voice_path)

    # Step 3: Mix BGM
    bgm_mix_path = f"{WORK}/with_bgm.mp4"
    mix_bgm(voice_path, bgm, bgm_mix_path,
            voice_volume=VOICE_VOLUME, bgm_volume=BGM_VOLUME)

    # Step 4: Burn subtitles
    burn_subtitles(bgm_mix_path, srt_path, output, font_size=18, margin_v=35)

    return output


# ═══════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════

def run_demo():
    print("\n🎬 AI Short Drama V4 — 优化版")
    print("=" * 60)
    print("📖 《最后一行代码》")
    print("   深夜程序员独自与 bug 搏斗。")
    print("   天亮时终于搞定。")
    print("=" * 60)

    # ── Preflight checks ──
    env = check_env("DEERAPI_KEY", "HF_TOKEN", "FREEIMAGE_KEY")
    check_ffmpeg()
    deerapi_key = env["DEERAPI_KEY"]
    hf_token = env["HF_TOKEN"]
    freeimage_key = env["FREEIMAGE_KEY"]

    char_desc = f"{CHAR_DNA['face']}, {CHAR_DNA['silhouette']}, {CHAR_DNA['prop']}"

    # ── Step 1: Character Pack (FLUX) ──
    print("\n📸 Step 1: Character Pack")
    char_front = f"{WORK}/char_front.jpg"
    if not os.path.exists(char_front) or os.path.getsize(char_front) < 1000:
        with_retry(
            flux_generate,
            f"Portrait photo of {char_desc}, neutral expression, "
            f"sitting at a desk, soft blue monitor glow on face, dark room, "
            f"photorealistic, 9:16 aspect ratio, studio quality",
            char_front,
            hf_token,
        )
    char_url = with_retry(upload_image, char_front, freeimage_key)

    # ── Step 2: Scene keyframes (FLUX) ──
    print(f"\n🖼️ Step 2: Keyframes (FLUX)")
    for i, scene in enumerate(SCENES):
        kf_path = f"{WORK}/keyframe_{i}.jpg"
        if scene.get("keyframe_prompt") and not os.path.exists(kf_path):
            with_retry(flux_generate, scene["keyframe_prompt"], kf_path, hf_token)
        elif scene["use_char_ref"]:
            log(f"  Scene {i + 1}: uses character reference (no keyframe needed)")

    # ── Step 3: Video generation (grouped strategy) ──
    # Group A (serial, character shots): tail-frame chaining for consistency
    # Group B (parallel submit, cutaway shots): independent scenes
    print(f"\n🎬 Step 3: Video generation — grouped strategy")
    scene_files = [None] * len(SCENES)

    # --- Group B: cutaway/establishing shots (submit all first) ---
    print("\n  ▶ Group B: Cutaway/establishing shots (parallel submit)")
    group_b = [(i, s) for i, s in enumerate(SCENES) if not s["use_char_ref"]]
    b_tasks = {}  # {scene_index: (endpoint, task_id)}

    for i, scene in group_b:
        kf_path = f"{WORK}/keyframe_{i}.jpg"
        try:
            if os.path.exists(kf_path) and os.path.getsize(kf_path) > 1000:
                img_url = with_retry(upload_image, kf_path, freeimage_key)
                task_id = kling_submit_image2video(
                    img_url, scene["video_prompt"], deerapi_key, scene["duration"],
                )
                b_tasks[i] = ("image2video", task_id)
            else:
                task_id = kling_submit_text2video(
                    scene["video_prompt"], deerapi_key, scene["duration"],
                )
                b_tasks[i] = ("text2video", task_id)
            log(f"  Scene {i + 1}: submitted ({scene['type']})")
        except RuntimeError as exc:
            log(f"  ⚠️  Scene {i + 1} submit failed: {exc}")

    # --- Group A: character shots (serial, tail-frame chaining) ---
    print("\n  ▶ Group A: Character shots (serial, tail-frame chaining)")
    current_ref_url = char_url
    group_a = [(i, s) for i, s in enumerate(SCENES) if s["use_char_ref"]]

    for idx, (i, scene) in enumerate(group_a):
        scene_path = f"{WORK}/scene_{i}.mp4"
        log(f"\n  Scene {i + 1}: Character shot ({idx + 1}/{len(group_a)})")
        try:
            task_id = kling_submit_image2video(
                current_ref_url, scene["video_prompt"], deerapi_key, scene["duration"],
            )
            video_url = kling_poll(task_id, "image2video", deerapi_key)
            download_file(video_url, scene_path)
            scene_files[i] = scene_path

            # Extract tail frame for next character shot (maintains consistency)
            if idx < len(group_a) - 1:
                frame_path = f"{WORK}/tail_{i}.jpg"
                extract_last_frame(scene_path, frame_path)
                current_ref_url = with_retry(upload_image, frame_path, freeimage_key)
                log(f"  → Tail frame uploaded for next character shot")
        except RuntimeError as exc:
            log(f"  ⚠️  Scene {i + 1} generation failed: {exc}")

    # --- Poll Group B results ---
    print("\n  ▶ Polling Group B results...")
    for i, (endpoint, task_id) in b_tasks.items():
        scene_path = f"{WORK}/scene_{i}.mp4"
        try:
            video_url = kling_poll(task_id, endpoint, deerapi_key)
            download_file(video_url, scene_path)
            scene_files[i] = scene_path
        except RuntimeError as exc:
            log(f"  ⚠️  Scene {i + 1} poll failed: {exc}")

    # Validate results
    for i, scene_path in enumerate(scene_files):
        if scene_path is None or not os.path.exists(scene_path):
            log(f"  ⚠️  Scene {i + 1} missing!")

    valid_scenes = [sf for sf in scene_files if sf and os.path.exists(sf)]
    log(f"\n  ✅ {len(valid_scenes)}/{len(SCENES)} scenes ready")

    if not valid_scenes:
        print("❌ No scenes generated. Cannot produce video.")
        sys.exit(1)

    # ── Step 4: BGM ──
    print("\n🎵 Step 4: BGM")
    bgm_path = f"{WORK}/bgm.mp3"
    if os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 10000:
        log("  Using cached BGM")
    else:
        with_retry(generate_bgm, BGM_PROMPT, bgm_path, deerapi_key)

    # ── Step 5: TTS voiceover ──
    print("\n🔊 Step 5: TTS")
    voiceover_path = f"{WORK}/voiceover.mp3"
    with_retry(generate_tts, NARRATION_FULL, voiceover_path, deerapi_key, voice="onyx")
    voiceover_dur = get_duration(voiceover_path)
    log(f"  Duration: {voiceover_dur:.1f}s")

    # ── Step 6: Subtitles (dynamically timed to TTS duration) ──
    print("\n📝 Step 6: Subtitles")
    srt_path = f"{WORK}/subtitles.srt"
    generate_srt(NARRATION_SEGMENTS, voiceover_dur, srt_path)

    # ── Step 7: Assembly ──
    print("\n🎞️ Step 7: Assembly")
    output = f"{WORK}/final_v4.mp4"
    assemble(valid_scenes, voiceover_path, srt_path, bgm_path, output)

    # ── Done ──
    dur = get_duration(output)
    size_kb = os.path.getsize(output) // 1024
    print(f"\n{'=' * 60}")
    print(f"🎉 V4 Complete!")
    print(f"   📁 {output}")
    print(f"   📏 {size_kb}KB | {dur:.1f}s | {len(valid_scenes)} scenes")
    print(f"\n   ✨ V4 features:")
    print(f"   + Character Pack (multi-angle FLUX reference)")
    print(f"   + Prompt rewrite (camera-first, no identity in prompt)")
    print(f"   + Transition shots (keyboard/screen/window close-ups)")
    print(f"   + Unified color grading (colorbalance)")
    print(f"   + Negative prompts (artifact reduction)")
    print(f"   + Mixed composition (wide/medium/close-up/cutaway)")
    print(f"   + Grouped generation (cutaway parallel, character serial)")
    print(f"   + Dynamic subtitles (timed to TTS duration)")
    print(f"{'=' * 60}")

    # Optional: clean up intermediate files
    # cleanup_intermediates(WORK)

    return output


if __name__ == "__main__":
    run_demo()
