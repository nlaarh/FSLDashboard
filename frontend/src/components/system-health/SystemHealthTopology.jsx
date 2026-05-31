import { Activity, Power, RefreshCw, Terminal } from 'lucide-react'
import { clsx } from 'clsx'
import {
  OpenLink,
  SERVICE_LABELS,
  TOPOLOGY_ORDER,
  ServiceIcon,
  StatusBadge,
  normalizeStatus,
  statusTone,
} from './systemHealthUi'

// 4-column architecture layout — shared PostgreSQL between FleetPulse and SalesPulse:
//
//                       SALESFORCE (top center)
//                      /                       \
//  CACHE ─── FLEETPULSE APP            SALESPULSE APP ─── OPENAI
//              /        \DR              /DR        \
//         [ACTIVE]   [STANDBY]       [STANDBY]   [ACTIVE shared DB]
//            /            \              \            /
//      PRIMARY DB     FLEETPULSE DR   SALESPULSE DR
//   (EAST US)    \         \               /        (DR ZONE · WEST US 2)
//                 └──────── FSLAPP-PG DR ─┘ (PITR clone · EAST US 2)
//
//   GITHUB REPO (bottom-left)                  AZURE APP SVC (bottom-right)
const NODE_POSITIONS = {
  salesforce:    'top-[10px] left-[50%] -translate-x-1/2',
  cache:         'top-[200px] left-[10px]',
  app:           'top-[200px] left-[185px]',
  salespulse:    'top-[200px] right-[185px]',
  openai:        'top-[200px] right-[10px]',
  postgres:      'top-[410px] left-[10px]',
  app_dr:        'top-[410px] left-[185px]',
  salespulse_dr: 'top-[410px] right-[185px]',
  dr_postgres:   'top-[620px] left-[50%] -translate-x-1/2',
  github:        'bottom-[10px] left-[10px]',
  azure:         'bottom-[10px] right-[10px]',
}

export default function SystemHealthTopology({ health, logs, loading, pinging, onRefresh, onPing }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div className="si-card-premium relative flex min-h-[1150px] flex-col overflow-hidden border border-slate-700/40 bg-black/25 p-6 dark:bg-black/45 lg:col-span-2">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(94,106,210,0.08),transparent_65%)]" />
        <div className="relative z-10 flex items-center justify-between border-b border-slate-700/40 pb-3">
          <div>
            <h3 className="flex items-center gap-1.5 text-[13px] font-bold uppercase tracking-wider text-indigo-300">
              <Activity className="h-4 w-4 animate-pulse text-indigo-300" />
              System Architecture Topology
            </h3>
            <p className="text-[11px] text-slate-500">
              Live service graph — data paths and DR failover links
            </p>
          </div>
          <button
            onClick={onRefresh}
            disabled={loading}
            title="Refresh health snapshot"
            className="rounded-lg border border-slate-700 bg-slate-800/50 p-1.5 text-slate-500 transition hover:bg-slate-800 hover:text-slate-100 disabled:opacity-50"
          >
            <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          </button>
        </div>
        <ArchTopology health={health} pinging={pinging} onPing={onPing} />
      </div>

      <ConsoleLogs logs={logs} />
    </div>
  )
}

function ArchTopology({ health, pinging, onPing }) {
  return (
    <div className="relative my-2 flex h-[1080px] w-full select-none items-center justify-center">
      <ConnectionLines health={health} />
      {TOPOLOGY_ORDER.map((key) =>
        health.services[key] ? (
          <TopologyNode
            key={key}
            serviceKey={key}
            service={health.services[key]}
            pinging={Boolean(pinging[key])}
            onPing={onPing}
          />
        ) : null,
      )}
    </div>
  )
}

function ConnectionLines({ health }) {
  const svc = (key) => health.services[key]
  const hex = (key) => statusTone(svc(key)?.status).hex
  const isOnline = (key) => normalizeStatus(svc(key)?.status) !== 'offline'
  const hasBoth = svc('postgres') && svc('dr_postgres')

  // SVG coordinate system (viewBox 800×1080). Node centers (x):
  //   cache=85  app=260  salesforce=400  salespulse=540  openai=715
  //   postgres=85  app_dr=260  salespulse_dr=540  dr_postgres=400
  // Node row tops (y): row1=10  row2=200  row3=410  row4=620

  return (
    <svg viewBox="0 0 800 1080" className="pointer-events-none absolute inset-0 z-0 h-full w-full">
      <defs>
        <style>{'@keyframes pulseLine{to{stroke-dashoffset:-20}}.lp{stroke-dasharray:4 12;animation:pulseLine 1.2s linear infinite}.rp{stroke-dasharray:3 6;animation:pulseLine 0.9s linear infinite}'}</style>
      </defs>

      {/* DR Zone — covers app_dr, salespulse_dr, dr_postgres */}
      <rect x="178" y="395" width="450" height="420" rx="8"
        fill="none" stroke="#F59E0B" strokeWidth="0.9"
        strokeDasharray="5 4" opacity="0.25" />
      <text x="184" y="408" fill="#F59E0B" fontSize="6" fontFamily="monospace"
        fontWeight="bold" opacity="0.55" letterSpacing="1">DR ZONE · APPS: WEST US 2 · DB: EAST US 2</text>

      {/* Prod DB label */}
      <text x="8" y="405" fill="#10B981" fontSize="6" fontFamily="monospace"
        fontWeight="bold" opacity="0.35" letterSpacing="0.5">PROD DB · EAST US 2</text>

      {/* Salesforce → FleetPulse App */}
      {svc('salesforce') && svc('app') && (
        <g>
          <path d="M 400 148 C 360 175 290 196 260 200"
            stroke={hex('salesforce')} strokeWidth="1.5" opacity=".25" fill="none" />
          {isOnline('salesforce') && (
            <path d="M 400 148 C 360 175 290 196 260 200"
              stroke={hex('salesforce')} strokeWidth="1.5" className="lp" fill="none" />
          )}
        </g>
      )}

      {/* Salesforce → SalesPulse App */}
      {svc('salesforce') && svc('salespulse') && (
        <g>
          <path d="M 400 148 C 440 175 510 196 540 200"
            stroke={hex('salesforce')} strokeWidth="1.5" opacity=".25" fill="none" />
          {isOnline('salesforce') && (
            <path d="M 400 148 C 440 175 510 196 540 200"
              stroke={hex('salesforce')} strokeWidth="1.5" className="lp" fill="none" />
          )}
        </g>
      )}

      {/* FleetPulse App → Cache */}
      {svc('cache') && svc('app') && (
        <g>
          <path d="M 185 268 L 160 268"
            stroke={hex('cache')} strokeWidth="1.5" opacity=".25" fill="none" />
          {isOnline('cache') && (
            <path d="M 185 268 L 160 268"
              stroke={hex('cache')} strokeWidth="1.5" className="lp" fill="none" />
          )}
        </g>
      )}

      {/* SalesPulse App → OpenAI */}
      {svc('openai') && svc('salespulse') && (
        <g>
          <path d="M 615 268 L 640 268"
            stroke={hex('openai')} strokeWidth="1.5" opacity=".25" fill="none" />
          {isOnline('openai') && (
            <path d="M 615 268 L 640 268"
              stroke={hex('openai')} strokeWidth="1.5" className="lp" fill="none" />
          )}
        </g>
      )}

      {/* FleetPulse → Primary DB (ACTIVE) */}
      {svc('postgres') && svc('app') && (
        <g>
          <path d="M 215 348 C 178 378 128 402 85 410"
            stroke={hex('postgres')} strokeWidth="2" opacity=".55" fill="none" />
          {isOnline('postgres') && (
            <path d="M 215 348 C 178 378 128 402 85 410"
              stroke={hex('postgres')} strokeWidth="2" className="lp" fill="none" />
          )}
          <rect x="108" y="374" width="56" height="12" rx="3"
            fill="#0F172A" opacity="0.85" />
          <text x="136" y="383" fill={hex('postgres')} fontSize="6.5" fontFamily="monospace"
            fontWeight="bold" opacity="1" textAnchor="middle">✦ ACTIVE</text>
        </g>
      )}

      {/* SalesPulse → Primary DB (ACTIVE, shared co-tenant) */}
      {svc('postgres') && svc('salespulse') && (
        <g>
          <path d="M 490 348 C 390 378 220 402 85 410"
            stroke={hex('postgres')} strokeWidth="1.5" opacity=".35" fill="none" strokeDasharray="5 3" />
          {isOnline('postgres') && (
            <path d="M 490 348 C 390 378 220 402 85 410"
              stroke={hex('postgres')} strokeWidth="1.5" className="lp" fill="none" />
          )}
          <rect x="252" y="374" width="56" height="12" rx="3"
            fill="#0F172A" opacity="0.85" />
          <text x="280" y="383" fill={hex('postgres')} fontSize="6.5" fontFamily="monospace"
            fontWeight="bold" opacity="0.85" textAnchor="middle">SHARED</text>
        </g>
      )}

      {/* FleetPulse → FleetPulse DR (DR STANDBY — vertical) */}
      {svc('app_dr') && svc('app') && (
        <g>
          <path d="M 310 348 C 330 378 330 398 310 410"
            stroke="#F59E0B" strokeWidth="2" opacity=".55" fill="none" strokeDasharray="6 4" />
          <path d="M 310 348 C 330 378 330 398 310 410"
            stroke="#F59E0B" strokeWidth="2" className="rp" fill="none" />
          <rect x="316" y="372" width="62" height="12" rx="3"
            fill="#0F172A" opacity="0.85" />
          <text x="347" y="381" fill="#F59E0B" fontSize="6" fontFamily="monospace"
            fontWeight="bold" opacity="1" textAnchor="middle">⚡ DR STBY</text>
        </g>
      )}

      {/* SalesPulse → SalesPulse DR (DR STANDBY — vertical) */}
      {svc('salespulse_dr') && svc('salespulse') && (
        <g>
          <path d="M 490 348 C 470 378 470 398 490 410"
            stroke="#F59E0B" strokeWidth="2" opacity=".55" fill="none" strokeDasharray="6 4" />
          <path d="M 490 348 C 470 378 470 398 490 410"
            stroke="#F59E0B" strokeWidth="2" className="rp" fill="none" />
          <rect x="422" y="372" width="62" height="12" rx="3"
            fill="#0F172A" opacity="0.85" />
          <text x="453" y="381" fill="#F59E0B" fontSize="6" fontFamily="monospace"
            fontWeight="bold" opacity="1" textAnchor="middle">⚡ DR STBY</text>
        </g>
      )}

      {/* FleetPulse DR → DR Postgres */}
      {svc('app_dr') && svc('dr_postgres') && (
        <g>
          <path d="M 260 555 C 285 585 330 612 350 620"
            stroke="#F59E0B" strokeWidth="1.5" opacity=".4" fill="none" strokeDasharray="4 3" />
          {isOnline('app_dr') && (
            <path d="M 260 555 C 285 585 330 612 350 620"
              stroke="#F59E0B" strokeWidth="1.5" className="rp" fill="none" />
          )}
        </g>
      )}

      {/* SalesPulse DR → DR Postgres */}
      {svc('salespulse_dr') && svc('dr_postgres') && (
        <g>
          <path d="M 540 555 C 515 585 470 612 450 620"
            stroke="#F59E0B" strokeWidth="1.5" opacity=".4" fill="none" strokeDasharray="4 3" />
          {isOnline('salespulse_dr') && (
            <path d="M 540 555 C 515 585 470 612 450 620"
              stroke="#F59E0B" strokeWidth="1.5" className="rp" fill="none" />
          )}
        </g>
      )}

      {/* Primary DB ↔ DR Postgres: PITR replication */}
      {hasBoth && (
        <g>
          <path d="M 160 490 C 220 560 285 610 325 650"
            stroke="#F59E0B" strokeWidth="2" opacity=".32" fill="none" strokeDasharray="3 2" />
          <path d="M 160 490 C 220 560 285 610 325 650"
            stroke="#F59E0B" strokeWidth="1.5" className="rp" fill="none" />
          <text x="215" y="568" textAnchor="middle" fill="#F59E0B" fontSize="6"
            fontFamily="monospace" fontWeight="bold" opacity="0.65"
            transform="rotate(-45 215 568)">PITR REPLICATION</text>
        </g>
      )}

      {/* Primary DB → GitHub */}
      {svc('github') && svc('postgres') && (
        <g>
          <path d="M 85 820 L 85 865" stroke={hex('github')} strokeWidth="1.5" opacity=".2" fill="none" />
        </g>
      )}
    </svg>
  )
}

function TopologyNode({ serviceKey, service, pinging, onPing }) {
  const tone = statusTone(service.status)
  const isDr = serviceKey === 'dr_postgres'
  const isDrApp = serviceKey === 'app_dr' || serviceKey === 'salespulse_dr'
  const isPrimary = serviceKey === 'postgres'
  const isCotenant = serviceKey === 'salespulse' || serviceKey === 'salespulse_dr'
  const hostLink = service.host_link || service.details?.server_url
  const recentLog = service.logs?.[0]

  return (
    <div className={clsx('absolute z-20 w-[150px]', NODE_POSITIONS[serviceKey])}>
      <div className={clsx(
        'w-full rounded-lg border bg-slate-900/95 p-2.5 shadow-xl backdrop-blur',
        tone.border,
        (isDr || isDrApp) && 'ring-1 ring-amber-500/30',
        isCotenant && 'ring-1 ring-sky-500/25',
      )}>
        {/* Header */}
        <div className="mb-1.5 flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-1.5">
            <ServiceIcon serviceKey={serviceKey} small />
            <span className="truncate font-mono text-[9px] font-bold text-slate-100">
              {SERVICE_LABELS[serviceKey]}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            {hostLink && <OpenLink href={hostLink} />}
            <Power className={clsx('h-3 w-3', tone.text, pinging && 'animate-pulse')} />
          </div>
        </div>

        {/* Role badge */}
        {(isPrimary || isDr || isDrApp || isCotenant) && (
          <div className="mb-1.5">
            <span className={clsx(
              'inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-wider',
              isDr || isDrApp
                ? 'border border-amber-500/30 bg-amber-500/10 text-amber-400'
                : isCotenant
                  ? 'border border-sky-500/30 bg-sky-500/10 text-sky-400'
                  : 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
            )}>
              {isDr ? '⚡ DR REPLICA' : isDrApp ? '⚡ DR APP' : isCotenant ? '◈ CO-TENANT' : '✦ PRIMARY'}
            </span>
          </div>
        )}

        {/* Data rows */}
        <div className="mb-2 space-y-0.5">
          <NodeRow
            label="Status"
            value={pinging ? 'CHECKING' : normalizeStatus(service.status).toUpperCase()}
            valueClass={clsx('font-semibold uppercase', tone.text)}
          />
          {service.latency_ms != null && (
            <NodeRow
              label="Latency"
              value={`${service.latency_ms} ms`}
              valueClass={service.latency_ms > 500 ? 'font-semibold text-amber-400' : 'font-semibold text-emerald-400'}
            />
          )}
          {service.host && (
            <NodeRow
              label="Host"
              value={service.host}
              valueClass="font-mono text-[8px] text-slate-300 truncate max-w-[72px]"
            />
          )}
          {service.region && (
            <NodeRow label="Region" value={service.region} valueClass="text-slate-300" />
          )}
          {service.schema && (
            <NodeRow label="Schema" value={service.schema} valueClass="font-mono text-[8px] text-slate-300" />
          )}
        </div>

        {/* Most recent log */}
        {recentLog && (
          <div className="mb-1.5 truncate rounded bg-zinc-900 px-1.5 py-1 font-mono text-[7.5px] text-zinc-400" title={recentLog}>
            {recentLog}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-700/30 pt-1.5">
          <StatusBadge status={service.status} />
          <button
            onClick={() => onPing(serviceKey)}
            disabled={pinging}
            className="rounded border border-indigo-400/25 bg-indigo-500/10 px-1.5 py-0.5 text-[8px] font-bold text-indigo-300 transition hover:bg-indigo-500/20 disabled:opacity-50"
          >
            {pinging ? '···' : 'PING'}
          </button>
        </div>
      </div>
    </div>
  )
}

function NodeRow({ label, value, valueClass }) {
  return (
    <div className="flex items-center justify-between gap-1 border-b border-slate-700/20 pb-0.5 text-[8.5px]">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className={clsx('text-right', valueClass)}>{value}</span>
    </div>
  )
}

function ConsoleLogs({ logs }) {
  return (
    <div className="si-card-premium flex h-[1150px] flex-col overflow-hidden border border-zinc-800 bg-zinc-950 font-mono">
      <div className="flex shrink-0 items-center gap-2 border-b border-zinc-800 bg-zinc-900/40 px-4 py-3 text-indigo-300">
        <Terminal className="h-4 w-4 text-indigo-300" />
        <span className="text-[11px] font-bold uppercase tracking-wider">System Console Logs</span>
      </div>
      <div className="flex-1 space-y-2.5 overflow-y-auto bg-zinc-950 p-4 text-[10px] leading-relaxed">
        {logs.map((line, idx) => (
          <div key={`${line}-${idx}`} className="whitespace-pre-wrap border-l-2 border-sky-500/30 pl-2 text-zinc-200">
            {line}
          </div>
        ))}
      </div>
    </div>
  )
}
