import { useState, useEffect, useCallback } from 'react'
import { Shield, Database, Activity, Trash2, RefreshCw, Loader2, CheckCircle2, AlertTriangle, XCircle, Zap, Clock, Server, Map, Users, UserPlus, Edit3, Trash, Eye, Radio, Bot, Save, ToggleLeft, ToggleRight } from 'lucide-react'
import { adminVerify, adminStatus, adminFlush, adminFlushLive, adminFlushHistorical, adminFlushStatic, adminListUsers, adminCreateUser, adminUpdateUser, adminDeleteUser, adminListSessions, adminGetSettings, adminUpdateSettings, adminGetBonusTiers, adminSetBonusTiers, fetchChatbotModels, fetchFeatures } from '../api'
import { MAP_STYLES, getMapStyle, setMapStyle as saveMapStyle } from '../mapStyles'

const ROLES = ['admin', 'supervisor', 'viewer']

export default function Admin() {
  const [pin, setPin] = useState('')
  const [mapStyle, setMapStyleState] = useState(getMapStyle)
  const [authed, setAuthed] = useState(false)
  const [authError, setAuthError] = useState('')
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [flushing, setFlushing] = useState(null)
  const [lastAction, setLastAction] = useState(null)

  // User management state
  const [userList, setUserList] = useState([])
  const [sessions, setSessions] = useState([])
  const [showUserForm, setShowUserForm] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [userForm, setUserForm] = useState({ username: '', password: '', name: '', role: 'viewer' })
  const [userError, setUserError] = useState('')
  const [userSaving, setUserSaving] = useState(false)

  // Feature flags state
  const [features, setFeatures] = useState({})
  const [featureSaving, setFeatureSaving] = useState(false)
  const [featureSaved, setFeatureSaved] = useState(false)
  const [helpVideoUrl, setHelpVideoUrl] = useState('')
  const [videoSaving, setVideoSaving] = useState(false)
  const [videoSaved, setVideoSaved] = useState(false)

  // Bonus tiers state
  const [bonusTiers, setBonusTiers] = useState([])
  const [tiersSaving, setTiersSaving] = useState(false)
  const [tiersSaved, setTiersSaved] = useState(false)

  // AI Assistant config state
  const [aiProvider, setAiProvider] = useState('')
  const [aiApiKey, setAiApiKey] = useState('')
  const [aiPrimaryModel, setAiPrimaryModel] = useState('')
  const [aiFallbackModel, setAiFallbackModel] = useState('')
  const [aiModelCatalog, setAiModelCatalog] = useState({})
  const [aiChatEnabled, setAiChatEnabled] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)
  const [aiSaved, setAiSaved] = useState(false)

  const verify = async () => {
    setAuthError('')
    try {
      await adminVerify(pin)
      setAuthed(true)
    } catch {
      setAuthError('Invalid PIN')
    }
  }

  const refresh = useCallback(async () => {
    if (!authed) return
    setLoading(true)
    try {
      const s = await adminStatus(pin)
      setStatus(s)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [authed, pin])

  const loadUsers = useCallback(async () => {
    if (!authed) return
    try {
      const u = await adminListUsers(pin)
      setUserList(u)
    } catch { /* ignore */ }
  }, [authed, pin])

  const loadSessions = useCallback(async () => {
    if (!authed) return
    try {
      const s = await adminListSessions(pin)
      setSessions(s)
    } catch { /* ignore */ }
  }, [authed, pin])

  // Load AI config + model catalog on auth
  const loadAiConfig = useCallback(async () => {
    if (!authed) return
    try {
      const [settings, rawCatalog] = await Promise.all([
        adminGetSettings(pin),
        fetchChatbotModels(),
      ])
      // Normalize catalog: convert old {low:{id,label}, mid:...} to [{id,label,tier},...] if needed
      const catalog = {}
      for (const [prov, val] of Object.entries(rawCatalog || {})) {
        if (Array.isArray(val)) {
          catalog[prov] = val
        } else {
          // Old format: {low: {id, label}, mid: ..., high: ...}
          catalog[prov] = [
            { id: val.low?.id || '', label: val.low?.label || '', tier: 'fast' },
            { id: val.mid?.id || '', label: val.mid?.label || '', tier: 'balanced' },
            { id: val.high?.id || '', label: val.high?.label || '', tier: 'reasoning' },
          ].filter(m => m.id)
        }
      }
      setAiModelCatalog(catalog)
      const cb = settings.chatbot || {}
      setAiChatEnabled(cb.enabled || false)
      setAiProvider(cb.provider || '')
      setAiApiKey(cb.api_key || '')
      // Support both new (primary_model) and old (models.mid) settings
      setAiPrimaryModel(cb.primary_model || cb.models?.mid || cb.models?.high || '')
      setAiFallbackModel(cb.fallback_model || cb.models?.low || '')
    } catch { /* ignore */ }
  }, [authed, pin])

  const saveAiConfig = async () => {
    setAiSaving(true)
    setAiSaved(false)
    try {
      await adminUpdateSettings(pin, {
        chatbot: { enabled: aiChatEnabled, provider: aiProvider, api_key: aiApiKey, primary_model: aiPrimaryModel, fallback_model: aiFallbackModel },
      })
      setAiSaved(true)
      setTimeout(() => setAiSaved(false), 3000)
    } catch { /* ignore */ }
    finally { setAiSaving(false) }
  }

  useEffect(() => {
    if (authed) {
      refresh()
      loadUsers()
      loadSessions()
      loadAiConfig()
      fetchFeatures().then(f => { setFeatures(f); setHelpVideoUrl(f.help_video_url || '') }).catch(() => {})
      adminGetBonusTiers(pin).then(setBonusTiers).catch(() => {})
      const id = setInterval(() => { refresh(); loadSessions() }, 5000)
      return () => clearInterval(id)
    }
  }, [authed, refresh, loadUsers, loadSessions, loadAiConfig])

  const handleFlush = async (type, fn) => {
    setFlushing(type)
    try {
      const result = await fn(pin)
      setStatus(s => s ? { ...s, cache: result.cache_after } : s)
      setLastAction({ type, time: new Date(), flushed: result.flushed })
    } catch { /* ignore */ }
    finally { setFlushing(null) }
  }

  const handleMapStyleChange = (key) => {
    saveMapStyle(key)
    setMapStyleState(key)
    window.dispatchEvent(new Event('mapStyleChanged'))
  }

  const openCreateUser = () => {
    setEditingUser(null)
    setUserForm({ username: '', password: '', name: '', role: 'viewer' })
    setUserError('')
    setShowUserForm(true)
  }

  const openEditUser = (u) => {
    setEditingUser(u.username)
    setUserForm({ username: u.username, password: '', name: u.name, role: u.role })
    setUserError('')
    setShowUserForm(true)
  }

  const saveUser = async () => {
    setUserError('')
    setUserSaving(true)
    try {
      if (editingUser) {
        const data = { name: userForm.name, role: userForm.role }
        if (userForm.password) data.password = userForm.password
        await adminUpdateUser(pin, editingUser, data)
      } else {
        if (!userForm.username || !userForm.password || !userForm.name) {
          setUserError('All fields are required')
          setUserSaving(false)
          return
        }
        await adminCreateUser(pin, userForm)
      }
      setShowUserForm(false)
      loadUsers()
    } catch (e) {
      setUserError(e.response?.data?.detail || 'Error saving user')
    } finally { setUserSaving(false) }
  }

  const deleteUser = async (username) => {
    if (!confirm(`Delete user "${username}"?`)) return
    try {
      await adminDeleteUser(pin, username)
      loadUsers()
    } catch { /* ignore */ }
  }

  const toggleActive = async (u) => {
    try {
      await adminUpdateUser(pin, u.username, { active: !u.active })
      loadUsers()
    } catch { /* ignore */ }
  }

  // PIN gate
  if (!authed) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="glass rounded-2xl p-8 w-full max-w-sm">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-brand-600/20 flex items-center justify-center">
              <Shield className="w-5 h-5 text-brand-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">Admin Panel</h1>
              <p className="text-xs text-slate-500">Enter PIN to continue</p>
            </div>
          </div>
          <div className="space-y-3">
            <input
              type="password"
              value={pin}
              onChange={e => setPin(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && verify()}
              placeholder="Enter PIN"
              autoFocus
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-center text-lg tracking-[0.3em]
                         focus:outline-none focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500/40"
            />
            {authError && <p className="text-red-400 text-sm text-center">{authError}</p>}
            <button onClick={verify}
              className="w-full py-2.5 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-semibold transition-colors">
              Unlock
            </button>
          </div>
        </div>
      </div>
    )
  }

  const c = status?.cache || {}
  const sf = status?.salesforce || {}
  const uptime = status?.uptime_seconds || 0
  const uptimeStr = uptime >= 3600
    ? `${Math.floor(uptime / 3600)}h ${Math.floor((uptime % 3600) / 60)}m`
    : `${Math.floor(uptime / 60)}m`

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-600/20 flex items-center justify-center">
            <Shield className="w-5 h-5 text-brand-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">System Admin</h1>
            <p className="text-xs text-slate-500">Users, cache & system health</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {loading && <Loader2 className="w-4 h-4 animate-spin text-brand-400" />}
          <button onClick={() => { refresh(); loadUsers(); loadSessions() }}
            className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-white
                       transition-colors flex items-center gap-1.5">
            <RefreshCw className="w-3 h-3" /> Refresh
          </button>
          <div className="text-xs text-slate-600 flex items-center gap-1">
            <Server className="w-3 h-3" /> Uptime: {uptimeStr}
          </div>
          <div className="px-2 py-0.5 rounded-md bg-brand-600/20 border border-brand-500/30 text-[10px] font-mono text-brand-400">
            v2.0
          </div>
        </div>
      </div>

      {/* ── Users & Sessions ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* User Management */}
        <div className="lg:col-span-2 glass rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
            <Users className="w-4 h-4 text-brand-400" />
            <h2 className="text-sm font-semibold text-white">Users</h2>
            <span className="ml-1 text-xs text-slate-500">({userList.length})</span>
            <button onClick={openCreateUser}
              className="ml-auto px-2.5 py-1 text-[11px] bg-brand-600 hover:bg-brand-500 rounded-lg font-semibold
                         flex items-center gap-1 transition-colors">
              <UserPlus className="w-3 h-3" /> Add User
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-2.5 px-4 font-medium">Username</th>
                  <th className="text-left py-2.5 px-4 font-medium">Name</th>
                  <th className="text-left py-2.5 px-4 font-medium">Role</th>
                  <th className="text-center py-2.5 px-4 font-medium">Status</th>
                  <th className="text-right py-2.5 px-4 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {userList.map(u => (
                  <tr key={u.username} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="py-2.5 px-4 text-slate-300 font-mono font-medium">{u.username}</td>
                    <td className="py-2.5 px-4 text-slate-300">{u.name}</td>
                    <td className="py-2.5 px-4">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        u.role === 'admin' ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20' :
                        u.role === 'supervisor' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                        'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                      }`}>{u.role}</span>
                    </td>
                    <td className="py-2.5 px-4 text-center">
                      <button onClick={() => toggleActive(u)}
                        className={`px-2 py-0.5 rounded text-[10px] font-bold cursor-pointer transition-colors ${
                          u.active
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20'
                            : 'bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20'
                        }`}>
                        {u.active ? 'Active' : 'Disabled'}
                      </button>
                    </td>
                    <td className="py-2.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button onClick={() => openEditUser(u)}
                          className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-500 hover:text-white transition-colors">
                          <Edit3 className="w-3 h-3" />
                        </button>
                        <button onClick={() => deleteUser(u.username)}
                          className="p-1.5 rounded-lg hover:bg-red-900/30 text-slate-500 hover:text-red-400 transition-colors">
                          <Trash className="w-3 h-3" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {userList.length === 0 && (
                  <tr><td colSpan={5} className="py-8 text-center text-slate-600">No users</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Inline create/edit form */}
          {showUserForm && (
            <div className="border-t border-slate-700/50 p-4 bg-slate-800/30">
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-semibold text-white">{editingUser ? `Edit ${editingUser}` : 'Create User'}</h3>
                <button onClick={() => setShowUserForm(false)} className="ml-auto text-xs text-slate-500 hover:text-white">Cancel</button>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Username</label>
                  <input value={userForm.username} onChange={e => setUserForm(f => ({ ...f, username: e.target.value }))}
                    disabled={!!editingUser}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs
                               focus:outline-none focus:ring-1 focus:ring-brand-500/40 disabled:opacity-50"
                    placeholder="jdoe" />
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Name</label>
                  <input value={userForm.name} onChange={e => setUserForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs
                               focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                    placeholder="John Doe" />
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">
                    Password {editingUser && <span className="text-slate-600">(leave blank to keep)</span>}
                  </label>
                  <input type="password" value={userForm.password} onChange={e => setUserForm(f => ({ ...f, password: e.target.value }))}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs
                               focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                    placeholder="••••••" />
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Role</label>
                  <select value={userForm.role} onChange={e => setUserForm(f => ({ ...f, role: e.target.value }))}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs
                               focus:outline-none focus:ring-1 focus:ring-brand-500/40">
                    {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>
              </div>
              {userError && <p className="text-red-400 text-xs mt-2">{userError}</p>}
              <button onClick={saveUser} disabled={userSaving}
                className="mt-3 px-4 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs font-semibold
                           transition-colors disabled:opacity-50 flex items-center gap-1.5">
                {userSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                {editingUser ? 'Update' : 'Create'}
              </button>
            </div>
          )}
        </div>

        {/* Active Sessions */}
        <div className="glass rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
            <Radio className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white">Who's Online</h2>
            <span className="ml-1 text-xs text-slate-500">({sessions.length})</span>
          </div>
          <div className="p-3 space-y-2">
            {sessions.map((s, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-slate-800/40">
                <div className="w-8 h-8 rounded-full bg-brand-600/20 flex items-center justify-center text-xs font-bold text-brand-400">
                  {(s.name || s.user || '?')[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-white truncate">{s.name || s.user}</div>
                  <div className="text-[10px] text-slate-500">
                    {s.role} — {s.idle_min === 0 ? 'active now' : `idle ${s.idle_min}m`}
                  </div>
                </div>
                <div className={`w-2 h-2 rounded-full ${s.idle_min < 5 ? 'bg-emerald-400' : s.idle_min < 30 ? 'bg-amber-400' : 'bg-slate-600'}`} />
              </div>
            ))}
            {sessions.length === 0 && (
              <div className="py-6 text-center text-slate-600 text-xs">No active sessions</div>
            )}
          </div>
        </div>
      </div>

      {/* ── Map Style ── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <Map className="w-4 h-4 text-brand-400" />
          <h2 className="text-sm font-semibold text-white">Map Style</h2>
        </div>
        <div className="p-4">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {Object.entries(MAP_STYLES).map(([key, style]) => (
              <button key={key} onClick={() => handleMapStyleChange(key)}
                className={`rounded-xl border overflow-hidden text-left transition-all ${
                  mapStyle === key
                    ? 'border-brand-500 ring-2 ring-brand-500/30'
                    : 'border-slate-700/50 hover:border-slate-500'
                }`}>
                <div className="relative w-full h-20 bg-slate-800 overflow-hidden">
                  <img src={style.preview} alt={style.name}
                    className="w-full h-full object-cover"
                    style={style.filter ? { filter: style.filter } : {}}
                    loading="lazy" />
                  {mapStyle === key && (
                    <div className="absolute top-1.5 right-1.5 flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-brand-600/90 text-[9px] text-white font-bold">
                      <CheckCircle2 className="w-2.5 h-2.5" /> Active
                    </div>
                  )}
                </div>
                <div className="px-2.5 py-2">
                  <div className="text-xs font-semibold text-white">{style.name}</div>
                  <div className="text-[10px] text-slate-500">{style.description}</div>
                </div>
              </button>
            ))}
          </div>
          <p className="text-[10px] text-slate-600 mt-3">Changes apply to all maps immediately. Preference saved in browser.</p>
        </div>
      </div>

      {/* ── AI Assistant Config ── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <Bot className="w-4 h-4 text-brand-400" />
          <h2 className="text-sm font-semibold text-white">AI Help Assistant</h2>
          {aiSaved && <span className="text-[10px] text-emerald-400 ml-auto flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Saved</span>}
        </div>
        <div className="p-4 space-y-5">
          <p className="text-[11px] text-slate-500">Configure the AI chatbot. Pick a provider, enter your API key, then choose a primary model and an optional fallback.</p>

          {/* Example questions for dispatchers */}
          <div className="bg-slate-800/30 rounded-lg px-4 py-3 border border-slate-700/30 mb-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-2">Example questions dispatchers can ask</div>
            <div className="space-y-1 text-xs text-slate-500 italic">
              <div>"Which garages are over capacity right now?"</div>
              <div>"What's the average response time for Battery calls today?"</div>
              <div>"How many calls did 076DO handle this week?"</div>
              <div>"Show me Fleet vs Towbook split for today"</div>
              <div>"Who are the top 3 fastest drivers this week?"</div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Left column: Provider + API Key */}
            <div className="space-y-4">
              {/* Provider dropdown */}
              <div>
                <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">Provider</label>
                <div className="relative">
                  <select value={aiProvider} onChange={e => {
                    const p = e.target.value
                    setAiProvider(p)
                    setAiApiKey('')
                    const cat = Array.isArray(aiModelCatalog[p]) ? aiModelCatalog[p] : []
                    const balanced = cat.find(m => m.tier === 'balanced')
                    const fast = cat.find(m => m.tier === 'fast')
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

              {/* API Key */}
              {aiProvider && (
                <div>
                  <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">API Key</label>
                  <input value={aiApiKey} onChange={e => setAiApiKey(e.target.value)}
                    type="password" placeholder={`Enter your ${aiProvider} API key...`}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2.5 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 font-mono" />
                  <p className="text-[10px] text-slate-600 mt-1">
                    {aiProvider === 'openai' && 'Get your key at platform.openai.com/api-keys'}
                    {aiProvider === 'anthropic' && 'Get your key at console.anthropic.com/settings/keys'}
                    {aiProvider === 'google' && 'Get your key at aistudio.google.com/apikey'}
                  </p>
                </div>
              )}
            </div>

            {/* Right column: Primary + Fallback model */}
            {aiProvider && (
              <div className="space-y-4">
                {/* Primary Model */}
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
                  <p className="text-[10px] text-slate-600 mt-1">Used for all chatbot questions</p>
                </div>

                {/* Fallback Model */}
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
                  <p className="text-[10px] text-slate-600 mt-1">If primary fails, this model takes over automatically</p>
                </div>
              </div>
            )}
          </div>

          {/* Save button */}
          {aiProvider && (
            <div className="flex items-center gap-3 pt-1">
              <button onClick={saveAiConfig} disabled={aiSaving || !aiApiKey || !aiPrimaryModel}
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 rounded-lg text-xs font-semibold text-white transition-colors">
                {aiSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                {aiSaving ? 'Saving...' : 'Save AI Configuration'}
              </button>
              {aiPrimaryModel && (
                <span className="text-[10px] text-slate-600">
                  Primary: <span className="text-slate-400 font-mono">{aiPrimaryModel}</span>
                  {aiFallbackModel && <> / Fallback: <span className="text-slate-400 font-mono">{aiFallbackModel}</span></>}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Feature Modules ── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <ToggleRight className="w-4 h-4 text-brand-400" />
          <h2 className="text-sm font-semibold text-white">Feature Modules</h2>
          <span className="text-[10px] text-slate-500 ml-1">Toggle modules on/off — hidden from all users when off</span>
          {featureSaved && <span className="text-[10px] text-emerald-400 ml-auto flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Saved</span>}
        </div>
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { key: 'pta_advisor', label: 'PTA Advisor', desc: 'Promised time projections' },
            { key: 'onroute', label: 'Route Tracker', desc: 'En-route drivers & live tracking links' },
            { key: 'matrix', label: 'Insights', desc: 'Priority matrix advisor' },
            { key: 'chat', label: 'AI Chat', desc: 'Floating chatbot assistant' },
          ].map(m => {
            const on = features[m.key] !== false
            return (
              <div key={m.key} className={`flex items-center justify-between rounded-lg border px-4 py-3 transition-colors ${
                on ? 'bg-slate-800/30 border-slate-700/50' : 'bg-slate-900/50 border-slate-800/30 opacity-60'
              }`}>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-200">{m.label}</div>
                  <div className="text-[10px] text-slate-500">{m.desc}</div>
                </div>
                <button
                  disabled={featureSaving}
                  onClick={async () => {
                    const next = { ...features, [m.key]: !on }
                    setFeatures(next)
                    setFeatureSaving(true)
                    try {
                      await adminUpdateSettings(pin, { features: next })
                      window.dispatchEvent(new Event('featuresChanged'))
                      setFeatureSaved(true)
                      setTimeout(() => setFeatureSaved(false), 2000)
                    } catch { /* ignore */ }
                    finally { setFeatureSaving(false) }
                  }}
                  className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ml-3 ${on ? 'bg-emerald-500' : 'bg-slate-600'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${on ? 'translate-x-5' : ''}`} />
                </button>
              </div>
            )
          })}
        </div>
        {/* Help Video URL */}
        <div className="px-4 pb-4 pt-2 border-t border-slate-700/30 mt-3">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">Help Page Video URL</label>
          <div className="flex items-center gap-2">
            <input value={helpVideoUrl} onChange={e => setHelpVideoUrl(e.target.value)}
              placeholder="https://youtu.be/..."
              className="flex-1 bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2
                         focus:outline-none focus:ring-1 focus:ring-brand-500/40 font-mono text-slate-300 placeholder:text-slate-600" />
            <button disabled={videoSaving}
              onClick={async () => {
                setVideoSaving(true); setVideoSaved(false)
                try {
                  await adminUpdateSettings(pin, { help_video_url: helpVideoUrl })
                  setVideoSaved(true)
                  setTimeout(() => setVideoSaved(false), 2000)
                } catch { /* ignore */ }
                finally { setVideoSaving(false) }
              }}
              className="px-3 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-1.5">
              {videoSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
              Save
            </button>
            {videoSaved && <span className="text-[10px] text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Saved</span>}
          </div>
          <p className="text-[10px] text-slate-600 mt-1">YouTube link shown in the Help &gt; How It Works section. Leave blank to hide.</p>
        </div>

        {/* ── Bonus Tiers ── */}
        <div className="pt-4 border-t border-slate-800/50">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-semibold text-white">Contractor Bonus Tiers</span>
            <span className="text-[10px] text-slate-500">Based on Technician "Totally Satisfied" %</span>
          </div>
          <div className="space-y-2">
            {bonusTiers.map((t, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-slate-500 w-6">≥</span>
                  <input type="number" value={t.min_pct} onChange={e => {
                    const next = [...bonusTiers]; next[i] = { ...t, min_pct: parseFloat(e.target.value) || 0 }; setBonusTiers(next)
                  }} className="w-16 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white" />
                  <span className="text-[10px] text-slate-500">%</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-slate-500">$</span>
                  <input type="number" step="0.5" value={t.bonus_per_sa} onChange={e => {
                    const next = [...bonusTiers]; next[i] = { ...t, bonus_per_sa: parseFloat(e.target.value) || 0 }; setBonusTiers(next)
                  }} className="w-16 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white" />
                  <span className="text-[10px] text-slate-500">/SA</span>
                </div>
                <button onClick={() => setBonusTiers(bonusTiers.filter((_, j) => j !== i))}
                  className="text-red-400 hover:text-red-300 text-xs"><Trash className="w-3 h-3" /></button>
              </div>
            ))}
            <div className="flex items-center gap-2 pt-1">
              <button onClick={() => setBonusTiers([...bonusTiers, { min_pct: 90, bonus_per_sa: 0, label: '≥90%' }])}
                className="text-[10px] text-brand-400 hover:text-brand-300">+ Add Tier</button>
              <button onClick={() => {
                setTiersSaving(true); setTiersSaved(false)
                adminSetBonusTiers(pin, bonusTiers).then(setBonusTiers).then(() => setTiersSaved(true))
                  .catch(() => {}).finally(() => setTiersSaving(false))
              }} disabled={tiersSaving}
                className="flex items-center gap-1 px-3 py-1 bg-brand-600 hover:bg-brand-500 text-white text-[10px] font-medium rounded transition disabled:opacity-50">
                {tiersSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                Save Tiers
              </button>
              {tiersSaved && <span className="text-[10px] text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Saved</span>}
            </div>
          </div>
          <p className="text-[10px] text-slate-600 mt-2">Bonus paid to contractor garages only. Fleet (100/800) excluded. Tiers matched highest-first.</p>
        </div>
      </div>

      {lastAction && (
        <div className="glass rounded-xl px-4 py-2.5 border-l-2 border-l-emerald-500 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span className="text-sm text-slate-300">
            Flushed <span className="font-semibold text-white">{lastAction.flushed}</span>
            {' '}at {lastAction.time.toLocaleTimeString()}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Salesforce Health ── */}
        <div className="glass rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
            <Activity className="w-4 h-4 text-brand-400" />
            <h2 className="text-sm font-semibold text-white">Salesforce Connection</h2>
            {sf.breaker_open
              ? <span className="ml-auto px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-500/10 text-red-400 border border-red-500/20">CIRCUIT OPEN</span>
              : <span className="ml-auto px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">HEALTHY</span>
            }
          </div>
          <div className="p-4 space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-slate-400">API Calls (last 60s)</span>
                <span className="text-sm font-bold text-white">{sf.calls_last_60s || 0} / {sf.rate_limit || 60}</span>
              </div>
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    (sf.calls_last_60s || 0) > (sf.rate_limit || 60) * 0.8 ? 'bg-red-500' :
                    (sf.calls_last_60s || 0) > (sf.rate_limit || 60) * 0.5 ? 'bg-amber-500' : 'bg-emerald-500'
                  }`}
                  style={{ width: `${Math.min(100, ((sf.calls_last_60s || 0) / (sf.rate_limit || 60)) * 100)}%` }}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <StatBox icon={<Zap className="w-3.5 h-3.5" />} label="Total Calls" value={sf.total_calls || 0} />
              <StatBox icon={<XCircle className="w-3.5 h-3.5" />} label="Errors"
                value={sf.errors || 0} color={sf.errors > 0 ? 'text-red-400' : 'text-emerald-400'} />
              <StatBox icon={<AlertTriangle className="w-3.5 h-3.5" />} label="Breaker Failures"
                value={sf.breaker_failures || 0} color={sf.breaker_failures > 0 ? 'text-amber-400' : 'text-slate-400'} />
              <StatBox icon={<Clock className="w-3.5 h-3.5" />} label="Rate Waits" value={sf.rate_waits || 0} />
            </div>
            {sf.breaker_open && (
              <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-3 text-sm text-red-300">
                Circuit breaker is OPEN — Salesforce calls are paused. App is serving cached data.
                The breaker will auto-retry after cooldown.
              </div>
            )}
          </div>
        </div>

        {/* ── Cache Status ── */}
        <div className="glass rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
            <Database className="w-4 h-4 text-brand-400" />
            <h2 className="text-sm font-semibold text-white">Cache</h2>
          </div>
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <StatBox label="Active Keys" value={c.alive || 0} color="text-emerald-400" />
              <StatBox label="Stale Keys" value={c.stale || 0} color="text-amber-400" />
              <StatBox label="Pending Fetches" value={c.pending_fetches || 0} color="text-brand-400" />
            </div>
            <div className="text-xs text-slate-500 bg-slate-900/50 rounded-lg p-3 leading-relaxed">
              <span className="text-slate-400 font-semibold">How it works: </span>
              Each endpoint caches results with a TTL. When cache expires, one thread fetches from
              Salesforce while others wait (no duplicate queries). If SF is down, stale cached data is served.
            </div>
          </div>
        </div>
      </div>

      {/* ── Flush Controls ── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <Trash2 className="w-4 h-4 text-red-400" />
          <h2 className="text-sm font-semibold text-white">Cache Controls</h2>
        </div>
        <div className="p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            <FlushCard
              title="Live / Operational"
              description="Command Center, Queue Board, Driver GPS, SA Lookup, Dispatch Map"
              ttl="TTL: 30s - 120s"
              color="blue"
              loading={flushing === 'live'}
              onClick={() => handleFlush('live', adminFlushLive)}
            />
            <FlushCard
              title="Historical / Analytics"
              description="Scorecard, Performance, Decomposition, Forecast, Score"
              ttl="TTL: 300s - 3600s"
              color="amber"
              loading={flushing === 'historical'}
              onClick={() => handleFlush('historical', adminFlushHistorical)}
            />
            <FlushCard
              title="Static / Reference"
              description="Garage List, Map Grids, Weather, Skills, Territories"
              ttl="TTL: 600s - 3600s"
              color="emerald"
              loading={flushing === 'static'}
              onClick={() => handleFlush('static', adminFlushStatic)}
            />
            <FlushCard
              title="Flush Everything"
              description="Clear all cached data. Next request will fetch fresh from Salesforce."
              ttl="Nuclear option"
              color="red"
              loading={flushing === 'all'}
              onClick={() => handleFlush('all', (p) => adminFlush(p))}
            />
          </div>
        </div>
      </div>

      {/* ── Cache TTL Reference ── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50">
          <h2 className="text-sm font-semibold text-white">Cache TTL Reference</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 px-4 font-medium">Endpoint</th>
                <th className="text-left py-2 px-4 font-medium">Cache Key</th>
                <th className="text-center py-2 px-4 font-medium">TTL</th>
                <th className="text-left py-2 px-4 font-medium">Category</th>
                <th className="text-left py-2 px-4 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {CACHE_ENTRIES.map((e, i) => (
                <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="py-2 px-4 text-slate-300 font-medium">{e.endpoint}</td>
                  <td className="py-2 px-4 text-slate-500 font-mono text-[10px]">{e.key}</td>
                  <td className="py-2 px-4 text-center">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      e.ttl <= 60 ? 'bg-blue-500/10 text-blue-400' :
                      e.ttl <= 600 ? 'bg-amber-500/10 text-amber-400' :
                      'bg-emerald-500/10 text-emerald-400'
                    }`}>{e.ttl}s</span>
                  </td>
                  <td className="py-2 px-4 text-slate-500">{e.category}</td>
                  <td className="py-2 px-4 text-slate-600">{e.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}


const CACHE_ENTRIES = [
  { endpoint: 'Command Center', key: 'command_center_{hours}', ttl: 120, category: 'Live', notes: 'Shared across all users' },
  { endpoint: 'Queue Board', key: 'queue_live', ttl: 30, category: 'Live', notes: 'Shared, auto-refresh 30s' },
  { endpoint: 'SA Lookup', key: 'sa_lookup_{number}', ttl: 30, category: 'Live', notes: 'Per SA number' },
  { endpoint: 'Map Drivers', key: 'map_drivers', ttl: 120, category: 'Live', notes: 'GPS positions' },
  { endpoint: 'Dispatch Map', key: 'simulate_{tid}_{date}', ttl: 120, category: 'Live', notes: 'Per territory per day' },
  { endpoint: 'Recommend Driver', key: 'recommend_{sa_id}', ttl: 60, category: 'Live', notes: 'Per SA' },
  { endpoint: 'Cascade', key: 'cascade_{tid}', ttl: 60, category: 'Live', notes: 'Per territory' },
  { endpoint: 'Score', key: 'scorer_{tid}_{days}', ttl: 300, category: 'Historical', notes: 'Composite score' },
  { endpoint: 'Scorecard', key: 'scorecard_{tid}_{weeks}', ttl: 3600, category: 'Historical', notes: 'Per territory' },
  { endpoint: 'Performance', key: 'perf_{tid}_{start}_{end}', ttl: 3600, category: 'Historical', notes: 'Per territory + period' },
  { endpoint: 'Decomposition', key: 'decomp_{tid}_{start}_{end}', ttl: 3600, category: 'Historical', notes: 'Response time breakdown' },
  { endpoint: 'Forecast', key: 'forecast_{tid}_{weeks}', ttl: 3600, category: 'Historical', notes: 'DOW + weather' },
  { endpoint: 'Garage List', key: 'garages_list', ttl: 600, category: 'Static', notes: 'All territories' },
  { endpoint: 'Map Grids', key: 'map_grids', ttl: 3600, category: 'Static', notes: 'Grid geometry' },
  { endpoint: 'Map Weather', key: 'map_weather', ttl: 900, category: 'Static', notes: 'Weather stations' },
  { endpoint: 'Skills', key: 'skills_{tid}', ttl: 3600, category: 'Static', notes: 'Per territory' },
  { endpoint: 'Priority Matrix', key: 'priority_matrix', ttl: 600, category: 'Static', notes: 'Ops dashboard' },
  { endpoint: 'Ops Territories', key: 'ops_territories', ttl: 120, category: 'Live', notes: 'Territory list with live counts' },
  { endpoint: 'PTA Advisor', key: 'pta_advisor', ttl: 900, category: 'Live', notes: 'Projected PTA, configurable interval' },
]


function StatBox({ icon, label, value, color = 'text-white' }) {
  return (
    <div className="bg-slate-900/50 rounded-lg p-3">
      <div className="flex items-center gap-1.5 text-slate-500 mb-1">
        {icon}
        <span className="text-[10px] uppercase tracking-wider">{label}</span>
      </div>
      <div className={`text-lg font-bold ${color}`}>{typeof value === 'number' ? value.toLocaleString() : value}</div>
    </div>
  )
}


function FlushCard({ title, description, ttl, color, loading, onClick }) {
  const colors = {
    blue: 'border-blue-500/20 hover:border-blue-500/40',
    amber: 'border-amber-500/20 hover:border-amber-500/40',
    emerald: 'border-emerald-500/20 hover:border-emerald-500/40',
    red: 'border-red-500/20 hover:border-red-500/40',
  }
  const btnColors = {
    blue: 'bg-blue-600 hover:bg-blue-500',
    amber: 'bg-amber-600 hover:bg-amber-500',
    emerald: 'bg-emerald-600 hover:bg-emerald-500',
    red: 'bg-red-600 hover:bg-red-500',
  }

  return (
    <div className={`rounded-xl border bg-slate-900/30 p-4 flex flex-col transition-colors ${colors[color]}`}>
      <h3 className="text-sm font-semibold text-white mb-1">{title}</h3>
      <p className="text-[11px] text-slate-500 leading-relaxed mb-1">{description}</p>
      <p className="text-[10px] text-slate-600 mb-3">{ttl}</p>
      <button
        onClick={onClick}
        disabled={loading}
        className={`mt-auto w-full py-2 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50
                    flex items-center justify-center gap-1.5 ${btnColors[color]}`}
      >
        {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
        {loading ? 'Flushing...' : 'Flush'}
      </button>
    </div>
  )
}
