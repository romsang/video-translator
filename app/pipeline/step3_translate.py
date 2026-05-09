"""
step3_translate.py — 约束时长翻译
使用 OpenAI 最强模型将中文字幕片段翻译为目标语言。

核心策略：
  - 告知模型每段原始时长，要求译文在该时间内可以讲完（时长约束）
  - 批量翻译（每次最多 20 段），减少 API 调用次数
  - 超长时自动重试，附加"缩短"指令
"""

import asyncio
import json
import logging
import math
import re

from openai import AsyncOpenAI

from app.models.schemas import TranslationTask, Segment

logger = logging.getLogger(__name__)

# 每批翻译的最大片段数（避免 prompt 过长，超出 token 限制）
BATCH_SIZE = 20


async def translate_segments(task: TranslationTask, config: dict) -> None:
    """
    Step 3 主函数：批量翻译所有字幕片段。

    执行后填充：
      segment.translated_text  ← 每段的译文
    """
    client = AsyncOpenAI(api_key=config["api_keys"]["openai"])
    model  = config["models"]["translate"]
    target = task.target_language
    rates  = config["translation"]["speaking_rates"]
    retries = config["translation"]["max_retries"]

    # 目标语言平均语速（词/秒），未配置的语言默认 2.5
    speaking_rate = rates.get(target, 2.5)

    # 分批处理，避免单次请求过大
    batches = _make_batches(task.segments, BATCH_SIZE)
    logger.info(
        f"[{task.task_id}] 翻译 {len(task.segments)} 段 → {target}，"
        f"共 {len(batches)} 批（语速: {speaking_rate} 词/秒）"
    )

    for batch_idx, batch in enumerate(batches):
        logger.info(f"[{task.task_id}] 翻译第 {batch_idx+1}/{len(batches)} 批")
        await _translate_batch(
            segments=batch,
            client=client,
            model=model,
            target=target,
            speaking_rate=speaking_rate,
            max_retries=retries,
            task_id=task.task_id,
        )
        # 批次间短暂暂停，避免触发速率限制
        if batch_idx < len(batches) - 1:
            await asyncio.sleep(0.3)

    logger.info(f"[{task.task_id}] 翻译完成")


async def _translate_batch(
    segments: list[Segment],
    client: AsyncOpenAI,
    model: str,
    target: str,
    speaking_rate: float,
    max_retries: int,
    task_id: str,
) -> None:
    """
    翻译一批片段（最多 BATCH_SIZE 段）。
    如果某段译文超长，单独对该段进行重试翻译。
    """
    # 第一次：批量翻译
    translations = await _call_translation_api(
        segments=segments,
        client=client,
        model=model,
        target=target,
        speaking_rate=speaking_rate,
        shorten_instruction="",    # 首次不添加额外缩短指令
    )

    # 填入结果，检查哪些片段超长需要重试
    needs_retry = []
    for seg, trans in zip(segments, translations):
        seg.translated_text = trans
        # 估算译文语音时长：词数 / 语速
        estimated_duration = _estimate_duration(trans, speaking_rate)
        if estimated_duration > seg.original_duration * 1.5 and max_retries > 0:
            # 超过原始时长 50% → 需要重新翻译
            needs_retry.append(seg)

    # 对超长片段逐一重试
    for seg in needs_retry:
        logger.info(
            f"[{task_id}] 片段 #{seg.index} 超长，重新翻译（原时长 {seg.original_duration:.1f}s）"
        )
        for attempt in range(max_retries):
            shorten_pct = 20 * (attempt + 1)  # 每次多缩短 20%
            retried = await _call_translation_api(
                segments=[seg],
                client=client,
                model=model,
                target=target,
                speaking_rate=speaking_rate,
                shorten_instruction=f"Please shorten by {shorten_pct}% compared to your previous translation.",
            )
            seg.translated_text = retried[0]
            estimated = _estimate_duration(retried[0], speaking_rate)
            if estimated <= seg.original_duration * 1.5:
                break   # 已满足要求，停止重试


async def _call_translation_api(
    segments: list[Segment],
    client: AsyncOpenAI,
    model: str,
    target: str,
    speaking_rate: float,
    shorten_instruction: str,
) -> list[str]:
    """
    调用 OpenAI API 进行翻译。

    Prompt 设计要点：
      1. 提供每段时长和对应的最大词数（时长约束）
      2. 要求保持语义，允许省略填充词/语气词
      3. 返回 JSON 数组，便于解析
    """
    # 构建带时长约束的输入列表
    input_list = []
    for seg in segments:
        max_words = math.floor(seg.original_duration * speaking_rate)
        input_list.append({
            "id": seg.index,
            "text": seg.original_text,
            "duration_seconds": round(seg.original_duration, 2),
            "max_words": max(max_words, 3),  # 最少 3 个词，避免过度压缩
        })

    system_prompt = f"""You are a professional subtitle translator specializing in video dubbing.
Translate the provided Chinese text segments into {target}.

CRITICAL CONSTRAINTS:
1. Each segment has a "duration_seconds" field — the translation MUST be speakable within that time
2. Each segment has a "max_words" field — do NOT exceed this word count
3. Preserve the original meaning; you may drop filler words to fit the time limit
4. Return ONLY a JSON array of translated strings, in the same order as input
5. Do NOT add explanations or extra text outside the JSON array
{shorten_instruction}

Example output format: ["translated text 1", "translated text 2", ...]"""

    user_prompt = f"Translate these {len(segments)} segments:\n{json.dumps(input_list, ensure_ascii=False)}"

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.3,         # 低随机性，翻译任务要准确
    )

    choice = response.choices[0]
    raw = choice.message.content
    logger.info(f"OpenAI finish_reason={choice.finish_reason}, content_len={len(raw) if raw else 0}")
    if not raw:
        # content 为空时重试一次（偶发问题）
        logger.warning("OpenAI 返回空内容，重试中...")
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
        )
        raw = response.choices[0].message.content
        if not raw:
            raise RuntimeError(f"OpenAI 两次均返回空内容，finish_reason={response.choices[0].finish_reason}")
    return _parse_translation_response(raw, len(segments))


def _parse_translation_response(raw: str, expected_count: int) -> list[str]:
    """
    解析翻译 API 返回的 JSON 字符串。
    兼容两种格式：
      - 直接数组：["a", "b", ...]
      - 包装对象：{"translations": ["a", "b", ...]}
    """
    try:
        # 去掉模型可能加的 markdown 代码块包裹
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        cleaned = m.group(1).strip() if m else raw.strip()
        # 去掉可能的前后多余文字，只保留 JSON 部分
        start = cleaned.find('[')
        end = cleaned.rfind(']')
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]
        data = json.loads(cleaned)
        if isinstance(data, list):
            translations = data
        elif isinstance(data, dict):
            # 尝试常见 key
            for key in ("translations", "results", "segments", "output"):
                if key in data and isinstance(data[key], list):
                    translations = data[key]
                    break
            else:
                # fallback: 取第一个 list 类型的值
                translations = next(
                    (v for v in data.values() if isinstance(v, list)), []
                )
        else:
            translations = []

        # 确保数量匹配
        if len(translations) != expected_count:
            logger.warning(
                f"翻译结果数量不匹配: 期望 {expected_count}，实际 {len(translations)}"
            )
            # 补齐或截断
            while len(translations) < expected_count:
                translations.append("")
            translations = translations[:expected_count]

        return [str(t) for t in translations]

    except json.JSONDecodeError as e:
        logger.error(f"翻译结果 JSON 解析失败: {e}\n原始内容: {raw[:200]}")
        # 兜底：返回空字符串列表，不中断流水线
        return [""] * expected_count


def _estimate_duration(text: str, speaking_rate: float) -> float:
    """
    估算一段文字的朗读时长（秒）。
    简单按空格分词，不同语言需要不同分词策略。
    """
    word_count = len(text.split())
    return word_count / speaking_rate if speaking_rate > 0 else 999


def _make_batches(segments: list[Segment], batch_size: int) -> list[list[Segment]]:
    """将 segments 列表切分为指定大小的批次"""
    return [segments[i:i+batch_size] for i in range(0, len(segments), batch_size)]
