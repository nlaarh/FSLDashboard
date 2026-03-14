import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { Bug, X, Loader2, CheckCircle2 } from 'lucide-react'
import { submitIssue } from '../api'
import axios from 'axios'

const PAGE_NAMES = {
  '/': 'Command Center',
  '/garages': 'Garages List',
  '/queue': 'Queue Board',
  '/pta': 'PTA Advisor',
  '/forecast': 'Forecast',
  '/matrix': 'Territory Matrix',
  '/data': 'Data Dictionary',
  '/issues': 'Issues',
  '/help': 'Help',
  '/admin': 'Admin',
}

function getPageLabel(pathname) {
  if (PAGE_NAMES[pathname]) return PAGE_NAMES[pathname]
  if (pathname.startsWith('/garage/')) return 'Garage Detail'
  return pathname
}

const SEVERITIES = [
  { key: 'low', label: 'Low', color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  { key: 'medium', label: 'Medium', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30' },
  { key: 'high', label: 'High', color: 'bg-red-500/20 text-red-400 border-red-500/30' },
]

export default function ReportIssue() {
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState('medium')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState(null)
  const userLoaded = useRef(false)

  // Load logged-in user info on first mount
  useEffect(() => {
    if (userLoaded.current) return
    userLoaded.current = true
    axios.get('/api/auth/me').then(r => {
      const u = r.data
      if (u.name && u.name !== 'Developer') setName(u.name)
      if (u.email) setEmail(u.email)
    }).catch(() => {
      // Fall back to localStorage
      setName(localStorage.getItem('fsl_reporter_name') || '')
      setEmail(localStorage.getItem('fsl_reporter_email') || '')
    })
  }, [])

  useEffect(() => {
    if (submitted) {
      const t = setTimeout(() => { setSubmitted(false); setOpen(false) }, 2000)
      return () => clearTimeout(t)
    }
  }, [submitted])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!description.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      if (name.trim()) localStorage.setItem('fsl_reporter_name', name.trim())
      if (email.trim()) localStorage.setItem('fsl_reporter_email', email.trim())
      await submitIssue({
        page: pathname,
        description: description.trim(),
        severity,
        reporter: name.trim() || 'Anonymous',
        email: email.trim() || '',
      })
      setSubmitted(true)
      setDescription('')
      setSeverity('medium')
    } catch {
      setError('Failed to submit. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => { setOpen(true); setSubmitted(false); setError(null) }}
        className="fixed bottom-6 left-6 z-40 w-10 h-10 rounded-full bg-slate-700 hover:bg-slate-600
                   shadow-lg flex items-center justify-center transition-all
                   hover:scale-105 active:scale-95"
        title="Report an issue"
      >
        <Bug className="w-5 h-5 text-white" />
      </button>

      {/* Modal */}
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => !submitting && setOpen(false)} />

          {/* Card */}
          <div className="relative w-full max-w-md bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Bug className="w-4 h-4 text-brand-400" />
                <h2 className="text-sm font-bold text-white">Report an Issue</h2>
              </div>
              <button onClick={() => !submitting && setOpen(false)}
                className="p-1 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            {submitted ? (
              <div className="px-5 py-10 text-center">
                <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
                <p className="text-sm font-semibold text-white">Thank you!</p>
                <p className="text-xs text-slate-500 mt-1">Your issue has been submitted for review.</p>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">
                {/* Page (auto-detected) */}
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Page</label>
                  <div className="text-sm text-slate-300 bg-slate-800/50 rounded-lg px-3 py-2 border border-slate-700/50">
                    {getPageLabel(pathname)}
                  </div>
                </div>

                {/* Name + Email row */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Your Name</label>
                    <input
                      type="text"
                      value={name}
                      onChange={e => setName(e.target.value)}
                      placeholder="Name"
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm
                                 text-slate-200 placeholder-slate-600
                                 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Email</label>
                    <input
                      type="email"
                      value={email}
                      onChange={e => setEmail(e.target.value)}
                      placeholder="your@email.com"
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm
                                 text-slate-200 placeholder-slate-600
                                 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                    />
                  </div>
                </div>

                {/* Description */}
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">
                    What happened? <span className="text-red-400">*</span>
                  </label>
                  <textarea
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                    placeholder="Describe what looks wrong, what you expected, or what confused you..."
                    rows={4}
                    required
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm
                               text-slate-200 placeholder-slate-600 resize-none
                               focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                  />
                </div>

                {/* Severity */}
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Severity</label>
                  <div className="flex gap-2">
                    {SEVERITIES.map(s => (
                      <button
                        key={s.key}
                        type="button"
                        onClick={() => setSeverity(s.key)}
                        className={`flex-1 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                          severity === s.key
                            ? s.color
                            : 'bg-slate-800/50 text-slate-500 border-slate-700/50 hover:text-slate-300'
                        }`}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>

                {error && (
                  <p className="text-xs text-red-400">{error}</p>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={submitting || !description.trim()}
                  className="w-full py-2.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-sm font-semibold
                             transition-colors disabled:opacity-50 disabled:cursor-not-allowed
                             flex items-center justify-center gap-2"
                >
                  {submitting ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Submitting...</>
                  ) : (
                    'Submit Issue'
                  )}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  )
}
