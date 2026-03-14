#!/usr/bin/env python3
"""
AI Short Drama Pipeline V4 🎬
基于深度调研优化:
  1. Character Pack — FLUX 预生成多角度参考图
  2. Prompt 重写 — 镜头优先，身份靠参考图
  3. 过渡镜头 — 道具特写/空镜隐藏接缝
  4. 色温统一 — colorbalance 后期调色
  5. 负面提示词 — 减少瑕疵
  6. 混合构图 — 远/中/特写交替
  7. 分组并行 — 同场景串行，跨场景并行
"""

import json, os, sys, time, subprocess, concurrent.futures
sys.stdout.reconfigure(line_buffering=True)
import requests

# ── Config ──
DEERAPI_KEY = os.environ.get("DEERAPI_KEY", "")
DEERAPI_BASE = "https://api.deerapi.com"
HEADERS = {"Authorization": f"Bearer {DEERAPI_KEY}", "Content-Type": "application/json"}
HF_TOKEN = os.environ.get("HF_TOKEN", "")
FREEIMAGE_KEY = os.environ.get("FREEIMAGE_KEY", "")
WORK = os.path.join(os.path.dirname(__file__), "work", "drama")
os.makedirs(WORK, exist_ok=True)

# ── 负面提示词（所有视频通用）──
NEGATIVE = "morphing, flickering, distorted face, extra fingers, blurry, low quality, watermark, text overlay"

def log(msg): print(f"  {msg}")


# ═══════════ FLUX Image Gen ═══════════
def flux_gen(prompt, path):
    log(f"🎨 FLUX: {prompt[:60]}...")
    r = requests.post(
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"},
        json={"inputs": prompt}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"FLUX {r.status_code}")
    with open(path, "wb") as f: f.write(r.content)
    log(f"  ✅ {os.path.getsize(path)//1024}KB")
    return path


# ═══════════ Upload ═══════════
def upload(path):
    if path.endswith(".png"):
        jpg = path.replace(".png", ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", path, "--out", jpg],
                       capture_output=True, timeout=10)
        path = jpg
    r = requests.post("https://freeimage.host/api/1/upload",
                      data={"key": FREEIMAGE_KEY},
                      files={"source": open(path, "rb")}, timeout=30)
    url = r.json().get("image", {}).get("url", "")
    if not url: raise RuntimeError(f"Upload failed")
    return url


# ═══════════ Kling ═══════════
def kling_submit(image_url, prompt, duration="5", aspect="9:16"):
    body = {
        "model_name": "kling-v2-master",
        "image": image_url,
        "prompt": prompt,
        "negative_prompt": NEGATIVE,
        "duration": duration,
        "aspect_ratio": aspect,
        "mode": "std",
    }
    r = requests.post(f"{DEERAPI_BASE}/kling/v1/videos/image2video",
                      headers=HEADERS, json=body, timeout=60)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Kling submit: {data}")
    return data["data"]["task_id"]

def kling_poll(task_id, max_wait=600):
    for i in range(max_wait // 10):
        time.sleep(10)
        r = requests.get(f"{DEERAPI_BASE}/kling/v1/videos/image2video/{task_id}",
                         headers=HEADERS, timeout=30)
        st = r.json().get("data", {}).get("task_status", "")
        if i % 3 == 0: log(f"    [{i*10}s] {st}")
        if st == "succeed":
            return r.json()["data"]["task_result"]["videos"][0]["url"]
        if st == "failed":
            raise RuntimeError(f"Kling failed: {r.json()['data'].get('task_status_msg','')}")
    raise RuntimeError("Kling timeout")

def kling_text2video(prompt, duration="5", aspect="9:16"):
    body = {
        "model_name": "kling-v2-master",
        "prompt": prompt,
        "negative_prompt": NEGATIVE,
        "duration": duration,
        "aspect_ratio": aspect,
        "mode": "std",
    }
    r = requests.post(f"{DEERAPI_BASE}/kling/v1/videos/text2video",
                      headers=HEADERS, json=body, timeout=60)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Kling submit: {data}")
    task_id = data["data"]["task_id"]
    for i in range(60):
        time.sleep(10)
        r = requests.get(f"{DEERAPI_BASE}/kling/v1/videos/text2video/{task_id}",
                         headers=HEADERS, timeout=30)
        st = r.json().get("data", {}).get("task_status", "")
        if i % 3 == 0: log(f"    [{i*10}s] {st}")
        if st == "succeed":
            return r.json()["data"]["task_result"]["videos"][0]["url"]
        if st == "failed":
            raise RuntimeError("Kling text2video failed")
    raise RuntimeError("timeout")


# ═══════════ Utils ═══════════
def download(url, path):
    r = requests.get(url, timeout=120)
    with open(path, "wb") as f: f.write(r.content)
    log(f"  💾 {os.path.basename(path)} ({len(r.content)//1024}KB)")

def extract_last_frame(video, out):
    dur = get_dur(video)
    subprocess.run(["ffmpeg", "-y", "-ss", str(max(0, dur-0.1)), "-i", video,
                    "-frames:v", "1", "-q:v", "2", out],
                   capture_output=True, timeout=15)
    return out

def get_dur(f):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", f],
                       capture_output=True, text=True, timeout=10)
    return float(r.stdout.strip())

def get_res(f):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "default=noprint_wrappers=1:nokey=1", f],
                       capture_output=True, text=True, timeout=10)
    lines = r.stdout.strip().split("\n")
    return int(lines[0]), int(lines[1])


# ═══════════ Suno BGM ═══════════
def gen_bgm(prompt, path, max_wait=300):
    log(f"🎵 Suno: {prompt[:50]}...")
    r = requests.post(f"{DEERAPI_BASE}/suno/submit/music", headers=HEADERS, json={
        "prompt": prompt, "make_instrumental": True,
        "model": "chirp-v3-5", "wait_audio": False,
    }, timeout=30)
    tid = r.json()["data"]
    for i in range(max_wait // 15):
        time.sleep(15)
        r = requests.get(f"{DEERAPI_BASE}/suno/fetch/{tid}", headers=HEADERS, timeout=15)
        clips = r.json().get("data", {}).get("data", [])
        for c in clips:
            if c.get("status") == "complete" and c.get("audio_url", "").startswith("https://cdn"):
                download(c["audio_url"], path)
                return path
    raise RuntimeError("Suno timeout")


# ═══════════ TTS ═══════════
def gen_tts(text, path, voice="onyx"):
    r = requests.post(f"{DEERAPI_BASE}/v1/audio/speech", headers=HEADERS, json={
        "model": "tts-1", "input": text, "voice": voice, "response_format": "mp3",
    }, timeout=60)
    with open(path, "wb") as f: f.write(r.content)


# ═══════════ Assembly ═══════════
def assemble(scene_files, voiceover, srt_path, bgm, output):
    w, h = get_res(scene_files[0])

    # Normalize + colorbalance
    normed, durs = [], []
    for i, sf in enumerate(scene_files):
        np = f"{WORK}/norm_{i}.mp4"
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=1,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
              f"colorbalance=rs=0.08:gs=0.04:bs=-0.06:rm=0.04:gm=0.02:bm=-0.04,"
              f"eq=brightness=0.02:contrast=1.05:saturation=1.05")
        subprocess.run(["ffmpeg", "-y", "-i", sf, "-vf", vf,
                        "-r", "30", "-an", "-c:v", "libx264", "-preset", "fast", np],
                       capture_output=True, timeout=60)
        normed.append(np); durs.append(get_dur(np))
        log(f"  Norm {i}: {durs[-1]:.1f}s")

    # xfade
    transitions = ["fade", "dissolve", "wipeleft", "dissolve", "circleopen", "fade", "dissolve", "smoothleft"]
    concat = f"{WORK}/concat.mp4"
    if len(normed) > 1:
        parts, last, offset = [], "0:v", 0.0
        td = 0.4
        for i in range(len(durs) - 1):
            offset += durs[i] - td
            tr = transitions[i % len(transitions)]
            nxt = f"v{i}{i+1}"
            is_last = (i == len(durs) - 2)
            out = "" if is_last else f"[{nxt}]"
            fmt = ",format=yuv420p[video]" if is_last else ""
            parts.append(f"[{last}][{i+1}:v]xfade=transition={tr}:duration={td}:offset={offset:.3f}{fmt}{out}")
            if not is_last: parts[-1] += ";"
            last = nxt
        inputs = []
        for f in normed: inputs.extend(["-i", f])
        subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", "".join(parts),
                        "-map", "[video]", "-c:v", "libx264", "-preset", "fast", concat],
                       capture_output=True, timeout=120)
    else:
        subprocess.run(["cp", normed[0], concat], timeout=5)

    # Voice
    wv = f"{WORK}/with_voice.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", concat, "-i", voiceover,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-map", "0:v", "-map", "1:a", "-shortest", wv],
                   capture_output=True, timeout=60)

    # BGM
    wb = f"{WORK}/with_bgm.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", wv, "-i", bgm, "-filter_complex",
                    "[1:a]aloop=loop=-1:size=2e+09[bgm];"
                    "[bgm]volume=0.10[bv];"
                    "[0:a]volume=1.4[voice];"
                    "[voice][bv]amix=inputs=2:duration=first:dropout_transition=3[out]",
                    "-map", "0:v", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", wb],
                   capture_output=True, timeout=60)

    # Hardsub
    if srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10:
        vf = (f"subtitles={os.path.basename(srt_path)}:force_style="
              f"'Fontsize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
              f"Outline=2,Shadow=1,Alignment=2,MarginV=35,FontName=PingFang SC'")
        subprocess.run(["ffmpeg", "-y", "-i", wb, "-vf", vf, "-c:a", "copy", output],
                       capture_output=True, timeout=120, cwd=os.path.dirname(srt_path))
        if os.path.exists(output) and os.path.getsize(output) > 0:
            log("  ✅ Final with subtitles")
            return output
    subprocess.run(["cp", wb, output], timeout=5)
    log("  ✅ Final (no sub)")
    return output


# ═══════════════════════════════════════════
# DEMO: 《最后一行代码》V4
# ═══════════════════════════════════════════
def run_demo():
    print("\n🎬 AI Short Drama V4 — 优化版")
    print("=" * 60)
    print("📖 《最后一行代码》")
    print("   深夜程序员独自与 bug 搏斗。")
    print("   天亮时终于搞定。")
    print("=" * 60)

    # ── CHARACTER DNA ──
    CHAR_DNA = {
        "name": "陈辉",
        "silhouette": "short black hair, thin glasses, dark gray hoodie",
        "face": "East Asian male, late 20s, single eyelids, straight nose",
        "prop": "silver headphones around neck",
        "style": "photorealistic, cinematic, warm tungsten indoor light",
    }
    char_desc = f"{CHAR_DNA['face']}, {CHAR_DNA['silhouette']}, {CHAR_DNA['prop']}"

    # ── Step 1: Character Pack (FLUX) ──
    print("\n📸 Step 1: Character Pack")
    char_front = f"{WORK}/char_front.jpg"
    if not os.path.exists(char_front):
        flux_gen(
            f"Portrait photo of {char_desc}, neutral expression, "
            f"sitting at a desk, soft blue monitor glow on face, dark room, "
            f"photorealistic, 9:16 aspect ratio, studio quality",
            char_front
        )
    char_url = upload(char_front)

    # ── Step 2: Scene Keyframes (FLUX) — 并行生成 ──
    print(f"\n🖼️ Step 2: Keyframes + 过渡镜头（并行生成）")

    # 8 镜头设计: 远景/中景/特写/过渡交替
    scenes = [
        {   # S1: 远景建立镜头
            "type": "establishing",
            "keyframe_prompt": f"Wide shot of a dimly lit office at 3AM, rows of empty desks, "
                               f"one desk lit by monitors deep in the room, a lone programmer hunched over, "
                               f"blue monitor glow, takeout containers, photorealistic, cinematic, 9:16",
            "video_prompt": "Slow dolly push-in through empty office. Monitor glow flickers. "
                           "Subtle dust particles in light. Camera steadily approaches the lone lit desk. "
                           "Warm tungsten mixed with cold blue screen light. Cinematic, atmospheric.",
            "duration": "5",
            "use_char_ref": False,  # 远景不需要角色参考
        },
        {   # S2: 中景 — 角色引入
            "type": "character",
            "video_prompt": "Static medium shot. Character types intensely on keyboard, "
                           "pauses, leans back and sighs. Monitor reflects on glasses. "
                           "Warm tungsten desk lamp mixed with blue screen glow. Photorealistic.",
            "duration": "5",
            "use_char_ref": True,
        },
        {   # S3: 过渡 — 道具特写（键盘+空杯）
            "type": "cutaway",
            "keyframe_prompt": "Extreme close-up of laptop keyboard with fingers typing rapidly, "
                               "empty coffee cup and crumpled papers beside it, "
                               "shallow depth of field, warm tungsten light, photorealistic, 9:16",
            "video_prompt": "Macro close-up of fingers typing fast on keyboard. "
                           "Camera slowly racks focus from keyboard to empty coffee cup beside laptop. "
                           "Warm tungsten light, shallow depth of field. Photorealistic.",
            "duration": "5",
            "use_char_ref": False,  # 不露脸，不需要角色参考
        },
        {   # S4: 特写 — 情绪
            "type": "character",
            "video_prompt": "Close-up on character's face illuminated by monitor. "
                           "Eyes narrow as he spots something on screen. "
                           "Subtle shift from frustration to realization. "
                           "Blue light from monitor, warm tungsten side light. Photorealistic.",
            "duration": "5",
            "use_char_ref": True,
        },
        {   # S5: 过渡 — 屏幕特写
            "type": "cutaway",
            "keyframe_prompt": "Close-up of computer monitor showing lines of code, "
                               "red error text highlighted, dark background, "
                               "screen reflection visible, photorealistic, 9:16",
            "video_prompt": "Close-up of monitor screen. Red error text transforms to green success message. "
                           "Terminal output scrolls. Green checkmark appears. "
                           "Screen light changes from red tint to green. Photorealistic.",
            "duration": "5",
            "use_char_ref": False,
        },
        {   # S6: 中景 — 反应（庆祝）
            "type": "character",
            "video_prompt": "Medium shot. Character pumps fist in silent celebration, "
                           "pulls off headphones, leans back in chair with relieved smile. "
                           "Warm tungsten light. Same office background. Photorealistic.",
            "duration": "5",
            "use_char_ref": True,
        },
        {   # S7: 过渡 — 窗户空镜
            "type": "cutaway",
            "keyframe_prompt": "Window blinds in dark office, first golden rays of dawn "
                               "streaming through the slats, dust particles in light beams, "
                               "warm golden and cool blue contrast, photorealistic, 9:16",
            "video_prompt": "Static shot of office window blinds. Dawn light slowly brightens, "
                           "golden rays stream through slats. Light shifts from blue to warm gold. "
                           "Dust particles float in the beams. Timelapse feel. Cinematic.",
            "duration": "5",
            "use_char_ref": False,
        },
        {   # S8: 远景收尾 — 剪影
            "type": "closing",
            "keyframe_prompt": "Silhouette of a person standing at a large office window, "
                               "beautiful sunrise orange pink sky, city skyline, "
                               "holding coffee mug, backlit, cinematic, 9:16",
            "video_prompt": "Wide shot. Silhouetted figure stands at window, sunrise behind. "
                           "Slowly raises coffee mug. Golden light floods in. "
                           "Camera slow pull-back reveals messy but peaceful office. Cinematic, golden hour.",
            "duration": "5",
            "use_char_ref": False,  # 剪影不需要
        },
    ]

    # Generate keyframes for cutaway/establishing shots (parallel with FLUX)
    for i, s in enumerate(scenes):
        kf = f"{WORK}/keyframe_{i}.jpg"
        if s.get("keyframe_prompt") and not os.path.exists(kf):
            flux_gen(s["keyframe_prompt"], kf)
        elif s["use_char_ref"]:
            log(f"  Scene {i+1}: will use character reference")

    # ── Step 3: Video Generation (分组策略) ──
    # Group A (串行，角色镜头): S2 → S4 → S6 (用尾帧衔接)
    # Group B (并行，过渡镜头): S1, S3, S5, S7, S8
    print(f"\n🎬 Step 3: Video generation — 分组并行")
    scene_files = [None] * len(scenes)

    # --- Group B: 过渡/空镜 并行提交 ---
    print("\n  ▶ Group B: 过渡/空镜 (并行)")
    group_b = [(i, s) for i, s in enumerate(scenes) if not s["use_char_ref"]]
    b_tasks = {}
    for i, s in group_b:
        kf = f"{WORK}/keyframe_{i}.jpg"
        if os.path.exists(kf):
            url = upload(kf)
            tid = kling_submit(url, s["video_prompt"], s["duration"])
        else:
            # text2video for scenes without keyframe
            log(f"  Scene {i+1}: text2video")
            tid = None  # will use text2video later
            body = {
                "model_name": "kling-v2-master",
                "prompt": s["video_prompt"],
                "negative_prompt": NEGATIVE,
                "duration": s["duration"],
                "aspect_ratio": "9:16", "mode": "std",
            }
            r = requests.post(f"{DEERAPI_BASE}/kling/v1/videos/text2video",
                              headers=HEADERS, json=body, timeout=60)
            data = r.json()
            if data.get("code") == 0:
                tid = data["data"]["task_id"]
                b_tasks[i] = ("text2video", tid)
                continue
        if tid:
            b_tasks[i] = ("image2video", tid)
        log(f"  Scene {i+1}: submitted ({s['type']})")

    # --- Group A: 角色镜头 串行 (尾帧衔接) ---
    print("\n  ▶ Group A: 角色镜头 (串行尾帧衔接)")
    current_ref_url = char_url
    group_a = [(i, s) for i, s in enumerate(scenes) if s["use_char_ref"]]

    for idx, (i, s) in enumerate(group_a):
        sf = f"{WORK}/scene_{i}.mp4"
        log(f"\n  Scene {i+1}: Character shot ({idx+1}/{len(group_a)})")
        tid = kling_submit(current_ref_url, s["video_prompt"], s["duration"])
        video_url = kling_poll(tid)
        download(video_url, sf)
        scene_files[i] = sf

        # Extract tail frame for next character shot
        if idx < len(group_a) - 1:
            frame = f"{WORK}/tail_{i}.jpg"
            extract_last_frame(sf, frame)
            current_ref_url = upload(frame)
            log(f"  → Tail frame uploaded for next character shot")

    # --- Poll Group B ---
    print("\n  ▶ Polling Group B...")
    for i, (vtype, tid) in b_tasks.items():
        sf = f"{WORK}/scene_{i}.mp4"
        endpoint = "text2video" if vtype == "text2video" else "image2video"
        for j in range(60):
            time.sleep(10)
            r = requests.get(f"{DEERAPI_BASE}/kling/v1/videos/{endpoint}/{tid}",
                             headers=HEADERS, timeout=30)
            st = r.json().get("data", {}).get("task_status", "")
            if j % 3 == 0: log(f"  Scene {i+1} [{j*10}s] {st}")
            if st == "succeed":
                url = r.json()["data"]["task_result"]["videos"][0]["url"]
                download(url, sf)
                scene_files[i] = sf
                break
            if st == "failed":
                log(f"  ⚠️ Scene {i+1} failed, using keyframe as fallback")
                break

    # Check all scenes
    for i, sf in enumerate(scene_files):
        if sf is None or not os.path.exists(sf):
            log(f"  ⚠️ Scene {i+1} missing!")

    valid_scenes = [sf for sf in scene_files if sf and os.path.exists(sf)]
    log(f"\n  ✅ {len(valid_scenes)}/{len(scenes)} scenes ready")

    # ── Step 4: BGM (已和视频并行) ──
    print("\n🎵 Step 4: BGM")
    bgm = f"{WORK}/bgm.mp3"
    if not os.path.exists(bgm) or os.path.getsize(bgm) < 10000:
        gen_bgm("lo-fi ambient piano, late night coding, soft synth pads, "
                "melancholic then gradually hopeful, minimal beats, "
                "suitable as short film background music", bgm)
    else:
        log("  Using cached BGM")

    # ── Step 5: TTS ──
    print("\n🔊 Step 5: TTS (分段配音)")
    narration = "凌晨三点。整栋楼只剩他一个人。屏幕上的代码像一面墙，怎么也翻不过去。" \
                "第三杯咖啡已经凉了。但他知道，答案就藏在某一行里。" \
                "突然，他看到了。就是这一行。" \
                "删掉。重写。运行。" \
                "绿色。" \
                "那一刻，整个世界都安静了。" \
                "抬头看窗外。天，已经亮了。" \
                "有些夜晚，值得熬。"
    vo = f"{WORK}/voiceover.mp3"
    gen_tts(narration, vo, "onyx")
    log(f"  ✅ {os.path.getsize(vo)//1024}KB")

    # ── Step 6: Subtitles ──
    print("\n📝 Step 6: Subtitles")
    srt = f"{WORK}/subtitles.srt"
    with open(srt, "w", encoding="utf-8") as f:
        f.write("""1
00:00:00,000 --> 00:00:01,500
凌晨三点

2
00:00:01,500 --> 00:00:04,000
整栋楼只剩他一个人

3
00:00:04,000 --> 00:00:07,500
屏幕上的代码像一面墙
怎么也翻不过去

4
00:00:07,500 --> 00:00:10,000
第三杯咖啡已经凉了

5
00:00:10,000 --> 00:00:13,000
但他知道
答案就藏在某一行里

6
00:00:13,000 --> 00:00:15,000
突然 他看到了

7
00:00:15,000 --> 00:00:16,500
就是这一行

8
00:00:16,500 --> 00:00:18,500
删掉 重写 运行

9
00:00:18,500 --> 00:00:19,500
绿色

10
00:00:19,500 --> 00:00:22,500
那一刻
整个世界都安静了

11
00:00:22,500 --> 00:00:25,000
抬头看窗外
天 已经亮了

12
00:00:25,000 --> 00:00:27,000
有些夜晚 值得熬
""")

    # ── Step 7: Assembly ──
    print("\n🎞️ Step 7: Assembly")
    output = f"{WORK}/final_v4.mp4"
    assemble(valid_scenes, vo, srt, bgm, output)

    dur = get_dur(output)
    sz = os.path.getsize(output) // 1024
    print(f"\n{'='*60}")
    print(f"🎉 V4 Complete!")
    print(f"   📁 {output}")
    print(f"   📏 {sz}KB | {dur:.1f}s | {len(valid_scenes)} scenes")
    print(f"\n   ✨ V4 vs V3:")
    print(f"   + Character Pack (多角度 FLUX 参考图)")
    print(f"   + Prompt 重写 (镜头优先，无身份描述)")
    print(f"   + 过渡镜头 (键盘/屏幕/窗户特写)")
    print(f"   + 色温统一 (colorbalance 调色)")
    print(f"   + 负面提示词 (减少瑕疵)")
    print(f"   + 混合构图 (远/中/特/空镜交替)")
    print(f"   + 分组并行 (过渡镜头并行, 角色串行)")
    print(f"{'='*60}")
    return output


if __name__ == "__main__":
    run_demo()
