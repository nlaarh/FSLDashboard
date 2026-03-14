import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, X, Bot, User, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { askChatbot } from '../api'
import axios from 'axios'

/* Chat bubble icon (not phone) */
function ChatBubbleIcon({ className }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" />
    </svg>
  )
}

export default function FloatingChat() {
  const [enabled, setEnabled] = useState(false)
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [complexity, setComplexity] = useState('mid')
  const scrollRef = useRef(null)

  // Check if chat is enabled via admin settings
  useEffect(() => {
    axios.get('/api/chatbot/status').then(r => setEnabled(r.data?.enabled ?? false)).catch(() => setEnabled(false))
  }, [])

  // ── Drag state ──
  const [pos, setPos] = useState({ x: null, y: null })
  const dragRef = useRef(null)
  const dragging = useRef(false)
  const dragStart = useRef({ mx: 0, my: 0, px: 0, py: 0 })

  const onMouseDown = useCallback((e) => {
    // Only drag from the header area
    if (e.target.closest('select') || e.target.closest('button')) return
    e.preventDefault()
    dragging.current = true
    const panel = dragRef.current
    const rect = panel.getBoundingClientRect()
    dragStart.current = { mx: e.clientX, my: e.clientY, px: rect.left, py: rect.top }
    document.body.style.userSelect = 'none'
  }, [])

  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current) return
      const dx = e.clientX - dragStart.current.mx
      const dy = e.clientY - dragStart.current.my
      setPos({ x: dragStart.current.px + dx, y: dragStart.current.py + dy })
    }
    const onUp = () => {
      dragging.current = false
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  }, [])

  // Reset position when closing
  const handleClose = () => {
    setOpen(false)
    setPos({ x: null, y: null })
  }

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, loading])

  const send = async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setError('')
    const userMsg = { role: 'user', content: q }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)
    try {
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      const res = await askChatbot(q, complexity, history)
      setMessages(prev => [...prev, { role: 'assistant', content: res.answer, model: res.model }])
    } catch (e) {
      const detail = e.response?.data?.detail || e.message
      if (detail === 'security_violation' || e.response?.status === 403) {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Session terminated due to security policy violation.', isError: true }])
        setTimeout(() => { window.location.href = '/login' }, 2000)
        return
      }
      setError(detail)
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${detail}`, isError: true }])
    } finally { setLoading(false) }
  }

  const handleKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }

  // Panel positioning
  const panelStyle = pos.x !== null
    ? { left: pos.x, top: pos.y, bottom: 'auto', right: 'auto' }
    : { bottom: '96px', right: '24px' }

  if (!enabled) return null

  return (
    <>
      {/* ── WhatsApp-style floating button ── */}
      <button
        onClick={() => setOpen(o => !o)}
        className={clsx(
          'fixed bottom-6 right-6 z-[60] w-14 h-14 rounded-full shadow-2xl flex items-center justify-center transition-all duration-300',
          open
            ? 'bg-slate-700 hover:bg-slate-600 rotate-90 scale-90'
            : 'bg-emerald-500 hover:bg-emerald-400 shadow-emerald-500/30 hover:shadow-emerald-400/40 hover:scale-105'
        )}
      >
        {open
          ? <X className="w-6 h-6 text-white" />
          : <ChatBubbleIcon className="w-7 h-7 text-white" />
        }
      </button>

      {/* Unread dot when closed */}
      {!open && messages.length === 0 && (
        <span className="fixed bottom-[68px] right-[22px] z-[61] w-5 h-5 rounded-full bg-red-500 text-[10px] text-white font-bold flex items-center justify-center shadow-lg animate-bounce pointer-events-none">
          1
        </span>
      )}

      {/* ── Chat panel ── */}
      {open && (
        <div
          ref={dragRef}
          className="fixed z-[55] w-[380px] rounded-2xl border border-slate-700/40 shadow-2xl shadow-black/50 flex flex-col overflow-hidden"
          style={{
            height: 'min(520px, calc(100vh - 140px))',
            background: 'linear-gradient(180deg, #0f172a 0%, #1e293b 100%)',
            ...panelStyle,
          }}
        >
          {/* Header — draggable green bar */}
          <div
            className="flex items-center justify-between px-4 py-3 bg-emerald-600 cursor-grab active:cursor-grabbing select-none"
            onMouseDown={onMouseDown}
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div>
                <div className="font-semibold text-sm text-white">FleetPulse Assistant</div>
                <div className="text-[10px] text-emerald-100/70">
                  {loading ? 'typing...' : 'online'}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <select value={complexity} onChange={e => setComplexity(e.target.value)}
                className="bg-emerald-700 border border-emerald-500/30 rounded text-[10px] text-emerald-100 px-1.5 py-1 focus:outline-none">
                <option value="low">Quick</option>
                <option value="mid">Standard</option>
                <option value="high">Deep</option>
              </select>
              <button onClick={handleClose} title="Close chat"
                className="ml-1 p-1.5 rounded-lg text-emerald-200 hover:text-white hover:bg-emerald-700 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Messages area */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
            style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%23334155\' fill-opacity=\'0.15\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")' }}
          >
            {messages.length === 0 && (
              <div className="text-center py-6 space-y-3">
                <div className="w-16 h-16 mx-auto rounded-full bg-emerald-500/10 flex items-center justify-center">
                  <Bot className="w-8 h-8 text-emerald-400/60" />
                </div>
                <p className="text-xs text-slate-400">Ask me anything about your fleet data.</p>
                <div className="space-y-1.5">
                  {['How do you calculate ATA?', 'What fields capture when a call is assigned?', 'How does the composite score work?'].map(q => (
                    <button key={q} onClick={() => setInput(q)}
                      className="block w-full text-left text-[11px] text-slate-400 hover:text-emerald-300 bg-slate-800/40 hover:bg-slate-800/70 rounded-lg px-3 py-2 transition-colors">
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={clsx('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                {m.role === 'assistant' && (
                  <div className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0 mt-0.5">
                    <Bot className="w-3.5 h-3.5 text-emerald-400" />
                  </div>
                )}
                <div className={clsx('rounded-lg px-3 py-2 text-xs leading-relaxed max-w-[80%] shadow-sm',
                  m.role === 'user'
                    ? 'bg-emerald-700/40 text-emerald-100 rounded-tr-none'
                    : m.isError
                      ? 'bg-red-950/40 text-red-300 border border-red-800/30 rounded-tl-none'
                      : 'bg-slate-800/70 text-slate-200 rounded-tl-none'
                )}>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                  {m.model && <div className="text-[9px] text-slate-500 mt-1 text-right">{m.model}</div>}
                </div>
                {m.role === 'user' && (
                  <div className="w-6 h-6 rounded-full bg-slate-600/50 flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-3.5 h-3.5 text-slate-300" />
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="flex gap-2">
                <div className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0">
                  <Bot className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                <div className="bg-slate-800/70 rounded-lg rounded-tl-none px-4 py-2.5 shadow-sm">
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-emerald-400/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 bg-emerald-400/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 bg-emerald-400/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Input */}
          <div className="px-3 py-3 bg-slate-900/80 border-t border-slate-700/30">
            <div className="flex gap-2 items-end">
              <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKey}
                placeholder="Type a message..."
                disabled={loading}
                className="flex-1 bg-slate-800 border border-slate-700/50 rounded-full text-xs px-4 py-2.5
                           placeholder:text-slate-500 text-slate-200
                           focus:outline-none focus:ring-2 focus:ring-emerald-500/30 disabled:opacity-50" />
              <button onClick={send} disabled={!input.trim() || loading}
                className="w-9 h-9 rounded-full bg-emerald-500 hover:bg-emerald-400 disabled:opacity-30
                           flex items-center justify-center transition-all shrink-0">
                <Send className="w-4 h-4 text-white" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
