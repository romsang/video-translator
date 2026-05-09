"""
gradio_app.py — Gradio Web 界面
提供本地浏览器操作界面：上传视频、选择目标语言、查看进度、下载结果。
访问地址：http://localhost:7860
"""

import asyncio
import time
import uuid
import logging
from pathlib import Path

import gradio as gr
import yaml

# 导入流水线各步骤
from app.models.schemas import TranslationTask, TaskStatus
from app.utils.file_utils import ensure_dirs, get_output_dir
from app.pipeline.step1_preprocess import preprocess
from app.pipeline.step2_asr        import run_asr
from app.pipeline.step3_translate  import translate_segments
from app.pipeline.step4_tts        import synthesize_tts
from app.pipeline.step5_lipsync    import run_lipsync
from app.pipeline.step6_assemble   import assemble_output

logger = logging.getLogger(__name__)

# 加载配置
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# 支持的目标语言列表
SUPPORTED_LANGUAGES = [
    "English", "Japanese", "Korean", "Spanish", "French",
    "German", "Portuguese", "Arabic", "Russian", "Thai",
]

# 内存任务存储（Gradio 会话内共享）
_current_task: TranslationTask | None = None


# ════════════════════════════════════════════════════════════
# 核心处理函数（同步包装异步流水线）
# ════════════════════════════════════════════════════════════

def run_translation(video_file, target_language, enable_lipsync):
    """
    Gradio 调用的主处理函数。
    由于 Gradio 的生成器（yield）机制，此函数逐步 yield 进度信息。

    参数：
      video_file     ← Gradio 上传的临时文件路径
      target_language ← 目标语言字符串
      enable_lipsync  ← 是否启用口型同步

    yield：(进度文本, 进度百分比, 视频路径, SRT路径, 文稿路径)
    """
    global _current_task

    if video_file is None:
        yield "❌ 请先上传视频文件", 0, None, None, None
        return

    # ── 初始化任务 ─────────────────────────────────────────
    task_id = uuid.uuid4().hex[:8]
    ensure_dirs(CONFIG)

    # 更新口型同步配置（根据界面开关）
    config = CONFIG.copy()
    config["lipsync"] = CONFIG["lipsync"].copy()
    config["lipsync"]["enabled"] = enable_lipsync

    task = TranslationTask(
        task_id=task_id,
        input_video_path=video_file,
        target_language=target_language,
        status=TaskStatus.RUNNING,
    )
    _current_task = task

    # ── 逐步执行流水线，yield 进度 ─────────────────────────
    steps = [
        ("🎬 Step 1: 音视频预处理...", 5,  preprocess),
        ("🎤 Step 2: 语音识别（ASR）...", 20, run_asr),
        ("🌐 Step 3: 翻译中...", 35, translate_segments),
        ("🔊 Step 4: 语音合成（TTS）...", 50, synthesize_tts),
        ("👄 Step 5: 口型同步...", 70, run_lipsync),
        ("🎞️  Step 6: 合成输出...", 88, assemble_output),
    ]

    for step_name, progress_start, step_fn in steps:
        yield step_name, progress_start, None, None, None
        try:
            # 在新事件循环中运行异步步骤
            asyncio.run(step_fn(task, config))
        except Exception as e:
            error_msg = f"❌ {step_name} 失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield error_msg, progress_start, None, None, None
            return

    # ── 完成 ────────────────────────────────────────────
    task.status = TaskStatus.COMPLETED
    output_dir  = get_output_dir(task_id, config)

    summary = (
        f"✅ 翻译完成！\n"
        f"任务 ID: {task_id}\n"
        f"片段数: {len(task.segments)}\n"
        f"目标语言: {target_language}\n"
        f"输出目录: {output_dir}"
    )
    yield summary, 100, task.output_video_path, task.output_srt_path, task.output_transcript_path


# ════════════════════════════════════════════════════════════
# Gradio UI 布局
# ════════════════════════════════════════════════════════════

def build_ui():
    """构建 Gradio 界面，返回 gr.Blocks 对象"""

    with gr.Blocks(
        title="🎬 视频翻译工具",
        theme=gr.themes.Soft(),
        css=".status-box textarea { font-family: monospace; font-size: 13px; }",
    ) as demo:

        gr.Markdown("""
        # 🎬 视频翻译工具
        上传中文视频，自动翻译为目标语言 · 支持字幕 · 口型同步
        """)

        with gr.Row():
            # ── 左栏：输入设置 ─────────────────────────────
            with gr.Column(scale=1):
                gr.Markdown("### 📤 输入设置")

                video_input = gr.Video(
                    label="上传中文视频",
                    sources=["upload"],
                )

                target_lang = gr.Dropdown(
                    choices=SUPPORTED_LANGUAGES,
                    value="English",
                    label="目标语言",
                )

                lipsync_toggle = gr.Checkbox(
                    label="启用口型同步（调用 Sync.so API，有额外费用）",
                    value=True,
                )

                submit_btn = gr.Button(
                    "🚀 开始翻译",
                    variant="primary",
                    size="lg",
                )

                gr.Markdown("""
                **提示：**
                - 处理时间约为视频时长的 2~4 倍
                - 请确保 config.yaml 中已填入 API Keys
                - 口型同步只处理含人脸的画面，自动跳过其他场景
                """)

            # ── 右栏：输出结果 ─────────────────────────────
            with gr.Column(scale=1):
                gr.Markdown("### 📥 处理结果")

                status_box = gr.Textbox(
                    label="处理状态",
                    value="等待上传视频...",
                    interactive=False,
                    lines=5,
                    elem_classes=["status-box"],
                )

                progress = gr.Slider(
                    label="总体进度",
                    minimum=0,
                    maximum=100,
                    value=0,
                    interactive=False,
                )

                video_output = gr.Video(
                    label="翻译后视频",
                    interactive=False,
                )

                with gr.Row():
                    srt_output = gr.File(
                        label="字幕文件 (.srt)",
                        interactive=False,
                    )
                    transcript_output = gr.File(
                        label="对照文稿 (.txt)",
                        interactive=False,
                    )

        # ── 绑定事件 ──────────────────────────────────────
        submit_btn.click(
            fn=run_translation,
            inputs=[video_input, target_lang, lipsync_toggle],
            outputs=[status_box, progress, video_output, srt_output, transcript_output],
        )

        # ── 使用示例 ──────────────────────────────────────
        gr.Markdown("""
        ---
        ### 📋 使用流程
        1. 在 `config.yaml` 中填入三个 API Key（DashScope、OpenAI、Sync.so）
        2. 上传中文视频（支持 mp4 / mov / avi）
        3. 选择目标语言，点击「开始翻译」
        4. 等待处理完成，下载结果文件
        """)

    return demo


# ════════════════════════════════════════════════════════════
# 启动入口
# ════════════════════════════════════════════════════════════

def launch():
    """启动 Gradio Web 界面"""
    ensure_dirs(CONFIG)
    demo = build_ui()
    demo.launch(
        server_name="127.0.0.1",  # 仅本地访问，不对外暴露
        server_port=7860,
        share=False,              # 不创建公网隧道
        inbrowser=True,           # 自动打开浏览器
    )


if __name__ == "__main__":
    launch()
