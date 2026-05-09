# UI Kit · 视频翻译 Gradio App

A pixel-faithful recreation of the live Gradio UI from `app/ui/gradio_app.py`, applying the formal design system tokens. Cosmetic-only — no real video processing happens; the pipeline progress is faked client-side so you can step through the full happy path.

## Files
- `index.html` — clickable demo, end-to-end (upload → run → download)
- `Header.jsx` — sticky page header with logo + title + tagline
- `UploadPanel.jsx` — left column: drop zone, language select, lipsync toggle, run CTA, tips
- `OutputPanel.jsx` — right column: status box, progress, video player, file downloads
- `PipelineStepper.jsx` — six-stage stepper used in the running state
- `Primitives.jsx` — Button, Select, Checkbox, Card, Pill (shared)

## Source mapping
| File in this kit | Gradio source |
|---|---|
| `Header.jsx` | `gr.Markdown("# 🎬 视频翻译工具 …")` |
| `UploadPanel.jsx` | `gr.Video`, `gr.Dropdown`, `gr.Checkbox`, `gr.Button` (left column) |
| `OutputPanel.jsx` | `gr.Textbox`, `gr.Slider`, `gr.Video`, `gr.File` (right column) |
| `PipelineStepper.jsx` | the `steps = [...]` loop in `run_translation()` |

## What's intentionally simplified
- No actual file upload (uses a fake video object).
- The "run" button advances through the six pipeline stages on a timer.
- Download links are placeholders.
