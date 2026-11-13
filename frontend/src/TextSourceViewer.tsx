import { useEffect, useRef, useState, useMemo } from 'react';
import type { FormEvent } from 'react';
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  Code,
  Copy,
  Download,
  Eye,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Maximize2,
  Music,
  RotateCcw,
  Search,
  Table as TableIcon,
  Video as VideoIcon,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { locationLabel } from './sourceTypes';
import { highlightSpan } from './textHighlight';
import type { LocatedSource } from './sourceTypes';

type API = (path: string, method?: string, body?: unknown) => Promise<Response>;
type Unit = LocatedSource & { page_number: number; text?: string; warnings?: string[] };
type Hit = LocatedSource & { page_number: number; chunk_id: number; passage: string; source_sha256?: string };
type Props = {
  data: {
    doc: LocatedSource & { id: string; title: string; filename: string; folder_name: string; sha256?: string };
    page: number;
    hit?: Hit;
  };
  api: API;
  onClose: () => void;
  onRecover: () => void;
  onReadingPage: (page: number) => Promise<void>;
  onReadingError: (message: string) => void;
};

// Simple, fast syntax highlighter for code
function highlightCode(raw: string) {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Comments
    .replace(/(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)/g, '<span class="tok-comm">$1</span>')
    // Strings
    .replace(/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)/g, '<span class="tok-str">$1</span>')
    // Keywords
    .replace(
      /\b(def|class|return|if|else|elif|for|while|import|from|as|try|except|finally|async|await|const|let|var|function|type|interface|select|from|where|insert|delete|update|public|private)\b/g,
      '<span class="tok-kw">$1</span>'
    )
    // Numbers
    .replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="tok-num">$1</span>');
}

// Lightweight Markdown to HTML formatter
function parseMarkdownToHtml(md: string) {
  let html = md
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Headings
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
  html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');

  // Blockquotes
  html = html.replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>');

  // Code blocks
  html = html.replace(/```([a-z0-9_-]*)\n([\s\S]*?)```/gim, '<pre><code>$2</code></pre>');

  // Inline code
  html = html.replace(/`([^`]+)`/gim, '<code>$1</code>');

  // Bold & Italic
  html = html.replace(/\*\*([^*]+)\*\*/gim, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/gim, '<em>$1</em>');

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/gim, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');

  // Horizontal rules
  html = html.replace(/^---$/gim, '<hr/>');

  // Paragraphs
  html = html
    .split(/\n\n+/)
    .map(p => {
      const trimmed = p.trim();
      if (!trimmed) return '';
      if (/^<(?:h[1-6]|pre|blockquote|hr|ul|ol|table)/i.test(trimmed)) return trimmed;
      return `<p>${trimmed.replace(/\n/g, '<br/>')}</p>`;
    })
    .join('\n');

  return html;
}

// Simple CSV / TSV parser
function parseDelimited(text: string, sep: string) {
  const lines = text.split(/\r?\n/).filter(l => l.trim().length > 0);
  const rows: string[][] = [];
  for (const line of lines) {
    const row: string[] = [];
    let cur = '', inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') {
        inQuotes = !inQuotes;
      } else if (c === sep && !inQuotes) {
        row.push(cur.trim());
        cur = '';
      } else {
        cur += c;
      }
    }
    row.push(cur.trim());
    rows.push(row);
  }
  return rows;
}

export default function TextSourceViewer({
  data,
  api,
  onClose,
  onRecover,
  onReadingPage,
  onReadingError,
}: Props) {
  const revision = data.hit?.source_sha256 || data.doc.sha256 || '';
  const frame = useRef<HTMLDivElement>(null);
  const request = useRef(0);
  const codeHitRef = useRef<HTMLTableRowElement>(null);

  const [units, setUnits] = useState<Unit[]>([]);
  const [number, setNumber] = useState(data.page);
  const [unit, setUnit] = useState<Unit | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [searching, setSearching] = useState(false);
  const [note, setNote] = useState('');
  const [activeHit, setActiveHit] = useState<Hit | undefined>(data.hit);

  // Everything Viewer Format Detection
  const ext = useMemo(() => {
    return (data.doc.filename.split('.').pop() || '').toLowerCase();
  }, [data.doc.filename]);

  const isMarkdown = useMemo(() => ['md', 'markdown'].includes(ext), [ext]);
  const isCode = useMemo(() => {
    return [
      'py', 'js', 'ts', 'tsx', 'jsx', 'json', 'jsonl', 'yaml', 'yml',
      'html', 'css', 'sql', 'sh', 'ps1', 'bat', 'cmd', 'env', 'log',
      'c', 'cpp', 'h', 'rs', 'go', 'java', 'xml'
    ].includes(ext);
  }, [ext]);
  const isTable = useMemo(() => ['csv', 'tsv'].includes(ext), [ext]);
  const isImage = useMemo(() => ['png', 'jpg', 'jpeg', 'webp', 'svg', 'gif', 'bmp', 'ico'].includes(ext), [ext]);
  const isVideo = useMemo(() => ['mp4', 'webm', 'mov', 'mkv'].includes(ext), [ext]);
  const isAudio = useMemo(() => ['mp3', 'wav', 'm4a', 'ogg', 'flac'].includes(ext), [ext]);
  const isMedia = isVideo || isAudio;

  // View Mode: 'rich' or 'raw'
  const defaultMode = (isMarkdown || isCode || isTable || isImage || isMedia) ? 'rich' : 'raw';
  const [viewMode, setViewMode] = useState<'rich' | 'raw'>(defaultMode);

  // Table filter
  const [tableFilter, setTableFilter] = useState('');

  // Image controls
  const [zoom, setZoom] = useState(1);
  const [imgDims, setImgDims] = useState<{ w: number; h: number } | null>(null);

  // Code copy feedback
  const [copied, setCopied] = useState(false);

  // Direct file URL
  const fileUrl = `/api/documents/${data.doc.id}/file`;
  const downloadUrl = `/api/documents/${data.doc.id}/file?download=true`;

  const latest = useRef(number);
  const persist = useRef(onReadingPage);
  const report = useRef(onReadingError);
  latest.current = number;
  persist.current = onReadingPage;
  report.current = onReadingError;

  useEffect(() => {
    const timer = setTimeout(() => {
      void persist.current(latest.current).catch(e => report.current((e as Error).message));
    }, 700);
    return () => clearTimeout(timer);
  }, [number]);

  useEffect(() => () => {
    void persist.current(latest.current).catch(e => report.current((e as Error).message));
  }, []);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    frame.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => previous?.focus();
  }, []);

  useEffect(() => {
    let active = true;
    void api(`/documents/${data.doc.id}`)
      .then(r => r.json())
      .then(r => {
        if (active) setUnits(r.pages || []);
      })
      .catch(e => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [data.doc.id]);

  useEffect(() => {
    const current = ++request.current;
    setLoading(true);
    setError('');
    setUnit(null);
    void api(`/documents/${data.doc.id}/units/${number}?revision=${encodeURIComponent(revision)}`)
      .then(r => r.json())
      .then(value => {
        if (current === request.current) setUnit(value);
      })
      .catch(e => {
        if (current === request.current) setError(e.message);
      })
      .finally(() => {
        if (current === request.current) setLoading(false);
      });
    return () => {
      request.current++;
    };
  }, [data.doc.id, number, revision]);

  // Scroll to active hit in code view
  useEffect(() => {
    if (viewMode === 'rich' && isCode && codeHitRef.current) {
      codeHitRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [viewMode, isCode, activeHit, unit]);

  const evidence =
    unit &&
    activeHit &&
    (activeHit.unit_number ?? activeHit.page_number) === number &&
    activeHit.source_sha256 === revision
      ? highlightSpan(unit.text || '', activeHit.passage)
      : null;

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setNote('');
    try {
      const response = await (
        await api('/search', 'POST', { query, document_id: data.doc.id, content_only: true })
      ).json();
      setHits(response.results);
      setNote(response.results.length ? 'Matching source sections' : 'No strong source match in this document.');
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setSearching(false);
    }
  }

  function copyCode() {
    if (!unit?.text) return;
    navigator.clipboard.writeText(unit.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // Parse lines for code view
  const codeLines = useMemo(() => {
    if (!unit?.text) return [];
    return unit.text.split(/\r?\n/);
  }, [unit?.text]);

  // Parse table rows for CSV/TSV view
  const tableData = useMemo(() => {
    if (!unit?.text || !isTable) return { headers: [], rows: [] };
    const sep = ext === 'tsv' ? '\t' : ',';
    const parsed = parseDelimited(unit.text, sep);
    if (!parsed.length) return { headers: [], rows: [] };
    const headers = parsed[0];
    const rows = parsed.slice(1);
    const filtered = tableFilter.trim()
      ? rows.filter(r => r.some(cell => cell.toLowerCase().includes(tableFilter.toLowerCase())))
      : rows;
    return { headers, rows: filtered, totalCount: rows.length };
  }, [unit?.text, isTable, ext, tableFilter]);

  return (
    <div
      ref={frame}
      className="viewer-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`Document viewer: ${data.doc.filename}`}
      onKeyDown={e => {
        if (e.key !== 'Tab') return;
        const controls = frame.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,select');
        if (!controls?.length) return;
        const first = controls[0],
          last = controls[controls.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }}
    >
      <header className="viewer-header">
        <button className="button secondary small" onClick={onClose}>
          <ArrowLeft size={14} /> Back
        </button>
        <div>
          <strong>{data.doc.title}</strong>
          <small>
            {data.doc.folder_name} · {data.doc.filename}
          </small>
        </div>
        <a className="button secondary small" href={downloadUrl} download={data.doc.filename}>
          <Download size={14} /> Download original
        </a>
        <button className="icon-button" aria-label="Close document viewer" onClick={onClose}>
          <X size={21} />
        </button>
      </header>

      <div className="viewer-layout">
        <div className="everything-column">
          {/* Universal Toolbar with Format-Specific Mode Toggles */}
          <div className="everything-toolbar">
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#ded4e5' }}>
                Section
                <select
                  aria-label="Source section"
                  value={number}
                  onChange={e => setNumber(Number(e.target.value))}
                  style={{
                    background: '#1b181d',
                    color: '#ebe7ee',
                    border: '1px solid #413a46',
                    borderRadius: '6px',
                    padding: '4px 8px',
                    fontSize: '12px',
                  }}
                >
                  {units.length ? (
                    units.map(item => (
                      <option key={item.unit_number ?? item.page_number} value={item.unit_number ?? item.page_number}>
                        {locationLabel({ ...data.doc, ...item })}
                      </option>
                    ))
                  ) : (
                    <option value={number}>{locationLabel({ ...data.doc, page_number: number })}</option>
                  )}
                </select>
              </label>

              {/* View Mode Switcher */}
              {(isMarkdown || isCode || isTable || isImage || isMedia) && (
                <div className="everything-tabs">
                  <button
                    className={`everything-tab ${viewMode === 'rich' ? 'active' : ''}`}
                    onClick={() => setViewMode('rich')}
                  >
                    {isMarkdown && <><Eye size={13} /> Rendered</>}
                    {isCode && <><Code size={13} /> Code Studio</>}
                    {isTable && <><TableIcon size={13} /> Grid Table</>}
                    {isImage && <><ImageIcon size={13} /> Image</>}
                    {isMedia && <>{isVideo ? <VideoIcon size={13} /> : <Music size={13} />} Player</>}
                  </button>
                  <button
                    className={`everything-tab ${viewMode === 'raw' ? 'active' : ''}`}
                    onClick={() => setViewMode('raw')}
                  >
                    <FileText size={13} /> Source Text
                  </button>
                </div>
              )}
            </div>

            {/* Format-Specific Quick Actions */}
            <div className="everything-actions">
              {isCode && viewMode === 'rich' && (
                <button className="button secondary small" onClick={copyCode} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {copied ? <><Check size={13} color="#86efac" /> Copied</> : <><Copy size={13} /> Copy</>}
                </button>
              )}

              {isImage && viewMode === 'rich' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <button className="icon-button" title="Zoom Out" onClick={() => setZoom(z => Math.max(0.25, z - 0.25))}>
                    <ZoomOut size={16} />
                  </button>
                  <span style={{ fontSize: '11px', color: '#b0a6b6', minWidth: '40px', textAlign: 'center' }}>
                    {Math.round(zoom * 100)}%
                  </span>
                  <button className="icon-button" title="Zoom In" onClick={() => setZoom(z => Math.min(4, z + 0.25))}>
                    <ZoomIn size={16} />
                  </button>
                  <button className="icon-button" title="Reset Zoom" onClick={() => setZoom(1)}>
                    <RotateCcw size={14} />
                  </button>
                  {imgDims && (
                    <span style={{ fontSize: '11px', color: '#8a7c93', marginLeft: '6px' }}>
                      {imgDims.w}×{imgDims.h}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Main Viewer Body */}
          {loading ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ded4e5', gap: '10px' }}>
              <LoaderCircle size={22} className="spin" /> Loading source file…
            </div>
          ) : error ? (
            <div role="alert" style={{ padding: '32px', textAlign: 'center' }}>
              <p style={{ color: '#f87171', marginBottom: '16px' }}>{error}</p>
              <button className="button secondary" onClick={onRecover}>
                Fix source or extraction
              </button>
            </div>
          ) : viewMode === 'rich' && isImage ? (
            /* IMAGE VIEWER */
            <div className="image-viewer-container">
              <div className="image-viewport">
                <img
                  src={fileUrl}
                  alt={data.doc.title}
                  className="image-element"
                  style={{ transform: `scale(${zoom})` }}
                  onLoad={e => {
                    const img = e.currentTarget;
                    setImgDims({ w: img.naturalWidth, h: img.naturalHeight });
                  }}
                />
              </div>
            </div>
          ) : viewMode === 'rich' && isMedia ? (
            /* MEDIA (AUDIO / VIDEO) VIEWER */
            <div className="media-viewer-container">
              {isVideo ? (
                <video controls className="video-player" src={fileUrl} />
              ) : (
                <div className="audio-card">
                  <div className="audio-icon-wrap">
                    <Music size={34} />
                  </div>
                  <div className="media-info">
                    <h3>{data.doc.title}</h3>
                    <p>{data.doc.filename}</p>
                  </div>
                  <audio controls className="audio-player" src={fileUrl} />
                </div>
              )}
            </div>
          ) : viewMode === 'rich' && isTable ? (
            /* CSV / TSV DATA TABLE VIEWER */
            <div className="table-viewer-container">
              <div className="table-filter-bar">
                <input
                  type="text"
                  placeholder="Filter table rows…"
                  value={tableFilter}
                  onChange={e => setTableFilter(e.target.value)}
                  className="table-filter-input"
                />
                <span className="table-meta-badge">
                  {tableData.rows.length} of {tableData.totalCount} rows
                </span>
              </div>
              <div className="table-scroll">
                <table className="everything-table">
                  <thead>
                    <tr>
                      <th className="table-row-idx">#</th>
                      {tableData.headers.map((h, i) => (
                        <th key={i}>{h || `Col ${i + 1}`}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.rows.map((row, rIdx) => {
                      const isHitRow = activeHit && row.some(c => activeHit.passage && activeHit.passage.includes(c));
                      return (
                        <tr key={rIdx} className={isHitRow ? 'table-hit-row' : ''}>
                          <td className="table-row-idx">{rIdx + 1}</td>
                          {row.map((cell, cIdx) => (
                            <td key={cIdx} title={cell}>
                              {activeHit?.passage && cell && activeHit.passage.includes(cell) ? (
                                <mark>{cell}</mark>
                              ) : (
                                cell
                              )}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : viewMode === 'rich' && isCode ? (
            /* CODE & SCRIPTS VIEWER WITH LINE NUMBERS */
            <div className="code-viewer-container">
              <div className="code-wrapper">
                {codeLines.map((line, idx) => {
                  const lineNum = idx + 1;
                  const isHitLine =
                    activeHit?.passage &&
                    line.trim().length > 3 &&
                    activeHit.passage.includes(line.trim());
                  return (
                    <div
                      key={idx}
                      ref={isHitLine ? codeHitRef : undefined}
                      className={`code-line ${isHitLine ? 'code-hit-line' : ''}`}
                    >
                      <div className="code-gutter">{lineNum}</div>
                      <div
                        className="code-content"
                        dangerouslySetInnerHTML={{ __html: highlightCode(line) || '&nbsp;' }}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          ) : viewMode === 'rich' && isMarkdown ? (
            /* FORMATTED MARKDOWN VIEWER */
            <div className="markdown-container">
              <div
                dangerouslySetInnerHTML={{
                  __html: parseMarkdownToHtml(unit?.text || 'No content in this section.'),
                }}
              />
            </div>
          ) : (
            /* SOURCE / FALLBACK TEXT VIEWER */
            <article className="text-source-content" aria-live="polite" style={{ overflow: 'auto', flex: 1 }}>
              <h2>{locationLabel({ ...data.doc, ...unit })}</h2>
              <p className="subtle">Indexed source text. Check formatting in original file.</p>
              {unit?.warnings?.map((w, i) => (
                <p className="notice" key={i}>
                  {w}
                </p>
              ))}
              <div className="source-text">
                {evidence && unit?.text ? (
                  <>
                    {unit.text.slice(0, evidence[0])}
                    <mark>{unit.text.slice(evidence[0], evidence[1])}</mark>
                    {unit.text.slice(evidence[1])}
                  </>
                ) : (
                  unit?.text || 'No extractable text in this section.'
                )}
              </div>
            </article>
          )}
        </div>

        {/* Right Sidebar: Semantic Exploration & Hit Matches */}
        <aside className="viewer-context">
          <div className="viewer-aside-heading">
            <Search size={16} />
            <h2>Explore this document</h2>
          </div>
          <form className="document-search" onSubmit={e => void search(e)}>
            <input
              aria-label="Search this document"
              placeholder="Ask about this document…"
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
            <button className="icon-button" aria-label="Run document search" disabled={searching || !query.trim()}>
              {searching ? <LoaderCircle className="spin" size={16} /> : <ArrowUpRight size={17} />}
            </button>
          </form>
          {note && <p className="viewer-note">{note}</p>}
          {hits.map(hit => (
            <button
              className="viewer-hit"
              key={hit.chunk_id}
              onClick={() => {
                setActiveHit(hit);
                setNumber(hit.unit_number ?? hit.page_number);
              }}
            >
              <strong>
                {locationLabel(hit)}
                <ArrowUpRight size={12} />
              </strong>
              <span>{hit.passage.slice(0, 210)}</span>
            </button>
          ))}
          {activeHit && (
            <div className="matched-context">
              <h3>Matching text</h3>
              <button className="page-tag" onClick={() => setNumber(activeHit.unit_number ?? activeHit.page_number)}>
                {locationLabel(activeHit)}
              </button>
              <p>{activeHit.passage}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
