/* global React */
const PIPELINE_STEPS = [
  { num: '01', emoji: '🎬', name: '预处理',   key: 'preprocess' },
  { num: '02', emoji: '🎤', name: 'ASR',      key: 'asr' },
  { num: '03', emoji: '🌐', name: '翻译',     key: 'translate' },
  { num: '04', emoji: '🔊', name: 'TTS',      key: 'tts' },
  { num: '05', emoji: '👄', name: '口型同步', key: 'lipsync' },
  { num: '06', emoji: '🎞️', name: '合成',     key: 'assemble' },
];

// confirmStep: 正在等待人工确认的步骤序号（0-based）
// activeIndex: 正在执行的步骤序号（-1 = idle）
function PipelineStepper({ activeIndex = -1, completed = false, confirmStep = -1 }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, padding: '4px 0' }}>
      {PIPELINE_STEPS.map((s, i) => {
        const isDone      = completed || i < activeIndex || (confirmStep > -1 && i < confirmStep);
        const isActive    = !completed && i === activeIndex;
        const isConfirm   = !completed && i === confirmStep && activeIndex === -1;

        const badgeBg = isActive   ? 'var(--accent)'
                      : isConfirm  ? 'var(--accent-soft)'
                      : isDone     ? 'var(--ink-100)'
                      :              'var(--ink-50)';

        const badgeBorder = isActive   ? 'var(--accent)'
                          : isConfirm  ? 'var(--accent)'
                          : isDone     ? 'var(--ink-200)'
                          :              'var(--ink-150)';

        const labelColor  = isActive || isConfirm ? 'var(--accent-press)'
                          : isDone                ? 'var(--ink-700)'
                          :                         'var(--ink-300)';

        const icon = isDone    ? '✅'
                   : isConfirm ? '✍️'
                   :              s.emoji;

        return (
          <React.Fragment key={s.key}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-300)' }}>{s.num}</span>
              <div style={{
                width: 40, height: 40, borderRadius: 999,
                background: badgeBg, border: `1.5px solid ${badgeBorder}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 20,
                boxShadow: (isActive || isConfirm) ? '0 0 0 6px var(--accent-ring)' : 'none',
                animation: isActive  ? 'vt-breathe 1.4s ease-in-out infinite'
                         : isConfirm ? 'vt-breathe 2.2s ease-in-out infinite'
                         :              'none',
                transition: 'background var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out)',
              }}>
                {icon}
              </div>
              <span style={{
                fontFamily: 'var(--font-sans-cjk)', fontSize: 11,
                fontWeight: (isActive || isConfirm) ? 600 : 500,
                color: labelColor,
              }}>
                {isConfirm ? '待确认' : s.name}
              </span>
            </div>
            {i < PIPELINE_STEPS.length - 1 && (
              <div style={{
                flex: '0 0 18px', height: 2, marginTop: 28,
                background: (i < activeIndex || completed || (confirmStep > -1 && i < confirmStep))
                  ? 'var(--accent)' : 'var(--ink-150)',
                transition: 'background var(--dur-base) var(--ease-out)',
              }}/>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}
Object.assign(window, { PipelineStepper, PIPELINE_STEPS });
