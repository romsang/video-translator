/* global React */
function Header() {
  return (
    <header style={{
      position: 'sticky', top: 0, zIndex: 10,
      background: 'rgba(250, 247, 242, 0.82)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      borderBottom: '1px solid var(--ink-150)',
    }}>
      <div style={{
        maxWidth: 1200, margin: '0 auto',
        padding: '14px 28px',
        display: 'flex', alignItems: 'center', gap: 16, justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <img src="../../assets/logo-mark.svg" alt="" width="36" height="36"/>
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.15 }}>
            <span style={{ fontFamily: 'var(--font-sans-cjk)', fontSize: 18, fontWeight: 700, color: 'var(--ink-900)' }}>视频翻译工具</span>
            <span style={{ fontSize: 12, color: 'var(--ink-500)' }}>Upload Chinese video · auto translate · subtitles · lip-sync</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <a href="#" style={{ fontSize: 13, color: 'var(--ink-700)', borderBottom: 'none' }}>📋 任务历史</a>
          <a href="#" style={{ fontSize: 13, color: 'var(--ink-700)', borderBottom: 'none' }}>📁 outputs/</a>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-500)',
            background: 'var(--ink-100)', padding: '4px 10px', borderRadius: 9999,
          }}>v1.0.0 · localhost:7860</span>
        </div>
      </div>
    </header>
  );
}
window.Header = Header;
