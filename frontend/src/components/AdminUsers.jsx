import { useState, useEffect, useCallback, useMemo } from 'react'
import { Users, UserPlus, Edit3, Trash, Radio, CheckCircle2, Copy, RefreshCw, RotateCcw, EyeOff, LogIn, ChevronUp, ChevronDown, ChevronsUpDown, ShieldCheck, X, Send } from 'lucide-react'
import { adminListUsers, adminCreateUser, adminUpdateUser, adminDeleteUser, adminRestoreUser, adminListSessions, adminImpersonate } from '../api'
import { clsx } from 'clsx'
import AdminUserEditor from './AdminUserEditor'
import { DEPT_STYLE, ROLE_STYLE } from '../constants/users'
import { EMPTY_USER_FORM, FORM_PASSWORD_COPY_KEY, generatePassword, passwordIssues } from '../utils/passwords'

export default function AdminUsers({ pin }) {
  const [userList, setUserList] = useState([])
  const [sessions, setSessions] = useState([])
  const [showUserForm, setShowUserForm] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [userForm, setUserForm] = useState(EMPTY_USER_FORM)
  const [userError, setUserError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  const [userSaving, setUserSaving] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [passwordChangeOpen, setPasswordChangeOpen] = useState(false)
  const [copied, setCopied] = useState(null) // username of copied password
  const [generatedPw, setGeneratedPw] = useState({}) // username -> last generated pw (in-memory only)
  const [emailUrl, setEmailUrl] = useState(null) // Outlook compose URL for welcome / password changed
  const [emailSubject, setEmailSubject] = useState('')
  const [emailBody, setEmailBody] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [actionError, setActionError] = useState('')
  const [currentUser, setCurrentUser] = useState(null)
  // Sorting
  const [sortCol, setSortCol] = useState('username')
  const [sortDir, setSortDir] = useState('asc')
  // Certify Access
  const [showCertify, setShowCertify] = useState(false)
  const [certifyDecisions, setCertifyDecisions] = useState({}) // username -> 'keep'|'remove'
  const [certifyStep, setCertifyStep] = useState('review') // 'review' | 'confirm' | 'done'
  const [certifyApplying, setCertifyApplying] = useState(false)
  const [certifyDone, setCertifyDone] = useState(null) // list of suspended usernames after apply
  const [certifyEmailRecipient, setCertifyEmailRecipient] = useState('')
  const [showCertifyEmail, setShowCertifyEmail] = useState(false)
  const [certifyEmailCopied, setCertifyEmailCopied] = useState(false)

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
    fetch('/api/auth/me').then(r => r.ok ? r.json() : {}).then(d => setCurrentUser(d)).catch(() => {})
    const id = setInterval(loadSessions, 5000)
    return () => clearInterval(id)
  }, [loadUsers, loadSessions])

  const closeUserForm = () => {
    setShowUserForm(false)
    setEditingUser(null)
    setPasswordChangeOpen(false)
    setShowPassword(false)
    setUserError('')
    setSaveMessage('')
    setCopied(null)
    setGeneratedPw({})
    setEmailUrl(null)
    setEmailSubject('')
    setEmailBody('')
  }

  const openCreateUser = () => {
    const pw = generatePassword()
    setEditingUser(null)
    setUserForm({ ...EMPTY_USER_FORM, password: pw, passwordConfirm: pw })
    setShowPassword(true)
    setPasswordChangeOpen(true)
    setUserError('')
    setSaveMessage('')
    setCopied(null)
    setShowUserForm(true)
  }

  const openEditUser = (u) => {
    setEditingUser(u.username)
    setUserForm({ username: u.username, password: '', passwordConfirm: '', name: u.name, role: u.role, email: u.email || '', phone: u.phone || '', department: u.department || '', garages: u.garages || [] })
    setShowPassword(false)
    setPasswordChangeOpen(false)
    setUserError('')
    setSaveMessage('')
    setCopied(null)
    setShowUserForm(true)
  }

  const beginPasswordChange = () => {
    setPasswordChangeOpen(true)
    setUserForm(f => ({ ...f, password: '', passwordConfirm: '' }))
    setShowPassword(false)
    setUserError('')
    setSaveMessage('')
    setCopied(null)
  }

  const generateFormPassword = () => {
    const pw = generatePassword()
    setPasswordChangeOpen(true)
    setUserForm(f => ({ ...f, password: pw, passwordConfirm: pw }))
    setShowPassword(true)
    setUserError('')
    setSaveMessage('Generated password is ready. Copy it or update the user to apply it.')
    setCopied(null)
  }

  const copyFormPassword = () => {
    if (!userForm.password) return
    navigator.clipboard.writeText(userForm.password)
    setCopied(FORM_PASSWORD_COPY_KEY)
    setTimeout(() => setCopied(null), 2000)
  }

  const validatePassword = () => {
    if (!userForm.password || !userForm.passwordConfirm) return 'Enter and confirm the new password'
    if (userForm.password !== userForm.passwordConfirm) return 'Passwords do not match'
    const issues = passwordIssues(userForm.password)
    if (issues.length) return `Password must include: ${issues.join(', ')}`
    return ''
  }

  const saveUser = async () => {
    setUserError('')
    setSaveMessage('')
    setUserSaving(true)
    try {
      if (editingUser) {
        const changingPassword = passwordChangeOpen || userForm.password || userForm.passwordConfirm
        if (changingPassword) {
          const passwordError = validatePassword()
          if (passwordError) {
            setUserError(passwordError)
            return
          }
        }
        const data = { name: userForm.name, role: userForm.role, email: userForm.email, phone: userForm.phone, department: userForm.department, garages: userForm.garages || [] }
        if (changingPassword) data.password = userForm.password
        const result = await adminUpdateUser(pin, editingUser, data)
        if (changingPassword) {
          setSaveMessage(`Password changed for ${editingUser}. Copy it before closing.`)
          setShowPassword(true)
          if (result?.password_changed_email_url) setEmailUrl(result.password_changed_email_url)
          if (result?.email_subject) setEmailSubject(result.email_subject)
          if (result?.email_body) setEmailBody(result.email_body)
          loadUsers()
          return
        }
      } else {
        if (!userForm.username || !userForm.name) {
          setUserError('Username, name, and password are required')
          return
        }
        const passwordError = validatePassword()
        if (passwordError) {
          setUserError(passwordError)
          return
        }
        const result = await adminCreateUser(pin, { ...userForm })
        showPwTemporarily(userForm.username, userForm.password)
        setEditingUser(userForm.username)
        setSaveMessage(`User ${userForm.username} created. Copy the password before closing.`)
        setShowPassword(true)
        if (result?.welcome_email_url) setEmailUrl(result.welcome_email_url)
        if (result?.email_subject) setEmailSubject(result.email_subject)
        if (result?.email_body) setEmailBody(result.email_body)
        loadUsers()
        return
      }
      closeUserForm()
      loadUsers()
    } catch (e) {
      setUserError(e.response?.data?.detail || 'Error saving user')
    } finally { setUserSaving(false) }
  }

  const deleteUser = async (username) => {
    if (!confirm(`Deactivate user "${username}"? They won't be able to log in. You can restore them later.`)) return
    setActionError('')
    try {
      await adminDeleteUser(pin, username)
      loadUsers()
    } catch (e) {
      setActionError(e.response?.data?.detail || `Failed to deactivate ${username}`)
    }
  }

  const restoreUser = async (username) => {
    setActionError('')
    try {
      await adminRestoreUser(pin, username)
      loadUsers()
    } catch (e) {
      setActionError(e.response?.data?.detail || `Failed to restore ${username}`)
    }
  }

  const loginAs = async (u) => {
    try {
      // Server sets the httponly cookie directly — no JS cookie manipulation needed
      const data = await adminImpersonate(pin, u.username)
      sessionStorage.setItem('impersonating', JSON.stringify({
        name: data.name, role: data.role,
        originCookie: data.origin_cookie || '',
      }))
      window.location.href = '/'
    } catch (e) {
      setActionError(e?.response?.data?.detail || 'Failed to impersonate')
    }
  }

  const toggleActive = async (u) => {
    try {
      await adminUpdateUser(pin, u.username, { active: !u.active })
      loadUsers()
    } catch { /* ignore */ }
  }

  const showPwTemporarily = (username, pw) => {
    setGeneratedPw(prev => ({ ...prev, [username]: pw }))
    setTimeout(() => setGeneratedPw(prev => { const n = { ...prev }; delete n[username]; return n }), 60000)
  }

  const resetPassword = (user) => {
    openEditUser(user)
    setPasswordChangeOpen(true)
    const pw = generatePassword()
    setUserForm(f => ({ ...f, password: pw, passwordConfirm: pw }))
    setShowPassword(true)
    setSaveMessage('Generated password is ready. Copy it or update the user to apply it.')
  }

  const copyPassword = (username) => {
    const pw = generatedPw[username]
    if (pw) {
      navigator.clipboard.writeText(pw)
      setCopied(username)
      setTimeout(() => setCopied(null), 2000)
    }
  }

  const toggleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const SortIcon = ({ col }) => {
    if (sortCol !== col) return <ChevronsUpDown className="w-3 h-3 opacity-30" />
    return sortDir === 'asc' ? <ChevronUp className="w-3 h-3 text-brand-400" /> : <ChevronDown className="w-3 h-3 text-brand-400" />
  }

  const openCertifyModal = () => {
    const initial = {}
    userList.filter(u => u.active).forEach(u => { initial[u.username] = 'keep' })
    setCertifyDecisions(initial)
    setCertifyStep('review')
    setCertifyDone(null)
    setCertifyEmailRecipient('')
    setShowCertifyEmail(false)
    setShowCertify(true)
  }

  const certifyToRemove = userList.filter(u => u.active && certifyDecisions[u.username] === 'remove')

  const openCertifyReviewEmail = async () => {
    const activeUsers = userList.filter(u => u.active)
    const today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
    const rowsHtml = activeUsers.map((u, i) => `
      <tr style="background:${i % 2 === 0 ? '#ffffff' : '#f8f9fa'}">
        <td style="padding:8px 12px;border:1px solid #dee2e6">${u.name || ''}</td>
        <td style="padding:8px 12px;border:1px solid #dee2e6">${u.username || ''}</td>
        <td style="padding:8px 12px;border:1px solid #dee2e6">${u.role || ''}</td>
        <td style="padding:8px 12px;border:1px solid #dee2e6">${u.department || '—'}</td>
      </tr>`).join('')
    const html = `
      <p>Hi,</p>
      <p>Please review the list of active <strong>FleetPulse</strong> users below as of <strong>${today}</strong>.<br>
      Reply to this email with the names or usernames of any users whose access should be <strong>removed</strong>.</p>
      <table style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;width:100%;max-width:700px">
        <thead>
          <tr style="background:#1e3a5f;color:#ffffff">
            <th style="padding:10px 12px;border:1px solid #1e3a5f;text-align:left;color:#ffffff;background:#1e3a5f">Name</th>
            <th style="padding:10px 12px;border:1px solid #1e3a5f;text-align:left;color:#ffffff;background:#1e3a5f">Username</th>
            <th style="padding:10px 12px;border:1px solid #1e3a5f;text-align:left;color:#ffffff;background:#1e3a5f">Role</th>
            <th style="padding:10px 12px;border:1px solid #1e3a5f;text-align:left;color:#ffffff;background:#1e3a5f">Department</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
      <p style="color:#6c757d;font-size:12px">Total active users: ${activeUsers.length}</p>
      <p>Thank you,<br>FleetPulse Admin</p>`
    try {
      await navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }) })])
      setCertifyEmailCopied(true)
      setTimeout(() => setCertifyEmailCopied(false), 8000)
    } catch { /* clipboard write failed — still open Outlook */ }
    const subject = `FleetPulse Access Review — ${today}`
    const url = `https://outlook.cloud.microsoft/mail/deeplink/compose?to=${encodeURIComponent(certifyEmailRecipient)}&subject=${encodeURIComponent(subject)}`
    window.open(url, '_blank')
  }

  const applyCertify = async () => {
    setCertifyApplying(true)
    const suspended = []
    for (const u of certifyToRemove) {
      try {
        await adminDeleteUser(pin, u.username)
        suspended.push(u)
      } catch { /* ignore individual failures */ }
    }
    await loadUsers()
    setCertifyApplying(false)
    setCertifyDone(suspended)
    setCertifyStep('done')
  }

  const inactiveCount = userList.filter(u => !u.active).length
  const displayedUsers = useMemo(() => {
    const filtered = userList.filter(u => showInactive || u.active)
    return [...filtered].sort((a, b) => {
      let av = '', bv = ''
      if (sortCol === 'username') { av = a.username || ''; bv = b.username || '' }
      else if (sortCol === 'name') { av = a.name || ''; bv = b.name || '' }
      else if (sortCol === 'role') { av = a.role || ''; bv = b.role || '' }
      else if (sortCol === 'department') { av = a.department || ''; bv = b.department || '' }
      else if (sortCol === 'status') { av = a.active ? '1' : '0'; bv = b.active ? '1' : '0' }
      return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
    })
  }, [userList, showInactive, sortCol, sortDir])
  const fmtSessionTime = (epoch) => epoch
    ? new Date(epoch * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : '—'

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* User Management */}
      <div className="lg:col-span-2 glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <Users className="w-4 h-4 text-brand-400" />
          <h2 className="text-sm font-semibold text-white">Users</h2>
          <span className="ml-1 text-xs text-slate-500">({userList.filter(u => u.active).length} active)</span>
          {inactiveCount > 0 && (
            <button
              onClick={() => setShowInactive(s => !s)}
              className={clsx('flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-colors border',
                showInactive
                  ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                  : 'text-slate-500 border-slate-700/40 hover:text-slate-300'
              )}
            >
              <EyeOff className="w-3 h-3" />
              {showInactive ? 'Hide' : 'Show'} deactivated ({inactiveCount})
            </button>
          )}
          {actionError && (
            <span className="text-[10px] text-red-400 ml-1 truncate max-w-[200px]">{actionError}</span>
          )}
          <button onClick={openCertifyModal}
            className="ml-auto px-2.5 py-1 text-[11px] bg-slate-700 hover:bg-slate-600 rounded-lg font-semibold
                       flex items-center gap-1 transition-colors border border-slate-600/50">
            <ShieldCheck className="w-3 h-3 text-amber-400" /> Certify Access
          </button>
          <button onClick={openCreateUser}
            className="px-2.5 py-1 text-[11px] bg-brand-600 hover:bg-brand-500 rounded-lg font-semibold
                       flex items-center gap-1 transition-colors">
            <UserPlus className="w-3 h-3" /> Add User
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                {[['username','Username'],['name','Name'],['role','Role'],['department','Dept']].map(([col, label]) => (
                  <th key={col} className="text-left py-2.5 px-4 font-medium cursor-pointer hover:text-slate-300 select-none"
                    onClick={() => toggleSort(col)}>
                    <span className="inline-flex items-center gap-1">{label}<SortIcon col={col} /></span>
                  </th>
                ))}
                <th className="text-center py-2.5 px-4 font-medium">Password</th>
                <th className="text-center py-2.5 px-4 font-medium cursor-pointer hover:text-slate-300 select-none"
                  onClick={() => toggleSort('status')}>
                  <span className="inline-flex items-center gap-1">Status<SortIcon col="status" /></span>
                </th>
                <th className="text-right py-2.5 px-4 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {displayedUsers.map(u => (
                <tr key={u.username} className={clsx('border-b border-slate-800/50 hover:bg-slate-800/30', !u.active && 'opacity-50')}>
                  <td className="py-2.5 px-4">
                    <div className="text-slate-300 font-medium">{u.username}</div>
                    {u.email && <div className="text-[10px] text-slate-600">{u.email}</div>}
                    {u.phone && <div className="text-[10px] text-slate-600">{u.phone}</div>}
                  </td>
                  <td className="py-2.5 px-4 text-slate-300">{u.name}</td>
                  <td className="py-2.5 px-4">
                    <span className={clsx('px-2 py-0.5 rounded text-[10px] font-bold border',
                      ROLE_STYLE[u.role] || ROLE_STYLE.viewer)}>
                      {u.role === 'contractor' && (u.garages?.length > 0)
                        ? `contractor (${u.garages.length} garage${u.garages.length !== 1 ? 's' : ''})`
                        : u.role}
                    </span>
                  </td>
                  <td className="py-2.5 px-4">
                    {u.department ? (
                      <span className={clsx('px-2 py-0.5 rounded text-[10px] font-bold border',
                        DEPT_STYLE[u.department] || 'bg-slate-500/10 text-slate-400 border-slate-500/20')}>
                        {u.department}
                      </span>
                    ) : <span className="text-[10px] text-slate-600">—</span>}
                  </td>
                  <td className="py-2.5 px-4 text-center">
                    <div className="flex items-center justify-center gap-1">
                      {generatedPw[u.username] ? (
                        <>
                          <code className="text-[10px] text-emerald-400 bg-emerald-950/30 px-1.5 py-0.5 rounded font-mono">
                            {generatedPw[u.username]}
                          </code>
                          <button onClick={() => copyPassword(u.username)} title="Copy password"
                            className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-white transition">
                            {copied === u.username ? <CheckCircle2 className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                          </button>
                        </>
                      ) : (
                        <span className="text-[10px] text-slate-600">••••••</span>
                      )}
                      {u.active && (
                        <button onClick={() => resetPassword(u)} title="Change password"
                          className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-amber-400 transition">
                          <RefreshCw className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 px-4 text-center">
                    <span className={clsx('px-2 py-0.5 rounded text-[10px] font-bold border',
                      u.active
                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                        : 'bg-slate-700/30 text-slate-500 border-slate-700/30'
                    )}>
                      {u.active ? 'Active' : 'Deactivated'}
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      {u.active ? (
                        <>
                          <button onClick={() => openEditUser(u)} title="Edit user"
                            className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-500 hover:text-white transition-colors">
                            <Edit3 className="w-3 h-3" />
                          </button>
                          <button onClick={() => deleteUser(u.username)} title="Deactivate user"
                            className="p-1.5 rounded-lg hover:bg-red-900/30 text-slate-500 hover:text-red-400 transition-colors">
                            <Trash className="w-3 h-3" />
                          </button>
                          {currentUser?.role === 'superadmin' && u.active && u.username !== currentUser?.user && (
                            <button onClick={() => loginAs(u)} title={`Log in as ${u.name}`}
                              className="p-1.5 rounded-lg hover:bg-indigo-900/30 text-slate-500 hover:text-indigo-400 transition-colors">
                              <LogIn className="w-3 h-3" />
                            </button>
                          )}
                        </>
                      ) : (
                        <button onClick={() => restoreUser(u.username)} title="Restore user"
                          className="p-1.5 rounded-lg hover:bg-emerald-900/30 text-slate-500 hover:text-emerald-400 transition-colors flex items-center gap-1 text-[10px]">
                          <RotateCcw className="w-3 h-3" /> Restore
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {displayedUsers.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-slate-600">No users</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {showUserForm && (
          <AdminUserEditor
            pin={pin}
            editingUser={editingUser}
            userForm={userForm}
            setUserForm={setUserForm}
            userError={userError}
            saveMessage={saveMessage}
            userSaving={userSaving}
            showPassword={showPassword}
            setShowPassword={setShowPassword}
            passwordChangeOpen={passwordChangeOpen}
            beginPasswordChange={beginPasswordChange}
            generateFormPassword={generateFormPassword}
            copyFormPassword={copyFormPassword}
            copied={copied}
            emailUrl={emailUrl}
            emailSubject={emailSubject}
            emailBody={emailBody}
            onClose={closeUserForm}
            onSave={saveUser}
          />
        )}
      </div>

      {/* Active Sessions */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
          <Radio className="w-4 h-4 text-emerald-400" />
          <h2 className="text-sm font-semibold text-white">Who's Online Now</h2>
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
                <div className="text-[10px] text-slate-600">
                  In {fmtSessionTime(s.login_time)} · seen {fmtSessionTime(s.last_seen)}
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

      {/* Certify Access Modal */}
      {showCertify && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="glass rounded-xl w-full max-w-2xl max-h-[90vh] flex flex-col">

            {/* Header */}
            <div className="px-5 py-4 border-b border-slate-700/50 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-semibold text-white flex-1">
                {certifyStep === 'review' && 'Certify User Access'}
                {certifyStep === 'confirm' && 'Confirm Suspension'}
                {certifyStep === 'done' && 'Access Updated'}
              </h2>
              <button onClick={() => setShowCertify(false)} className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-white transition">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Step 1 — Review table */}
            {certifyStep === 'review' && (
              <>
                <div className="overflow-y-auto flex-1 p-2">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-slate-500 border-b border-slate-800">
                        <th className="text-left py-2 px-3 font-medium">Name</th>
                        <th className="text-left py-2 px-3 font-medium">Username</th>
                        <th className="text-left py-2 px-3 font-medium">Role</th>
                        <th className="text-center py-2 px-3 font-medium">Keep</th>
                        <th className="text-center py-2 px-3 font-medium">Remove</th>
                      </tr>
                    </thead>
                    <tbody>
                      {userList.filter(u => u.active).map(u => (
                        <tr key={u.username} className={clsx('border-b border-slate-800/50 hover:bg-slate-800/30',
                          certifyDecisions[u.username] === 'remove' && 'bg-red-950/20')}>
                          <td className="py-2 px-3 text-slate-300">{u.name}</td>
                          <td className="py-2 px-3 text-slate-400">{u.username}</td>
                          <td className="py-2 px-3">
                            <span className={clsx('px-2 py-0.5 rounded text-[10px] font-bold border', ROLE_STYLE[u.role] || ROLE_STYLE.viewer)}>
                              {u.role}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-center">
                            <input type="radio" name={`cert-${u.username}`} value="keep"
                              checked={certifyDecisions[u.username] === 'keep'}
                              onChange={() => setCertifyDecisions(d => ({ ...d, [u.username]: 'keep' }))}
                              className="accent-emerald-500 cursor-pointer w-4 h-4" />
                          </td>
                          <td className="py-2 px-3 text-center">
                            <input type="radio" name={`cert-${u.username}`} value="remove"
                              checked={certifyDecisions[u.username] === 'remove'}
                              onChange={() => setCertifyDecisions(d => ({ ...d, [u.username]: 'remove' }))}
                              className="accent-red-500 cursor-pointer w-4 h-4" />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-5 py-4 border-t border-slate-700/50 space-y-3">
                  {/* Email for review */}
                  <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[11px] text-slate-400">
                        Send active user list to someone for review — they reply with who to remove
                      </span>
                      <button onClick={openCertifyReviewEmail}
                        className="px-3 py-1.5 text-xs bg-brand-600 hover:bg-brand-500 rounded-lg font-semibold flex items-center gap-1.5 transition-colors whitespace-nowrap flex-shrink-0">
                        <Send className="w-3 h-3" /> Email List
                      </button>
                    </div>
                    {certifyEmailCopied && (
                      <p className="mt-2 text-[11px] text-emerald-400 font-medium">
                        Table copied to clipboard — paste into the email body with Ctrl+V (or ⌘V)
                      </p>
                    )}
                  </div>

                  {/* Apply changes */}
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-500">
                      {certifyToRemove.length > 0
                        ? <span className="text-red-400 font-semibold">{certifyToRemove.length} user{certifyToRemove.length > 1 ? 's' : ''} marked for removal</span>
                        : 'No changes — all users marked Keep'}
                    </span>
                    <div className="flex gap-2">
                      <button onClick={() => setShowCertify(false)}
                        className="px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors">
                        Cancel
                      </button>
                      <button
                        onClick={() => setCertifyStep('confirm')}
                        disabled={certifyToRemove.length === 0}
                        className="px-3 py-1.5 text-xs bg-red-700 hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg font-semibold transition-colors">
                        Review Changes →
                      </button>
                    </div>
                  </div>
                </div>
              </>
            )}

            {/* Step 2 — Confirm */}
            {certifyStep === 'confirm' && (
              <>
                <div className="flex-1 overflow-y-auto p-5 space-y-4">
                  <div className="p-3 rounded-lg bg-red-950/40 border border-red-700/40 text-xs text-red-300">
                    The following {certifyToRemove.length} user{certifyToRemove.length > 1 ? 's' : ''} will be <strong>suspended immediately</strong> and will no longer be able to log in.
                    This action can be reversed from the Users table (Restore button).
                  </div>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-slate-500 border-b border-slate-800">
                        <th className="text-left py-2 px-2 font-medium">Name</th>
                        <th className="text-left py-2 px-2 font-medium">Username</th>
                        <th className="text-left py-2 px-2 font-medium">Role</th>
                      </tr>
                    </thead>
                    <tbody>
                      {certifyToRemove.map(u => (
                        <tr key={u.username} className="border-b border-red-900/30 bg-red-950/10">
                          <td className="py-2 px-2 text-red-300 font-medium">{u.name}</td>
                          <td className="py-2 px-2 text-red-400">{u.username}</td>
                          <td className="py-2 px-2">
                            <span className={clsx('px-2 py-0.5 rounded text-[10px] font-bold border', ROLE_STYLE[u.role] || ROLE_STYLE.viewer)}>
                              {u.role}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-5 py-4 border-t border-slate-700/50 flex items-center justify-between">
                  <button onClick={() => setCertifyStep('review')}
                    className="px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors">
                    ← Back
                  </button>
                  <button onClick={applyCertify} disabled={certifyApplying}
                    className="px-4 py-1.5 text-xs bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg font-semibold flex items-center gap-1.5 transition-colors">
                    {certifyApplying ? 'Suspending…' : `Confirm — Suspend ${certifyToRemove.length} User${certifyToRemove.length > 1 ? 's' : ''}`}
                  </button>
                </div>
              </>
            )}

            {/* Step 3 — Done */}
            {certifyStep === 'done' && (
              <>
                <div className="flex-1 p-5 space-y-4">
                  <div className="p-3 rounded-lg bg-emerald-950/30 border border-emerald-700/30 text-xs text-emerald-300">
                    Done. {certifyDone?.length} user{certifyDone?.length !== 1 ? 's' : ''} suspended successfully.
                  </div>
                  {certifyDone?.length > 0 && (
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-800">
                          <th className="text-left py-2 px-2 font-medium">Name</th>
                          <th className="text-left py-2 px-2 font-medium">Username</th>
                        </tr>
                      </thead>
                      <tbody>
                        {certifyDone.map(u => (
                          <tr key={u.username} className="border-b border-slate-800/50">
                            <td className="py-2 px-2 text-slate-400">{u.name}</td>
                            <td className="py-2 px-2 text-slate-500">{u.username}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                <div className="px-5 py-4 border-t border-slate-700/50 flex justify-end">
                  <button onClick={() => setShowCertify(false)}
                    className="px-4 py-1.5 text-xs bg-brand-600 hover:bg-brand-500 rounded-lg font-semibold transition-colors">
                    Close
                  </button>
                </div>
              </>
            )}

          </div>
        </div>
      )}
    </div>
  )
}
