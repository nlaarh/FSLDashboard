import { useEffect, useState } from 'react'
import { Download, RefreshCw, FileJson, Calendar, Layers, ChevronDown, ChevronRight } from 'lucide-react'
import { optimizerListFiles, optimizerLatestDate, optimizerRunZipUrl, optimizerDateZipUrl } from '../api'

function fmtSize(bytes) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// SF/DuckDB timestamps come without a TZ suffix but represent UTC.
function parseUtc(iso) {
  if (!iso) return null
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z')
}

function fmtTime(iso) {
  const d = parseUtc(iso); if (!d) return ''
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function fmtClock(iso) {
  const d = parseUtc(iso); if (!d) return ''
  return d.toLocaleString('en-US', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function todayIso() {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}

// Group runs by batch_id (FSL splits big optimizations into N parallel chunks).
// Returns [{batchId, runAt, runs:[chunks sorted by chunk_num]}], newest batch first.
function groupByBatch(runs) {
  const buckets = new Map()
  const ungrouped = []
  for (const r of runs) {
    if (r.batch_id) {
      if (!buckets.has(r.batch_id)) buckets.set(r.batch_id, [])
      buckets.get(r.batch_id).push(r)
    } else {
      ungrouped.push(r)
    }
  }
  const grouped = [...buckets.entries()].map(([batchId, chunks]) => ({
    batchId,
    runAt: chunks[0].run_at,
    runs: chunks.sort((a, b) => (a.chunk_num ?? 99) - (b.chunk_num ?? 99)),
  }))
  // ungrouped each in their own pseudo-batch for layout consistency
  for (const r of ungrouped) {
    grouped.push({ batchId: null, runAt: r.run_at, runs: [r] })
  }
  return grouped.sort((a, b) => (b.runAt || '').localeCompare(a.runAt || ''))
}

function BatchGroup({ batchId, runAt, chunks }) {
  const [open, setOpen] = useState(true)
  const totalSize = chunks.reduce((s, c) => s + (c.total_size || 0), 0)
  const totalFiles = chunks.reduce((s, c) => s + (c.blobs?.length || 0), 0)
  const isBatch = chunks.length > 1 || !!batchId
  return (
    <div className="border-t border-slate-800/50">
      {isBatch && (
        <button
          onClick={() => setOpen(o => !o)}
          className="w-full flex items-center gap-2 px-3 py-2 bg-slate-900/60 hover:bg-slate-800/40 transition-colors text-left"
        >
          {open ? <ChevronDown size={11} className="text-slate-500" /> : <ChevronRight size={11} className="text-slate-500" />}
          <Layers size={11} className="text-amber-400" />
          <span className="text-[11px] font-semibold text-slate-300">
            {fmtClock(runAt)} batch
          </span>
          <span className="text-[10px] text-slate-500">
            {chunks.length} chunk{chunks.length > 1 ? 's' : ''} · {totalFiles} files · {fmtSize(totalSize)}
          </span>
          {batchId && (
            <span className="ml-2 text-[9px] font-mono text-slate-600 truncate" title={batchId}>
              {batchId.slice(-12)}
            </span>
          )}
        </button>
      )}
      {open && (
        <table className="w-full text-xs">
          <tbody>
            {chunks.map(r => {
              const lastMod = r.blobs.reduce((a, b) => (b.last_modified > (a || '')) ? b.last_modified : a, '')
              return (
                <tr key={r.run_id} className="border-t border-slate-800/40 hover:bg-slate-800/20 transition-colors">
                  <td className="pl-7 pr-2 py-2 font-mono text-indigo-300 w-44">
                    {r.run_name || r.run_id}
                    {r.chunk_num != null && (
                      <span className="ml-2 text-[10px] text-amber-400/80 font-semibold">#{r.chunk_num}</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-slate-300">
                    {r.blobs.map(b => (
                      <span key={b.name}
                            className="inline-block mr-2 px-1.5 py-0.5 rounded bg-slate-800/60 text-[10px] text-slate-400 font-mono"
                            title={`${b.name} — ${fmtSize(b.size)}`}>
                        {b.name}
                      </span>
                    ))}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-slate-400 whitespace-nowrap">{fmtSize(r.total_size)}</td>
                  <td className="px-2 py-2 text-slate-500 font-mono text-[11px] whitespace-nowrap">{fmtTime(lastMod)}</td>
                  <td className="px-3 py-2 text-right">
                    <a
                      href={optimizerRunZipUrl(r.run_id)}
                      download={`optimizer-${r.run_id}.zip`}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-slate-800/60 hover:bg-indigo-600/40 border border-slate-700/40 hover:border-indigo-500 rounded text-[11px] text-slate-300 hover:text-indigo-200 transition-colors"
                    >
                      <Download size={10} />
                      ZIP
                    </a>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function OptimizerFileBrowser() {
  const [date, setDate]       = useState(todayIso())
  const [runs, setRuns]       = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const load = async (d) => {
    setLoading(true); setError(null)
    try {
      const data = await optimizerListFiles(d)
      setRuns(data.runs || [])
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
      setRuns([])
    } finally {
      setLoading(false)
    }
  }

  // On mount, auto-select the latest date that has data
  useEffect(() => {
    optimizerLatestDate()
      .then(({ date: latest }) => { setDate(latest); return load(latest) })
      .catch(() => load(todayIso()))
  }, [])

  const totalSize = runs.reduce((s, r) => s + (r.total_size || 0), 0)
  const totalFiles = runs.reduce((s, r) => s + (r.blobs?.length || 0), 0)

  return (
    <div className="flex flex-col h-full bg-slate-900/40 border border-slate-700/40 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-3 shrink-0 bg-slate-800/40">
        <FileJson size={16} className="text-indigo-400" />
        <h3 className="text-sm font-semibold text-slate-200">Optimizer JSON Archive</h3>
        <span className="text-[11px] text-slate-500">(Azure Blob: <code className="text-slate-400">fslappopt</code>)</span>

        <div className="ml-auto flex items-center gap-2">
          <Calendar size={13} className="text-slate-500" />
          <input
            type="date"
            value={date}
            max={todayIso()}
            onChange={(e) => setDate(e.target.value)}
            className="bg-slate-800/60 border border-slate-700/50 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
          />
          <button
            onClick={() => load(date)}
            title="Refresh"
            className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800/60 rounded transition-colors"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
          {runs.length > 0 && (
            <a
              href={optimizerDateZipUrl(date)}
              download={`optimizer-${date}.zip`}
              className="ml-1 px-3 py-1 bg-indigo-600/80 hover:bg-indigo-600 text-white text-xs font-medium rounded inline-flex items-center gap-1.5 transition-colors"
            >
              <Download size={12} />
              All ({totalFiles} files, {fmtSize(totalSize)})
            </a>
          )}
        </div>
      </div>

      {/* Stats strip */}
      <div className="px-4 py-2 bg-slate-900/60 border-b border-slate-700/30 flex gap-5 text-[11px] shrink-0">
        <span className="text-slate-400">Date: <span className="font-mono text-slate-200">{date}</span></span>
        <span className="text-slate-400">Runs: <span className="font-mono text-slate-200">{runs.length}</span></span>
        <span className="text-slate-400">Files: <span className="font-mono text-slate-200">{totalFiles}</span></span>
        <span className="text-slate-400">Total size: <span className="font-mono text-slate-200">{fmtSize(totalSize)}</span></span>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="p-4 text-sm text-red-400 bg-red-950/30 border-b border-red-900/40">
            <strong>Error:</strong> {error}
          </div>
        )}
        {loading && (
          <div className="p-10 text-center text-slate-500 flex flex-col items-center gap-3">
            <RefreshCw size={28} className="animate-spin opacity-60" />
            <div className="text-xs">Loading {date} from Azure Blob…</div>
            <div className="text-[10px] text-slate-600">(can take 5-10s for days with hundreds of runs)</div>
          </div>
        )}
        {!loading && !error && runs.length === 0 && (
          <div className="p-10 text-center text-slate-500">
            <FileJson size={32} className="mx-auto mb-3 opacity-40" />
            <div className="text-sm">No runs in Azure Blob for {date}.</div>
            <div className="text-[11px] mt-1.5 text-slate-600">
              Run the extractor on your Mac to populate this date:<br />
              <code className="text-slate-500">python -m optimizer_extractor.runner --days 1</code>
            </div>
          </div>
        )}
        {!loading && runs.length > 0 && groupByBatch(runs).map(({ batchId, runAt, runs: chunks }) => (
          <BatchGroup key={batchId || chunks[0].run_id} batchId={batchId} runAt={runAt} chunks={chunks} />
        ))}
      </div>
    </div>
  )
}
