/* global React, PIPELINE_STEPS */
const { useState, useEffect, useRef } = React;

// Per-step messages that stream into the log feed
const STEP_MESSAGES = {
  preprocess: [
    '提取视频音轨...',
    '探测时长 02:03 · 采样率 48000Hz',
    '运行 Demucs 人声分离...',
    '生成 reference_audio (8s)',
    '✅ 预处理完成',
  ],
  asr: [
    '调用 dashscope · qwen3-asr-flash',
    '上传音频 4.8 MB...',
    '识别中... 收到 12 段',
    '识别中... 收到 28 段',
    '识别中... 收到 47 段',
    '✅ ASR 完成 · 47 segments',
  ],
  translate: [
    '目标语言: English · 语速 2.5 词/秒',
    '分批 3 批 · BATCH_SIZE = 20',
    '🌐 批 1/3 · gpt-4o',
    '🌐 批 2/3 · gpt-4o',
    '⚠ 段 23 译文超长 (1.62×) · retry',
    '🌐 重试段 23...',
    '🌐 批 3/3 · gpt-4o',
    '✅ 翻译完成 · 47 segments',
  ],
  tts: [
    '调用 openai · tts-1-hd · voice=alloy',
    '🔊 合成 1/47...',
    '🔊 合成 24/47...',
    '段 12 时长比 1.18× · 加速对齐',
    '🔊 合成 47/47...',
    '✅ TTS 完成',
  ],
  lipsync: [
    '人脸检测 · OpenCV (conf 0.7)',
    '36/47 段含人脸',
    '👄 sync.so · sync-1.6.0',
    '👄 处理 12/36...',
    '👄 处理 36/36...',
    '✅ 口型同步完成',
  ],
  assemble: [
    '混音 · ffmpeg -filter_complex',
    '生成 SRT 字幕...',
    '生成 transcript.txt 对照文件',
    '封装 mp4 · libx264 + aac',
    '✅ 输出 ./outputs/{taskId}/output.mp4',
  ],
};

function formatElapsed(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function formatStamp(date) {
  const h = String(date.getHours()).padStart(2, '0');
  const m = String(date.getMinutes()).padStart(2, '0');
  const s = String(date.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function LiveStatus({ activeIndex, progress, completed, taskId }) {
  const [logs, setLogs] = useState([]);
  const [elapsed, setElapsed] = useState(0);
  const [pendingMsgs, setPendingMsgs] = useState([]);
  const startedAt = useRef(null);
  const logRef = useRef(null);
  const lastStepRef = useRef(null);

  // Reset when a new run starts
  useEffect(() => {
    if (activeIndex === 0 && lastStepRef.current === null) {
      startedAt.current = Date.now();
      setLogs([{ ts: new Date(), level: 'INFO', text: '🚀 流水线启动', accent: true }]);
    }
    if (activeIndex === -1 && !completed) {
      setLogs([]);
      setElapsed(0);
      startedAt.current = null;
      lastStepRef.current = null;
    }
  }, [activeIndex, completed]);

  // Tick elapsed timer
  useEffect(() => {
    if (activeIndex < 0 && !completed) return;
    const id = setInterval(() => {
      if (startedAt.current) setElapsed(Date.now() - startedAt.current);
    }, 200);
    return () => clearInterval(id);
  }, [activeIndex, completed]);

  // When step changes, queue its messages to stream
  useEffect(() => {
    if (activeIndex < 0) return;
    if (lastStepRef.current === activeIndex) return;
    lastStepRef.current = activeIndex;
    const step = PIPELINE_STEPS[activeIndex];
    const msgs = STEP_MESSAGES[step.key] || [];
    // header line
    setLogs((prev) => [...prev, {
      ts: new Date(), level: 'STEP',
      text: `${step.emoji} Step ${activeIndex + 1}: ${step.name}`,
      accent: true, stepKey: step.key,
    }]);
    setPendingMsgs(msgs.map((m) => ({ text: m, stepKey: step.key })));
  }, [activeIndex]);

  // Stream queued messages one-by-one
  useEffect(() => {
    if (pendingMsgs.length === 0) return;
    const next = pendingMsgs[0];
    const delay = 300 + Math.random() * 350;
    const id = setTimeout(() => {
      const isWarn = next.text.startsWith('⚠');
      const isOk = next.text.startsWith('✅');
      setLogs((prev) => [...prev, {
        ts: new Date(),
        level: isWarn ? 'WARN' : isOk ? 'OK' : 'INFO',
        text: next.text.replace('{taskId}', taskId),
        stepKey: next.stepKey,
      }]);
      setPendingMsgs((rest) => rest.slice(1));
    }, delay);
    return () => clearTimeout(id);
  }, [pendingMsgs, taskId]);

  // Final completion line
  useEffect(() => {
    if (completed && lastStepRef.current !== 'done') {
      lastStepRef.current = 'done';
      setLogs((prev) => [...prev, {
        ts: new Date(), level: 'OK',
        text: `✅ 完成 → ./outputs/${taskId}/output.mp4`,
        accent: true,
      }]);
    }
  }, [completed, taskId]);

  // Auto-scroll
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const idle = activeIndex < 0 && !completed;
  const currentStep = activeIndex >= 0 ? PIPELINE_STEPS[activeIndex] : null;
  const stepCount = PIPELINE_STEPS.length;

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      borderRadius: 'var(--radius-md)', overflow: 'hidden',
      border: '1px solid var(--ink-1000)',
      background: 'var(--ink-1000)',
    }}>
      {/* ── header strip with current status ────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '10px 14px',
        background: idle ? '#1f1a13' : completed ? '#143821' : currentStep ? `linear-gradient(90deg, ${stepBg(currentStep.key)} 0%, #1f1a13 60%)` : '#1f1a13',
        borderBottom: '1px solid rgba(250,247,242,0.08)',
        transition: 'background var(--dur-slow) var(--ease-out)',
        minHeight: 44,
      }}>
        {/* live dot */}
        <span style={{
          width: 8, height: 8, borderRadius: 999,
          background: idle ? '#7A7164' : completed ? '#6BCE93' : '#FFA679',
          boxShadow: idle ? 'none' : `0 0 0 0 ${completed ? 'rgba(107,206,147,0.55)' : 'rgba(255,166,121,0.55)'}`,
          animation: !idle && !completed ? 'vt-livedot 1.1s ease-out infinite' : 'none',
          flexShrink: 0,
        }}/>
        {/* current step */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          {idle ? (
            <>
              <span style={{ fontSize: 18 }}>💤</span>
              <span style={{ fontFamily: 'var(--font-sans-cjk)', fontSize: 13, color: '#B8AE9D' }}>等待任务</span>
            </>
          ) : completed ? (
            <>
              <span style={{ fontSize: 20 }}>✅</span>
              <span style={{ fontFamily: 'var(--font-sans-cjk)', fontSize: 13, color: '#FAF7F2', fontWeight: 500 }}>翻译完成</span>
            </>
          ) : currentStep ? (
            <>
              <span style={{ fontSize: 20 }}>{currentStep.emoji}</span>
              <span style={{ fontFamily: 'var(--font-sans-cjk)', fontSize: 13, color: '#FAF7F2', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                Step {activeIndex + 1}/{stepCount} · {currentStep.name}
              </span>
              {/* dotted progress sparkles */}
              <span className="vt-typing" style={{ color: '#FFA679', fontFamily: 'var(--font-mono)', fontSize: 12, marginLeft: 2 }}>
                <span/><span/><span/>
              </span>
            </>
          ) : null}
        </div>
        {/* meta on right */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontFamily: 'var(--font-mono)', fontSize: 11, color: '#B8AE9D' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>
            </svg>
            {formatElapsed(elapsed)}
          </span>
          <span style={{ color: '#7A7164' }}>·</span>
          <span>task <span style={{ color: '#FFA679' }}>{taskId}</span></span>
        </div>
      </div>

      {/* ── micro progress bar inside the panel ────── */}
      <div style={{ height: 2, background: 'rgba(250,247,242,0.08)' }}>
        <div style={{
          height: '100%', width: `${progress}%`,
          background: completed ? '#6BCE93' : '#E66A3D',
          transition: 'width var(--dur-slow) var(--ease-out)',
        }}/>
      </div>

      {/* ── live log feed ───────────────────────────── */}
      <div ref={logRef} style={{
        fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.65,
        color: '#E8E2D9',
        padding: '12px 14px',
        height: 200, overflow: 'auto',
        background: 'var(--ink-1000)',
      }}>
        {logs.length === 0 && (
          <span style={{ color: '#7A7164' }}>$ 等待启动 · click 🚀 开始翻译</span>
        )}
        {logs.map((l, i) => (
          <div key={i} className="vt-log-line" style={{
            display: 'flex', gap: 8, opacity: l.accent ? 1 : 0.92,
            paddingLeft: l.accent ? 0 : 12,
          }}>
            <span style={{ color: '#7A7164', flexShrink: 0 }}>[{formatStamp(l.ts)}]</span>
            <span style={{ color: levelColor(l.level), flexShrink: 0, width: 36 }}>{l.level}</span>
            <span style={{ color: l.accent ? '#FAF7F2' : '#D7CFC2' }}>
              {l.text.split(/(\b[a-f0-9]{8}\b|\.\/[\w/.\-]+)/).map((part, j) => {
                if (/^[a-f0-9]{8}$/.test(part)) return <span key={j} style={{ color: '#FFA679' }}>{part}</span>;
                if (/^\.\//.test(part)) return <span key={j} style={{ color: '#9DC8F5' }}>{part}</span>;
                return <span key={j}>{part}</span>;
              })}
            </span>
          </div>
        ))}
        {/* blinking caret while running */}
        {!idle && !completed && (
          <div style={{ display: 'flex', gap: 8, paddingLeft: 12, color: '#7A7164' }}>
            <span>›</span>
            <span className="vt-caret" style={{ display: 'inline-block', width: 7, height: 14, background: '#FFA679', verticalAlign: 'middle' }}/>
          </div>
        )}
      </div>
    </div>
  );
}

function stepBg(key) {
  return {
    preprocess: 'rgba(230,106,61,0.35)',
    asr:        'rgba(217,161,43,0.30)',
    translate:  'rgba(122,143,58,0.30)',
    tts:        'rgba(46,140,140,0.30)',
    lipsync:    'rgba(92,95,184,0.32)',
    assemble:   'rgba(142,74,138,0.32)',
  }[key] || 'rgba(255,255,255,0.05)';
}

function levelColor(level) {
  return {
    INFO: '#F0BC5B',
    OK:   '#6BCE93',
    WARN: '#FFA679',
    ERR:  '#F08A7E',
    STEP: '#FFA679',
  }[level] || '#B8AE9D';
}

window.LiveStatus = LiveStatus;
