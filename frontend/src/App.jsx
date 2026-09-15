import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive, Bot, CalendarDays, Check, ChevronRight, Clock3,
  Download, File, FileArchive, FileChartColumn, FileSpreadsheet, FileText,
  Folder, FolderOpen, HardDrive, LayoutDashboard, ListFilter, LoaderCircle,
  Menu, MessageSquareText, MoreHorizontal, Plus, Search, Send, Settings,
  ShieldCheck, Sparkles, Upload, Users, X,
} from 'lucide-react'

const navItems = [
  { id: 'library', label: '문서함', icon: FolderOpen },
  { id: 'ai', label: 'AI 통합검색', icon: Sparkles },
  { id: 'reports', label: '업무일지', icon: CalendarDays },
  { id: 'admin', label: '관리', icon: Settings },
]

const fileMeta = {
  pdf: { label: 'PDF', icon: FileText, color: 'red' },
  ppt: { label: 'PPT', icon: FileChartColumn, color: 'orange' },
  pptx: { label: 'PPTX', icon: FileChartColumn, color: 'orange' },
  xls: { label: 'XLS', icon: FileSpreadsheet, color: 'green' },
  xlsx: { label: 'XLSX', icon: FileSpreadsheet, color: 'green' },
  hwp: { label: 'HWP', icon: FileText, color: 'blue' },
  hwpx: { label: 'HWPX', icon: FileText, color: 'blue' },
  docx: { label: 'DOCX', icon: FileText, color: 'blue' },
}

const suggestedQuestions = [
  '지금까지 발견된 취약점을 날짜별로 정리해줘',
  '지난달 다이텍 관련 업무를 요약해줘',
  '8월 31일에 진행된 업무와 주요 일정은?',
]

function formatDate(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function extensionOf(item) {
  return item.source_type || item.original_filename?.split('.').pop()?.toLowerCase() || 'file'
}

function FileGlyph({ item, size = 'normal' }) {
  const meta = fileMeta[extensionOf(item)] || { label: 'FILE', icon: File, color: 'slate' }
  const Icon = meta.icon
  return <div className={`file-glyph ${meta.color} ${size}`}><Icon size={size === 'large' ? 26 : 19} /><span>{meta.label}</span></div>
}

function Status({ value }) {
  const status = {
    completed: ['처리 완료', 'success'], processing: ['분석 중', 'working'],
    uploaded: ['대기 중', 'waiting'], failed: ['처리 실패', 'failed'],
  }[value] || [value, 'waiting']
  return <span className={`status ${status[1]}`}><i />{status[0]}</span>
}

function EmptyState({ query }) {
  return <div className="empty-state"><FileArchive size={34} /><h3>문서를 찾지 못했습니다</h3><p>{query ? `'${query}'와 일치하는 문서가 없습니다.` : '새 문서를 업로드해 지식 문서함을 채워보세요.'}</p></div>
}

function Library({ reports, loading, query, setQuery, onSearch, onUpload, onOpen }) {
  const [type, setType] = useState('all')
  const filtered = type === 'all' ? reports : reports.filter((r) => extensionOf(r) === type)
  const completed = reports.filter((r) => r.status === 'completed').length
  const indexed = reports.filter((r) => r.status === 'completed' && r.index_status === 'indexed').length
  return <main className="page">
    <div className="page-heading">
      <div><p className="eyebrow">DOCUMENT LIBRARY</p><h1>사내 문서함</h1><p>흩어진 문서를 한곳에 모으고, 필요한 정보를 빠르게 찾아보세요.</p></div>
      <button className="primary" onClick={onUpload}><Upload size={18} />문서 업로드</button>
    </div>

    <section className="metrics">
      <div className="metric"><span className="metric-icon navy"><Folder size={21} /></span><div><p>전체 문서</p><strong>{reports.length}</strong><small>개의 문서</small></div></div>
      <div className="metric"><span className="metric-icon cyan"><Check size={21} /></span><div><p>문서 분석 완료</p><strong>{completed}</strong><small>개의 문서</small></div></div>
      <div className="metric"><span className="metric-icon violet"><Bot size={21} /></span><div><p>AI 검색 인덱싱</p><strong>{reports.length ? Math.round(indexed / reports.length * 100) : 0}%</strong><small>{indexed}개 검색 준비 완료</small></div></div>
    </section>

    <section className="content-card">
      <div className="toolbar">
        <form className="search-box" onSubmit={onSearch}><Search size={18} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="파일명, 내용, 작성자 검색" /><kbd>Enter</kbd></form>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="파일 형식"><option value="all">전체 형식</option><option value="pdf">PDF</option><option value="pptx">PPT</option><option value="xlsx">Excel</option><option value="hwp">한글</option></select>
        <button className="icon-button" title="필터"><ListFilter size={19} /></button>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>문서명</th><th>분류</th><th>작성자 / 부서</th><th>기준일</th><th>크기</th><th>상태</th><th></th></tr></thead>
          <tbody>{filtered.map((item) => <tr key={item.id} onClick={() => onOpen(item.id)}>
            <td><div className="document-name"><FileGlyph item={item} /><div><strong>{item.original_filename}</strong><span>업로드 {formatDate(item.created_at)}</span></div></div></td>
            <td><span className="category-pill">{item.source_type === 'pptx' || item.source_type === 'ppt' ? '업무일지' : '일반 문서'}</span></td>
            <td><div className="person"><strong>{item.author || '미지정'}</strong><span>{item.department || '부서 미지정'}</span></div></td>
            <td>{item.report_date || '-'}</td><td>{formatBytes(item.file_size)}</td><td><div className="status-stack"><Status value={item.status} />{item.status === 'completed' && item.index_status !== 'indexed' && <span className="index-wait">검색 {item.index_status === 'failed' ? '실패' : '준비 중'}</span>}</div></td>
            <td><button className="row-action" onClick={(e) => e.stopPropagation()}><MoreHorizontal size={18} /></button></td>
          </tr>)}</tbody>
        </table>
        {!loading && filtered.length === 0 && <EmptyState query={query} />}
        {loading && <div className="loading-row"><LoaderCircle className="spin" />문서를 불러오는 중입니다</div>}
      </div>
      <div className="card-footer"><span>총 {filtered.length}개 문서</span><span>최근 업로드 순</span></div>
    </section>
  </main>
}

function InlineAnswerText({ text }) {
  return <>{text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => part.startsWith('**') && part.endsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong> : part)}</>
}

function AnswerContent({ content }) {
  const blocks = []
  let list = []
  const flushList = () => { if (list.length) { blocks.push({ type: 'list', items: list }); list = [] } }
  const normalized = (content || '')
    .replace(/\\n/g, '\n')
    .replace(/\r/g, '')
    .replace(/\s+(?=(?:[-•▪]|\d+[.)])\s+)/g, '\n')
  for (const rawLine of normalized.split('\n')) {
    const line = rawLine.trim()
    if (!line) { flushList(); continue }
    const heading = line.match(/^#{1,3}\s+(.+)$/)
    const bullet = line.match(/^(?:[-*•▪]|\d+[.)])\s+(.+)$/)
    if (heading) { flushList(); blocks.push({ type: 'heading', text: heading[1] }); continue }
    if (bullet) { list.push(bullet[1]); continue }
    flushList()
    const previous = blocks.at(-1)
    if (previous?.type === 'paragraph') previous.text += ` ${line}`
    else blocks.push({ type: 'paragraph', text: line })
  }
  flushList()
  return <div className="answer-content">
    <div className="answer-label"><Sparkles size={14} />검색 결과</div>
    {blocks.map((block, index) => block.type === 'heading' ? <h3 key={index}><InlineAnswerText text={block.text} /></h3> : block.type === 'list' ? <ul key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}><InlineAnswerText text={item} /></li>)}</ul> : <p key={index}><InlineAnswerText text={block.text} /></p>)}
  </div>
}

function AiSearch({ onOpen }) {
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState([])
  const ask = async (question = query) => {
    const clean = question.trim(); if (!clean || busy) return
    setQuery(''); setBusy(true); setMessages((m) => [...m, { role: 'user', content: clean }])
    try {
      const response = await fetch('/api/ai/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: clean }) })
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || '검색에 실패했습니다.')
      setMessages((m) => [...m, { role: 'assistant', content: body.answer, sources: body.sources || [] }])
    } catch (error) { setMessages((m) => [...m, { role: 'assistant', error: true, content: error.message }]) }
    finally { setBusy(false) }
  }
  return <main className="page ai-page">
    <div className="page-heading"><div><p className="eyebrow">AI DOCUMENT SEARCH</p><h1>AI 통합검색</h1><p>사내 문서를 근거로 질문에 답하고, 필요한 내용을 정리합니다.</p></div><span className="secure-badge"><ShieldCheck size={16} />사내 데이터에서만 검색</span></div>
    <section className="chat-surface">
      {messages.length === 0 ? <div className="ai-welcome">
        <div className="ai-orb"><Sparkles size={28} /></div><h2>무엇을 찾아드릴까요?</h2><p>파일명이나 정확한 문구를 몰라도 괜찮습니다.<br />업무, 날짜, 사람을 자연스럽게 질문해 보세요.</p>
        <div className="suggestions">{suggestedQuestions.map((q) => <button key={q} onClick={() => ask(q)}><MessageSquareText size={16} />{q}<ChevronRight size={16} /></button>)}</div>
      </div> : <div className="messages">{messages.map((m, index) => <div className={`message ${m.role}`} key={index}>
        <div className="message-avatar">{m.role === 'user' ? '나' : <Sparkles size={17} />}</div><div className={`bubble ${m.error ? 'error' : ''}`}>{m.role === 'assistant' && !m.error ? <AnswerContent content={m.content} /> : <p>{m.content}</p>}
        {m.sources?.length > 0 && <div className="source-list"><span>참고한 문서 {m.sources.length}개</span>{m.sources.map((s) => <button key={s.id} onClick={() => onOpen(s.id)}><FileText size={15} /><div><strong>{s.filename}{s.page_number ? ` · ${s.page_number}페이지` : ''}</strong><small>{s.heading ? `${s.heading} — ` : ''}{s.snippet}</small></div><ChevronRight size={15} /></button>)}</div>}</div>
      </div>)}{busy && <div className="message assistant"><div className="message-avatar"><Sparkles size={17} /></div><div className="bubble thinking"><i /><i /><i />문서를 찾고 있습니다</div></div>}</div>}
      <div className="composer"><textarea value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }} placeholder="예: 올해 발견된 보안 취약점을 날짜별로 정리해줘" rows="1" /><button onClick={() => ask()} disabled={!query.trim() || busy} aria-label="질문 보내기"><Send size={19} /></button><p>근거 문서에서 확인되지 않는 내용은 답변하지 않습니다.</p></div>
    </section>
  </main>
}

function Reports({ reports, onOpen, onUpload }) {
  const batches = useMemo(() => reports.filter((r) => ['ppt', 'pptx'].includes(extensionOf(r))), [reports])
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">WEEKLY REPORTS</p><h1>업무일지</h1><p>기존 주간업무일지를 사람별·기간별로 모아봅니다.</p></div><button className="primary" onClick={onUpload}><Plus size={18} />업무일지 추가</button></div>
    <section className="report-grid">{batches.map((item) => <article className="report-card" key={item.id} onClick={() => onOpen(item.id)}><div className="report-card-top"><FileGlyph item={item} size="large" /><Status value={item.status} /></div><h3>{item.author || item.original_filename}</h3><p>{item.department || '부서 미지정'} · {item.report_date || '날짜 미지정'}</p><div className="report-divider" /><div className="report-stat"><span>파일</span><strong>{item.original_filename}</strong></div><button>상세 업무 보기<ChevronRight size={16} /></button></article>)}</section>
    {batches.length === 0 && <section className="content-card"><EmptyState /></section>}
  </main>
}

function Admin({ reports }) {
  const failed = reports.filter((r) => r.status === 'failed')
  const [system, setSystem] = useState(null); const [rebuilding, setRebuilding] = useState(false); const [notice, setNotice] = useState('')
  const refresh = () => fetch('/api/system/status').then((r) => r.json()).then(setSystem).catch(() => setSystem(null))
  useEffect(() => { refresh() }, [])
  const rebuild = async () => { setRebuilding(true); const response = await fetch('/api/index/rebuild', { method: 'POST' }); const body = await response.json(); setNotice(`${body.queued || 0}개 문서를 재색인 대기열에 등록했습니다.`); setRebuilding(false); setTimeout(refresh, 1200) }
  const ok = (part) => system?.[part]?.status === 'ok'
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">SYSTEM MANAGEMENT</p><h1>관리</h1><p>문서 처리 상태와 저장소 연결 상태를 확인합니다.</p></div><button className="primary" onClick={rebuild} disabled={rebuilding}>{rebuilding ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={18} />}전체 문서 재색인</button></div>
    {notice && <div className="admin-notice"><Check size={17} />{notice}</div>}
    <section className="admin-grid"><article className="admin-card"><span className="metric-icon cyan"><HardDrive size={21} /></span><h3>데이터베이스</h3><p>{system ? `${system.database.driver.toUpperCase()} 메타데이터 · 원본 파일 영구 저장소` : '연결 상태를 확인하고 있습니다.'}</p><div className={`health ${ok('database') ? '' : 'bad'}`}><i />{ok('database') ? '정상 연결' : '확인 중'}</div></article><article className="admin-card"><span className="metric-icon violet"><Bot size={21} /></span><h3>Ollama AI</h3><p>{system?.ollama?.models_ready ? '대화 모델과 한국어 임베딩 모델이 준비되었습니다.' : '설치된 AI 모델을 확인하고 있습니다.'}</p><div className={`health ${ok('ollama') ? '' : 'bad'}`}><i />{ok('ollama') ? '모델 서버 정상' : '연결 필요'}</div></article><article className="admin-card"><span className="metric-icon navy"><Archive size={21} /></span><h3>Qdrant 벡터 검색</h3><p>{system?.vector ? `${system.vector.mode === 'embedded' ? '로컬 영구 모드' : '서버 모드'} · ${system.vector.points || 0}개 청크 색인` : '벡터 저장소를 확인하고 있습니다.'}</p><div className={`health ${ok('vector') ? '' : 'bad'}`}><i />{ok('vector') ? '검색 엔진 정상' : '연결 필요'}</div></article></section>
    <section className="content-card admin-summary"><div><span>전체 문서</span><strong>{system?.counts?.documents ?? reports.length}</strong></div><div><span>검색 준비</span><strong>{system?.counts?.indexed ?? 0}</strong></div><div><span>문서 청크</span><strong>{system?.counts?.chunks ?? 0}</strong></div><div><span>처리 실패</span><strong>{system?.counts?.failed ?? failed.length}</strong></div></section>
  </main>
}

function UploadDialog({ open, onClose, onComplete }) {
  const inputRef = useRef(null); const [files, setFiles] = useState([]); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  if (!open) return null
  const choose = (list) => { setError(''); setFiles(Array.from(list).slice(0, 10)) }
  const upload = async () => {
    if (!files.length) return; setBusy(true); setError(''); const data = new FormData(); files.forEach((file) => data.append('files', file))
    try { const response = await fetch('/api/reports/batch', { method: 'POST', body: data }); const body = await response.json(); if (!response.ok) throw new Error(body.detail || '업로드하지 못했습니다.'); onComplete(body) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <div className="dialog-backdrop" onMouseDown={onClose}><div className="dialog" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true"><div className="dialog-head"><div><h2>문서 업로드</h2><p>최대 10개 파일을 한 번에 등록할 수 있습니다.</p></div><button className="icon-button" onClick={onClose}><X size={20} /></button></div>
    <div className="dropzone" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); choose(e.dataTransfer.files) }} onClick={() => inputRef.current?.click()}><input ref={inputRef} type="file" multiple hidden accept=".pdf,.ppt,.pptx,.hwp,.hwpx,.docx,.xls,.xlsx" onChange={(e) => choose(e.target.files)} /><span><Upload size={25} /></span><strong>파일을 끌어놓거나 클릭해서 선택</strong><p>PDF, PPT, 한글, Word, Excel · 파일당 최대 30MB</p></div>
    {files.length > 0 && <div className="selected-files">{files.map((file) => <div key={`${file.name}-${file.size}`}><FileText size={17} /><span>{file.name}</span><small>{formatBytes(file.size)}</small></div>)}</div>}{error && <p className="form-error">{error}</p>}
    <div className="dialog-actions"><button className="secondary" onClick={onClose}>취소</button><button className="primary" disabled={!files.length || busy} onClick={upload}>{busy ? <LoaderCircle className="spin" size={18} /> : <Upload size={18} />}{busy ? '업로드 중' : `${files.length || ''}개 문서 업로드`}</button></div>
  </div></div>
}

function summarySections(summary) {
  const sections = []; let current = { title: '문서 요약', items: [] }
  for (const raw of (summary || '').split('\n')) {
    const line = raw.trim(); if (!line) continue
    const heading = line.match(/^#{1,3}\s+(.+)$/)
    if (heading) { if (current.items.length) sections.push(current); current = { title: heading[1], items: [] }; continue }
    const item = line.match(/^(?:[-•▪]|\d+[.)])\s*(.+)$/)
    if (item) { current.items.push(item[1]); continue }
    if (current.items.length) current.items[current.items.length - 1] += ` ${line}`
    else current.items.push(line)
  }
  if (current.items.length) sections.push(current)
  return sections
}

function SummarySections({ summary }) {
  const sections = summarySections(summary)
  if (!sections.length) return <div className="summary-empty">문서 분석이 완료되면 요약이 표시됩니다.</div>
  const typeFor = (title) => title.includes('완료') ? ['done', Check] : title.includes('진행') ? ['progress', Clock3] : title.includes('일정') ? ['schedule', CalendarDays] : ['general', FileText]
  return <div className="summary-sections">{sections.map((section, index) => { const [type, Icon] = typeFor(section.title); return <article className={`summary-section ${type}`} key={`${section.title}-${index}`}><header><span><Icon size={15} /></span><h4>{section.title}</h4><small>{section.items.length}개 항목</small></header><ul>{section.items.map((entry, itemIndex) => <li key={itemIndex}>{entry}</li>)}</ul></article> })}</div>
}

function DetailDrawer({ id, onClose }) {
  const [item, setItem] = useState(null)
  useEffect(() => { if (id) fetch(`/api/reports/${id}`).then((r) => r.json()).then(setItem) }, [id])
  if (!id) return null
  return <div className="drawer-backdrop" onMouseDown={onClose}><aside className="drawer" onMouseDown={(e) => e.stopPropagation()}><div className="drawer-head"><span>문서 상세</span><button className="icon-button" onClick={onClose}><X size={20} /></button></div>{!item ? <div className="loading-row"><LoaderCircle className="spin" />불러오는 중</div> : <><div className="drawer-title"><FileGlyph item={item} size="large" /><div><h2>{item.original_filename}</h2><Status value={item.status} /></div></div><dl><div><dt>작성자</dt><dd>{item.author || '-'}</dd></div><div><dt>부서</dt><dd>{item.department || '-'}</dd></div><div><dt>기준일</dt><dd>{item.report_date || '-'}</dd></div><div><dt>파일 크기</dt><dd>{formatBytes(item.file_size)}</dd></div></dl><section className="detail-summary"><div className="detail-summary-head"><div><span>AI 분석 요약</span><small>문서에서 추출한 업무와 일정</small></div><span className="summary-badge">{item.index_status === 'indexed' ? '검색 준비 완료' : '분석 결과'}</span></div>{item.summary ? <SummarySections summary={item.summary} /> : item.status === 'failed' ? <div className="summary-empty error-text">{item.error_message}</div> : <div className="summary-empty">문서 분석이 완료되면 요약이 표시됩니다.</div>}</section><a className="download-button" href={`/api/reports/${id}/download`}><Download size={18} />원본 다운로드</a></>}</aside></div>
}

export default function App() {
  const [active, setActive] = useState('library'); const [mobileNav, setMobileNav] = useState(false)
  const [reports, setReports] = useState([]); const [loading, setLoading] = useState(true); const [query, setQuery] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false); const [detailId, setDetailId] = useState(null); const [toast, setToast] = useState('')
  const loadReports = async (keyword = '') => { setLoading(true); try { const response = await fetch(`/api/reports?limit=100${keyword ? `&keyword=${encodeURIComponent(keyword)}` : ''}`); setReports(await response.json()) } finally { setLoading(false) } }
  useEffect(() => { loadReports() }, [])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 3500); return () => clearTimeout(timer) }, [toast])
  const navigate = (id) => { setActive(id); setMobileNav(false) }
  useEffect(() => {
    const context = document.modelContext
    if (!context?.registerTool) return undefined
    const lifecycle = new AbortController()
    void Promise.resolve(context.registerTool({
      name: 'start_document_upload',
      title: '문서 업로드 열기',
      description: 'TEIN 문서함의 파일 선택 화면을 열어 사용자가 문서 업로드를 시작하게 합니다.',
      inputSchema: { type: 'object', properties: {}, additionalProperties: false },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute() {
        setActive('library')
        setUploadOpen(true)
        return { status: 'ready', message: '문서 업로드 화면을 열었습니다.' }
      },
    }, { signal: lifecycle.signal })).catch(() => {})
    return () => lifecycle.abort()
  }, [])
  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'open' : ''}`}><div className="brand"><img src="/tein-logo.png" alt="TEIN" /><span>SYSTEM</span></div><nav>{navItems.map(({ id, label, icon: Icon }) => <button className={active === id ? 'active' : ''} key={id} onClick={() => navigate(id)}><Icon size={19} />{label}{id === 'ai' && <span className="ai-tag">AI</span>}</button>)}</nav></aside>
    <div className="workspace"><header><button className="mobile-menu" onClick={() => setMobileNav((v) => !v)}><Menu /></button><div className="global-search" onClick={() => navigate('ai')}><Search size={18} /><span>문서와 사내 지식을 검색하세요</span><kbd>⌘ K</kbd></div><button className="header-upload" onClick={() => setUploadOpen(true)}><Plus size={18} />새 문서</button></header>
      {active === 'library' && <Library reports={reports} loading={loading} query={query} setQuery={setQuery} onSearch={(e) => { e.preventDefault(); loadReports(query) }} onUpload={() => setUploadOpen(true)} onOpen={setDetailId} />}
      {active === 'ai' && <AiSearch onOpen={setDetailId} />}{active === 'reports' && <Reports reports={reports} onOpen={setDetailId} onUpload={() => setUploadOpen(true)} />}{active === 'admin' && <Admin reports={reports} />}
    </div>
    <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onComplete={(body) => { setUploadOpen(false); setToast(`${body.reports.length}개 문서 업로드를 시작했습니다.`); loadReports() }} />
    <DetailDrawer id={detailId} onClose={() => setDetailId(null)} />{toast && <div className="toast"><Check size={18} />{toast}</div>}
  </div>
}
