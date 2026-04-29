import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, RefreshCw, Sparkles, Cpu, User } from 'lucide-react'
import { optimizerChat } from '../api'
import OptDecisionTree from './OptDecisionTree'
import OptKpiBar from './OptKpiBar'
import OptExclusionChart from './OptExclusionChart'

const STARTERS = [
  'What happened in the most recent WNY Fleet run?',
  'Which drivers get excluded most often, and why?',
  'Are there SAs that keep failing to schedule?',
  'What exclusion patterns have you seen this week?',
]

// ── Minimal markdown renderer ─────────────────────────────────────────────────

function InlineFmt({ text }) {
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_|`[^`]+`)/g)
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**'))
          return <strong key={i} className="font-semibold text-white">{p.slice(2, -2)}</strong>
        if (p.startsWith('_') && p.endsWith('_') && p.length > 2)
          return <em key={i} className="italic text-slate-200">{p.slice(1, -1)}</em>
        if (p.startsWith('`') && p.endsWith('`'))
          return <code key={i} className="px-1.5 py-0.5 rounded text-[11px] font-mono bg-slate-900 text-amber-300 border border-slate-700/40">{p.slice(1, -1)}</code>
        return p
      })}
    </>
  )
}

function MdLine({ line }) {
  const t = line
  if (/^#{1,3} /.test(t)) {
    const n   = t.match(/^(#+)/)[1].length
    const cls = n === 1 ? 'font-bold text-white text-[13px] mt-3 mb-1' : 'font-semibold text-slate-200 text-xs mt-2 mb-0.5 uppercase tracking-wide'
    return <div className={cls}><InlineFmt text={t.slice(n + 1)} /></div>
  }
  if (/^[-*] /.test(t)) {
    return (
      <div className="flex gap-2 my-0.5">
        <span className="text-slate-500 shrink-0 mt-0.5 select-none">•</span>
        <span><InlineFmt text={t.slice(2)} /></span>
      </div>
    )
  }
  if (/^\d+\. /.test(t)) {
    const m = t.match(/^(\d+)\. (.*)/)
    return (
      <div className="flex gap-2 my-0.5">
        <span className="text-slate-500 shrink-0 font-mono text-[11px] mt-0.5 w-4 text-right">{m[1]}.</span>
        <span><InlineFmt text={m[2]} /></span>
      </div>
    )
  }
  if (t.trim() === '') return <div className="h-1.5" />
  return <span><InlineFmt text={t} /></span>
}

function Md({ text }) {
  if (!text) return null
  const segments = text.split(/(```[\s\S]*?```)/g)
  return (
    <>
      {segments.map((seg, si) => {
        if (seg.startsWith('```')) {
          const body = seg.slice(3, -3)
          const nl   = body.indexOf('\n')
          const code = nl >= 0 ? body.slice(nl + 1) : body
          try {
            const parsed = JSON.parse(code)
            if (parsed?.visualization_type) return null
          } catch { /* not a viz block — render as code */ }
          return (
            <pre key={si} className="my-2 p-3 bg-slate-950 rounded-lg overflow-x-auto text-[11px] font-mono text-emerald-300 border border-slate-700/40">
              {code}
            </pre>
          )
        }
        const lines = seg.split('\n')
        return (
          <span key={si}>
            {lines.map((line, li) => (
              <span key={li}>
                <MdLine line={line} />
                {li < lines.length - 1 && line.trim() !== '' && !/^#{1,3} |^[-*] |^\d+\. /.test(line) && <br />}
              </span>
            ))}
          </span>
        )
      })}
    </>
  )
}

function VizBlock({ viz }) {
  if (!viz?.visualization_type) return null
  if (viz.visualization_type === 'decision_tree')  return <OptDecisionTree data={viz} />
  if (viz.visualization_type === 'kpi_comparison') return <OptKpiBar data={viz} />
  if (viz.visualization_type === 'exclusion_chart') return <OptExclusionChart data={viz} />
  return null
}

function TypingDots() {
  return (
    <div className="flex gap-3 opt-msg-enter">
      <div className="w-7 h-7 rounded-full bg-brand-600/30 border border-brand-500/30 flex items-center justify-center shrink-0 mt-0.5">
        <Cpu size={13} className="text-brand-400" />
      </div>
      <div className="bg-slate-800/70 border border-slate-700/40 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1.5">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-slate-500"
            style={{ animation: `optBounce 1s ease-in-out ${i * 0.16}s infinite` }}
          />
        ))}
      </div>
    </div>
  )
}

function Message({ msg }) {
  const isAI = msg.role === 'assistant'
  return (
    <div className={`flex gap-3 opt-msg-enter ${isAI ? '' : 'flex-row-reverse'}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5
        ${isAI ? 'bg-brand-600/30 border border-brand-500/30' : 'bg-slate-700 border border-slate-600/30'}`}>
        {isAI ? <Cpu size={13} className="text-brand-400" /> : <User size={13} className="text-slate-400" />}
      </div>
      <div className={`flex-1 max-w-[90%] ${isAI ? '' : 'flex flex-col items-end'}`}>
        <div className={`rounded-2xl px-4 py-3 text-[13px] leading-relaxed
          ${isAI
            ? 'bg-slate-800/70 border border-slate-700/40 text-slate-200 rounded-tl-sm'
            : 'bg-brand-600/20 border border-brand-500/20 text-brand-100 rounded-tr-sm'}`}>
          {isAI ? <Md text={msg.content} /> : msg.content}
        </div>
        {isAI && msg.visualization && <VizBlock viz={msg.visualization} />}
        {msg.error && <div className="mt-1 px-1 text-[11px] text-red-400">{msg.error}</div>}
      </div>
    </div>
  )
}

// ── Main chat ─────────────────────────────────────────────────────────────────

export default function OptimizerChat({ runContext }) {
  const [messages, setMessages] = useState([])
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const scrollRef = useRef(null)
  const inputRef  = useRef(null)
  const prevCtxId = useRef(null)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, loading])

  // When runContext changes (user clicked "Ask AI" in run detail), auto-ask
  useEffect(() => {
    if (!runContext || runContext.run_id === prevCtxId.current) return
    prevCtxId.current = runContext.run_id
    const t = runContext.run_at
      ? new Date(runContext.run_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
      : ''
    send(`Tell me about run **${runContext.run_name}** (${runContext.territory_name}${t ? `, ${t}` : ''}). What were the key decisions, any unscheduled SAs, and notable exclusion patterns?`)
  }, [runContext])

  const send = useCallback(async (text) => {
    const q = (typeof text === 'string' ? text : input).trim()
    if (!q || loading) return
    setInput('')

    const userMsg = { role: 'user', content: q }
    const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }))
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await optimizerChat(history, runContext)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: res.text,
        visualization: res.visualization,
      }])
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || 'Unknown error'
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'I couldn\'t reach the optimizer AI. Verify the Anthropic API key is set in **Admin → Settings**.',
        error: detail,
      }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [messages, input, loading, runContext])

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const handleInput = (e) => {
    setInput(e.target.value)
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'
  }

  const isEmpty = messages.length === 0

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2.5 bg-slate-800/60 border-b border-slate-700/50 flex items-center gap-3 shrink-0">
        <Sparkles size={14} className="text-brand-400" />
        <span className="text-sm font-semibold text-white">AI Chat</span>
        {!isEmpty && (
          <button
            onClick={() => { setMessages([]); prevCtxId.current = null }}
            className="ml-auto text-[11px] text-slate-500 hover:text-slate-300 transition-colors px-2 py-1 rounded hover:bg-slate-700/40"
          >
            New conversation
          </button>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {isEmpty && (
          <div className="flex flex-col items-center justify-center h-full gap-5 text-center">
            <div>
              <div className="w-12 h-12 mx-auto rounded-2xl bg-brand-600/15 border border-brand-500/20 flex items-center justify-center mb-3">
                <Cpu size={22} className="text-brand-400" />
              </div>
              <h3 className="text-white font-semibold text-[14px]">Optimizer AI</h3>
              <p className="text-slate-400 text-xs mt-1.5 max-w-[220px] leading-relaxed">
                Ask about assignments, exclusions, or click "Ask AI" on any run.
              </p>
            </div>
            <div className="space-y-1.5 w-full">
              {STARTERS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s)}
                  className="w-full text-left px-3 py-2.5 rounded-xl border border-slate-700/50 bg-slate-800/40 hover:bg-slate-800 hover:border-brand-500/30 text-slate-300 text-xs transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        {loading && <TypingDots />}
      </div>

      <div className="px-4 pb-4 pt-3 shrink-0 border-t border-slate-800/60">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKey}
            placeholder="Ask about a driver, SA, or run…"
            rows={1}
            style={{ maxHeight: '120px', overflowY: 'hidden', resize: 'none' }}
            className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded-xl px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/50 transition-colors"
          />
          <button
            onClick={() => send()}
            disabled={!input.trim() || loading}
            className="w-9 h-9 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:bg-slate-700 disabled:text-slate-500 text-white flex items-center justify-center transition-colors shrink-0 self-end"
          >
            {loading ? <RefreshCw size={13} className="animate-spin" /> : <Send size={13} />}
          </button>
        </div>
        <div className="text-[10px] text-slate-600 mt-1 px-1">Enter · Shift+Enter for new line</div>
      </div>
    </div>
  )
}
