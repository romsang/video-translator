"""
main.py — 应用入口
启动 FastAPI 后端服务，加载配置，注册路由
运行方式：python main.py
"""

import asyncio
import logging
import uuid
import yaml
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.models.schemas import (
    TranslationTask, TaskStatus, CreateTaskRequest, TaskStatusResponse,
    SegmentOut, SegmentsResponse, ConfirmASRRequest, ConfirmTranslationRequest,
)
from app.utils.file_utils import ensure_dirs, cleanup_workspace
from app.pipeline.step1_preprocess import preprocess
from app.pipeline.step2_asr       import run_asr
from app.pipeline.step3_translate  import translate_segments
from app.pipeline.step4_tts        import synthesize_tts
from app.pipeline.step5_lipsync    import run_lipsync
from app.pipeline.step6_assemble   import assemble_output

# ── 日志配置 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── 加载全局配置 ──────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# ── 内存中的任务存储（生产环境可换成数据库）────────────────────
# key: task_id, value: TranslationTask
TASKS: dict[str, TranslationTask] = {}

# ── 人工确认事件：流水线暂停时等待此 Event 被 set ───────────────
# key: task_id, value: asyncio.Event
CONFIRM_EVENTS: dict[str, asyncio.Event] = {}


# ════════════════════════════════════════════════════════════
# 应用生命周期：启动时创建必要目录
# ════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子：启动时初始化目录结构"""
    ensure_dirs(CONFIG)
    logger.info("📁 工作目录初始化完成")
    logger.info("🚀 视频翻译服务启动")
    yield
    logger.info("👋 服务关闭")


# ── FastAPI 实例 ──────────────────────────────────────────────
app = FastAPI(
    title="视频翻译工具",
    description="上传中文视频，翻译为目标语言视频和字幕",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS：允许本地前端页面调用 API ──────────────────────────────
# 前端以 file:// 或 localhost 打开，需要允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 本地工具，允许所有来源
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 静态文件：托管前端页面 ────────────────────────────────────
_frontend_dir = Path(__file__).parent / "frontend"
if _frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
    assets_dir = _frontend_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


# ════════════════════════════════════════════════════════════
# 核心流水线（异步后台运行）
# ════════════════════════════════════════════════════════════

async def run_pipeline(task: TranslationTask):
    """
    完整流水线：依次执行 Step 1~6
    每步完成后更新 task.progress，出错时记录错误信息
    """
    try:
        task.status = TaskStatus.RUNNING

        # 将任务级 lipsync 设置覆盖到 config（避免影响全局 CONFIG）
        task_config = {**CONFIG, "lipsync": {**CONFIG["lipsync"], "enabled": task.lipsync_enabled}}

        # ── Step 1：音视频预处理 ─────────────────────────────
        logger.info(f"[{task.task_id}] Step 1: 预处理")
        task.current_step = "preprocess"
        task.progress = 5.0
        await preprocess(task, task_config)
        task.progress = 20.0

        # ── Step 2：ASR 语音识别 ─────────────────────────────
        logger.info(f"[{task.task_id}] Step 2: ASR 识别")
        task.current_step = "asr"
        await run_asr(task, task_config)
        task.progress = 20.0

        # ── 暂停①：等待用户确认 ASR 结果 ────────────────────
        logger.info(f"[{task.task_id}] ⏸ 等待 ASR 确认（{len(task.segments)} 片段）")
        task.status = TaskStatus.WAITING_ASR_CONFIRM
        task.current_step = None
        _event_asr = asyncio.Event()
        CONFIRM_EVENTS[f"{task.task_id}:asr"] = _event_asr
        await _event_asr.wait()
        CONFIRM_EVENTS.pop(f"{task.task_id}:asr", None)
        task.status = TaskStatus.RUNNING
        logger.info(f"[{task.task_id}] ▶ ASR 已确认，继续翻译")

        # ── Step 3：翻译 ─────────────────────────────────────
        logger.info(f"[{task.task_id}] Step 3: 翻译 ({len(task.segments)} 片段)")
        task.current_step = "translate"
        await translate_segments(task, task_config)
        task.progress = 50.0

        # ── 暂停②：等待用户确认翻译结果 ─────────────────────
        logger.info(f"[{task.task_id}] ⏸ 等待翻译确认")
        task.status = TaskStatus.WAITING_TRANSLATION_CONFIRM
        task.current_step = None
        _event_tr = asyncio.Event()
        CONFIRM_EVENTS[f"{task.task_id}:translation"] = _event_tr
        await _event_tr.wait()
        CONFIRM_EVENTS.pop(f"{task.task_id}:translation", None)
        task.status = TaskStatus.RUNNING
        logger.info(f"[{task.task_id}] ▶ 翻译已确认，继续 TTS")

        # ── Step 4：TTS 合成 + 时长对齐 ──────────────────────
        logger.info(f"[{task.task_id}] Step 4: TTS 合成")
        task.current_step = "tts"
        await synthesize_tts(task, task_config)
        task.progress = 70.0

        # ── Step 5：口型同步 ─────────────────────────────────
        logger.info(f"[{task.task_id}] Step 5: 口型同步")
        task.current_step = "lipsync"
        await run_lipsync(task, task_config)
        task.progress = 88.0

        # ── Step 6：最终合成输出 ─────────────────────────────
        logger.info(f"[{task.task_id}] Step 6: 合成输出")
        task.current_step = "assemble"
        await assemble_output(task, task_config)
        task.progress = 100.0

        # ── 完成 ─────────────────────────────────────────────
        task.status = TaskStatus.COMPLETED
        task.current_step = None
        logger.info(f"[{task.task_id}] ✅ 完成 -> {task.output_video_path}")

        # 清理中间文件（可选）
        if task_config["misc"]["cleanup_workspace"]:
            cleanup_workspace(task.task_id, task_config)

    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error_message = str(e)
        logger.error(f"[{task.task_id}] ❌ 流水线失败: {e}", exc_info=True)


# ════════════════════════════════════════════════════════════
# API 路由
# ════════════════════════════════════════════════════════════

@app.post("/tasks", response_model=TaskStatusResponse, summary="提交翻译任务")
async def create_task(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的中文视频文件"),
    target_language: str = Form("English"),
    lipsync: str = Form("true"),
):
    """
    接收视频文件，创建翻译任务并在后台异步执行流水线。
    返回 task_id 供后续查询进度。
    """
    # 生成唯一任务 ID
    task_id = uuid.uuid4().hex[:8]

    # 保存上传的视频到工作目录
    workspace = Path(CONFIG["paths"]["workspace"]) / task_id
    workspace.mkdir(parents=True, exist_ok=True)
    input_path = workspace / f"input{Path(file.filename).suffix}"

    with open(input_path, "wb") as f:
        content = await file.read()
        f.write(content)
    logger.info(f"[{task_id}] 收到文件: {file.filename} ({len(content)/1024/1024:.1f} MB)")

    # 解析 lipsync 字符串 → bool
    lipsync_enabled = lipsync.lower() not in ("false", "0", "no")

    # 创建任务对象
    task = TranslationTask(
        task_id=task_id,
        input_video_path=str(input_path),
        target_language=target_language,
        lipsync_enabled=lipsync_enabled,
    )
    TASKS[task_id] = task

    # 后台执行流水线（不阻塞 HTTP 响应）
    background_tasks.add_task(run_pipeline, task)

    return TaskStatusResponse(
        task_id=task_id,
        status=task.status,
        progress=task.progress,
    )


@app.get("/tasks/{task_id}", response_model=TaskStatusResponse, summary="查询任务进度")
async def get_task(task_id: str):
    """根据 task_id 查询任务当前状态和进度"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        current_step=task.current_step,
        progress=task.progress,
        error_message=task.error_message,
        output_video_path=task.output_video_path,
        output_srt_path=task.output_srt_path,
    )


@app.get("/tasks/{task_id}/download/video", summary="下载输出视频")
async def download_video(task_id: str):
    """任务完成后，下载翻译后的视频文件"""
    task = TASKS.get(task_id)
    if not task or task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="任务未完成或不存在")
    return FileResponse(task.output_video_path, media_type="video/mp4")


@app.get("/tasks/{task_id}/download/srt", summary="下载字幕文件")
async def download_srt(task_id: str):
    """任务完成后，下载 SRT 字幕文件"""
    task = TASKS.get(task_id)
    if not task or task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="任务未完成或不存在")
    return FileResponse(task.output_srt_path, media_type="text/plain")


@app.get("/tasks/{task_id}/segments", response_model=SegmentsResponse, summary="获取片段列表")
async def get_segments(task_id: str):
    """返回当前任务的所有片段，供前端展示和编辑"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return SegmentsResponse(
        segments=[
            SegmentOut(
                index=s.index,
                start=s.start,
                end=s.end,
                original_text=s.original_text,
                translated_text=s.translated_text,
            )
            for s in task.segments
        ],
        target_language=task.target_language,
    )


@app.post("/tasks/{task_id}/confirm/asr", summary="确认 ASR 识别结果")
async def confirm_asr(task_id: str, body: ConfirmASRRequest):
    """
    用户确认（或编辑后提交）中文识别结果。
    body.segments: [{index, text}, ...]
    接口收到后将编辑内容写回 segments，并恢复流水线继续翻译。
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    if task.status != TaskStatus.WAITING_ASR_CONFIRM:
        raise HTTPException(status_code=400, detail="任务不在等待 ASR 确认状态")

    # 将用户编辑的文本写回 segments
    edited = {item["index"]: item["text"] for item in body.segments}
    for seg in task.segments:
        if seg.index in edited:
            seg.original_text = edited[seg.index]

    # 触发流水线继续
    event = CONFIRM_EVENTS.get(f"{task_id}:asr")
    if event:
        event.set()
    return {"status": "ok", "segments": len(task.segments)}


@app.post("/tasks/{task_id}/confirm/translation", summary="确认翻译结果")
async def confirm_translation(task_id: str, body: ConfirmTranslationRequest):
    """
    用户确认（或编辑后提交）译文。
    body.segments: [{index, translated_text}, ...]
    接口收到后将译文写回 segments，并恢复流水线继续 TTS。
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    if task.status != TaskStatus.WAITING_TRANSLATION_CONFIRM:
        raise HTTPException(status_code=400, detail="任务不在等待翻译确认状态")

    # 将用户编辑的译文写回 segments
    edited = {item["index"]: item["translated_text"] for item in body.segments}
    for seg in task.segments:
        if seg.index in edited:
            seg.translated_text = edited[seg.index]

    # 触发流水线继续
    event = CONFIRM_EVENTS.get(f"{task_id}:translation")
    if event:
        event.set()
    return {"status": "ok", "segments": len(task.segments)}


@app.get("/tasks/{task_id}/download/transcript", summary="下载对照文稿")
async def download_transcript(task_id: str):
    """任务完成后，下载原文 + 译文对照文稿"""
    task = TASKS.get(task_id)
    if not task or task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="任务未完成或不存在")
    return FileResponse(task.output_transcript_path, media_type="text/plain")


# ════════════════════════════════════════════════════════════
# 启动入口
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,   # 生产模式关闭热重载
        log_level=CONFIG["misc"]["log_level"].lower(),
    )
