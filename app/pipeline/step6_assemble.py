"""
step6_assemble.py — 最终合成输出

核心修复：
  - 保留原视频的所有片段（含语音段之间的静音/间隙）
  - 对每段语音用 TTS 音频替换；间隙段保留原始音轨
  - 对配音音轨重跑 whisper-1 ASR 生成精准 SRT 时间戳

输出产物：
  - output.mp4       ← 干净视频（不烧录字幕）
  - output.srt       ← 外挂 SRT（精准时间戳）
  - dubbed.mp3       ← 独立配音音轨
  - transcript.txt   ← 原文 + 译文对照
"""

import difflib
import logging
import re
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

    # ── 4. 提取 16kHz WAV 供 gpt-4o-transcribe ASR ───────
    dubbed_wav = str(workspace / "dubbed_for_asr.wav")
    await _extract_audio_wav_16k(final_video_path, dubbed_wav, config)

    # ── 5. whisper-1 → 精准时间戳 → SRT ─────────────────
    logger.info(f"[{task.task_id}] 对配音音轨重跑 whisper-1 ASR，生成精准时间戳...")
    srt_path = str(output_dir / "output.srt")
    await _generate_srt_via_openai(
        dubbed_wav=dubbed_wav,
        srt_path=srt_path,
        api_key=config["api_keys"]["openai"],
    )
    task.output_srt_path = srt_path
    logger.info(f"[{task.task_id}] SRT 已生成: {srt_path}")

    # ── 5b. SRT 词级纠错（用译文替换 Whisper 识别错误的词）──
    _correct_srt_with_translation(srt_path, task)

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
    max_gap_sec = getattr(task, "max_gap_sec", 2.0)   # 前端用户设置的最大间隔
    prev_end    = 0.0
    gap_idx     = 0

    for seg in task.segments:
        # ── 填充该语音段之前的间隙 ──────────────────────────
        gap_start = prev_end
        gap_end   = seg.start
        raw_gap   = gap_end - gap_start
        if raw_gap > 0.05:   # 超过 50ms 才提取，避免极短碎片
            # 超出 max_gap_sec 的部分直接丢弃，让节奏更紧凑
            capped_end = gap_start + min(raw_gap, max_gap_sec)
            gap_path = str(gaps_dir / f"gap_{gap_idx:04d}.mp4")
            await extract_video_segment(video_path, gap_path, gap_start, capped_end, config,
                                        mute_audio=True)  # 间隙静音，避免背景音与配音不匹配
            pieces.append(gap_path)
            gap_idx += 1
            if raw_gap > max_gap_sec:
                logger.debug(f"  间隙 [{gap_start:.2f}s → {gap_end:.2f}s] 截断至 {max_gap_sec}s（原 {raw_gap:.1f}s）")
            else:
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
        await extract_video_segment(video_path, tail_path, prev_end, total_dur, config,
                                    mute_audio=True)  # 尾部间隙同样静音
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
# gpt-4o-transcribe ASR → SRT
# ════════════════════════════════════════════════════════════

async def _generate_srt_via_openai(
    dubbed_wav: str,
    srt_path: str,
    api_key: str,
) -> None:
    """
    用 whisper-1 获取词级时间戳，按标点分组后生成精准分句 SRT。

    流程：
      1. verbose_json + timestamp_granularities=["word"] → 每个词的真实 start/end
      2. 按标点把词分组为子句（. ! ? 必断，, ; 达到字数阈值才断）
      3. 每个子句时间戳 = 第一个词 start → 最后一个词 end（基于实际语音，不是估算）
      4. 写入标准 SRT
    """
    file_size = Path(dubbed_wav).stat().st_size
    logger.info(f"[OpenAI ASR] 配音音轨大小: {file_size / 1024 / 1024:.1f} MB，模型: whisper-1（词级时间戳）")

    client = AsyncOpenAI(api_key=api_key)

    try:
        with open(dubbed_wav, "rb") as f:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment", "word"],  # segment 含标点，word 含精准时间戳
            )
    except Exception as e:
        logger.warning(f"[OpenAI ASR] 识别失败: {e}，SRT 将为空")
        Path(srt_path).write_text("", encoding="utf-8")
        return

    segments = getattr(response, "segments", None) or []
    words    = getattr(response, "words",    None) or []

    if not segments:
        logger.warning("[OpenAI ASR] 未获取到 segment，SRT 将为空")
        Path(srt_path).write_text("", encoding="utf-8")
        return

    logger.info(f"[OpenAI ASR] 获取到 {len(segments)} 个 segment，{len(words)} 个词级时间戳，按标点分句...")
    srt_content = _words_to_srt(segments, words)

    if not srt_content.strip():
        logger.warning("[OpenAI ASR] 分句结果为空")
    else:
        count = srt_content.count("\n\n") + 1
        logger.info(f"[OpenAI ASR] SRT 生成成功，共 {count} 条字幕")

    Path(srt_path).write_text(srt_content, encoding="utf-8")


def _words_to_srt(segments: list, words: list, min_clause_chars: int = 15) -> str:
    """
    用 segment 文本（含标点）+ word 时间戳（精准）生成分句 SRT。

    逻辑：
      1. 对每个 segment 的文本按标点拆分为子句
      2. 把该 segment 时间范围内的 words 按字符比例分配给各子句
      3. 每个子句时间戳 = 分配到的首词 start → 末词 end

    注意：Whisper-1 词级 token 不带标点，标点只在 segment.text 里，
          因此必须用 segment 提供断句依据，用 words 提供精准时间。
    """
    PRIMARY   = frozenset('.!?。！？…')
    SECONDARY = frozenset(',;，；')

    def _get(obj, attr, default=None):
        return getattr(obj, attr, None) if hasattr(obj, attr) else obj.get(attr, default)

    def _split_text(text: str) -> list[str]:
        """按标点把文本拆成子句列表"""
        clauses, buf, chars = [], [], 0
        for ch in text:
            buf.append(ch)
            chars += 1
            if ch in PRIMARY:
                clauses.append(''.join(buf).strip())
                buf, chars = [], 0
            elif ch in SECONDARY and chars >= min_clause_chars:
                clauses.append(''.join(buf).strip())
                buf, chars = [], 0
        if buf:
            tail = ''.join(buf).strip()
            if tail:
                clauses.append(tail)
        return [c for c in clauses if c]

    clauses: list[tuple[float, float, str]] = []

    for seg in segments:
        seg_start = float(_get(seg, 'start', 0))
        seg_end   = float(_get(seg, 'end',   seg_start))
        seg_text  = (_get(seg, 'text', '') or '').strip()

        if not seg_text:
            continue

        # 拿出属于本 segment 时间范围内的词
        seg_words = [
            w for w in words
            if float(_get(w, 'start', 0)) >= seg_start - 0.15
            and float(_get(w, 'end', 0))  <= seg_end   + 0.15
        ]

        sub_clauses = _split_text(seg_text)

        # 无法拆分 → 直接用 segment 时间戳
        if len(sub_clauses) <= 1:
            clauses.append((seg_start, seg_end, seg_text))
            continue

        # 没有词级数据 → 按字符比例在 segment 时间内估算
        if not seg_words:
            total_chars = sum(len(c) for c in sub_clauses)
            cur = seg_start
            for sub in sub_clauses:
                ratio   = len(sub) / total_chars if total_chars else 1 / len(sub_clauses)
                sub_end = cur + (seg_end - seg_start) * ratio
                clauses.append((round(cur, 3), round(sub_end, 3), sub))
                cur = sub_end
            continue

        # 按字符比例把 seg_words 分配给各子句，取首词 start / 末词 end
        total_chars = sum(len(c) for c in sub_clauses)
        word_idx    = 0
        n_words     = len(seg_words)
        for sub in sub_clauses:
            ratio    = len(sub) / total_chars if total_chars else 1 / len(sub_clauses)
            n_assign = max(1, round(n_words * ratio))
            assigned = seg_words[word_idx: word_idx + n_assign]
            word_idx = min(word_idx + n_assign, n_words)

            if not assigned:
                # 词已分配完但还有剩余子句：沿用上一个词的结束时间到 segment 结尾
                last_end = float(_get(seg_words[-1], 'end', seg_end)) if seg_words else seg_end
                clauses.append((last_end, seg_end, sub))
                continue

            sub_start = float(_get(assigned[0],  'start', seg_start))
            sub_end   = float(_get(assigned[-1], 'end',   seg_end))
            clauses.append((sub_start, sub_end, sub))

    # 写成标准 SRT
    lines = []
    for idx, (start, end, text) in enumerate(clauses, 1):
        lines.append(str(idx))
        lines.append(f"{_seconds_to_srt_time(start)} --> {_seconds_to_srt_time(end)}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


def _seconds_to_srt_time(seconds: float) -> str:
    """秒数 → SRT 时间格式 HH:MM:SS,mmm"""
    ms = int((seconds % 1) * 1000)
    s  = int(seconds) % 60
    m  = int(seconds) // 60 % 60
    h  = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ════════════════════════════════════════════════════════════
# SRT 词级纠错（用人工确认的译文替换 Whisper 识别错误的词）
# ════════════════════════════════════════════════════════════

def _correct_srt_with_translation(srt_path: str, task: TranslationTask) -> None:
    """
    策略：
      1. 取 Whisper SRT 末尾 5 词，在完整译文中定位截断点
      2. 截断点（Whisper 最后一词）本身及之后的译文不参与纠错
      3. 在纠错范围内做词序 diff，1:1 replace 用译文词替换，insert/delete 跳过
      4. 保留原词的首字母大写状态；保留原词的尾部标点
      5. 时间戳完全不动
    """
    srt_text = Path(srt_path).read_text(encoding="utf-8").strip()
    if not srt_text:
        return

    blocks = _parse_srt(srt_text)
    if not blocks:
        return

    # ── 构建完整译文 ──────────────────────────────────────────
    full_translation = " ".join(
        seg.translated_text.strip()
        for seg in task.segments
        if seg.translated_text and seg.translated_text.strip()
    )
    if not full_translation:
        return

    # ── 构建 Whisper 全文词表，记录每词的 (块索引, 块内词索引) ──
    # whisper_map[i] = (block_idx, word_in_block_idx, original_word_str)
    whisper_map: list[tuple[int, int, str]] = []
    for bi, (_, _, _, text) in enumerate(blocks):
        for wi, w in enumerate(text.split()):
            whisper_map.append((bi, wi, w))

    if not whisper_map:
        return

    # ── 定位截断点 ────────────────────────────────────────────
    ANCHOR = 5
    anchor_norm = [_norm(w) for _, _, w in whisper_map[-ANCHOR:]]
    trans_words = full_translation.split()
    trans_norm  = [_norm(w) for w in trans_words]

    cutoff = _find_anchor(anchor_norm, trans_norm)
    if cutoff is None:
        logger.warning("  [SRT纠错] 无法定位截断点，跳过纠错")
        return

    # cutoff = anchor 最后一词在 trans_words 中的索引（不含该词）
    trans_correction = trans_words[:cutoff]       # 译文纠错范围
    whisper_correction = whisper_map[:-1]         # Whisper 纠错范围（不含最后一词）

    trans_cn   = [_norm(w) for w in trans_correction]
    whisper_cn = [_norm(w) for _, _, w in whisper_correction]

    # ── 词序 diff ─────────────────────────────────────────────
    replacements: dict[tuple[int, int], str] = {}
    matcher = difflib.SequenceMatcher(None, whisper_cn, trans_cn, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        if (i2 - i1) != 1 or (j2 - j1) != 1:
            # 多词 replace（实为 insert/delete 混合），跳过
            continue

        bi, wi, old_word = whisper_correction[i1]
        new_core = trans_correction[j1]

        # 保留 Whisper 原词的尾部标点（逗号、句号等）
        trailing = re.search(r"[^\w]+$", old_word)
        if trailing:
            new_core = re.sub(r"[^\w]+$", "", new_core) + trailing.group()

        # 保留首字母大写状态
        if old_word[0].isupper() and new_core and new_core[0].islower():
            new_core = new_core[0].upper() + new_core[1:]

        replacements[(bi, wi)] = new_core
        logger.info(f"  [SRT纠错] 块#{bi+1} 词#{wi}: '{old_word}' → '{new_core}'")

    if not replacements:
        logger.info("  [SRT纠错] 无需替换，SRT 已准确")
        return

    # ── 写回 SRT ─────────────────────────────────────────────
    corrected: list[tuple] = []
    for bi, (idx, start_ts, end_ts, text) in enumerate(blocks):
        words = text.split()
        for wi in range(len(words)):
            if (bi, wi) in replacements:
                words[wi] = replacements[(bi, wi)]
        corrected.append((idx, start_ts, end_ts, " ".join(words)))

    Path(srt_path).write_text(_write_srt(corrected), encoding="utf-8")
    logger.info(f"  [SRT纠错] 完成，替换 {len(replacements)} 个词: {srt_path}")


def _norm(word: str) -> str:
    """去标点、转小写，用于词比较"""
    return re.sub(r"[^\w]", "", word, flags=re.UNICODE).lower()


def _find_anchor(anchor_norm: list[str], trans_norm: list[str]) -> int | None:
    """
    从右向左在 trans_norm 中找 anchor_norm 序列。
    返回 anchor 最后一词的索引（不含该词，即 cutoff = 该索引，
    调用方取 trans_words[:cutoff] 即排除最后一词）。
    允许 anchor 中有 1 个词不匹配（应对个别 Whisper 末尾误识别）。
    """
    n = len(anchor_norm)
    if n == 0 or len(trans_norm) < n:
        return None

    # 精确匹配（从右向左）
    for i in range(len(trans_norm) - n, -1, -1):
        if trans_norm[i:i + n] == anchor_norm:
            return i + n - 1  # 最后一词的索引（调用方 [:cutoff] 不含它）

    # 模糊匹配：允许 1 个词不同
    for i in range(len(trans_norm) - n, -1, -1):
        mismatches = sum(a != b for a, b in zip(anchor_norm, trans_norm[i:i + n]))
        if mismatches <= 1:
            return i + n - 1

    return None


def _parse_srt(content: str) -> list[tuple[int, str, str, str]]:
    """解析 SRT → [(index, start_ts, end_ts, text), ...]"""
    blocks = []
    for block in content.strip().split("\n\n"):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        ts = lines[1].split("-->")
        if len(ts) != 2:
            continue
        text = " ".join(lines[2:]).strip()
        blocks.append((idx, ts[0].strip(), ts[1].strip(), text))
    return blocks


def _write_srt(blocks: list[tuple]) -> str:
    """[(index, start_ts, end_ts, text), ...] → SRT 格式字符串"""
    parts = []
    for idx, start_ts, end_ts, text in blocks:
        parts.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")
    return "\n".join(parts)


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
