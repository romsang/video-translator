"""
step1_preprocess.py — 音视频预处理
职责：
  1. 从视频中提取完整音频
  2. 用 Demucs 分离人声（去除背景音乐/噪声）→ 提升 ASR 准确率
  3. 截取前 10 秒人声作为 TTS 参考音频（用于声音风格参考）
"""

import logging
from pathlib import Path

import torch
import torchaudio
import demucs.separate

# 强制使用 soundfile 后端保存音频
# torchaudio 2.x 新版本默认尝试 torchcodec，在 macOS 上可能未安装
try:
    torchaudio.set_audio_backend("soundfile")
except Exception:
    pass  # 部分版本已弃用此方法，忽略即可

from app.models.schemas import TranslationTask
from app.utils.file_utils import get_task_workspace
from app.utils.ffmpeg_utils import extract_audio, extract_audio_segment

logger = logging.getLogger(__name__)

# Demucs 使用的模型名称
# htdemucs：高质量人声分离（推荐），mdx_extra：速度更快
DEMUCS_MODEL = "htdemucs"


async def preprocess(task: TranslationTask, config: dict) -> None:
    """
    Step 1 主函数：预处理视频，提取并分离人声。

    执行后填充：
      task.audio_path          ← 原始完整音频
      task.vocal_path          ← 人声音频（Demucs 分离）
      task.reference_audio_path ← 前 10 秒人声（TTS 参考）
    """
    workspace = get_task_workspace(task.task_id, config)
    video_path = task.input_video_path

    # ── 1. 提取原始音频 ───────────────────────────────────────
    raw_audio_path = str(workspace / "audio_raw.wav")
    logger.info(f"[{task.task_id}] 提取音频: {video_path}")
    await extract_audio(video_path, raw_audio_path, config)
    task.audio_path = raw_audio_path

    # ── 2. Demucs 人声分离 ────────────────────────────────────
    logger.info(f"[{task.task_id}] Demucs 人声分离（模型: {DEMUCS_MODEL}）")
    vocal_path = await _run_demucs(raw_audio_path, workspace, config)
    task.vocal_path = vocal_path
    logger.info(f"[{task.task_id}] 人声分离完成: {vocal_path}")

    # ── 3. 截取参考音频（取前 10 秒人声）────────────────────────
    # TTS 合成时可以用原始说话人声音作为风格参考
    ref_audio_path = str(workspace / "reference_audio.wav")
    await extract_audio_segment(
        video_path=vocal_path,
        output_path=ref_audio_path,
        start=0.0,
        duration=10.0,   # 10 秒足够 TTS 捕捉声音特征
        config=config,
    )
    task.reference_audio_path = ref_audio_path
    logger.info(f"[{task.task_id}] 参考音频已截取: {ref_audio_path}")


async def _run_demucs(
    audio_path: str,
    workspace: Path,
    config: dict,
) -> str:
    """
    调用 Demucs 进行人声/背景分离。

    Demucs 输出目录结构：
      <workspace>/demucs/<model>/<stem>/vocals.wav
      <workspace>/demucs/<model>/<stem>/drums.wav  （不需要，忽略）
      ...

    返回：vocals.wav 的路径
    """
    demucs_out_dir = workspace / "demucs"
    demucs_out_dir.mkdir(exist_ok=True)

    # 判断运行设备：M2 Mac 使用 MPS（Metal），无 GPU 退回 CPU
    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    logger.info(f"[Demucs] 使用设备: {device}")

    # Demucs 命令式 API 调用
    # -n: 模型名  --out: 输出目录  --two-stems: 只分离 vocals/other（更快）
    demucs.separate.main([
        "--two-stems", "vocals",   # 只分 人声 / 其他，不需要鼓/贝斯等
        "-n", DEMUCS_MODEL,
        "--out", str(demucs_out_dir),
        "--device", device,
        audio_path,
    ])

    # 找到输出的 vocals.wav
    # Demucs 输出路径：<out>/<model>/<input_stem>/vocals.wav
    stem = Path(audio_path).stem
    vocal_path = demucs_out_dir / DEMUCS_MODEL / stem / "vocals.wav"

    if not vocal_path.exists():
        # 如果 Demucs 失败，降级使用原始音频（不影响后续流程）
        logger.warning(f"[Demucs] 未找到 vocals.wav，使用原始音频: {audio_path}")
        return audio_path

    return str(vocal_path)
