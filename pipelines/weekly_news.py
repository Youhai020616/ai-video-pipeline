#!/usr/bin/env python3
"""
AI 周报视频生成器 🎬
产品君风格：图片轮播 + 配音 + 字幕 + BGM
Ken Burns 效果（缩放/平移）增加视觉动感
"""
import json, os, sys, time, subprocess
sys.stdout.reconfigure(line_buffering=True)
import requests

DEERAPI_KEY = os.environ.get("DEERAPI_KEY", "")
DEERAPI_BASE = "https://api.deerapi.com"
HEADERS = {"Authorization": f"Bearer {DEERAPI_KEY}", "Content-Type": "application/json"}
HF_TOKEN = os.environ.get("HF_TOKEN", "")
WORK = os.path.join(os.path.dirname(__file__), "work", "weekly-news")
os.makedirs(WORK, exist_ok=True)

def log(msg): print(f"  {msg}")

def flux_gen(prompt, path):
    r = requests.post(
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"},
        json={"inputs": prompt}, timeout=60)
    with open(path, "wb") as f: f.write(r.content)
    log(f"  ✅ {os.path.basename(path)} ({os.path.getsize(path)//1024}KB)")

def gen_tts(text, path, voice="nova"):
    r = requests.post(f"{DEERAPI_BASE}/v1/audio/speech", headers=HEADERS, json={
        "model": "tts-1", "input": text, "voice": voice, "response_format": "mp3",
    }, timeout=60)
    with open(path, "wb") as f: f.write(r.content)

def gen_bgm(prompt, path):
    log(f"🎵 Suno BGM...")
    r = requests.post(f"{DEERAPI_BASE}/suno/submit/music", headers=HEADERS, json={
        "prompt": prompt, "make_instrumental": True,
        "model": "chirp-v3-5", "wait_audio": False,
    }, timeout=30)
    tid = r.json()["data"]
    for i in range(20):
        time.sleep(15)
        r = requests.get(f"{DEERAPI_BASE}/suno/fetch/{tid}", headers=HEADERS, timeout=15)
        clips = r.json().get("data", {}).get("data", [])
        for c in clips:
            if c.get("status") == "complete" and c.get("audio_url", "").startswith("https://cdn"):
                data = requests.get(c["audio_url"], timeout=60).content
                with open(path, "wb") as f: f.write(data)
                log(f"  ✅ BGM ready ({len(data)//1024}KB)")
                return
    raise RuntimeError("Suno timeout")

def get_dur(f):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", f],
                       capture_output=True, text=True, timeout=10)
    return float(r.stdout.strip())


def run():
    print("\n🎬 本周 AI 大事 — 视频生成")
    print("=" * 60)

    # ── 新闻条目 ──
    news = [
        {
            "title": "GPT-5.4 重磅发布",
            "script": "本周最大新闻，OpenAI 发布 GPT-5.4。百万 token 上下文窗口，原生电脑操控能力，这是 AI 第一次能自己操作你的电脑完成任务。编程、推理、智能体工作流全面升级。",
            "image_prompt": "Futuristic digital brain with glowing neural connections, holographic computer screens floating around it, OpenAI logo style, dark blue background with gold accents, text 'GPT-5.4' glowing, cinematic sci-fi style, 9:16",
        },
        {
            "title": "Kling 3.0 AI视频革命",
            "script": "快手发布可灵 3.0。原生 4K 60帧，多场景一次生成，角色一致性大幅提升。AI 短片从玩具变成了真正的生产力工具。",
            "image_prompt": "A cinema film reel transforming into digital data streams, movie clapperboard with AI circuit patterns, neon blue and purple, dramatic lighting, futuristic movie production concept, 9:16",
        },
        {
            "title": "OpenAI融资1100亿美元",
            "script": "OpenAI 宣布完成史上最大科技融资，1100 亿美元。不过实际到手只有 150 亿，剩下的是条件承诺。AI 军备竞赛的资金规模已经超过了大多数国家的 GDP。",
            "image_prompt": "Mountain of gold coins and dollar bills with AI chip on top, digital rain of money falling, corporate skyscraper in background, dramatic cinematic lighting, wealth and technology fusion, 9:16",
        },
        {
            "title": "AI三巨头混战升级",
            "script": "谷歌 Gemini 3.2、Anthropic Claude 新版本、OpenAI GPT-5.4。三巨头在同一周密集发布。大模型的门槛越来越高，但价格却在疯狂下降。普通开发者反而是最大赢家。",
            "image_prompt": "Three giant robots facing each other in a futuristic arena, each representing different AI companies, dramatic battle scene with energy beams, cyberpunk style, epic scale, 9:16",
        },
        {
            "title": "AI短剧成新风口",
            "script": "AI 短剧市场预计 2030 年达到 260 亿美元。ReelShort 去年收入 7 亿美元。传统短剧制作要 30 万，AI 只要几百块。一个人加几个 AI，就能做一个剧组的活。这不就是我们在做的事情吗？",
            "image_prompt": "A single person sitting at a desk surrounded by holographic AI assistants, each doing different production tasks like filming directing editing, movie set atmosphere but futuristic, warm dramatic lighting, 9:16",
        },
    ]

    # ── Step 1: 生成配图 (并行) ──
    print("\n📸 Step 1: 生成配图")
    for i, n in enumerate(news):
        img = f"{WORK}/news_{i}.jpg"
        if not os.path.exists(img):
            flux_gen(n["image_prompt"], img)
        else:
            log(f"  Cached: news_{i}.jpg")

    # ── Step 2: 开场图 ──
    opener_img = f"{WORK}/opener.jpg"
    if not os.path.exists(opener_img):
        flux_gen(
            "Bold text '本周AI大事' in Chinese characters, futuristic holographic display, "
            "dark blue background with glowing grid lines, tech news broadcast style, "
            "date 'March 2026' visible, sleek modern design, 9:16",
            opener_img
        )

    # ── Step 3: 配音 ──
    print("\n🔊 Step 2: 配音")
    # 开场白
    opener_script = "大家好，这里是 AI 自动化工具人，带你盘点本周 AI 圈最重要的五件大事。"
    closer_script = "以上就是本周的 AI 大事盘点。如果觉得有用，记得点赞收藏。我们下周见。"

    full_script = opener_script
    for n in news:
        full_script += " " + n["title"] + "。" + n["script"]
    full_script += " " + closer_script

    vo = f"{WORK}/voiceover.mp3"
    gen_tts(full_script, vo, "nova")
    vo_dur = get_dur(vo)
    log(f"  ✅ Voiceover: {vo_dur:.1f}s")

    # ── Step 4: BGM ──
    print("\n🎵 Step 3: BGM")
    bgm = f"{WORK}/bgm.mp3"
    if not os.path.exists(bgm) or os.path.getsize(bgm) < 10000:
        gen_bgm("upbeat tech news background music, modern electronic, "
                "podcast style, energetic but not overwhelming, "
                "suitable for a tech news video, clean and professional", bgm)
    else:
        log("  Cached BGM")

    # ── Step 5: 字幕 ──
    print("\n📝 Step 4: 字幕")
    srt = f"{WORK}/subtitles.srt"
    # 计算每段配音的大致时间分配
    segments = [opener_script] + [n["title"] + "。" + n["script"] for n in news] + [closer_script]
    total_chars = sum(len(s) for s in segments)
    char_rate = vo_dur / total_chars  # seconds per char

    srt_entries = []
    t = 0.0
    idx = 1
    for seg in segments:
        # 分成短句（按句号/逗号分）
        import re
        sentences = re.split(r'[。，！？]', seg)
        sentences = [s.strip() for s in sentences if s.strip()]
        for sent in sentences:
            dur = len(sent) * char_rate
            start = t
            end = t + dur
            srt_entries.append(f"{idx}\n{_srt(start)} --> {_srt(end)}\n{sent}\n")
            idx += 1
            t = end

    with open(srt, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))
    log(f"  ✅ {idx-1} subtitle entries")

    # ── Step 6: 组装视频 ──
    print("\n🎞️ Step 5: 组装视频")
    # 每张图持续时间 = 对应段落配音长度
    # 用 Ken Burns 效果（缩放平移）让静态图有动感

    # 计算每张图的持续时间
    img_files = [f"{WORK}/opener.jpg"] + [f"{WORK}/news_{i}.jpg" for i in range(len(news))]
    seg_durs = []
    for seg in segments[:-1]:  # 不包括结尾（结尾用最后一张图）
        seg_durs.append(len(seg) * char_rate)
    # 最后一张图加上 closer 时间
    seg_durs[-1] += len(segments[-1]) * char_rate

    log(f"  Image durations: {[f'{d:.1f}s' for d in seg_durs]}")

    # 用 concat 方式：每张图转成视频片段，然后拼接
    clips = []
    for i, (img, dur) in enumerate(zip(img_files, seg_durs)):
        clip = f"{WORK}/clip_{i}.mp4"
        # Ken Burns: 随机选择缩放方向
        if i % 3 == 0:
            # Zoom in
            vf = f"zoompan=z='min(zoom+0.0008,1.3)':d={int(dur*30)}:s=1080x1920:fps=30,format=yuv420p"
        elif i % 3 == 1:
            # Pan right
            vf = f"zoompan=z='1.15':x='iw/2-(iw/zoom/2)+((iw/zoom)*on/{int(dur*30)}/4)':d={int(dur*30)}:s=1080x1920:fps=30,format=yuv420p"
        else:
            # Zoom out
            vf = f"zoompan=z='if(lte(zoom,1.0),1.3,max(1.001,zoom-0.0008))':d={int(dur*30)}:s=1080x1920:fps=30,format=yuv420p"

        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", img,
                        "-vf", vf, "-t", str(dur),
                        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", clip],
                       capture_output=True, timeout=120)
        if os.path.exists(clip) and os.path.getsize(clip) > 0:
            clips.append(clip)
            log(f"  Clip {i}: {dur:.1f}s ✅")
        else:
            log(f"  Clip {i}: FAILED")

    # Concat all clips
    concat_list = f"{WORK}/concat.txt"
    with open(concat_list, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")

    concat_vid = f"{WORK}/concat.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                    "-c:v", "libx264", "-preset", "fast", concat_vid],
                   capture_output=True, timeout=120)
    log(f"  Concat: {get_dur(concat_vid):.1f}s")

    # Add voice
    with_voice = f"{WORK}/with_voice.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", concat_vid, "-i", vo,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-map", "0:v", "-map", "1:a", "-shortest", with_voice],
                   capture_output=True, timeout=60)

    # Add BGM
    with_bgm = f"{WORK}/with_bgm.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", with_voice, "-i", bgm, "-filter_complex",
                    "[1:a]aloop=loop=-1:size=2e+09[bgm];"
                    "[bgm]volume=0.08[bv];"
                    "[0:a]volume=1.5[voice];"
                    "[voice][bv]amix=inputs=2:duration=first:dropout_transition=3[out]",
                    "-map", "0:v", "-map", "[out]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", with_bgm],
                   capture_output=True, timeout=60)

    # Hardsub
    output = f"{WORK}/final_weekly.mp4"
    vf = ("subtitles=subtitles.srt:force_style="
          "'Fontsize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
          "Outline=2,Shadow=1,Alignment=2,MarginV=40,FontName=PingFang SC'")
    r = subprocess.run(["ffmpeg", "-y", "-i", with_bgm, "-vf", vf, "-c:a", "copy", output],
                       capture_output=True, text=True, timeout=120, cwd=WORK)
    if not (os.path.exists(output) and os.path.getsize(output) > 0):
        log(f"  Sub failed, copying without")
        subprocess.run(["cp", with_bgm, output], timeout=5)

    dur = get_dur(output)
    sz = os.path.getsize(output) // 1024
    print(f"\n{'='*60}")
    print(f"🎉 Weekly AI News Video Complete!")
    print(f"   📁 {output}")
    print(f"   📏 {sz}KB | {dur:.1f}s | {len(news)} 条新闻")
    print(f"{'='*60}")


def _srt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


if __name__ == "__main__":
    run()
