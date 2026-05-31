import {
  CheckCircle2,
  Cloud,
  Cpu,
  Database,
  ExternalLink,
  GitBranch,
  Layers,
  Map,
  Mail,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Zap,
} from 'lucide-react'
import { clsx } from 'clsx'

export const SERVICE_LABELS = {
  salesforce: 'SALESFORCE',
  postgres: 'PRIMARY DB',
  dr_postgres: 'FSLAPP-PG DR',
  app: 'FLEETPULSE APP',
  app_dr: 'FLEETPULSE DR',
  salespulse: 'SALESPULSE APP',
  salespulse_dr: 'SALESPULSE DR',
  cache: 'CACHE',
  azure: 'AZURE APP SVC',
  openai: 'OPENAI SVC',
  github: 'GITHUB REPO',
  google_maps: 'GOOGLE MAPS',
  agentmail: 'AGENTMAIL',
  duckdb: 'DUCKDB',
}

export const TOPOLOGY_ORDER = ['salesforce', 'cache', 'app', 'salespulse', 'openai', 'postgres', 'app_dr', 'salespulse_dr', 'dr_postgres', 'github', 'azure']
export const SERVICE_ORDER = ['salesforce', 'postgres', 'app', 'salespulse', 'cache', 'azure', 'openai', 'github', 'google_maps', 'agentmail', 'duckdb']

export function normalizeStatus(status) {
  if (status === 'healthy') return 'online'
  if (status === 'unhealthy') return 'offline'
  return status || 'offline'
}

export function statusTone(status) {
  const normalized = normalizeStatus(status)
  if (normalized === 'online') {
    return { text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', hex: '#10B981' }
  }
  if (normalized === 'degraded') {
    return { text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', hex: '#F59E0B' }
  }
  return { text: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/20', hex: '#F43F5E' }
}

export function StatusBadge({ status }) {
  const normalized = normalizeStatus(status)
  const tone = statusTone(normalized)
  return (
    <span className={clsx('rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase', tone.bg, tone.text, tone.border)}>
      {normalized.toUpperCase()}
    </span>
  )
}

export function StatusIcon({ status }) {
  const normalized = normalizeStatus(status)
  if (normalized === 'online') return <CheckCircle2 className="h-4 w-4 text-emerald-400" />
  if (normalized === 'degraded') return <ShieldAlert className="h-4 w-4 animate-pulse text-amber-400" />
  return <ShieldAlert className="h-4 w-4 animate-bounce text-rose-400" />
}

export function ServiceIcon({ serviceKey, small = false }) {
  const cls = small ? 'h-3.5 w-3.5 text-indigo-300' : 'h-4 w-4 text-indigo-300'
  if (serviceKey === 'postgres' || serviceKey === 'dr_postgres') return <Database className={cls} />
  if (serviceKey === 'cache' || serviceKey === 'duckdb') return <Layers className={cls} />
  if (serviceKey === 'app' || serviceKey === 'app_dr' || serviceKey === 'salespulse' || serviceKey === 'salespulse_dr') return <Cpu className={cls} />
  if (serviceKey === 'salesforce') return <Layers className={cls} />
  if (serviceKey === 'openai') return <Zap className={cls} />
  if (serviceKey === 'github') return <GitBranch className={cls} />
  if (serviceKey === 'google_maps') return <Map className={cls} />
  if (serviceKey === 'agentmail') return <Mail className={cls} />
  return <Cloud className={cls} />
}

export function Field({ label, value, mono = false, strong = false, truncate = false }) {
  return (
    <div className={clsx(truncate && 'min-w-0')}>
      <span className="block text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      <span
        title={String(value ?? 'N/A')}
        className={clsx('block text-slate-100', mono ? 'font-mono text-[11px]' : 'font-medium', strong && 'font-semibold', truncate && 'truncate')}
      >
        {String(value ?? 'N/A')}
      </span>
    </div>
  )
}

export function CredentialBadge({ service }) {
  if (service.api_key_valid === undefined || service.api_key_valid === null) {
    const configured = service.status === 'healthy' || service.status === 'online'
    return configured ? (
      <span className="flex items-center gap-1 rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-bold text-emerald-400">
        <ShieldCheck className="h-3 w-3" />
        Configured
      </span>
    ) : <span className="text-[10px] text-slate-500">No credentials</span>
  }
  return service.api_key_valid ? (
    <span className="flex items-center gap-1 rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-bold text-emerald-400">
      <ShieldCheck className="h-3 w-3" />
      Valid
    </span>
  ) : (
    <span
      title={service.api_key_error || 'Credential verification failed'}
      className="flex items-center gap-1 rounded border border-rose-500/20 bg-rose-500/10 px-1.5 py-0.5 text-[10px] font-bold text-rose-400"
    >
      <ShieldAlert className="h-3 w-3" />
      Failed
    </span>
  )
}

function renderLogLine(line) {
  if (line.includes('No recent') || line.includes('No events') || line.includes('No logs')) {
    return <span className="italic text-zinc-500">{line}</span>
  }
  const match = line.match(/^(\[\d{2}:\d{2}:\d{2}\])\s+(\[[A-Z]+\]|[A-Z_]+(?:\s+[A-Z_]+)*)(:|\s+-)\s+(.*)$/)
  if (!match) return <span className="text-zinc-300">{line}</span>
  const [, stamp, level, sep, message] = match
  const parts = message.split(' | ')
  return (
    <>
      <span className="mr-1.5 select-none text-zinc-500">{stamp}</span>
      <span className="font-semibold tracking-wide text-cyan-400">{level}</span>
      <span className="mx-1 text-zinc-600">{sep}</span>
      {parts.map((part, idx) => (
        <span key={`${part}-${idx}`}>
          {idx > 0 && <span className="mx-1.5 select-none text-zinc-700">|</span>}
          <span className={clsx(
            idx === 0 && 'text-zinc-100',
            part.endsWith('ms') && (parseInt(part) > 500 ? 'font-semibold text-amber-400' : 'font-semibold text-emerald-400'),
            part.startsWith('rows=') && 'text-sky-400',
            part.startsWith('ERR=') && 'rounded border border-rose-500/20 bg-rose-500/10 px-1 font-bold text-rose-400',
            idx > 0 && !part.endsWith('ms') && !part.startsWith('rows=') && !part.startsWith('ERR=') && 'text-zinc-400',
          )}>
            {part}
          </span>
        </span>
      ))}
    </>
  )
}

export function ServiceLogs({ logs }) {
  if (!logs?.length) return null
  return (
    <div className="col-span-2 mt-2">
      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-indigo-300">
        <Terminal className="h-3.5 w-3.5" />
        Recent Service Transactions
      </div>
      <div className="max-h-[130px] overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 font-mono text-[10px] leading-relaxed shadow-inner">
        {logs.map((line, idx) => (
          <div key={`${line}-${idx}`} className="mb-1.5 break-words border-b border-zinc-900 pb-1.5 last:mb-0 last:border-b-0 last:pb-0">
            {renderLogLine(line)}
          </div>
        ))}
      </div>
    </div>
  )
}

export function OpenLink({ href }) {
  if (!href) return null
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title="Open resource link"
      className="rounded p-1 text-slate-500 transition hover:bg-slate-800 hover:text-slate-100"
    >
      <ExternalLink className="h-3.5 w-3.5" />
    </a>
  )
}
