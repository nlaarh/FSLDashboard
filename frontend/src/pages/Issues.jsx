import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchIssues, fetchIssue, addIssueComment, updateIssueStatus, triageIssues } from '../api'
import axios from 'axios'
import {
  Bug, MessageSquare, CheckCircle2, Send, Loader2,
  AlertTriangle, Clock, ChevronLeft, ChevronDown, ChevronUp, RefreshCw, Lock, Zap
} from 'lucide-react'

const SEV_STYLE = {
  high: 'bg-red-500/20 text-red-400 border-red-500/30',
  medium: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  low: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
}

// Workflow statuses — industry-standard issue lifecycle
const STATUSES = [
  { key: 'backlog',       label: 'Backlog',      color: 'bg-slate-500/20 text-slate-400 border-slate-500/30', dot: 'bg-slate-400' },
  { key: 'acknowledged',  label: 'Acknowledged',  color: 'bg-blue-500/20 text-blue-400 border-blue-500/30', dot: 'bg-blue-400' },
  { key: 'in-progress',   label: 'In Progress',   color: 'bg-amber-500/20 text-amber-400 border-amber-500/30', dot: 'bg-amber-400' },
  { key: 'testing',       label: 'Testing',        color: 'bg-purple-500/20 text-purple-400 border-purple-500/30', dot: 'bg-purple-400' },
  { key: 'released',      label: 'Released',       color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30', dot: 'bg-emerald-400' },
  { key: 'closed',        label: 'Closed',         color: 'bg-slate-600/20 text-slate-500 border-slate-600/30', dot: 'bg-slate-500' },
  { key: 'cancelled',     label: 'Cancelled',      color: 'bg-red-500/10 text-red-400/60 border-red-500/20', dot: 'bg-red-400/60' },
]

const STATUS_MAP = Object.fromEntries(STATUSES.map(s => [s.key, s]))

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function extractField(body, field) {
  const m = body?.match(new RegExp(`\\*\\*${field}:\\*\\*\\s*\`?([^\`\\n]+)\`?`))
  return m ? m[1].trim() : ''
}

function StatusBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP['backlog']
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold border ${s.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}

export default function Issues() {
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [expandedCard, setExpandedCard] = useState(null)  // issue number expanded in list
  const [cardDetails, setCardDetails] = useState({})       // cache: { issueNum: detail }
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  // User info for comments
  const [userName, setUserName] = useState('')
  const userLoaded = useRef(false)
  const [triaging, setTriaging] = useState(false)
  const [triageResult, setTriageResult] = useState(null)
  // Admin PIN (only for status changes + triage)
  const [pin, setPin] = useState(() => sessionStorage.getItem('admin_pin') || '')
  const [showPinInput, setShowPinInput] = useState(false)
  const [pinInput, setPinInput] = useState('')
  const [pendingStatus, setPendingStatus] = useState(null)
  const [pendingAction, setPendingAction] = useState(null) // 'status' or 'triage'

  // Load user info on mount
  useEffect(() => {
    if (userLoaded.current) return
    userLoaded.current = true
    axios.get('/api/auth/me').then(r => {
      if (r.data.name && r.data.name !== 'Developer') setUserName(r.data.name)
    }).catch(() => {
      setUserName(localStorage.getItem('fsl_reporter_name') || '')
    })
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchIssues(filter)
      setIssues(data.issues || [])
    } catch {
      setError('Failed to load issues')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { load() }, [load])

  const toggleCardExpand = async (num) => {
    if (expandedCard === num) {
      setExpandedCard(null)
      return
    }
    setExpandedCard(num)
    if (!cardDetails[num]) {
      try {
        const data = await fetchIssue(num)
        setCardDetails(prev => ({ ...prev, [num]: data }))
      } catch {
        // silently fail — card just won't show comments
      }
    }
  }

  const openDetail = async (num) => {
    setSelected(num)
    setDetail(null)
    setError(null)
    try {
      const data = await fetchIssue(num)
      setDetail(data)
    } catch {
      setError('Failed to load issue')
    }
  }

  const handleComment = async () => {
    if (!comment.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await addIssueComment(selected, comment.trim(), userName || 'Anonymous')
      setComment('')
      openDetail(selected)
    } catch {
      setError('Failed to add comment')
    } finally {
      setSubmitting(false)
    }
  }

  const handleTriage = async () => {
    if (!pin) {
      setPendingAction('triage')
      setShowPinInput(true)
      return
    }
    setTriaging(true)
    setTriageResult(null)
    setError(null)
    try {
      const data = await triageIssues(pin)
      setTriageResult(data)
      if (data.count > 0) load()
    } catch (e) {
      if (e.response?.status === 403) {
        setPin('')
        sessionStorage.removeItem('admin_pin')
        setPendingAction('triage')
        setShowPinInput(true)
        setError('Invalid PIN — try again')
      } else {
        setError('Failed to run triage')
      }
    } finally {
      setTriaging(false)
    }
  }

  const handleStatusChange = async (newStatus) => {
    if (!pin) {
      setPendingStatus(newStatus)
      setPendingAction('status')
      setShowPinInput(true)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await updateIssueStatus(pin, selected, newStatus)
      openDetail(selected)
      load()
    } catch (e) {
      if (e.response?.status === 403) {
        setPin('')
        sessionStorage.removeItem('admin_pin')
        setPendingStatus(newStatus)
        setPendingAction('status')
        setShowPinInput(true)
        setError('Invalid PIN — try again')
      } else {
        setError('Failed to update status')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handlePinSubmit = (e) => {
    e.preventDefault()
    if (!pinInput) return
    sessionStorage.setItem('admin_pin', pinInput)
    setPin(pinInput)
    setShowPinInput(false)
    const action = pendingAction
    const status = pendingStatus
    setPendingStatus(null)
    setPendingAction(null)
    setPinInput('')
    if (action === 'triage') {
      setTimeout(() => handleTriage(), 0)
    } else if (action === 'status' && status) {
      setTimeout(() => handleStatusChange(status), 0)
    }
  }

  // Re-bind handleStatusChange to use latest pin via ref
  const pinRef = useRef(pin)
  pinRef.current = pin

  // Detail view
  if (selected && detail) {
    const page = extractField(detail.body, 'Page')
    const reporter = extractField(detail.body, 'Reporter')
    const reporterEmail = extractField(detail.body, 'Email')
    const reportedAt = extractField(detail.body, 'Reported at')
    const descParts = detail.body?.split('---\n\n')
    const desc = descParts?.length > 1 ? descParts[descParts.length - 1].trim() : detail.body

    return (
      <div className="space-y-4">
        <button onClick={() => { setSelected(null); setDetail(null) }}
          className="flex items-center gap-1 text-xs text-slate-500 hover:text-white transition-colors">
          <ChevronLeft className="w-3 h-3" /> Back to issues
        </button>

        {/* Issue header */}
        <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-5">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h1 className="text-base font-bold text-white mb-1.5">
                #{detail.number} — {detail.title.replace(/^\[User Report\]\s*\w+:\s*/, '')}
              </h1>
              <div className="flex items-center gap-2 text-xs">
                <StatusBadge status={detail.status} />
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${SEV_STYLE[detail.severity]}`}>
                  {detail.severity}
                </span>
                {reportedAt && <span className="text-slate-500">Reported {reportedAt}</span>}
              </div>
            </div>
          </div>

          {/* Meta */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="bg-slate-800/50 rounded-lg px-3 py-2">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">Reporter</div>
              <div className="text-sm text-slate-200">{reporter || 'Anonymous'}</div>
            </div>
            <div className="bg-slate-800/50 rounded-lg px-3 py-2">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">Email</div>
              <div className="text-sm text-slate-200 truncate">{reporterEmail || '—'}</div>
            </div>
            <div className="bg-slate-800/50 rounded-lg px-3 py-2">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">Page</div>
              <div className="text-sm text-slate-200 font-mono">{page || '—'}</div>
            </div>
            <div className="bg-slate-800/50 rounded-lg px-3 py-2">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">Created</div>
              <div className="text-sm text-slate-200">{timeAgo(detail.created_at)}</div>
            </div>
          </div>

          {/* Description */}
          <div className="bg-slate-800/30 rounded-lg px-4 py-3 border border-slate-700/30 mb-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Description</div>
            <p className="text-sm text-slate-300 whitespace-pre-wrap">{desc}</p>
          </div>

          {/* Status dropdown */}
          <div className="flex items-center gap-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Status</div>
            <div className="relative">
              <select
                value={detail.status || 'backlog'}
                onChange={(e) => handleStatusChange(e.target.value)}
                disabled={submitting}
                className="appearance-none bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 pr-8 text-[11px] font-semibold text-slate-200 cursor-pointer hover:border-slate-500 transition-all focus:outline-none focus:ring-1 focus:ring-blue-500/50 disabled:opacity-40"
              >
                {STATUSES.map(s => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
              <ChevronDown className="w-3.5 h-3.5 text-slate-500 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
            <StatusBadge status={detail.status} />
          </div>
        </div>

        {/* PIN prompt (shown inline when needed) */}
        {showPinInput && (
          <div className="bg-slate-900 border border-amber-500/30 rounded-xl p-4">
            <form onSubmit={handlePinSubmit} className="flex items-center gap-3">
              <Lock className="w-4 h-4 text-amber-400 flex-shrink-0" />
              <span className="text-xs text-slate-400">Admin PIN required to change status:</span>
              <input
                type="password"
                value={pinInput}
                onChange={e => setPinInput(e.target.value)}
                placeholder="PIN"
                autoFocus
                className="w-32 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
              />
              <button type="submit" className="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-xs font-semibold">
                Unlock
              </button>
              <button type="button" onClick={() => { setShowPinInput(false); setPendingStatus(null) }}
                className="text-xs text-slate-600 hover:text-slate-400">Cancel</button>
            </form>
          </div>
        )}

        {/* Comments — open to all */}
        <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-5">
          <h2 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-brand-400" />
            Comments ({detail.comments?.length || 0})
          </h2>

          {detail.comments?.length > 0 ? (
            <div className="space-y-3 mb-4">
              {detail.comments.map(c => (
                <div key={c.id} className="bg-slate-800/50 rounded-lg px-4 py-3 border border-slate-700/30">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-slate-300">{c.user}</span>
                    <span className="text-[10px] text-slate-600">{timeAgo(c.created_at)}</span>
                  </div>
                  <p className="text-sm text-slate-400 whitespace-pre-wrap">{c.body}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-600 mb-4">No comments yet. Be the first to add one.</p>
          )}

          {/* Add comment — no PIN needed */}
          <div className="space-y-2">
            <input
              type="text"
              value={userName}
              onChange={e => { setUserName(e.target.value); localStorage.setItem('fsl_reporter_name', e.target.value) }}
              placeholder="Your name"
              className="w-48 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
            />
            <div className="flex gap-2">
              <textarea
                value={comment}
                onChange={e => setComment(e.target.value)}
                placeholder="Add a comment..."
                rows={2}
                className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:ring-1 focus:ring-brand-500/40"
              />
              <button onClick={handleComment} disabled={submitting || !comment.trim()}
                className="self-end px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-sm font-semibold transition-colors disabled:opacity-50 flex items-center gap-1.5">
                {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2 text-xs text-red-400 flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5" /> {error}
            <button onClick={() => setError(null)} className="ml-auto text-red-500 hover:text-red-300">dismiss</button>
          </div>
        )}
      </div>
    )
  }

  // Loading detail
  if (selected && !detail) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
      </div>
    )
  }

  // Issues list
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-white flex items-center gap-2">
          <Bug className="w-5 h-5 text-brand-400" /> Issues
        </h1>
        <div className="flex items-center gap-2">
          <div className="flex bg-slate-800 rounded-lg border border-slate-700/50 overflow-hidden">
            {['open', 'closed', 'all'].map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
                  filter === f ? 'bg-brand-600/30 text-brand-300' : 'text-slate-500 hover:text-white'
                }`}>
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
          <button onClick={handleTriage} disabled={triaging}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 text-xs font-semibold hover:bg-amber-500/20 transition-colors disabled:opacity-50"
            title="Auto-acknowledge all backlog issues">
            {triaging ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
            Triage
          </button>
          <button onClick={load} className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-colors">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Triage result */}
      {triageResult && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-4 py-3 text-xs text-amber-300 flex items-start gap-2">
          <Zap className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <div>
            {triageResult.count === 0 ? (
              <span>No backlog issues to triage — all caught up.</span>
            ) : (
              <>
                <span className="font-semibold">Triaged {triageResult.count} issue{triageResult.count > 1 ? 's' : ''}:</span>
                <ul className="mt-1 space-y-0.5">
                  {triageResult.triaged.map(t => (
                    <li key={t.number}>
                      #{t.number} ({t.severity}) — {t.title.replace(/^\[User Report\]\s*\w+:\s*/, '')}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
          <button onClick={() => setTriageResult(null)} className="ml-auto text-amber-500 hover:text-amber-300 flex-shrink-0">dismiss</button>
        </div>
      )}

      {/* PIN prompt for triage/status */}
      {showPinInput && !selected && (
        <div className="bg-slate-900 border border-amber-500/30 rounded-xl p-4">
          <form onSubmit={handlePinSubmit} className="flex items-center gap-3">
            <Lock className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span className="text-xs text-slate-400">Admin PIN required:</span>
            <input
              type="password"
              value={pinInput}
              onChange={e => setPinInput(e.target.value)}
              placeholder="PIN"
              autoFocus
              className="w-32 bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
            />
            <button type="submit" className="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-xs font-semibold">
              Unlock
            </button>
            <button type="button" onClick={() => { setShowPinInput(false); setPendingStatus(null); setPendingAction(null) }}
              className="text-xs text-slate-600 hover:text-slate-400">Cancel</button>
          </form>
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
        </div>
      ) : issues.length === 0 ? (
        <div className="text-center py-20">
          <CheckCircle2 className="w-10 h-10 text-slate-700 mx-auto mb-3" />
          <p className="text-sm text-slate-500">No {filter} issues</p>
        </div>
      ) : (
        <div className="space-y-2">
          {issues.map(iss => {
            const isExp = expandedCard === iss.number
            const cd = cardDetails[iss.number]
            const descParts = iss.body?.split('---\n\n')
            const desc = descParts?.length > 1 ? descParts[descParts.length - 1].trim() : ''

            return (
              <div key={iss.number}
                className={`bg-slate-900 border rounded-xl transition-all ${isExp ? 'border-brand-500/30' : 'border-slate-700/50 hover:border-slate-600/50'}`}>
                {/* Header row */}
                <div className="flex items-start gap-3 px-5 py-4 cursor-pointer" onClick={() => toggleCardExpand(iss.number)}>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-xs text-slate-600 font-mono">#{iss.number}</span>
                      <StatusBadge status={iss.status} />
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${SEV_STYLE[iss.severity]}`}>
                        {iss.severity}
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-slate-200 truncate">
                      {iss.title.replace(/^\[User Report\]\s*\w+:\s*/, '')}
                    </h3>
                    <div className="flex items-center gap-3 mt-1 text-xs text-slate-600">
                      <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {timeAgo(iss.created_at)}</span>
                      {iss.comments > 0 && (
                        <span className="flex items-center gap-1"><MessageSquare className="w-3 h-3" /> {iss.comments}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button onClick={(e) => { e.stopPropagation(); openDetail(iss.number) }}
                      className="px-2.5 py-1 rounded-lg text-[10px] font-semibold text-slate-500 hover:text-white hover:bg-slate-800 border border-slate-700/50 transition-colors">
                      Manage
                    </button>
                    {isExp
                      ? <ChevronUp className="w-4 h-4 text-slate-500" />
                      : <ChevronDown className="w-4 h-4 text-slate-500" />}
                  </div>
                </div>

                {/* Expanded: description + comments */}
                {isExp && (
                  <div className="border-t border-slate-800/60 px-5 py-4 space-y-3">
                    {/* Description */}
                    {desc && (
                      <div className="bg-slate-800/30 rounded-lg px-3 py-2 border border-slate-700/30">
                        <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Description</div>
                        <p className="text-xs text-slate-400 whitespace-pre-wrap">{desc}</p>
                      </div>
                    )}

                    {/* Comments */}
                    {cd?.comments?.length > 0 ? (
                      <div className="space-y-2">
                        <div className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1">
                          <MessageSquare className="w-3 h-3" /> {cd.comments.length} comment{cd.comments.length > 1 ? 's' : ''}
                        </div>
                        {cd.comments.map(c => (
                          <div key={c.id} className="bg-slate-800/40 rounded-lg px-3 py-2 border border-slate-700/20">
                            <div className="flex items-center gap-2 mb-0.5">
                              <span className="text-[11px] font-semibold text-slate-300">{c.user}</span>
                              <span className="text-[10px] text-slate-600">{timeAgo(c.created_at)}</span>
                            </div>
                            <p className="text-xs text-slate-400 whitespace-pre-wrap">{c.body}</p>
                          </div>
                        ))}
                      </div>
                    ) : cd ? (
                      <p className="text-[10px] text-slate-600">No comments yet.</p>
                    ) : (
                      <div className="flex items-center gap-2 text-[10px] text-slate-600">
                        <Loader2 className="w-3 h-3 animate-spin" /> Loading comments...
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
