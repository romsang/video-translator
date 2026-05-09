"""
step2_asr.py — 语音识别（ASR）
使用阿里云 Qwen3-ASR-Flash API 将中文人声音频转换为带时间戳的文字片段。

关键说明：
  Transcription.async_call 需要公网可访问的 file_urls，不支持本地路径。
  使用 Recognition.call（paraformer-realtime-v2）直接读取本地文件，
  并将音频预处理为 16kHz 单声道 WAV 以确保兼容性。
"""

import logging
import subprocess
from pathlib import Path

from app.models.schemas import TranslationTask, Segment
from app.utils.file_utils import get_task_workspace

logger = logging.getLogger(__name__)


async def run_asr(task: TranslationTask, config: dict) -> None:
    """
    Step 2 主函数：调用 Qwen3-ASR-Flash 识别人声音频。

    执行后填充：
      task.segments  ← 带原文、开始/结束时间的片段列表
    """
    import dashscope
    from dashscope.audio.asr import Recognition, RecognitionCallback

    api_key   = config["api_keys"]["dashscope"]
    workspace = get_task_workspace(task.task_id, config)

    dashscope.api_key = api_key

    # 使用 Demucs 分离后的人声（更准），否则用原始音频
    audio_path = Path(task.vocal_path or task.audio_path).resolve()
    logger.info(f"[{task.task_id}] ASR 输入: {audio_path}")

    # ── 转换为 16kHz 单声道 WAV（Recognition 要求）────────────────
    converted_path = workspace / "asr_input.wav"
    _convert_to_16k_mono(audio_path, converted_path)
    logger.info(f"[{task.task_id}] 已转换为 16kHz 单声道: {converted_path}")

    # ── 调用 DashScope ASR（Recognition，支持本地文件）─────────────
    callback = RecognitionCallback()
    rec = Recognition(
        model="paraformer-realtime-v2",
        callback=callback,
        format="wav",
        sample_rate=16000,
    )
    result = rec.call(str(converted_path))

    if result.status_code != 200:
        raise RuntimeError(f"ASR 失败: {result.message}")

    # 直接从返回值获取句子（on_event 回调不一定会触发）
    all_sentences = result.get_sentence() or []

    if not all_sentences:
        raise RuntimeError("ASR 失败: 未返回识别结果")

    # ── 解析结果 ─────────────────────────────────────────────────
    raw_segments = _parse_sentences(all_sentences)

    # ── 转换为内部 Segment 格式 ───────────────────────────────────
    segments = []
    for i, seg in enumerate(raw_segments):
        text = seg["text"].strip()
        if not text:
            continue
        segments.append(Segment(
            index=i,
            start=seg["start"],
            end=seg["end"],
            original_text=text,
        ))

    task.segments = segments
    logger.info(f"[{task.task_id}] ASR 完成，共 {len(segments)} 个片段")

    # ── 保存原始转录文本（调试用）──────────────────────────────────
    transcript_path = workspace / "transcript_original.txt"
    with open(transcript_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"[{seg.start:.2f} --> {seg.end:.2f}] {seg.original_text}\n")


def _convert_to_16k_mono(src: Path, dst: Path) -> None:
    """用 ffmpeg 将音频转为 16kHz 单声道 WAV"""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
        str(dst),
    ], capture_output=True, check=True)


def _parse_sentences(sentences: list) -> list[dict]:
    """
    解析 Recognition 回调收集到的句子列表，提取时间戳和文本。

    每个句子格式：
      {"begin_time": 100, "end_time": 2300, "text": "你好", ...}
    begin_time / end_time 单位：毫秒 → 转换为秒
    """
    segments = []
    try:
        for sentence in sentences:
            text = sentence.get("text", "").strip()
            if not text:
                continue
            segments.append({
                "start": sentence["begin_time"] / 1000.0,
                "end":   sentence["end_time"]   / 1000.0,
                "text":  text,
            })
    except Exception as e:
        logger.error(f"解析 ASR 结果失败: {e}")
        raise

    return segments
