import { useState, useEffect, useRef } from 'react'
import { MessageCircle, Send, X, Bot, User, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { askChatbot } from '../api'

export default function FloatingChat({ isOpen, onToggle }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [complexity, setComplexity] = useState('mid')
  const scrollRef = useRef(null)

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

  if (!isOpen) return null

  return (
    <div className="fixed bottom-6 right-6 z-50 w-[380px] glass rounded-2xl border border-slate-700/40 shadow-2xl shadow-black/40 flex flex-col"
      style={{ height: 'min(560px, calc(100vh - 140px))' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/30 rounded-t-2xl">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-brand-600/20 flex items-center justify-center">
            <Bot className="w-4 h-4 text-brand-400" />
          </div>
          <div>
            <div className="font-semibold text-sm text-white">FleetPulse Assistant</div>
            <div className="text-[10px] text-slate-500">Ask about data, metrics, calculations</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select value={complexity} onChange={e => setComplexity(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded text-[10px] text-slate-400 px-1.5 py-1 focus:outline-none">
            <option value="low">Quick</option>
            <option value="mid">Standard</option>
            <option value="high">Deep</option>
          </select>
          <button onClick={onToggle} className="p-1 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <div className="text-center py-6 space-y-3">
            <Bot className="w-8 h-8 text-brand-400/40 mx-auto" />
            <p className="text-xs text-slate-500">Ask me anything about fleet data, metrics, or calculations.</p>
            <div className="space-y-1.5">
              {['How do you calculate ATA?', 'What fields capture when a call is assigned?', 'How does the composite score work?'].map(q => (
                <button key={q} onClick={() => setInput(q)}
                  className="block w-full text-left text-[11px] text-slate-400 hover:text-brand-300 bg-slate-800/30 hover:bg-slate-800/60 rounded-lg px-3 py-2 transition-colors">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={clsx('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}>
            {m.role === 'assistant' && (
              <div className="w-6 h-6 rounded-full bg-brand-600/20 flex items-center justify-center shrink-0 mt-0.5">
                <Bot className="w-3.5 h-3.5 text-brand-400" />
              </div>
            )}
            <div className={clsx('rounded-xl px-3 py-2 text-xs leading-relaxed max-w-[85%]',
              m.role === 'user'
                ? 'bg-brand-600/20 text-brand-200'
                : m.isError ? 'bg-red-950/30 text-red-300 border border-red-800/30'
                : 'bg-slate-800/50 text-slate-300'
            )}>
              <div className="whitespace-pre-wrap">{m.content}</div>
              {m.model && <div className="text-[9px] text-slate-600 mt-1">{m.model}</div>}
            </div>
            {m.role === 'user' && (
              <div className="w-6 h-6 rounded-full bg-slate-700/50 flex items-center justify-center shrink-0 mt-0.5">
                <User className="w-3.5 h-3.5 text-slate-400" />
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-full bg-brand-600/20 flex items-center justify-center shrink-0">
              <Bot className="w-3.5 h-3.5 text-brand-400" />
            </div>
            <div className="bg-slate-800/50 rounded-xl px-3 py-2">
              <Loader2 className="w-4 h-4 animate-spin text-brand-400" />
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-3 py-3 border-t border-slate-700/30 rounded-b-2xl">
        <div className="flex gap-2">
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKey}
            placeholder="Ask about fields, metrics, calculations..."
            disabled={loading}
            className="flex-1 bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 disabled:opacity-50" />
          <button onClick={send} disabled={!input.trim() || loading}
            className="px-3 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-30 rounded-lg text-white transition-colors">
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
