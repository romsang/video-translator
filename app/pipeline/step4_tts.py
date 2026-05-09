"""
step4_tts.py — TTS 语音合成 + 三阶段时长对齐
使用 OpenAI TTS API 合成目标语言语音，并通过三阶段策略确保与原始视频时长对齐。

三阶段策略（按超长程度分级）：
  Stage 1 — 约束翻译（Step 3 已处理，此处不重复）
  Stage 2 — TTS 音频加速（ratio ≤ 1.20，atempo 滤镜）
  Stage 3 — 视频片段拉伸（ratio > 1.20，setpts 滤镜）
"""

import asyncio
import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.models.schemas import TranslationTask, Segment
from app.utils.file_utils import get_task_workspace
from app.utils.ffmpeg_utils import speedup_audio, get_video_duration, run_ffmpeg

logger = logging.getLogger(__name__)

# OpenAI TTS API 每次请求之间的最小间隔（秒），避免触发速率限制
TTS_REQUEST_INTERVAL = 0.2


async def synthesize_tts(task: TranslationTask, config: dict) -> None:
    """
    Step 4 主函数：为每个字幕片段合成目标语言语音，并对齐时长。

    执行后填充：
      segment.tts_audio_path       ← 原始 TTS 音频
      segment.tts_duration         ← TTS 实际时长（秒）
      segment.aligned_audio_path   ← 时长对齐后的音频
    """
    client    = AsyncOpenAI(api_key=config["api_keys"]["openai"])
    model     = config["models"]["tts"]
    voice     = config["models"]["tts_voice"]
    workspace = get_task_workspace(task.task_id, config)
    tts_dir   = workspace / "tts"
    tts_dir.mkdir(exist_ok=True)

    max_speedup  = config["timing"]["max_audio_speedup_ratio"]   # 默认 1.20
    retrans_thresh = config["timing"]["retranslate_threshold"]   # 默认 1.50

    logger.info(f"[{task.task_id}] TTS 合成 {len(task.segments)} 段（模型: {model}, 声音: {voice}）")

    for seg in task.segments:
        if not seg.translated_text.strip():
            # 跳过空片段（可能是无声段落）
            seg.tts_audio_path = ""
            seg.aligned_audio_path = ""
            continue

        # ── 合成 TTS 音频 ──────────────────────────────────────
        tts_path = str(tts_dir / f"seg_{seg.index:04d}_tts.mp3")
        await _synthesize_single(
            text=seg.translated_text,
            output_path=tts_path,
            client=client,
            model=model,
            voice=voice,
        )
        seg.tts_audio_path = tts_path

        # 测量 TTS 实际时长
        seg.tts_duration = get_video_duration(tts_path, config)

        # ── 三阶段时长对齐 ─────────────────────────────────────
        aligned_path = await _align_duration(
            seg=seg,
            tts_dir=tts_dir,
            config=config,
            max_speedup=max_speedup,
        )
        seg.aligned_audio_path = aligned_path

        logger.debug(
            f"  片段 #{seg.index}: 原始 {seg.original_duration:.2f}s | "
            f"TTS {seg.tts_duration:.2f}s | 比率 {seg.timing_ratio:.2f} | "
            f"对齐后 -> {Path(aligned_path).name}"
        )

        # 避免触发 API 速率限制
        await asyncio.sleep(TTS_REQUEST_INTERVAL)

    logger.info(f"[{task.task_id}] TTS 合成完成")


async def _synthesize_single(
    text: str,
    output_path: str,
    client: AsyncOpenAI,
    model: str,
    voice: str,
) -> None:
    """
    调用 OpenAI TTS API 合成单段语音。
    输出格式：mp3（OpenAI TTS 默认格式，体积小）
    """
    response = await client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        response_format="mp3",
        speed=1.0,   # 初始语速为正常速度；时长对齐由后处理完成
    )
    # 写入文件（新版 SDK 的 iter_bytes 是同步的）
    with open(output_path, "wb") as f:
        for chunk in response.iter_bytes(chunk_size=4096):
            f.write(chunk)


async def _align_duration(
    seg: Segment,
    tts_dir: Path,
    config: dict,
    max_speedup: float,
) -> str:
    """
    三阶段时长对齐逻辑。
    根据 timing_ratio（TTS时长 / 原始时长）决定处理方式：

    ratio ≤ 1.0  → TTS 比原始更短，直接使用（自然留白）
    1.0 < ratio ≤ max_speedup → Stage 2：加速 TTS 音频
    ratio > max_speedup        → Stage 3：标记需要视频拉伸（Step 5/6 处理）
    """
    ratio = seg.timing_ratio

    if ratio <= 1.0:
        # TTS 比原始短：补静音到原始时长，确保视频片段不被 -shortest 截断
        target_dur = seg.original_duration
        tts_dur    = seg.tts_duration
        pad_sec    = target_dur - tts_dur
        if pad_sec > 0.05:   # 超过 50ms 才补，避免无意义处理
            padded_path = str(tts_dir / f"seg_{seg.index:04d}_padded.mp3")
            await _pad_audio_with_silence(
                audio_path=seg.tts_audio_path,
                output_path=padded_path,
                total_duration=target_dur,   # 指定输出总时长，语义明确
                config=config,
            )
            logger.debug(
                f"  片段 #{seg.index}: TTS 较短 (ratio={ratio:.2f})，"
                f"补 {pad_sec:.2f}s 静音 → 总时长 {target_dur:.2f}s"
            )
            return padded_path
        logger.debug(f"  片段 #{seg.index}: TTS 与原始等长 (ratio={ratio:.2f})")
        return seg.tts_audio_path

    elif ratio <= max_speedup:
        # Stage 2：加速 TTS 音频以压缩到原始时长
        # atempo 值 = ratio（ratio=1.15 表示加速 15%）
        sped_path = str(tts_dir / f"seg_{seg.index:04d}_sped.mp3")
        await speedup_audio(
            audio_path=seg.tts_audio_path,
            output_path=sped_path,
            ratio=ratio,   # 传入实际比率
            config=config,
        )
        logger.debug(f"  片段 #{seg.index}: Stage 2 加速 x{ratio:.2f}")
        return sped_path

    else:
        # Stage 3：超出加速上限，标记需要拉伸视频
        # 视频拉伸在 Step 5 中处理（需要视频片段才能操作）
        logger.info(
            f"  片段 #{seg.index}: Stage 3 需要视频拉伸 (ratio={ratio:.2f})，"
            f"将在合成阶段处理"
        )
        return seg.tts_audio_path


async def _pad_audio_with_silence(
    audio_path: str,
    output_path: str,
    total_duration: float,
    config: dict,
) -> None:
    """
    将音频补到指定总时长（末尾追加静音）。
    用于 Stage 1（TTS 比原始短时），确保音频与原始视频段等长，
    避免 -shortest 截断视频。

    使用 whole_dur 而非 pad_dur：
      whole_dur 语义明确——"把输出补到整好 X 秒"，
      不受 ffmpeg 版本差异影响。
    """
    await run_ffmpeg([
        "-i", audio_path,
        "-af", f"apad=whole_dur={total_duration:.3f}",
        output_path,
    ], config)
