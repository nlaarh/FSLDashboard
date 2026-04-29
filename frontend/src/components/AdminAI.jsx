import { useState, useEffect, useCallback } from 'react'
import { Bot, Save, Loader2, CheckCircle2, Cpu } from 'lucide-react'
import { adminGetSettings, adminUpdateSettings, fetchChatbotModels } from '../api'

// Optimizer chat only supports providers with compatible tool-calling APIs
const OC_PROVIDERS = [
  { value: 'anthropic', label: 'Anthropic (Claude)' },
  { value: 'openai',    label: 'OpenAI (GPT)' },
]

export default function AdminAI({ pin }) {
  // ── Main chatbot state ──────────────────────────────────────────────────────
  const [aiProvider, setAiProvider] = useState('')
  const [aiApiKey, setAiApiKey]     = useState('')
  const [aiPrimaryModel, setAiPrimaryModel] = useState('')
  const [aiFallbackModel, setAiFallbackModel] = useState('')
  const [aiModelCatalog, setAiModelCatalog] = useState({})
  const [aiChatEnabled, setAiChatEnabled] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)
  const [aiSaved, setAiSaved]   = useState(false)

  // ── Optimizer chat state ────────────────────────────────────────────────────
  const [ocAnthropicKey, setOcAnthropicKey] = useState('')
  const [ocOpenaiKey, setOcOpenaiKey]       = useState('')
  const [ocProvider, setOcProvider]         = useState('anthropic')
  const [ocModel, setOcModel]               = useState('')
  const [ocSaving, setOcSaving] = useState(false)
  const [ocSaved, setOcSaved]   = useState(false)

  const loadConfig = useCallback(async () => {
    try {
      const [settings, rawCatalog] = await Promise.all([
        adminGetSettings(pin),
        fetchChatbotModels(),
      ])

      // Normalize catalog format
      const catalog = {}
      for (const [prov, val] of Object.entries(rawCatalog || {})) {
        catalog[prov] = Array.isArray(val) ? val : [
          { id: val.low?.id  || '', label: val.low?.label  || '', tier: 'fast' },
          { id: val.mid?.id  || '', label: val.mid?.label  || '', tier: 'balanced' },
          { id: val.high?.id || '', label: val.high?.label || '', tier: 'reasoning' },
        ].filter(m => m.id)
      }
      setAiModelCatalog(catalog)

      // Main chatbot
      const cb = settings.chatbot || {}
      setAiChatEnabled(cb.enabled || false)
      setAiProvider(cb.provider || '')
      setAiApiKey(cb.api_key || '')
      setAiPrimaryModel(cb.primary_model || cb.models?.mid || cb.models?.high || '')
      setAiFallbackModel(cb.fallback_model || cb.models?.low || '')

      // Optimizer chat
      const oc = settings.optimizer_chat || {}
      setOcProvider(oc.provider || 'anthropic')
      setOcModel(oc.model || '')
      setOcAnthropicKey(settings.anthropic_api_key || '')
      setOcOpenaiKey(settings.openai_api_key || '')
    } catch { /* ignore */ }
  }, [pin])

  useEffect(() => { loadConfig() }, [loadConfig])

  // Main chatbot save
  const saveAiConfig = async () => {
    setAiSaving(true); setAiSaved(false)
    try {
      await adminUpdateSettings(pin, {
        chatbot: { enabled: aiChatEnabled, provider: aiProvider, api_key: aiApiKey,
                   primary_model: aiPrimaryModel, fallback_model: aiFallbackModel },
      })
      setAiSaved(true)
      setTimeout(() => setAiSaved(false), 3000)
    } catch { /* ignore */ } finally { setAiSaving(false) }
  }

  // Optimizer chat save
  const saveOptimizerChat = async () => {
    setOcSaving(true); setOcSaved(false)
    try {
      await adminUpdateSettings(pin, {
        anthropic_api_key: ocAnthropicKey,
        openai_api_key:    ocOpenaiKey,
        optimizer_chat:    { provider: ocProvider, model: ocModel },
      })
      setOcSaved(true)
      setTimeout(() => setOcSaved(false), 3000)
    } catch { /* ignore */ } finally { setOcSaving(false) }
  }

  // Model list for optimizer chat (only Anthropic + OpenAI)
  const ocModels = aiModelCatalog[ocProvider] || []
  const ocDefaultModel = ocProvider === 'anthropic' ? 'claude-sonnet-4-6' : 'gpt-4o'
  const ocDisplayModel = ocModel || ocDefaultModel

  return (
    <div className="space-y-6">

      {/* ── Card 1: Main AI Help Chatbot ─────────────────────────────────────── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <Bot className="w-4 h-4 text-brand-400" />
          <h2 className="text-sm font-semibold text-white">AI Help Assistant</h2>
          {aiSaved && (
            <span className="text-[10px] text-emerald-400 ml-auto flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> Saved
            </span>
          )}
        </div>
        <div className="p-4 space-y-5">
          <p className="text-[11px] text-slate-500">
            Configure the AI chatbot for dispatcher questions. Pick a provider, enter your API key,
            then choose a primary model and an optional fallback.
          </p>

          <div className="bg-slate-800/30 rounded-lg px-4 py-3 border border-slate-700/30">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-2">Example questions</div>
            <div className="space-y-1 text-xs text-slate-500 italic">
              <div>"Which garages are over capacity right now?"</div>
              <div>"What's the average response time for Battery calls today?"</div>
              <div>"Show me Fleet vs Towbook split for today"</div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-4">
              <div>
                <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">Provider</label>
                <div className="relative">
                  <select value={aiProvider} onChange={e => {
                    const p = e.target.value
                    setAiProvider(p); setAiApiKey('')
                    const cat = Array.isArray(aiModelCatalog[p]) ? aiModelCatalog[p] : []
                    const balanced = cat.find(m => m.tier === 'balanced')
                    const fast     = cat.find(m => m.tier === 'fast')
                    setAiPrimaryModel(balanced?.id || cat[0]?.id || '')
                    setAiFallbackModel(fast?.id || '')
                  }}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 pr-8
                               focus:outline-none focus:ring-2 focus:ring-brand-500/40 appearance-none cursor-pointer text-white">
                    <option value="">-- Select Provider --</option>
                    <option value="openai">OpenAI (GPT)</option>
                    <option value="anthropic">Anthropic (Claude)</option>
                    <option value="google">Google (Gemini)</option>
                  </select>
                  <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
                </div>
              </div>

              {aiProvider && (
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">API Key</label>
                  <input value={aiApiKey} onChange={e => setAiApiKey(e.target.value)}
                    type="password" placeholder={`Enter your ${aiProvider} API key...`}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 font-mono" />
                </div>
              )}
            </div>

            {aiProvider && (
              <div className="space-y-4">
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">
                    Primary Model <span className="text-brand-400">(required)</span>
                  </label>
                  <div className="relative">
                    <select value={aiPrimaryModel} onChange={e => setAiPrimaryModel(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 pr-8
                                 focus:outline-none focus:ring-2 focus:ring-brand-500/40 appearance-none cursor-pointer text-white">
                      <option value="">-- Select Model --</option>
                      {(aiModelCatalog[aiProvider] || []).map(m => (
                        <option key={m.id} value={m.id}>{m.label} ({m.tier})</option>
                      ))}
                    </select>
                    <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">
                    Fallback Model <span className="text-slate-600">(optional)</span>
                  </label>
                  <div className="relative">
                    <select value={aiFallbackModel} onChange={e => setAiFallbackModel(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 pr-8
                                 focus:outline-none focus:ring-2 focus:ring-brand-500/40 appearance-none cursor-pointer text-white">
                      <option value="">-- None --</option>
                      {(aiModelCatalog[aiProvider] || []).filter(m => m.id !== aiPrimaryModel).map(m => (
                        <option key={m.id} value={m.id}>{m.label} ({m.tier})</option>
                      ))}
                    </select>
                    <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
                  </div>
                </div>
              </div>
            )}
          </div>

          {aiProvider && (
            <div className="flex items-center gap-3 pt-1">
              <button onClick={saveAiConfig} disabled={aiSaving || !aiApiKey || !aiPrimaryModel}
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 rounded-lg text-xs font-semibold text-white transition-colors">
                {aiSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                {aiSaving ? 'Saving...' : 'Save AI Configuration'}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Card 2: Optimizer Decoder Chat ───────────────────────────────────── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-purple-400" />
          <h2 className="text-sm font-semibold text-white">Optimizer Decoder Chat</h2>
          <span className="text-[10px] px-1.5 py-0.5 bg-purple-900/40 text-purple-300 rounded font-mono">
            {ocProvider} / {ocDisplayModel}
          </span>
          {ocSaved && (
            <span className="text-[10px] text-emerald-400 ml-auto flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> Saved
            </span>
          )}
        </div>
        <div className="p-4 space-y-5">
          <p className="text-[11px] text-slate-500">
            The Optimizer Decoder uses tool-calling AI to answer questions about FSL optimizer
            decisions. Configure API keys and pick your preferred LLM. Defaults to Anthropic Claude Sonnet.
          </p>

          {/* API Keys — side by side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">
                Anthropic API Key
              </label>
              <input value={ocAnthropicKey} onChange={e => setOcAnthropicKey(e.target.value)}
                type="password" placeholder="sk-ant-..."
                className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-purple-500/40 font-mono" />
              <p className="text-[10px] text-slate-600 mt-1">console.anthropic.com/settings/keys</p>
            </div>
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">
                OpenAI API Key
              </label>
              <input value={ocOpenaiKey} onChange={e => setOcOpenaiKey(e.target.value)}
                type="password" placeholder="sk-..."
                className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-purple-500/40 font-mono" />
              <p className="text-[10px] text-slate-600 mt-1">platform.openai.com/api-keys</p>
            </div>
          </div>

          {/* Provider + Model */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">LLM Provider</label>
              <div className="relative">
                <select value={ocProvider} onChange={e => { setOcProvider(e.target.value); setOcModel('') }}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 pr-8
                             focus:outline-none focus:ring-2 focus:ring-purple-500/40 appearance-none cursor-pointer text-white">
                  {OC_PROVIDERS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
                <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
              </div>
            </div>
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">
                Model <span className="text-slate-600">(leave blank for default)</span>
              </label>
              <div className="relative">
                <select value={ocModel} onChange={e => setOcModel(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 pr-8
                             focus:outline-none focus:ring-2 focus:ring-purple-500/40 appearance-none cursor-pointer text-white">
                  <option value="">-- Default ({ocDefaultModel}) --</option>
                  {ocModels.map(m => (
                    <option key={m.id} value={m.id}>{m.label} ({m.tier})</option>
                  ))}
                </select>
                <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-1">
            <button onClick={saveOptimizerChat} disabled={ocSaving}
              className="flex items-center gap-2 px-4 py-2 bg-purple-700 hover:bg-purple-600 disabled:opacity-40 rounded-lg text-xs font-semibold text-white transition-colors">
              {ocSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              {ocSaving ? 'Saving...' : 'Save Optimizer Chat Config'}
            </button>
            <span className="text-[10px] text-slate-600">
              Active: <span className="text-slate-400 font-mono">{ocProvider} / {ocDisplayModel}</span>
            </span>
          </div>
        </div>
      </div>

    </div>
  )
}
