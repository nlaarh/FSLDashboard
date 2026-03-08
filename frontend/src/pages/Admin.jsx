import { useState, useEffect, useCallback } from 'react'
import { Shield, Database, Activity, Trash2, RefreshCw, Loader2, CheckCircle2, AlertTriangle, XCircle, Zap, Clock, Server, Map, Users, UserPlus, Edit3, Trash, Eye, Radio } from 'lucide-react'
import { adminVerify, adminStatus, adminFlush, adminFlushLive, adminFlushHistorical, adminFlushStatic, adminListUsers, adminCreateUser, adminUpdateUser, adminDeleteUser, adminListSessions } from '../api'
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

  useEffect(() => {
    if (authed) {
      refresh()
      loadUsers()
      loadSessions()
      const id = setInterval(() => { refresh(); loadSessions() }, 5000)
      return () => clearInterval(id)
    }
  }, [authed, refresh, loadUsers, loadSessions])

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
