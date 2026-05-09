"""
step6_assemble.py — 最终合成输出

核心修复：
  - 保留原视频的所有片段（含语音段之间的静音/间隙）
  - 对每段语音用 TTS 音频替换；间隙段保留原始音轨
  - 对配音音轨重跑 Whisper ASR 生成精准 SRT 时间戳

输出产物：
  - output.mp4       ← 干净视频（不烧录字幕）
  - output.srt       ← 外挂 SRT（Whisper 精准时间戳）
  - dubbed.mp3       ← 独立配音音轨
  - transcript.txt   ← 原文 + 译文对照
"""

import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.models.schemas import TranslationTask, Segment
from app.utils.file_utils import get_task_workspace, get_output_dir
from app.utils.ffmpeg_utils import (
    concat_segments, run_ffmpeg, get_video_duration, extract_video_segment,
)

logger = logging.getLogger(__name__)


async def assemble_output(task: TranslationTask, config: dict) -> None:
    workspace  = get_task_workspace(task.task_id, config)
    output_dir = get_output_dir(task.task_id, config)

    # ── 1. 收集所有视频片段（含语音段间隙）──────────────────
    all_pieces = await _collect_all_pieces(task, workspace, config)
    logger.info(f"[{task.task_id}] 拼接 {len(all_pieces)} 个片段（含间隙填充）")

    # ── 2. 拼接为干净视频（不烧录字幕）─────────────────────
    final_video_path = str(output_dir / "output.mp4")
    await concat_segments(all_pieces, final_video_path, config)
    task.output_video_path = final_video_path
    logger.info(f"[{task.task_id}] 干净视频已生成: {final_video_path}")

    # ── 3. 提取配音音轨 MP3（供用户下载）───────────────────
    dubbed_mp3 = str(output_dir / "dubbed.mp3")
    await _extract_audio_mp3(final_video_path, dubbed_mp3, config)
    task.output_audio_path = dubbed_mp3

    # ── 4. 提取 16kHz WAV 供 Whisper 重新 ASR ────────────
    dubbed_wav = str(workspace / "dubbed_for_asr.wav")
    await _extract_audio_wav_16k(final_video_path, dubbed_wav, config)

    # ── 5. Whisper ASR → 精准时间戳 → SRT ────────────────
    logger.info(f"[{task.task_id}] 对配音音轨重跑 Whisper ASR，生成精准时间戳...")
    srt_path = str(output_dir / "output.srt")
    await _generate_srt_via_whisper(
        dubbed_wav=dubbed_wav,
        srt_path=srt_path,
        api_key=config["api_keys"]["openai"],
    )
    task.output_srt_path = srt_path
    logger.info(f"[{task.task_id}] SRT 已生成: {srt_path}")

    # ── 6. 原文 + 译文对照文稿 ──────────────────────────
    transcript_path = str(output_dir / "transcript.txt")
    _write_transcript(task.segments, transcript_path)
    task.output_transcript_path = transcript_path

    logger.info(
        f"[{task.task_id}] ✅ 全部输出已保存:\n"
        f"  视频 (干净): output.mp4\n"
        f"  字幕 (外挂): output.srt\n"
        f"  配音:        dubbed.mp3\n"
        f"  文稿:        transcript.txt"
    )


# ════════════════════════════════════════════════════════════
# 核心：收集所有片段 + 间隙填充
# ════════════════════════════════════════════════════════════

async def _collect_all_pieces(
    task: TranslationTask,
    workspace: Path,
    config: dict,
) -> list[str]:
    """
    按时间轴顺序收集所有视频片段，包括：
      - 语音段：已经过 TTS 替换 / 口型同步处理
      - 间隙段：两段语音之间的静音区域，保留原始音轨

    这样拼接出的视频时长与原始视频完全相等。
    """
    pieces: list[str] = []
    gaps_dir = workspace / "gaps"
    gaps_dir.mkdir(exist_ok=True)

    total_dur   = get_video_duration(task.input_video_path, config)
    video_path  = task.input_video_path
    prev_end    = 0.0
    gap_idx     = 0

    for seg in task.segments:
        # ── 填充该语音段之前的间隙 ──────────────────────────
        gap_start = prev_end
        gap_end   = seg.start
        if gap_end - gap_start > 0.05:   # 超过 50ms 才提取，避免极短碎片
            gap_path = str(gaps_dir / f"gap_{gap_idx:04d}.mp4")
            await extract_video_segment(video_path, gap_path, gap_start, gap_end, config)
            pieces.append(gap_path)
            gap_idx += 1
            logger.debug(f"  间隙 [{gap_start:.2f}s → {gap_end:.2f}s] 已保留")

        # ── 语音段本身 ───────────────────────────────────────
        if seg.lipsynced_segment_path and Path(seg.lipsynced_segment_path).exists():
            pieces.append(seg.lipsynced_segment_path)
        elif seg.video_segment_path and Path(seg.video_segment_path).exists():
            logger.warning(f"  片段 #{seg.index} 无 lipsync 结果，使用原始视频片段")
            pieces.append(seg.video_segment_path)
        else:
            # 该段没有被处理（可能是无译文段），回退到原始视频+原始音频
            logger.warning(f"  片段 #{seg.index} 无任何处理结果，回退原始片段")
            fallback_path = str(gaps_dir / f"orig_{seg.index:04d}.mp4")
            await extract_video_segment(video_path, fallback_path, seg.start, seg.end, config)
            pieces.append(fallback_path)

        prev_end = seg.end

    # ── 最后一段语音之后的尾部间隙 ──────────────────────────
    if total_dur - prev_end > 0.05:
        tail_path = str(gaps_dir / f"gap_{gap_idx:04d}_tail.mp4")
        await extract_video_segment(video_path, tail_path, prev_end, total_dur, config)
        pieces.append(tail_path)
        logger.debug(f"  尾部间隙 [{prev_end:.2f}s → {total_dur:.2f}s] 已保留")

    return pieces


# ════════════════════════════════════════════════════════════
# 音频提取
# ════════════════════════════════════════════════════════════

async def _extract_audio_mp3(video_path: str, output_path: str, config: dict) -> None:
    """提取配音音轨（高质量 MP3，供用户下载）"""
    await run_ffmpeg([
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "2",
        output_path,
    ], config)


async def _extract_audio_wav_16k(video_path: str, output_path: str, config: dict) -> None:
    """
    提取 16kHz 单声道 WAV，供 Whisper ASR 使用。
    16kHz 单声道是 Whisper 的原生格式，文件小且识别质量最佳。
    """
    await run_ffmpeg([
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path,
    ], config)


# ════════════════════════════════════════════════════════════
# Whisper ASR → SRT
# ════════════════════════════════════════════════════════════

async def _generate_srt_via_whisper(
    dubbed_wav: str,
    srt_path: str,
    api_key: str,
) -> None:
    """
    用 Whisper 对配音音轨重新识别，获取精准时间戳后生成 SRT。

    核心逻辑：
      TTS 配音就是最终视频里的声音。对它 ASR 拿到的时间戳
      天然与视频音轨完全对齐，无需任何估算或偏移修正。
      Whisper 的 segment 级时间戳精确到秒级，满足字幕需求。
    """
    client    = AsyncOpenAI(api_key=api_key)
    file_size = Path(dubbed_wav).stat().st_size
    logger.info(f"[Whisper ASR] 配音音轨大小: {file_size / 1024 / 1024:.1f} MB")

    with open(dubbed_wav, "rb") as f:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            # 不指定 language，让 Whisper 自动检测目标语言
        )

    segments = response.segments or []
    logger.info(f"[Whisper ASR] 识别到 {len(segments)} 个字幕段")

    if not segments:
        logger.warning("[Whisper ASR] 未识别到任何片段，SRT 将为空")
        Path(srt_path).write_text("", encoding="utf-8")
        return

    _write_srt_from_whisper(segments, srt_path)


def _write_srt_from_whisper(segments: list, output_path: str) -> None:
    """
    将 Whisper segments 写成标准 SRT 格式。
    每个 segment 一条字幕，一句话一行，时间戳精确到毫秒。
    """
    lines = []
    idx   = 1

    for seg in segments:
        text = getattr(seg, "text", "").strip()
        if not text:
            continue

        start = float(seg.start)
        end   = float(seg.end)
        if end <= start:
            end = start + 0.5   # 防止偶发的 start >= end

        lines.append(str(idx))
        lines.append(f"{_seconds_to_srt_time(start)} --> {_seconds_to_srt_time(end)}")
        lines.append(text)
        lines.append("")   # SRT 段间必须有空行
        idx += 1

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _seconds_to_srt_time(seconds: float) -> str:
    """秒数 → SRT 时间格式 HH:MM:SS,mmm"""
    ms = int((seconds % 1) * 1000)
    s  = int(seconds) % 60
    m  = int(seconds) // 60 % 60
    h  = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_transcript(segments: list[Segment], output_path: str) -> None:
    """生成原文 + 译文对照文稿"""
    lines = ["=" * 60, "视频翻译文稿（原文 + 译文对照）", "=" * 60, ""]
    for seg in segments:
        if not seg.original_text.strip():
            continue
        lines.append(f"#{seg.index + 1:03d}  [{seg.start:.1f}s → {seg.end:.1f}s]")
        lines.append(f"  原文：{seg.original_text}")
        lines.append(f"  译文：{seg.translated_text or '（未翻译）'}")
        lines.append("")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
