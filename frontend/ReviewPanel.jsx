/* global React, Card, Button, Pill */
const { useState, useMemo } = React;

// ── 各语言估算朗读速率（字符/秒）──────────────────────────────
const SPEAK_RATE = {
  zh:         4.5,
  English:    13,
  Japanese:   7,
  Korean:     5,
  Spanish:    14,
  French:     13,
  German:     12,
  Portuguese: 14,
  Arabic:     10,
  Russian:    10,
  Thai:       6,
};

function fmtSec(s) {
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const r = (s % 60).toFixed(0).padStart(2, '0');
  return `${m}:${r}`;
}

function fmtTime(s) {
  const m   = Math.floor(s / 60).toString().padStart(2, '0');
  const sec = (s % 60).toFixed(1).padStart(4, '0');
  return `${m}:${sec}`;
}

// ── 单条 ASR 片段行 ────────────────────────────────────────────
function ASRRow({ seg, onChange, readOnly }) {
  const chars      = seg.text.replace(/\s/g, '').length;
  const estTime    = chars / SPEAK_RATE['zh'];
  const origDur    = seg.end - seg.start;
  const ratio      = origDur > 0 ? estTime / origDur : 1;
  const ratioColor = ratio > 1.3 ? 'var(--danger)' : ratio > 1.05 ? '#D97706' : 'var(--success)';

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 8,
      padding: '12px 14px',
      background: readOnly ? 'var(--ink-50)' : 'var(--ink-0)',
      border: `1px solid ${readOnly ? 'var(--ink-100)' : 'var(--ink-150)'}`,
      borderRadius: 'var(--radius-md)',
      opacity: readOnly ? 0.85 : 1,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-400)',
          background: 'var(--ink-100)', padding: '2px 7px', borderRadius: 4, flexShrink: 0 }}>
          #{String(seg.index + 1).padStart(2, '0')}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-400)' }}>
          {fmtTime(seg.start)} → {fmtTime(seg.end)}
        </span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-500)' }}>
          原始 {fmtSec(origDur)}
        </span>
      </div>

      {readOnly ? (
        <div style={{
          padding: '8px 10px',
          fontFamily: 'var(--font-sans-cjk)', fontSize: 14, lineHeight: 1.6,
          color: 'var(--ink-700)',
        }}>
          {seg.text}
        </div>
      ) : (
        <textarea
          value={seg.text}
          onChange={(e) => onChange(seg.index, e.target.value)}
          rows={2}
          style={{
            width: '100%', boxSizing: 'border-box',
            fontFamily: 'var(--font-sans-cjk)', fontSize: 14, lineHeight: 1.6,
            padding: '8px 10px',
            background: 'var(--ink-50)', border: '1px solid var(--ink-200)',
            borderRadius: 'var(--radius-sm)', color: 'var(--ink-900)',
            resize: 'vertical', outline: 'none',
          }}
          onFocus={(e) => e.target.style.borderColor = 'var(--accent)'}
          onBlur={(e)  => e.target.style.borderColor = 'var(--ink-200)'}
        />
      )}

      <div style={{ display: 'flex', gap: 16, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ink-500)' }}>
        <span>{chars} 字</span>
        <span style={{ color: 'var(--ink-300)' }}>·</span>
        <span>预计朗读 <b style={{ color: 'var(--ink-700)' }}>{fmtSec(estTime)}</b></span>
        <span style={{ color: 'var(--ink-300)' }}>·</span>
        <span>时长比 <b style={{ color: ratioColor }}>{ratio.toFixed(2)}×</b></span>
      </div>
    </div>
  );
}

// ── 单条翻译对照行 ─────────────────────────────────────────────
function TranslationRow({ seg, targetLang, onChange, readOnly }) {
  const rate       = SPEAK_RATE[targetLang] || 12;
  const chars      = seg.translated.replace(/\s/g, '').length;
  const estTime    = chars / rate;
  const origDur    = seg.end - seg.start;
  const ratio      = origDur > 0 ? estTime / origDur : 1;
  const ratioColor = ratio > 1.3 ? 'var(--danger)' : ratio > 1.05 ? '#D97706' : 'var(--success)';

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 8,
      padding: '12px 14px',
      background: readOnly ? 'var(--ink-50)' : 'var(--ink-0)',
      border: `1px solid ${readOnly ? 'var(--ink-100)' : 'var(--ink-150)'}`,
      borderRadius: 'var(--radius-md)',
      opacity: readOnly ? 0.85 : 1,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-400)',
          background: 'var(--ink-100)', padding: '2px 7px', borderRadius: 4, flexShrink: 0 }}>
          #{String(seg.index + 1).padStart(2, '0')}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-400)' }}>
          {fmtTime(seg.start)} → {fmtTime(seg.end)}
        </span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-500)' }}>
          原始 {fmtSec(origDur)}
        </span>
      </div>

      {/* 原文只读 */}
      <div style={{
        padding: '7px 10px',
        background: 'var(--ink-100)', border: '1px solid var(--ink-150)',
        borderRadius: 'var(--radius-sm)',
        fontFamily: 'var(--font-sans-cjk)', fontSize: 13,
        color: 'var(--ink-600)', lineHeight: 1.6,
      }}>
        {seg.original}
      </div>

      {/* 译文：确认前可编辑，确认后只读 */}
      {readOnly ? (
        <div style={{
          padding: '8px 10px',
          fontFamily: 'var(--font-sans-latin)', fontSize: 14, lineHeight: 1.6,
          color: 'var(--ink-700)',
        }}>
          {seg.translated}
        </div>
      ) : (
        <textarea
          value={seg.translated}
          onChange={(e) => onChange(seg.index, e.target.value)}
          rows={2}
          style={{
            width: '100%', boxSizing: 'border-box',
            fontFamily: 'var(--font-sans-latin)', fontSize: 14, lineHeight: 1.6,
            padding: '8px 10px',
            background: 'var(--ink-50)', border: '1px solid var(--ink-200)',
            borderRadius: 'var(--radius-sm)', color: 'var(--ink-900)',
            resize: 'vertical', outline: 'none',
          }}
          onFocus={(e) => e.target.style.borderColor = 'var(--accent)'}
          onBlur={(e)  => e.target.style.borderColor = 'var(--ink-200)'}
        />
      )}

      <div style={{ display: 'flex', gap: 16, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ink-500)' }}>
        <span>{chars} chars</span>
        <span style={{ color: 'var(--ink-300)' }}>·</span>
        <span>预计朗读 <b style={{ color: 'var(--ink-700)' }}>{fmtSec(estTime)}</b></span>
        <span style={{ color: 'var(--ink-300)' }}>·</span>
        <span>时长比 <b style={{ color: ratioColor }}>{ratio.toFixed(2)}×</b></span>
      </div>
    </div>
  );
}

// ── 主组件 ─────────────────────────────────────────────────────
// confirmed=false → 可编辑 + 显示确认按钮
// confirmed=true  → 只读 + 显示"已确认"横幅，面板常驻不消失
function ReviewPanel({ mode, segments, targetLanguage, onConfirm, loading, confirmed }) {
  const isASR = mode === 'asr';

  const [rows, setRows] = useState(() =>
    segments.map((s) => ({
      index:      s.index,
      start:      s.start,
      end:        s.end,
      text:       s.original_text,
      original:   s.original_text,
      translated: s.translated_text || '',
    }))
  );

  const stats = useMemo(() => {
    const rate = isASR ? SPEAK_RATE['zh'] : (SPEAK_RATE[targetLanguage] || 12);
    let totalChars = 0, totalTime = 0;
    rows.forEach((r) => {
      const txt   = isASR ? r.text : r.translated;
      const chars = txt.replace(/\s/g, '').length;
      totalChars += chars;
      totalTime  += chars / rate;
    });
    return { totalChars, totalTime };
  }, [rows, isASR, targetLanguage]);

  function handleChange(index, value) {
    setRows((prev) =>
      prev.map((r) =>
        r.index === index
          ? isASR ? { ...r, text: value } : { ...r, translated: value }
          : r
      )
    );
  }

  function handleConfirm() {
    if (isASR) {
      onConfirm(rows.map((r) => ({ index: r.index, text: r.text })));
    } else {
      onConfirm(rows.map((r) => ({ index: r.index, translated_text: r.translated })));
    }
  }

  return (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 18, gridColumn: '1 / -1' }}>

      {/* ── 标题栏 ─────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 20 }}>{isASR ? '🎤' : '🌐'}</span>
          <h6 style={{ fontFamily: 'var(--font-sans-cjk)', margin: 0, fontSize: 16 }}>
            {isASR ? 'ASR 识别结果' : `翻译结果 · ${targetLanguage}`}
          </h6>
          {confirmed
            ? <Pill tone="success">✅ 已确认</Pill>
            : <Pill tone="running">⏸ 等待确认</Pill>
          }
        </div>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-500)' }}>
          {rows.length} 段
        </span>
      </div>

      {/* ── 已确认横幅 ────────────────────────────────── */}
      {confirmed && (
        <div style={{
          background: 'var(--success-soft)', border: '1px solid #BFE2CD',
          borderRadius: 'var(--radius-md)', padding: '10px 14px',
          color: '#1F6A40', fontSize: 13,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span>✅</span>
          <span>
            {isASR
              ? '识别结果已确认，已提交至翻译接口'
              : '译文已确认，已提交至 TTS 合成'}
          </span>
        </div>
      )}

      {/* ── 汇总统计 ──────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: 24,
        padding: '10px 14px',
        background: 'var(--ink-100)', borderRadius: 'var(--radius-md)',
        fontFamily: 'var(--font-mono)', fontSize: 12,
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ color: 'var(--ink-500)' }}>总字符</span>
          <span style={{ color: 'var(--ink-900)', fontWeight: 600, fontSize: 16 }}>
            {stats.totalChars.toLocaleString()}
          </span>
        </div>
        <div style={{ width: 1, background: 'var(--ink-200)' }}/>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ color: 'var(--ink-500)' }}>估算朗读时长</span>
          <span style={{ color: 'var(--ink-900)', fontWeight: 600, fontSize: 16 }}>
            {fmtSec(stats.totalTime)}
          </span>
        </div>
        <div style={{ width: 1, background: 'var(--ink-200)' }}/>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ color: 'var(--ink-500)' }}>{isASR ? '语速参考' : '目标语言语速'}</span>
          <span style={{ color: 'var(--ink-700)', fontSize: 13 }}>
            {isASR
              ? `${SPEAK_RATE['zh']} 字/秒（中文）`
              : `${SPEAK_RATE[targetLanguage] || 12} chars/s（${targetLanguage}）`}
          </span>
        </div>
      </div>

      {/* ── 片段列表 ───────────────────────────────────── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 520, overflowY: 'auto' }}>
        {rows.map((row) =>
          isASR
            ? <ASRRow         key={row.index} seg={row} readOnly={confirmed} onChange={handleChange} />
            : <TranslationRow key={row.index} seg={row} readOnly={confirmed} onChange={handleChange} targetLang={targetLanguage} />
        )}
      </div>

      {/* ── 确认按钮（已确认后隐藏）──────────────────── */}
      {!confirmed && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, paddingTop: 4 }}>
          <span style={{ fontSize: 12, color: 'var(--ink-400)', alignSelf: 'center' }}>
            {isASR ? '确认后将调用翻译接口' : '确认后将调用 TTS 合成'}
          </span>
          <Button variant="primary" size="lg" disabled={loading} onClick={handleConfirm}>
            {loading ? '提交中…' : `✅ 确认${isASR ? '识别结果' : '翻译结果'}`}
          </Button>
        </div>
      )}

    </Card>
  );
}

window.ReviewPanel = ReviewPanel;
