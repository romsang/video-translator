"""
step5_lipsync.py — 口型同步
策略：
  1. 用 OpenCV 对每段视频的中间帧做人脸检测
  2. 有人脸 → 截取该段视频 + TTS 音频 → 调用 Sync.so API → 得到口型同步片段
  3. 无人脸 → 直接替换音轨（FFmpeg），不调用付费 API（节省费用）

Sync.so API 文档：https://docs.sync.so/
"""

import asyncio
import logging
import time
from pathlib import Path

import cv2
import httpx

from app.models.schemas import TranslationTask, Segment
from app.utils.file_utils import get_task_workspace
from app.utils.ffmpeg_utils import (
    extract_video_segment,
    replace_audio,
    slowdown_video_segment,
    get_video_duration,
)

logger = logging.getLogger(__name__)

# Sync.so API 端点
SYNCSO_BASE_URL  = "https://api.sync.so/v2"
SYNCSO_LIPSYNC   = f"{SYNCSO_BASE_URL}/generate"
SYNCSO_POLL      = f"{SYNCSO_BASE_URL}/generate/{{job_id}}"

# OpenCV 人脸检测器（Haar Cascade，轻量，本地运行）
# 也可以换成 DNN 人脸检测器，准确率更高
_FACE_CASCADE = None

def _get_face_cascade():
    """懒加载人脸检测器（只初始化一次）"""
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        # OpenCV 内置的 Haar Cascade 分类器
        _FACE_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _FACE_CASCADE


async def run_lipsync(task: TranslationTask, config: dict) -> None:
    """
    Step 5 主函数：对每段视频执行口型同步或直接音频替换。

    执行后填充：
      segment.has_face                ← 是否检测到人脸
      segment.video_segment_path      ← 截取的原始视频片段
      segment.lipsynced_segment_path  ← 处理后的视频片段
    """
    if not config["lipsync"]["enabled"]:
        # 口型同步功能被禁用：所有片段直接替换音轨
        logger.info(f"[{task.task_id}] 口型同步已禁用，全部替换音轨")
        await _process_all_replace_audio(task, config)
        return

    api_key    = config["api_keys"]["syncso"]
    confidence = config["lipsync"]["face_detection_confidence"]
    workspace  = get_task_workspace(task.task_id, config)
    segs_dir   = workspace / "segments"
    segs_dir.mkdir(exist_ok=True)

    video_path = task.input_video_path
    lipsync_count = 0
    skip_count    = 0

    for seg in task.segments:
        if not seg.aligned_audio_path:
            # 空片段（无语音），跳过
            continue

        # ── 1. 截取该段原始视频 ───────────────────────────────
        seg_video_path = str(segs_dir / f"seg_{seg.index:04d}_orig.mp4")
        await extract_video_segment(
            video_path=video_path,
            output_path=seg_video_path,
            start=seg.start,
            end=seg.end,
            config=config,
        )
        seg.video_segment_path = seg_video_path

        # ── Stage 3 处理：如需拉伸视频，在此执行 ────────────────
        seg_video_path = await _maybe_stretch_video(
            seg=seg,
            seg_video_path=seg_video_path,
            segs_dir=segs_dir,
            config=config,
        )

        # ── 2. 检测人脸 ───────────────────────────────────────
        has_face = _detect_face_in_video(seg_video_path, confidence)
        seg.has_face = has_face

        if has_face:
            # ── 3a. 有人脸：调用 Sync.so 口型同步 ──────────────
            logger.info(f"  片段 #{seg.index}: 检测到人脸，调用 Sync.so")
            try:
                lipsynced_path = str(segs_dir / f"seg_{seg.index:04d}_lipsync.mp4")
                await _call_syncso(
                    video_path=seg_video_path,
                    audio_path=seg.aligned_audio_path,
                    output_path=lipsynced_path,
                    api_key=api_key,
                    config=config,
                )
                seg.lipsynced_segment_path = lipsynced_path
                lipsync_count += 1
            except Exception as e:
                # Sync.so 失败时降级为替换音轨
                logger.warning(f"  片段 #{seg.index}: Sync.so 失败，降级替换音轨: {e}")
                fallback_path = str(segs_dir / f"seg_{seg.index:04d}_fallback.mp4")
                await replace_audio(seg_video_path, seg.aligned_audio_path, fallback_path, config)
                seg.lipsynced_segment_path = fallback_path
        else:
            # ── 3b. 无人脸：直接替换音轨 ─────────────────────
            logger.debug(f"  片段 #{seg.index}: 无人脸，替换音轨")
            replaced_path = str(segs_dir / f"seg_{seg.index:04d}_replaced.mp4")
            await replace_audio(seg_video_path, seg.aligned_audio_path, replaced_path, config)
            seg.lipsynced_segment_path = replaced_path
            skip_count += 1

    logger.info(
        f"[{task.task_id}] 口型同步完成: "
        f"调用 API {lipsync_count} 段，跳过（无人脸）{skip_count} 段"
    )


async def _maybe_stretch_video(
    seg: Segment,
    seg_video_path: str,
    segs_dir: Path,
    config: dict,
) -> str:
    """
    如果该片段 TTS 比原始视频长超过加速上限（Stage 3），
    拉伸原始视频片段以匹配更长的 TTS 音频时长。
    返回处理后的视频路径。
    """
    max_speedup = config["timing"]["max_audio_speedup_ratio"]

    if seg.timing_ratio <= max_speedup:
        # 不需要视频拉伸，直接返回原始片段路径
        return seg_video_path

    # ratio 超过加速上限，需要拉伸视频
    max_stretch = config["timing"]["max_video_stretch_ratio"]
    actual_ratio = min(seg.timing_ratio, max_stretch)  # 最大拉伸 30%

    stretched_path = str(segs_dir / f"seg_{seg.index:04d}_stretched.mp4")
    await slowdown_video_segment(
        video_path=seg_video_path,
        output_path=stretched_path,
        ratio=actual_ratio,
        config=config,
    )
    logger.info(f"  片段 #{seg.index}: 视频拉伸 x{actual_ratio:.2f}")
    return stretched_path


def _detect_face_in_video(video_path: str, confidence_threshold: float) -> bool:
    """
    检测视频中间帧是否包含人脸。
    取视频中间帧（而非第一帧，中间帧更具代表性）进行检测。

    返回 True 表示检测到置信度足够的人脸。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False

    # 跳到视频中间帧
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return False

    # 转灰度图（人脸检测不需要彩色）
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Haar Cascade 人脸检测
    cascade = _get_face_cascade()
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30),   # 最小人脸尺寸（像素）
    )

    if len(faces) == 0:
        return False

    # 额外验证：检查人脸占画面的比例（太小的脸可能是误检）
    frame_area = frame.shape[0] * frame.shape[1]
    for (x, y, w, h) in faces:
        face_ratio = (w * h) / frame_area
        if face_ratio >= 0.01:  # 人脸至少占画面 1%（过滤极小误检）
            return True

    return False


async def _call_syncso(
    video_path: str,
    audio_path: str,
    output_path: str,
    api_key: str,
    config: dict,
) -> None:
    """
    调用 Sync.so API 进行口型同步。

    流程：
      1. POST /v2/generate → 提交任务，获取 job_id
      2. GET  /v2/generate/{job_id} → 轮询直到完成
      3. 下载结果视频到 output_path
    """
    model = config["lipsync"]["syncso_model"]
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        # ── 1. 上传并提交任务 ─────────────────────────────────
        with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
            resp = await client.post(
                SYNCSO_LIPSYNC,
                headers=headers,
                files={
                    "video": (Path(video_path).name, vf, "video/mp4"),
                    "audio": (Path(audio_path).name, af, "audio/mpeg"),
                },
                data={"model": model},
            )
        resp.raise_for_status()
        job_id = resp.json()["id"]
        logger.debug(f"  Sync.so 任务已提交: job_id={job_id}")

        # ── 2. 轮询任务状态 ───────────────────────────────────
        poll_url = SYNCSO_POLL.format(job_id=job_id)
        for attempt in range(120):  # 最多等待 120 * 3 = 360 秒
            await asyncio.sleep(3)
            poll_resp = await client.get(poll_url, headers=headers)
            poll_resp.raise_for_status()
            data = poll_resp.json()

            status = data.get("status", "")
            if status == "completed":
                result_url = data["outputUrl"]
                break
            elif status in ("failed", "error"):
                raise RuntimeError(f"Sync.so 任务失败: {data.get('error', '未知错误')}")
            # 仍在处理中，继续等待
        else:
            raise TimeoutError("Sync.so 超时（超过 360 秒）")

        # ── 3. 下载结果视频 ───────────────────────────────────
        dl_resp = await client.get(result_url)
        dl_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(dl_resp.content)
        logger.debug(f"  Sync.so 结果已下载: {output_path}")


async def _process_all_replace_audio(task: TranslationTask, config: dict) -> None:
    """
    口型同步禁用时的回退方案：
    对所有片段截取视频并直接替换音轨。
    """
    workspace = get_task_workspace(task.task_id, config)
    segs_dir  = workspace / "segments"
    segs_dir.mkdir(exist_ok=True)

    for seg in task.segments:
        if not seg.aligned_audio_path:
            continue
        seg_video_path = str(segs_dir / f"seg_{seg.index:04d}_orig.mp4")
        await extract_video_segment(
            task.input_video_path, seg_video_path,
            seg.start, seg.end, config
        )
        replaced_path = str(segs_dir / f"seg_{seg.index:04d}_replaced.mp4")
        await replace_audio(seg_video_path, seg.aligned_audio_path, replaced_path, config)
        seg.video_segment_path     = seg_video_path
        seg.lipsynced_segment_path = replaced_path
