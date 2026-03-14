<p align="center">
  <h1 align="center">🎬 AI Video Pipeline</h1>
  <p align="center">Generate AI short dramas and news videos from a single Python script.<br>Text → Images → Video → Voiceover → Subtitles → BGM → Final Cut.</p>
</p>

<p align="center">
  <a href="#pipelines">Pipelines</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#examples">Examples</a> •
  <a href="#customization">Customization</a> •
  <a href="./LICENSE">License</a>
</p>

---

## Why?

Traditional video production needs a team: scriptwriter, illustrator, animator, voice actor, editor, sound designer.

This project replaces the entire team with Python + AI APIs:

| Role | AI Replacement | Time |
|------|---------------|------|
| Illustrator | FLUX.1 (image generation) | 2-3s per image |
| Animator | Kling v2 (image-to-video) | 1-3min per shot |
| Voice Actor | OpenAI TTS | 5s per segment |
| Sound Designer | Suno v4 (music generation) | ~2min |
| Editor | ffmpeg (automated) | 30s |

**A 30-second short drama: ~15 minutes. A 90-second news video: ~5 minutes.** Zero manual editing.

## Pipelines

### 1. 📰 Weekly AI News (`pipelines/weekly_news.py`)

Generates a news recap video from a list of headlines:

- FLUX.1 generates a themed illustration per story
- Ken Burns effect (zoom/pan) makes static images cinematic
- TTS narrates the full script
- Suno generates background music
- ffmpeg assembles everything with hard-burned subtitles

**Output:** ~90 second vertical (9:16) news video with voiceover, BGM, and subtitles.

### 2. 🎭 Short Drama (`pipelines/short_drama.py`)

Generates a cinematic AI short film with character consistency:

- **Character Pack**: FLUX generates multi-angle reference images for the protagonist
- **8-shot cinematography**: Wide → Medium → Close-up → Cutaway, professionally mixed
- **Tail-frame chaining**: Each character shot uses the last frame of the previous one as reference, maintaining visual consistency
- **Parallel generation**: Cutaway shots generate in parallel; character shots chain serially
- **Post-production**: Color grading, crossfade transitions, TTS narration, Suno BGM, SRT subtitles

**Output:** ~27 second vertical (9:16) short drama with 8 shots, narration, and music.

## Quick Start

### Prerequisites

- Python 3.9+
- ffmpeg with libass (for subtitle burning)
  ```bash
  # macOS (with homebrew-ffmpeg tap for libass)
  brew install homebrew-ffmpeg/ffmpeg/ffmpeg
  
  # Ubuntu/Debian
  sudo apt install ffmpeg
  ```

### 1. Clone & Install

```bash
git clone https://github.com/Youhai020616/ai-video-pipeline.git
cd ai-video-pipeline
pip install -r requirements.txt
```

### 2. Set Up API Keys

```bash
cp .env.example .env
# Edit .env with your keys
```

You need:
- **DEERAPI_KEY** — Get from [DeerAPI](https://api.deerapi.com) (for Kling video gen, TTS, Suno BGM)
- **HF_TOKEN** — Get from [Hugging Face](https://huggingface.co/settings/tokens) (for FLUX.1 image gen, free)
- **FREEIMAGE_KEY** *(optional)* — Get from [freeimage.host](https://freeimage.host) (for image hosting in drama pipeline)

### 3. Run

```bash
# Load environment variables
export $(cat .env | xargs)

# Generate a news video
python pipelines/weekly_news.py

# Generate a short drama
python pipelines/short_drama.py
```

## How It Works

### News Video Pipeline

```
Headlines + Scripts
       ↓
  FLUX.1 generates illustrations (parallel, 2-3s each)
       ↓
  ffmpeg applies Ken Burns effect (zoom/pan per image)
       ↓
  OpenAI TTS generates voiceover
       ↓
  Suno generates background music
       ↓
  ffmpeg: concat clips + voice + BGM + subtitles → final.mp4
```

### Short Drama Pipeline

```
Character DNA (appearance description)
       ↓
  FLUX.1 generates character reference photos
       ↓
  ┌─────────────────────────────────────┐
  │  Group A (serial, character shots)   │
  │  Shot 2 → extract tail frame →       │
  │  Shot 4 → extract tail frame →       │
  │  Shot 6 (each uses previous frame)   │
  ├─────────────────────────────────────┤
  │  Group B (parallel, cutaway shots)   │
  │  Shot 1, 3, 5, 7, 8 (independent)   │
  └─────────────────────────────────────┘
       ↓
  ffmpeg: normalize resolution + color grading (colorbalance)
       ↓
  ffmpeg: crossfade transitions (fade/dissolve/wipe)
       ↓
  TTS narration + Suno BGM + SRT subtitles → final.mp4
```

### Key Techniques

**Character Consistency** — The hardest problem in AI video. Our approach:
1. Generate a "Character Pack" with FLUX (reference portrait)
2. Use image-to-video (not text-to-video) for character shots
3. Chain shots via tail-frame extraction — each shot starts from where the last one ended
4. Hide unavoidable drift with cutaway shots (keyboard close-ups, window shots, screen details)

**Cinematic Feel** — Not just "AI slop":
1. Mixed shot composition (wide/medium/close-up/cutaway alternating)
2. Transition shots between scenes (props, environment details)
3. Color grading with `colorbalance` (warm tungsten + cool blue)
4. Professional crossfade transitions (fade, dissolve, wipe, circle)
5. Negative prompts to reduce artifacts

## Examples

### Customize the News Video

Edit the `news` list in `weekly_news.py`:

```python
news = [
    {
        "title": "Your Headline",
        "script": "The narration text for this segment...",
        "image_prompt": "FLUX prompt for the illustration...",
    },
    # Add more stories...
]
```

### Customize the Drama

Edit `CHAR_DNA` and `scenes` in `short_drama.py`:

```python
CHAR_DNA = {
    "name": "Your Character",
    "silhouette": "long brown hair, leather jacket",
    "face": "European female, mid 30s, strong jawline",
    "prop": "vintage camera around neck",
    "style": "photorealistic, cinematic, golden hour light",
}

scenes = [
    {
        "type": "establishing",
        "keyframe_prompt": "Wide shot of...",
        "video_prompt": "Camera movement description...",
        "duration": "5",
        "use_char_ref": False,
    },
    # ...
]
```

## Customization

### Swap AI Providers

The pipeline is modular. Replace any component:

| Component | Current | Alternatives |
|-----------|---------|-------------|
| Image Gen | FLUX.1 (HuggingFace) | Stable Diffusion, DALL-E 3, Midjourney API |
| Video Gen | Kling v2 (DeerAPI) | Runway Gen-3, Pika, Sora API |
| TTS | OpenAI TTS (DeerAPI) | ElevenLabs, Fish Audio, Edge TTS (free) |
| Music | Suno v4 (DeerAPI) | Udio, Stable Audio |
| Subtitles | Character estimation | Whisper (more accurate) |
| Editor | ffmpeg | MoviePy |

### Cost Estimation

| Pipeline | API Calls | Approximate Cost |
|----------|-----------|-----------------|
| News (5 stories) | 5 FLUX + 1 TTS + 1 Suno | ~$0.50 |
| Short Drama (8 shots) | 2 FLUX + 8 Kling + 1 TTS + 1 Suno | ~$2.00 |

*Costs vary by provider. FLUX on HuggingFace is free. Main cost is video generation.*

## Project Structure

```
ai-video-pipeline/
├── README.md
├── LICENSE
├── requirements.txt
├── .env.example
├── .gitignore
└── pipelines/
    ├── weekly_news.py      # News video generator (~265 lines)
    └── short_drama.py      # Short drama generator (~568 lines)
```

## Limitations & Roadmap

**Current Limitations:**
- Character consistency is ~80% — close-ups may drift
- Chinese TTS quality is limited by OpenAI TTS
- Video generation takes 1-3 min per shot (Kling API)
- macOS recommended for ffmpeg subtitle burning (PingFang SC font)

**Roadmap:**
- [ ] Whisper-based subtitle timing (replace character estimation)
- [ ] Multi-character drama support
- [ ] Kling 3.0 / multi-elements API integration
- [ ] ElevenLabs / Fish Audio Chinese TTS
- [ ] Web UI for non-technical users
- [ ] Batch/queue system for production workflows

## Acknowledgments

Built with:
- [FLUX.1](https://huggingface.co/black-forest-labs/FLUX.1-schnell) by Black Forest Labs
- [Kling](https://klingai.kuaishou.com/) by Kuaishou
- [Suno](https://suno.ai/) for AI music
- [DeerAPI](https://api.deerapi.com) as unified API gateway
- [ffmpeg](https://ffmpeg.org/) for video processing

## License

[MIT](./LICENSE) — Use it however you want.

---

<p align="center">
  <sub>Built by <a href="https://github.com/Youhai020616">PocketAI</a> — one person + AI = entire production studio</sub>
</p>
