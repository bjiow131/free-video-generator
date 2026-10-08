# Agnes Video Generator — Free AI Video Generator


> **Completely free AI video generator** — Built on Agnes AI APIs; the client has no subscription layer and requires no local GPU. Type in a text idea and automatically generate multi-scene AI videos with narration and subtitles. Supports text-to-video, image-to-video, keyframes animation, digital anchor, and more. All AI compute runs in the cloud — a regular laptop is all you need.

> "The solution is not to suppress AI, but to make it a more equitable capability, so that everyone knows how to create more with AI. This is a very important vision for our company — to make world-class AI belong to everyone. What we can do may be insignificant, but this vision is very long-term and enduring."
>
> — Bruce Yang, Founder of Agnes AI


## Why Agnes Video Generator?

Making AI videos today has an absurdly high barrier. Overseas services like Runway and Pika charge monthly subscriptions of tens of dollars. Domestic platforms like Jimeng and Keling charge by the second once their free quotas run out. Want to run open-source models locally? A GPU capable of video generation easily costs over ten thousand RMB. For most people who want to try AI video creation, the door is essentially closed.

We believe what Bruce Yang said — AI should be a more equitable capability. World-class AI should belong to everyone, not just those who can afford the bill.

To be honest, Agnes's video model isn't perfect yet. The generated frames are sometimes unstable, and complex actions occasionally deform. The client has no subscription layer; actual Agnes AI quotas, rate limits, and availability are controlled by the provider. We choose to grow with it rather than wait for a "perfect" commercial solution. If you share this mindset, then this project is for you — all you need is a free [Agnes AI](https://platform.agnes-ai.com) API key and an ordinary computer that can run Python to start creating AI videos at zero cost.

### Comparison: Agnes Video Generator vs. Commercial AI Video Tools

| Feature | Agnes Video Generator | Runway Gen-3 | Pika 2.0 | OpenAI Sora | Kling 1.6 |
|---------|:---:|:---:|:---:|:---:|:---:|
| **Price** | No client subscription | $15–$95/month | $10–$28/month | $20+/month (limited) | Free quota, then pay-per-second |
| **Open Source** | Yes (MIT) | No | No | No | No |
| **Self-Hosted** | Yes | No | No | No | No |
| **Max Video Length** | 20s per clip, unlimited scenes | 10s per clip | 10s per clip | 20s per clip | 10s per clip |
| **Multi-Scene Pipeline** | Built-in (Creative/Manuscript) | Manual editing | Manual editing | Manual editing | Manual editing |
| **AI Narration (TTS)** | Free, built-in | Third-party | Third-party | Not available | Not available |
| **Auto Subtitles** | Word-level SRT | Not available | Not available | Not available | Not available |
| **Digital Anchor** | Built-in | No | No | No | No |
| **Resolution Options** | 9:16 / 16:9 / 1:1 | Multiple | Multiple | Multiple | Multiple |
| **Image-to-Video** | Yes | Yes | Yes | Image inputs | Yes |
| **Keyframes Animation** | Yes | Yes | Yes | Not available | Not available |
| **Local GPU Required** | No (cloud API) | No (cloud) | No (cloud) | No (cloud) | No (cloud) |
| **Watermark** | Configurable; disabled by default in local configuration | Built-in watermark | Built-in watermark | C2PA metadata | Built-in watermark |
| **Usage Limit** | No subscription; local concurrency guard uses `AGNES_RATE_LIMIT` (20/min default, 50% safety budget) | Billed by compute | Billed by generation | Billed by generation | Billed by generation |

## Core Features

### Multiple Creation Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **Simple Video** | Single prompt → single AI video. Full control over all parameters (generation mode, duration, resolution, seed, negative prompt). Also supports image-to-video and keyframes mode. | Quick single-clip AI video |
| **Creative Video** | Full AI pipeline: idea → story → script → character reference → multi-scene video → narration → subtitles → final output. 10-step pipeline, fully automated. | Storytelling, creative videos |
| **Manuscript Video** | Paste a long article or script → auto-split by reading duration → per-segment AI video → unified TTS narration + subtitle overlay → final output. 5-step pipeline. | Explainers, course content, vlogs |
| **Digital Anchor** | AI-generated digital anchor (or upload custom image) → dynamic anchor clip → TTS narration → subtitle positioning → looped concatenation. Optional reference image for appearance consistency. | Virtual anchors, product presentations, news broadcasts |

### Completely Free AI Model Chain

All core AI capabilities use the configured Agnes AI account. Watermarking is configurable and disabled by default in the local configuration:

| Capability | Model | Cost |
|-----------|-------|------|
| Text / Script Generation | `agnes-3.0-flash` | Configured Agnes AI access |
| Image Generation | `agnes-image-2.5-flash` | Configured Agnes AI access |
| Video Generation | `agnes-video-2.5-flash` / `agnes-video-2.5` | Configured Agnes AI access |
| Text-to-Speech Narration | Edge TTS (Microsoft) | Free, no extra API key needed |

All AI API calls share a global rate limiter. `AGNES_RATE_LIMIT` defaults to 20 requests/minute; task concurrency reserves 50% of that configured limit for safety (10 weighted slots by default). The exact effective throughput also depends on task type and the global API limiter. Long-running video jobs are persisted locally so they can be resumed after a restart.

### AI Narration & Smart Subtitles

Both Creative Video and Manuscript Video support:

- **Free TTS narration**: Based on Microsoft Edge TTS, offering 4 Chinese voice roles (gentle female, steady male, lively female, young male) with adjustable speech rate (-30% to +30%)
- **Word-level fine-grained subtitles**: SRT subtitles generated from TTS word-level timestamps, one entry every 2-3 seconds, with precise audio-video sync
- **Multi-line auto-wrapping**: Long subtitle text is intelligently split into two lines, preferring punctuation break points to prevent screen overflow
- **Fully configurable subtitle style**: Font, color, size, position (top/bottom), stroke, and semi-transparent background
- **Audio-video sync strategy**: All video clips are concatenated first, then audio and subtitles are overlaid as a whole, avoiding cumulative errors from per-segment overlay. TTS output is automatically amplified 2.5x to compensate for Edge TTS's low default volume

### Flexible Creative Controls

- **Custom reference images** — Upload character or scene reference images to maintain visual consistency across scenes
- **Custom end frames** — Specify end frame images per scene for precise visual transition control
- **Image-to-image end frames** — Auto-generate scene end frames via img2img from your reference image
- **Three video chaining modes** — `keyframes` (first+last frame interpolation, recommended) / `ti2vid` (inter-scene transition frames) / `none` (independent scenes)
- **Multiple resolutions** — Portrait 9:16 (768x1152), Landscape 16:9 (1152x648), Square 1:1 (1024x1024)
- **Flexible duration** — 4–12 seconds per Agnes Video 2.5 scene
- **Smart manuscript splitting** — Splits by period/question mark/exclamation mark, greedily merges into 5-12 second segments based on reading speed (~4 chars/sec), preserves long sentences, auto-merges short sentences forward

### Production-Grade Reliability

- **Checkpoint resume** — Automatically resumes from the last checkpoint after interruption; state is persisted after each step, no duplicate API calls
- **Task management** — Create, view, resume, and stop tasks from the Web UI
- **Real-time progress** — WebSocket pushes per-step generation progress (step name, status, percentage, current/total)
- **Built-in CJK fonts** — Project ships with Chinese fonts, no garbled characters in subtitle rendering

### AI Agent Friendly

Designed specifically for AI coding assistants (Claude, Cursor, etc.), with a complete `AGENTS.md` deployment guide. AI Agents can automatically:

- Check environment (Python 3.10+, ffmpeg)
- Install dependencies and start the server
- Configure API key
- Run 4-layer deployment verification (connectivity → static analysis → endpoint testing → subtitle feature)
- Execute 10-scenario regression test suite

### Multilingual Web UI

One-click launch, operate entirely in the browser. Interface available in **Russian UI**: Chinese, English, Russian, Japanese, Korean, Bahasa Melayu, Bahasa Indonesia.

## Quick Start

### Prerequisites

- Python 3.10+
- ffmpeg (for video concatenation and audio processing)

That's it. No GPU, no large RAM, a regular laptop is all you need.

### Option A: Windows (recommended)

**Step 1 — Clone & Launch**

```bat
git clone https://github.com/bjiow131/free-video-generator.git
cd free-video-generator
start_windows.bat
```

`start_windows.bat` requires an existing `.venv`, a Windows `AGNES_API_KEY`, and FFmpeg in PATH. It starts FastAPI and opens `http://127.0.0.1:8765`. Create the environment first as shown by the script.

For Linux/macOS, use `./start.sh`.

**Step 2 — Configure API Key**

Get a free API key from [Agnes AI](https://platform.agnes-ai.com), then choose one of these local options:

```bat
REM Windows CMD
set AGNES_API_KEY=your-api-key
```

```powershell
# Windows PowerShell
$env:AGNES_API_KEY = "your-api-key"
```

```bash
# Linux/macOS
export AGNES_API_KEY="your-api-key"
```

On Windows, the launcher requires `AGNES_API_KEY` in the environment. For other local launches, the key can also be saved through the Web UI. The local endpoint accepts multipart form data:

```bash
curl -X POST http://localhost:8765/api/config -F "api_key=your-api-key"
```
**Step 3 — Create Your First Video**

Open `http://localhost:8765`, choose a video mode (Simple / Creative / Manuscript / Anchor), enter your idea, and click "Start Generating".

### Option B: Docker (optional, local only)

One command to start everything — no need to install Python, ffmpeg, or any dependencies locally. Docker handles it all.

**Step 1 — Clone & Configure**

```bash
git clone https://github.com/bjiow131/free-video-generator.git
cd free-video-generator
```

Get a free API key from [Agnes AI](https://platform.agnes-ai.com), then create a `.env` file:

```bash
echo "AGNES_API_KEY=your-api-key" > .env
```

**Step 2 — One-Click Launch**

```bash
docker compose up -d --build
```

That's it. Open `http://localhost:8765` in your browser.

> **Note**: `--build` is only needed on the first run or after code changes. On subsequent starts, just use `docker compose up -d` for faster startup. To view logs: `docker compose logs -f`. To stop: `docker compose down`.

### Option C: AI Agent Assisted Setup

This project is designed for AI coding assistants. First, download the code and prepare your API key:

```bash
git clone https://github.com/bjiow131/free-video-generator.git
cd free-video-generator
```

Then tell your agent:

> "Read the AGENTS.md in this project, install dependencies, configure the API key `<your-key>`, and start the server."

The agent will read `AGENTS.md` (a comprehensive deployment guide) and handle: environment checks (Python 3.10+, ffmpeg), `pip install`, server launch, and API key configuration. After startup, you can also ask the agent to verify the deployment:

> "Run the deployment verification checks."

The agent will execute the 4-layer checklist from `AGENTS.md` (connectivity → static analysis → endpoint testing → subtitle feature) and report results.

## Usage

### 1. Configure API Key

Enter your free [Agnes AI](https://platform.agnes-ai.com) API key at the top of the page and save it. Or set it via environment variable:

```bash
export AGNES_API_KEY="your-api-key"
```

### 2. Choose a Video Mode

#### Simple Video

Quick single-clip generation with full parameter control:

| Field | Description |
|-------|-------------|
| Prompt | Describe the AI video scene in natural language |
| Generation Mode | Text-to-Video / Image-to-Video / Text+Image / Keyframes |
| Resolution | Portrait 9:16 / Landscape 16:9 / Square 1:1 |
| Duration | 4s–12s on Agnes Video 2.5; legacy presets 15s / 18s / 20s |
| Reference Image | Optional upload for image-to-video modes |
| End Frame Image | Optional end frame for keyframes mode |

#### Creative Video

AI-driven multi-scene storytelling:

| Field | Description | Required |
|-------|-------------|----------|
| Idea | Describe your AI video concept | Yes |
| User Requirements | Scene count, duration, and other constraints | - |
| Visual Style | Cinematic realism, anime, cyberpunk, etc. | - |
| Chaining Mode | keyframes (recommended) / ti2vid / none | - |
| Narration | Enable/disable TTS narration, choose voice and speed | - |
| Subtitle Style | Font, color, size, position, stroke, background | - |
| Reference Image | Optional character reference for visual consistency | - |
| End Frames | Custom or auto-generated per-scene end frames | - |

#### Manuscript Video

Long-form text to narrated video:

| Field | Description | Required |
|-------|-------------|----------|
| Manuscript Text | Paste your full article, script, or narration | Yes |
| Resolution | Portrait / Landscape / Square | - |
| Narration | Voice role and speech rate | - |
| Subtitle Style | Full subtitle customization | - |

> **Note**: Segment duration is auto-calculated based on text length (~4 chars/sec, 5-12s per segment) — no manual setting needed.

#### Digital Anchor

| Field | Description | Required |
|-------|-------------|----------|
| Anchor Script | Enter the text the anchor will say | Yes |
| Anchor Image | AI-generated or upload custom reference image | - |
| Resolution | Portrait / Landscape / Square | - |
| Narration | Voice role and speech rate | - |
| Subtitle Style | Full subtitle customization | - |

### 3. Click "Start Generating"

The progress panel shows real-time generation status for each step. For Creative Video: Init → Image Analysis → Story → Character Reference → Script → Narration → End Frame Prompts → End Frame Generation → Video Generation → Audio & Subtitles → Concatenation.

### 4. Checkpoint Resume & Task Management

If the server is interrupted, restart it and find the incomplete task in the "Task List" tab. Click "Resume" to continue from the last checkpoint. Running tasks can also be stopped and resumed later.

## Project Structure

```
free-video-generator/
├── start.sh                          # One-click launch script
├── requirements.txt                  # Python dependencies
├── server.py                         # FastAPI server (REST + WebSocket)
├── static/
│   └── ai-studio.html                # Frontend SPA served at `/`
├── core/
│   ├── config.py                     # API key, font resolution, default configs
│   ├── screenwriter.py               # Screenwriter Agent (LLM-powered story/script/narration)
│   ├── task_manager.py               # Task state persistence & checkpoint resume
│   ├── api/
│   │   ├── agnes_chat.py             # LLM Chat API (agnes-3.0-flash)
│   │   ├── agnes_image.py            # Image generation API (agnes-image-2.5-flash)
│   │   ├── agnes_video.py             # Video generation API (agnes-video-2.5-flash / 2.5)
│   │   └── rate_limiter.py            # Global token bucket limiter controlled by AGNES_RATE_LIMIT
│   ├── audio/
│   │   ├── tts.py                    # Edge TTS engine + silent fallback engine
│   │   └── subtitle.py               # SRT generation (fine-grained word-level) + overlay
│   ├── compositor/
│   │   ├── concatenator.py           # Video concatenation + audio/subtitle overlay
│   │   └── processor.py              # Video resize, frame extraction, freeze, silence gen
│   └── pipelines/
│       ├── simple_video.py           # Pipeline: Simple Video
│       ├── creative_video.py         # Pipeline: Creative Video (10-step)
│       ├── manuscript_video.py       # Pipeline: Manuscript Video (5-step)
│       └── anchor_video.py           # Pipeline: Digital Anchor
├── models/
│   └── task.py                       # Data models (5 task types, configs, requests)
├── resource/
│   └── fonts/                        # Built-in CJK fonts for subtitle rendering
├── utils/
│   ├── image.py                      # Image download / base64 conversion
│   └── video.py                      # Video download
├── scripts/
│   └── regression_runner.py          # 10-scenario regression test suite
└── docs/
    ├── regression_test_plan.md       # Regression test plan
    ├── plans-v1.0/                   # v1.0 design & planning docs
    ├── plans-v2.0/                   # v2.0 review & optimization docs
    └── plans-v3.0/                   # v3.0 feature planning docs
```

## Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Backend | Python FastAPI | Async + WebSocket |
| Frontend | HTML/CSS/JS + Tailwind CSS CDN | Zero build steps, single-file SPA |
| LLM | Agnes Chat (`agnes-3.0-flash`) | Story, script and narration generation |
| Image AI | `agnes-image-2.5-flash` | Reference images, end frames and standalone image generation |
| Video AI | `agnes-video-2.5-flash` / `agnes-video-2.5` | Text-to-video, image-to-video and keyframes |
| TTS | Edge TTS (Microsoft) | Free — 4 Chinese voices, no extra API key needed |
| Subtitles | moviepy + srt | Fine-grained word-level SRT, multi-line wrapping |
| Video Processing | moviepy + ffmpeg | Concatenation, subtitle overlay, audio mixing |

## Three AI Video Chaining Modes

| Mode | How It Works | Best For |
|------|-------------|----------|
| **keyframes** | Specify first + last frame per scene; server auto-interpolates transitions | Smooth transitions (recommended) |
| **ti2vid** | Last frame of previous scene → img2img transition → first frame of next scene | Visual continuity between scenes |
| **none** | All scenes share the same reference image, independent of each other | Fast output, independent scenes |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve Web UI |
| GET | `/health` | Service and FFmpeg health |
| GET | `/api/config` | Configuration status, workspaces and watermark settings |
| POST | `/api/config` | Save API key |
| GET/POST/DELETE | `/api/workspaces*` | Manage workspaces |
| POST | `/api/workspaces/pick-directory` | Pick a local directory |
| POST | `/api/config/watermark` | Configure optional watermark |
| DELETE | `/api/config` | Delete configured API key |
| GET | `/api/voices` | List available TTS voices |
| POST | `/api/ideas/generate` | Generate creative ideas |
| POST | `/api/image/generate` | Image generation |
| GET | `/api/image/{task_id}` | Serve generated image |
| POST | `/api/tasks/simple` | Create simple video task |
| POST | `/api/tasks/creative` | Create creative video task |
| POST | `/api/tasks/manuscript` | Create manuscript video task |
| POST | `/api/tasks/anchor` | Create digital anchor task |
| POST | `/api/tasks` | Generic task creation (backward-compatible) |
| GET | `/api/tasks` | List all tasks (with type badges) |
| GET | `/api/tasks/{id}` | Get task details |
| POST | `/api/tasks/{id}/resume` | Resume an interrupted task |
| POST | `/api/tasks/{id}/stop` | Stop a running task |
| GET | `/api/video/{id}` | Stream final video |
| GET | `/api/image/{id}/download` | Download final image |
| GET | `/api/video/{id}/download` | Download final video |
| WS | `/ws/{id}` | WebSocket real-time progress |
| POST | `/api/workspaces/pick-directory` | Pick a local directory |
| GET | `/api/concurrency` | Concurrency and rate status |
| POST | `/api/cleanup-regression` | Clean regression artifacts |
| GET/POST | `/api/comfyui/status`, `/api/comfyui/generate`, `/api/comfyui/preview` | Optional ComfyUI integration |

## Important Notes

This project is in early stage — corner cases may not be fully handled. Recommended workflow:

1. Fill in your idea on the page and submit an AI video task
2. Watch the **console logs** (the terminal running `server.py`) and be patient
3. All key operations are logged for easy debugging

### Log Reference

All important operations are logged to the server console:

| Prefix | Module |
|--------|--------|
| `[Startup]` | Server startup, stale task reset |
| `[WS]` | WebSocket connect/disconnect |
| `[Resume]` / `[Stop]` | Task resume/stop |
| `[Pipeline]` / `[Simple]` / `[Manuscript]` | Pipeline step execution |
| `[TTS]` / `[Subtitle]` | Audio and subtitle generation |
| `[Compositor]` | Video concatenation and processing |
| `[AgnesImage]` / `[AgnesVideo]` / `[AgnesChat]` | AI API calls |
| `[RateLimiter]` | Global rate limiter |
| `[TaskManager]` | Task state persistence |
| `[Screenwriter]` | Screenwriter Agent |

### Output Directory

All AI task artifacts are stored under `.working_dir/{timestamp}_{task_id}/`. This filesystem state is persistent only when the directory itself is persistent (for example, a local disk or Docker volume):

```
.working_dir/{timestamp}_{task_id}/
├── task_state.json              # Task state (required for checkpoint resume)
├── final_video.mp4              # Final video with narration + subtitles
├── story.txt                    # AI-generated story (creative mode)
├── script.json                  # Scene script (JSON format)
├── narration.mp3                # Combined TTS narration audio
├── narration.srt                # Combined subtitle file
├── scene_0/
│   ├── video.mp4                # Scene 0 AI video
│   ├── end_frame.png            # Scene 0 end frame
│   └── task.json                # Video generation task ID
├── scene_1/
│   └── ...
└── scene_2/
    └── ...
```

## Acknowledgments

This project is built upon the following open-source projects:

- [ViMax](https://github.com/HKUDS/ViMax) — AI video generation framework by HKU Data Science Lab
- [vimax-agnes](https://github.com/easyeye163/vimax-agnes) — Agnes AI adaptation based on ViMax

Special thanks to [Agnes AI](https://platform.agnes-ai.com) for providing access to its AI model APIs (text, image, and video generation) — this project runs at absolute zero cost thanks to their generosity.

## Feedback & Contributing

Bug reports and feature suggestions are welcome via [GitHub Issues](https://github.com/bjiow131/free-video-generator/issues).

## Support the Developer

Agnes Video Generator is open-source software. It has no built-in paid plans or subscription system.



## License

MIT

---

## FAQ

### Is Agnes Video Generator really free? Are there any hidden costs?

The application itself does not charge for software usage. Agnes AI availability, quotas, pricing, and any provider-side limits are controlled by Agnes AI and may change. The only TTS integration (Microsoft Edge TTS) is also free and requires no extra API key. You only need a free API key from [Agnes AI](https://platform.agnes-ai.com) to get started.

### Do I need a GPU to run this AI video generator?

No. All AI compute runs in the cloud via Agnes AI's free API. You just need a regular laptop or desktop computer that can run Python 3.10+ and ffmpeg. No GPU, no high RAM, no special hardware required.

### How is this different from Runway, Pika, or Sora?

Unlike commercial AI video tools that charge $10-$95/month, Agnes Video Generator is completely free and open-source (MIT). It offers built-in multi-scene pipelines, AI narration, auto subtitles, and digital anchor — features that require third-party tools or manual editing elsewhere. See the comparison table above for general positioning; third-party prices and limits can change.

### What video generation modes are supported?

Four modes: **Simple Video** (single prompt, full parameter control), **Creative Video** (AI story → multi-scene video with narration), **Manuscript Video** (long text → auto-split → narrated video), and **Digital Anchor** (AI anchor with TTS). Additional options include text-to-video, image-to-video, keyframes animation, and image-to-image end frame generation.

### Can I use my own images as references?

Yes. You can upload reference images for character or scene consistency across scenes, use custom end frames for precise visual transitions, or choose img2img to auto-generate end frames from your reference. Reference images are supported in both Creative Video and Digital Anchor modes.

### What languages does the UI support?

The current Web UI is primarily Russian-language; CJK text is supported in generated subtitles through the bundled fonts. Subtitles are generated in the source text language with CJK font support built-in.

### Can I host this on my own server?

Absolutely. The project is designed for self-hosting. Just clone the repo, run `./start.sh`, and the server starts on `http://localhost:8765`. No local GPU is required; Agnes AI is the external model provider. See the [Quick Start](#quick-start) section above.

### How do I get help or report issues?

Check the [GitHub Issues](https://github.com/bjiow131/free-video-generator/issues) page for existing reports or open a new one. The project also includes a comprehensive `AGENTS.md` for AI-agent-assisted debugging. For feature requests, bug reports, or questions, the Issues page is the best place.

**Keywords**: free AI video generator, AI video generation tool, text to video AI, free AI video maker, AI video creator, open source video generator, text-to-video, image-to-video, keyframes video, AI narration, auto subtitles, multi-scene video, zero cost AI video, no subscription AI video tool, digital anchor, self-hosted AI video generator, open source alternative to Runway

## Design refresh — QA

The `design/redesign` branch contains the final UI polish pass: responsive shell, creation workspace, production storyboard, task grid/player, settings/onboarding, focus states, reduced-motion support, lazy media loading and inline validation.

### Screenshots

Browser screenshots are intended to live under `docs/design/screenshots/`. They are not committed in this branch because the available repository tooling does not provide a browser/screenshot runtime; no synthetic images are substituted for real application screenshots.

For visual QA, capture the following states after deploying the branch: dark/light at 1440px, 768px and 360px, plus the Simple, Creative, Tasks and Settings screens.
