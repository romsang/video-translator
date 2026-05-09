/* global React, Card, Button, Select, Checkbox */
const { useState, useRef } = React;

const SUPPORTED_LANGUAGES = [
  'English', 'Japanese', 'Korean', 'Spanish', 'French',
  'German', 'Portuguese', 'Arabic', 'Russian', 'Thai',
];

function UploadPanel({ onRun, running, file, setFile }) {
  const [lang, setLang] = useState('English');
  const [lipsync, setLipsync] = useState(true);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);

  // 接收真实的 File 对象，同时保存元信息供 UI 展示
  function handleFile(f) {
    if (!f) return;
    setFile({ name: f.name, size: f.size, _raw: f });
  }

  return (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 20 }}>📤</span>
        <h6 style={{ fontFamily: 'var(--font-sans-cjk)', margin: 0, fontSize: 16 }}>输入设置</h6>
      </div>

      {/* drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault(); setDrag(false);
          const f = e.dataTransfer.files?.[0];
          if (f) handleFile(f);
        }}
        onClick={() => inputRef.current?.click()}
        style={{
          border: '1.5px dashed ' + (drag ? 'var(--accent)' : 'var(--ink-200)'),
          background: drag ? 'var(--accent-soft)' : (file ? 'var(--ink-50)' : 'var(--ink-50)'),
          borderRadius: 'var(--radius-lg)',
          padding: file ? '14px 16px' : '34px 18px',
          textAlign: 'center', cursor: 'pointer',
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
          transition: 'all var(--dur-base) var(--ease-out)',
        }}>
        {file ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, width: '100%' }}>
            <div style={{ width: 64, height: 36, background: 'var(--ink-1000)', borderRadius: 6, position: 'relative', overflow: 'hidden' }}>
              <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#FAF7F2', fontSize: 16 }}>🎬</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, textAlign: 'left' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--ink-900)' }}>{file.name}</span>
              <span style={{ fontSize: 11, color: 'var(--ink-500)' }}>{(file.size / 1024 / 1024).toFixed(1)} MB · 已就绪</span>
            </div>
            <button onClick={(e) => { e.stopPropagation(); setFile(null); }} style={{
              border: 'none', background: 'var(--ink-100)', borderRadius: 999,
              width: 28, height: 28, cursor: 'pointer', color: 'var(--ink-500)',
            }}>✕</button>
          </div>
        ) : (
          <>
            <span style={{ fontSize: 32 }}>{drag ? '🎬' : '📤'}</span>
            <span style={{ fontFamily: 'var(--font-sans-cjk)', fontSize: 14, fontWeight: 500, color: 'var(--ink-900)' }}>
              {drag ? '松开开始上传' : '上传中文视频'}
            </span>
            <span style={{ fontSize: 12, color: 'var(--ink-500)' }}>支持 mp4 / mov / avi · 最大 500 MB</span>
            <span style={{ fontSize: 11, color: 'var(--ink-300)', marginTop: 4 }}>点击选择文件，或拖拽到此处</span>
            <input
              ref={inputRef}
              type="file"
              accept="video/mp4,video/quicktime,video/x-msvideo,.mp4,.mov,.avi"
              style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />
          </>
        )}
      </div>

      <Select label="目标语言" value={lang} onChange={setLang} options={SUPPORTED_LANGUAGES}/>

      <Checkbox
        label="启用口型同步"
        checked={lipsync}
        onChange={setLipsync}
        hint="调用 Sync.so API（额外费用），仅处理含人脸片段"
      />

      <Button
        variant="primary"
        size="lg"
        disabled={!file || running}
        onClick={() => onRun({ lang, lipsync })}
      >
        🚀 {running ? '处理中…' : '开始翻译'}
      </Button>

      <div style={{
        background: 'var(--info-soft)',
        border: '1px solid #BFD3F2',
        borderRadius: 'var(--radius-md)',
        padding: '12px 14px',
        fontSize: 12, color: '#2A5996', lineHeight: 1.6,
      }}>
        <b style={{ display: 'block', marginBottom: 4 }}>ℹ 提示</b>
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          <li>处理时间约为视频时长的 2~4 倍</li>
          <li>请确保 <code style={{ background: 'rgba(63,125,201,0.12)', padding: '1px 5px', borderRadius: 3, fontFamily: 'var(--font-mono)', fontSize: 11 }}>config.yaml</code> 中已填入 API Keys</li>
          <li>口型同步只处理含人脸的画面</li>
        </ul>
      </div>
    </Card>
  );
}
window.UploadPanel = UploadPanel;
