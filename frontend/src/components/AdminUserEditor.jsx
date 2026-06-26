import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Copy, Eye, EyeOff, ExternalLink, KeyRound, Loader2, Mail, RefreshCw, X } from 'lucide-react'
import { clsx } from 'clsx'
import { DEPTS, ROLES } from '../constants/users'
import { FORM_PASSWORD_COPY_KEY, passwordChecks, passwordIssues } from '../utils/passwords'
import AdminGaragePicker from './AdminGaragePicker'

export default function AdminUserEditor({
  pin,
  editingUser,
  userForm,
  setUserForm,
  userError,
  saveMessage,
  userSaving,
  showPassword,
  setShowPassword,
  passwordChangeOpen,
  beginPasswordChange,
  generateFormPassword,
  copyFormPassword,
  copied,
  emailUrl,
  emailSubject,
  emailBody,
  onClose,
  onSave,
}) {
  const [emailCopied, setEmailCopied] = useState(false)
  const passwordSectionOpen = !editingUser || passwordChangeOpen
  const checks = passwordChecks(userForm.password)
  const currentPasswordIssues = passwordSectionOpen ? passwordIssues(userForm.password) : []
  const passwordsMatch = !!userForm.password && userForm.password === userForm.passwordConfirm
  const passwordReady = !passwordSectionOpen || (passwordsMatch && currentPasswordIssues.length === 0)
  const canSave = !userSaving && passwordReady

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 backdrop-blur-sm sm:p-6">
      <button className="absolute inset-0 h-full w-full cursor-default" onClick={onClose} aria-label="Close user editor" />
      <section className="relative flex flex-col w-full max-w-3xl max-h-[calc(100vh-1.5rem)] overflow-hidden rounded-xl border border-slate-700/70 bg-slate-950 shadow-2xl shadow-black/40">
        <header className="flex-shrink-0 flex items-center gap-3 border-b border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur sm:px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600/15 text-brand-300">
            <KeyRound className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-white">
              {editingUser ? `Edit ${editingUser}` : 'Create user'}
            </h3>
            <p className="text-[11px] text-slate-500">
              {editingUser ? 'Update profile details or change the account password.' : 'Create the user and copy the generated password before closing.'}
            </p>
          </div>
          <button
            onClick={onClose}
            title="Close"
            className="ml-auto rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-800 hover:text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-5 sm:py-5">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="Username">
              <input
                value={userForm.username}
                onChange={e => setUserForm(f => ({ ...f, username: e.target.value }))}
                disabled={!!editingUser}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20 disabled:opacity-50"
                placeholder="user@nyaaa.com"
              />
            </Field>
            <Field label="Name">
              <input
                value={userForm.name}
                onChange={e => setUserForm(f => ({ ...f, name: e.target.value }))}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20"
                placeholder="Full name"
              />
            </Field>
            <Field label="Role">
              <select
                value={userForm.role}
                onChange={e => setUserForm(f => ({ ...f, role: e.target.value }))}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20"
              >
                {ROLES.map(role => <option key={role} value={role}>{role}</option>)}
              </select>
            </Field>
            <Field label="Department">
              <select
                value={userForm.department}
                onChange={e => setUserForm(f => ({ ...f, department: e.target.value }))}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20"
              >
                {DEPTS.map(dept => <option key={dept.value} value={dept.value}>{dept.label}</option>)}
              </select>
            </Field>
            <Field label="Email">
              <input
                type="email"
                value={userForm.email}
                onChange={e => setUserForm(f => ({ ...f, email: e.target.value }))}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20"
                placeholder="user@nyaaa.com"
              />
            </Field>
            <Field label="Phone">
              <input
                type="tel"
                value={userForm.phone}
                onChange={e => setUserForm(f => ({ ...f, phone: e.target.value }))}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20"
                placeholder="(555) 123-4567"
              />
            </Field>
          </div>

          {/* Garage picker — contractor role only */}
          {userForm.role === 'contractor' && (
            <div className="mt-4">
              <AdminGaragePicker
                pin={pin}
                selected={userForm.territories || []}
                onChange={ids => setUserForm(f => ({ ...f, territories: ids }))}
              />
            </div>
          )}

          <section className="mt-5 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <h4 className="text-sm font-semibold text-white">Password</h4>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  Use a strong password, then copy it before closing the editor.
                </p>
              </div>
              {editingUser && !passwordChangeOpen && (
                <button
                  onClick={beginPasswordChange}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/15 focus:outline-none focus:ring-2 focus:ring-amber-500/30"
                >
                  <KeyRound className="h-3.5 w-3.5" />
                  Change password
                </button>
              )}
            </div>

            {passwordSectionOpen && (
              <div className="mt-4 space-y-3">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <Field label="New password">
                    <PasswordInput
                      value={userForm.password}
                      onChange={value => setUserForm(f => ({ ...f, password: value }))}
                      showPassword={showPassword}
                      toggle={() => setShowPassword(!showPassword)}
                    />
                  </Field>
                  <Field label="Confirm password">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={userForm.passwordConfirm}
                      onChange={e => setUserForm(f => ({ ...f, passwordConfirm: e.target.value }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-mono text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20"
                      placeholder="Confirm password"
                    />
                  </Field>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={generateFormPassword}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-amber-500/40 hover:text-amber-300 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Generate
                  </button>
                  <button
                    onClick={copyFormPassword}
                    disabled={!userForm.password}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-emerald-500/40 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
                  >
                    {copied === FORM_PASSWORD_COPY_KEY ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                    Copy password
                  </button>
                </div>

                <div className="grid grid-cols-1 gap-2 rounded-lg bg-slate-950/70 p-3 sm:grid-cols-2">
                  {checks.map(check => (
                    <div key={check.key} className={clsx('flex items-center gap-2 text-[11px]', check.ok ? 'text-emerald-300' : 'text-slate-500')}>
                      <CheckCircle2 className={clsx('h-3.5 w-3.5', check.ok ? 'opacity-100' : 'opacity-25')} />
                      {check.label}
                    </div>
                  ))}
                  <div className={clsx('flex items-center gap-2 text-[11px]', passwordsMatch ? 'text-emerald-300' : 'text-slate-500')}>
                    <CheckCircle2 className={clsx('h-3.5 w-3.5', passwordsMatch ? 'opacity-100' : 'opacity-25')} />
                    Passwords match
                  </div>
                </div>
              </div>
            )}
          </section>

          {userError && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-950/30 px-3 py-2 text-xs text-red-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
              <span>{userError}</span>
            </div>
          )}
          {saveMessage && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-300">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
              <span className="flex-1">{saveMessage}</span>
              {emailBody && (
                <Mail
                  onClick={() => {
                    navigator.clipboard.writeText(emailBody)
                    setEmailCopied(true)
                    setTimeout(() => setEmailCopied(false), 3000)
                    window.open('https://outlook.cloud.microsoft/mail', '_blank')
                  }}
                  title="Copy email text and open Outlook"
                  className="h-3.5 w-3.5 cursor-pointer"
                />
              )}
            </div>
          )}
        </div>

        <footer className="flex-shrink-0 flex flex-wrap justify-end gap-2 border-t border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur sm:px-5">
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:bg-slate-800 hover:text-white focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          >
            Close
          </button>
          <button
            onClick={onSave}
            disabled={!canSave}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          >
            {userSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            {editingUser ? 'Save changes' : 'Create user'}
          </button>
        </footer>
      </section>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="min-w-0">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      {children}
    </label>
  )
}

function PasswordInput({ value, onChange, showPassword, toggle }) {
  return (
    <div className="flex min-w-0 gap-1">
      <input
        type={showPassword ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-mono text-slate-200 outline-none transition focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/20"
        placeholder="New password"
      />
      <button
        onClick={toggle}
        title="Toggle visibility"
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-800 text-slate-500 transition hover:text-white focus:outline-none focus:ring-2 focus:ring-brand-500/30"
      >
        {showPassword ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}
