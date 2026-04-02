import { useState, useEffect, useCallback } from 'react'
import { Users, UserPlus, Edit3, Trash, Radio, Loader2, CheckCircle2 } from 'lucide-react'
import { adminListUsers, adminCreateUser, adminUpdateUser, adminDeleteUser, adminListSessions } from '../api'

const ROLES = ['admin', 'supervisor', 'viewer']

export default function AdminUsers({ pin }) {
  const [userList, setUserList] = useState([])
  const [sessions, setSessions] = useState([])
  const [showUserForm, setShowUserForm] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [userForm, setUserForm] = useState({ username: '', password: '', name: '', role: 'viewer' })
  const [userError, setUserError] = useState('')
  const [userSaving, setUserSaving] = useState(false)

  const loadUsers = useCallback(async () => {
    try {
      const u = await adminListUsers(pin)
      setUserList(u)
    } catch { /* ignore */ }
  }, [pin])

  const loadSessions = useCallback(async () => {
    try {
      const s = await adminListSessions(pin)
      setSessions(s)
    } catch { /* ignore */ }
  }, [pin])

  useEffect(() => {
    loadUsers()
    loadSessions()
    const id = setInterval(loadSessions, 5000)
    return () => clearInterval(id)
  }, [loadUsers, loadSessions])

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

  return (
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
  )
}
