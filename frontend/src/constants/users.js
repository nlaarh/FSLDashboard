export const ROLES = ['superadmin', 'admin', 'executive', 'ers', 'finance', 'manager', 'officer', 'viewer']

export const DEPTS = [
  { value: '', label: '— None —' },
  { value: 'ers', label: 'ERS' },
  { value: 'finance', label: 'Finance' },
  { value: 'executive', label: 'Executive' },
]

export const DEPT_STYLE = {
  ers: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  finance: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  executive: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
}

export const ROLE_STYLE = {
  superadmin: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  admin: 'bg-brand-500/10 text-brand-400 border-brand-500/20',
  executive: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  ers: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  finance: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  manager: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  officer: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  supervisor: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  viewer: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
}
