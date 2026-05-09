/* global React, Card, Button, Pill, PipelineStepper, PIPELINE_STEPS, LiveStatus */

const API = 'http://127.0.0.1:8000';

function OutputPanel({ activeIndex, confirmStep = -1, progress, completed, taskId, file, lang }) {
  const idle = activeIndex === -1 && !completed && confirmStep === -1;

  // 点击下载：通过 API 获取文件
  function download(type) {
    if (!taskId || !completed) return;
    const urls = {
      video:      `${API}/tasks/${taskId}/download/video`,
      srt:        `${API}/tasks/${taskId}/download/srt`,
      transcript: `${API}/tasks/${taskId}/download/transcript`,
    };
    const a = document.createElement('a');
    a.href = urls[type];
    a.download = type === 'video' ? 'output.mp4' : type === 'srt' ? 'output.srt' : 'transcript.txt';
    a.click();
  }

  return (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 20 }}>📥</span>
          <h6 style={{ fontFamily: 'var(--font-sans-cjk)', margin: 0, fontSize: 16 }}>处理结果</h6>
        </div>
        {idle      && <Pill tone="pending">等待上传视频</Pill>}
        {!idle && !completed && <Pill tone="running">{`Step ${activeIndex + 1} · ${PIPELINE_STEPS[activeIndex]?.name}`}</Pill>}
        {completed && <Pill tone="success">✅ 已完成</Pill>}
      </div>

      <PipelineStepper activeIndex={activeIndex} completed={completed} confirmStep={confirmStep}/>

      {/* live status + log feed */}
      <LiveStatus activeIndex={activeIndex} progress={progress} completed={completed} taskId={taskId}/>

      {/* progress bar (overall) */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
          <span style={{ color: 'var(--ink-500)' }}>总体进度</span>
          <span style={{ color: 'var(--ink-700)', fontFamily: 'var(--font-mono)' }}>{Math.round(progress)}%</span>
        </div>
        <div style={{ height: 8, background: 'var(--ink-100)', borderRadius: 999, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${progress}%`,
            background: 'var(--accent)', borderRadius: 999,
            transition: 'width var(--dur-slow) var(--ease-out)',
          }}/>
        </div>
      </div>

      {/* video player area */}
      <div style={{
        position: 'relative', aspectRatio: '16/9', borderRadius: 'var(--radius-md)',
        overflow: 'hidden', background: 'var(--ink-100)',
        border: '1px solid var(--ink-150)',
      }}>
        {completed ? (
          <>
            <img src="../../assets/placeholder-frame.svg" alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }}/>
            {/* video chrome */}
            <div style={{
              position: 'absolute', inset: 'auto 0 0 0',
              background: 'linear-gradient(180deg, transparent, rgba(22,18,13,0.78))',
              padding: '28px 16px 14px', color: '#FAF7F2',
              display: 'flex', flexDirection: 'column', gap: 8,
            }}>
              <div style={{ fontFamily: 'var(--font-sans-latin)', fontSize: 15, fontWeight: 500 }}>Hi everyone, welcome to this video.</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ width: 28, height: 28, borderRadius: 999, background: 'var(--accent)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 12 }}>▶</span>
                <div style={{ flex: 1, height: 3, background: 'rgba(250,247,242,0.25)', borderRadius: 999, overflow: 'hidden' }}>
                  <div style={{ width: '34%', height: '100%', background: 'var(--accent)' }}/>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>00:42 / 02:03</span>
              </div>
            </div>
          </>
        ) : (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8, color: 'var(--ink-300)' }}>
            <span style={{ fontSize: 32 }}>🎞️</span>
            <span style={{ fontSize: 13 }}>{idle ? '翻译完成后将在此显示' : '处理中…'}</span>
          </div>
        )}
      </div>

      {/* downloads */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
        {[
          { ico: '🎞️', name: 'output.mp4',     desc: 'translated video',  type: 'video' },
          { ico: '📝', name: 'output.srt',      desc: 'SRT subtitles',     type: 'srt' },
          { ico: '📄', name: 'transcript.txt',  desc: '原文 / 译文对照',    type: 'transcript' },
        ].map((f) => (
          <div key={f.name} style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: 10, borderRadius: 'var(--radius-md)',
            background: completed ? 'var(--ink-50)' : 'var(--ink-100)',
            border: '1px solid var(--ink-150)',
            opacity: completed ? 1 : 0.55,
          }}>
            <span style={{ fontSize: 18 }}>{f.ico}</span>
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
              <span style={{ fontSize: 10, color: 'var(--ink-500)' }}>{f.desc}</span>
            </div>
            <button
              disabled={!completed}
              onClick={() => download(f.type)}
              style={{
                border: 'none', background: 'transparent', cursor: completed ? 'pointer' : 'not-allowed',
                padding: 4, color: completed ? 'var(--accent)' : 'var(--ink-300)',
              }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </button>
          </div>
        ))}
      </div>

      {completed && (
        <div style={{
          background: 'var(--success-soft)', border: '1px solid #BFE2CD',
          borderRadius: 'var(--radius-md)', padding: '12px 14px',
          color: '#1F6A40', fontSize: 13, lineHeight: 1.6,
        }}>
          <b style={{ display: 'block', marginBottom: 4 }}>✅ 翻译完成</b>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#2D7A4E' }}>
            <div>task_id: <span style={{color:'#1F6A40', fontWeight: 500}}>{taskId}</span></div>
            <div>language: {lang}</div>
            <div>output_dir: ./outputs/{taskId}</div>
          </div>
        </div>
      )}
    </Card>
  );
}
window.OutputPanel = OutputPanel;
