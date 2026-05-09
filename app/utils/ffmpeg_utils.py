"""
ffmpeg_utils.py — FFmpeg 工具函数
封装所有 FFmpeg 命令调用，统一错误处理和日志
"""

import asyncio
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_ffmpeg(args: list[str], config: dict) -> None:
    """
    异步执行 FFmpeg 命令。
    args: ffmpeg 参数列表（不含 'ffmpeg' 本身）
    出错时抛出 RuntimeError 并附带 stderr 内容。
    """
    ffmpeg = config["paths"]["ffmpeg"]
    cmd = [ffmpeg, "-y"] + args   # -y：自动覆盖输出文件

    logger.debug(f"FFmpeg 命令: {' '.join(cmd)}")

    # 使用 asyncio subprocess 避免阻塞事件循环
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg 失败 (code {proc.returncode}):\n{stderr.decode('utf-8', errors='replace')}"
        )


async def extract_audio(video_path: str, audio_path: str, config: dict) -> None:
    """
    从视频中提取完整音频轨道。
    输出：16kHz 单声道 WAV（适合 ASR 模型输入）
    """
    await run_ffmpeg([
        "-i", video_path,
        "-vn",              # 不处理视频流
        "-acodec", "pcm_s16le",  # 16-bit PCM
        "-ar", "16000",     # 16kHz 采样率（ASR 标准）
        "-ac", "1",         # 单声道
        audio_path,
    ], config)
    logger.info(f"音频提取完成: {audio_path}")


async def extract_audio_segment(
    video_path: str, output_path: str,
    start: float, duration: float,
    config: dict
) -> None:
    """
    截取视频中指定时间段的音频。
    用于提取 TTS 参考音频（取视频前几秒人声）。
    """
    await run_ffmpeg([
        "-i", video_path,
        "-ss", str(start),       # 开始时间
        "-t",  str(duration),    # 持续时长
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "22050",          # 参考音频用稍高采样率
        "-ac", "1",
        output_path,
    ], config)


async def extract_video_segment(
    video_path: str, output_path: str,
    start: float, end: float,
    config: dict
) -> None:
    """
    截取视频片段（含画面，用于口型同步处理）。
    使用 -avoid_negative_ts 保证时间戳正确。
    """
    await run_ffmpeg([
        "-i", video_path,
        "-ss", str(start),
        "-to", str(end),
        "-c:v", "libx264",   # H.264 编码
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ], config)


async def replace_audio(
    video_path: str, audio_path: str,
    output_path: str, config: dict
) -> None:
    """
    将视频的音轨替换为指定音频（无口型同步时使用）。
    如果音频比视频短，视频会在音频结束时截断。
    """
    await run_ffmpeg([
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",          # 视频流直接复制，不重编码（快）
        "-map", "0:v:0",         # 取第一个输入的视频流
        "-map", "1:a:0",         # 取第二个输入的音频流
        "-shortest",             # 以最短流为准截断
        output_path,
    ], config)


async def speedup_audio(
    audio_path: str, output_path: str,
    ratio: float, config: dict
) -> None:
    """
    加速音频（atempo 滤镜）。
    ratio > 1.0 表示加速，例如 1.15 = 加速 15%。
    注意：atempo 滤镜范围是 0.5~2.0，超出需链式叠加。
    """
    # 单个 atempo 最大值为 2.0，这里限制在 1.5 以内避免链式
    clamped = min(ratio, 1.5)
    await run_ffmpeg([
        "-i", audio_path,
        "-filter:a", f"atempo={clamped:.4f}",
        output_path,
    ], config)
    logger.debug(f"音频加速 x{clamped:.2f}: {output_path}")


async def slowdown_video_segment(
    video_path: str, output_path: str,
    ratio: float, config: dict
) -> None:
    """
    拉伸（减速）视频片段以匹配更长的 TTS 音频。
    ratio > 1.0 表示拉伸，例如 1.25 = 拉长 25%。
    使用 setpts 拉伸画面，minterpolate 插帧保持流畅。
    """
    pts_factor = ratio  # setpts 的 PTS 倍数
    await run_ffmpeg([
        "-i", video_path,
        "-filter:v",
        f"setpts={pts_factor:.4f}*PTS,minterpolate=fps=25:mi_mode=blend",
        "-an",           # 先只处理视频，音频单独处理
        output_path,
    ], config)
    logger.debug(f"视频拉伸 x{pts_factor:.2f}: {output_path}")


async def burn_subtitles(
    video_path: str, srt_path: str,
    output_path: str, config: dict
) -> None:
    """
    将 SRT 字幕硬烧到视频画面上。
    使用 subtitles 滤镜（需要带 libass 的 FFmpeg）。
    字体样式：白色文字+黑色描边，位于画面底部。
    """
    import shutil, tempfile

    # 复制 SRT 到纯 ASCII 临时路径（避免中文路径问题）
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_srt = tmp_dir / "sub.srt"
    shutil.copy2(srt_path, tmp_srt)

    srt_filter = tmp_srt.as_posix()
    # FFmpeg subtitles filter 路径转义
    srt_filter = srt_filter.replace("\\", "\\\\").replace(":", "\\:").replace("[", "\\[").replace("]", "\\]")
    # force_style 中的逗号需要转义
    style = "FontSize=20\\,PrimaryColour=&Hffffff\\,OutlineColour=&H000000\\,Outline=2"
    try:
        await run_ffmpeg([
            "-i", video_path,
            "-vf",
            f"subtitles={srt_filter}:force_style={style}",
            "-c:a", "copy",
            output_path,
        ], config)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def concat_segments(
    segment_paths: list[str], output_path: str,
    config: dict
) -> None:
    """
    将多个视频片段按顺序拼接为完整视频。
    使用 concat 协议（文本列表方式），避免重编码画面质量损失。
    """
    # 创建临时拼接列表文件
    list_path = Path(output_path).parent / "concat_list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for seg in segment_paths:
            f.write(f"file '{Path(seg).resolve().as_posix()}'\n")

    await run_ffmpeg([
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",        # 直接复制，不重编码
        output_path,
    ], config)

    # 清理临时列表文件
    list_path.unlink(missing_ok=True)


async def get_audio_duration(audio_path: str, config: dict) -> float:
    """
    异步获取音频文件时长（秒）。
    供分段 ASR 等需要在协程中获取时长的场景使用。
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, get_video_duration, audio_path, config
    )


def get_video_duration(video_path: str, config: dict) -> float:
    """
    同步获取视频/音频时长（秒）。
    使用 ffprobe 读取 duration 元数据。
    """
    ffprobe = config["paths"]["ffprobe"]
    result = subprocess.run(
        [ffprobe, "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         video_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr}")
    return float(result.stdout.strip())
