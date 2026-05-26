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

// Left column: postgres (PRIMARY) → dr_postgres (DR REPLICA) → github (bottom)
// Right column: app → openai → cache → azure (bottom)
// Both DB nodes share the left column and are connected by a replication cable.
const NODE_POSITIONS = {
  salesforce:  'top-[10px] left-[50%] -translate-x-1/2',
  postgres:    'top-[100px] left-[10px]',
  dr_postgres: 'top-[265px] left-[10px]',
  app:         'top-[100px] right-[10px]',
  openai:      'top-[255px] right-[10px]',
  cache:       'top-[405px] right-[10px]',
  github:      'bottom-[10px] left-[10px]',
  azure:       'bottom-[10px] right-[10px]',
}

export default function SystemHealthTopology({ health, logs, loading, pinging, onRefresh, onPing }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div className="si-card-premium relative flex min-h-[730px] flex-col overflow-hidden border border-slate-700/40 bg-black/25 p-6 dark:bg-black/45 lg:col-span-2">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(94,106,210,0.08),transparent_65%)]" />
        <div className="relative z-10 flex items-center justify-between border-b border-slate-700/40 pb-3">
          <div>
            <h3 className="flex items-center gap-1.5 text-[13px] font-bold uppercase tracking-wider text-indigo-300">
              <Activity className="h-4 w-4 animate-pulse text-indigo-300" />
              Cybernetic Power Switchboard Topology
            </h3>
            <p className="text-[11px] text-slate-500">
              Tactical panel: service nodes plugged into central PDU power distributor
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
        <PowerTopology health={health} pinging={pinging} onPing={onPing} />
      </div>

      <ConsoleLogs logs={logs} />
    </div>
  )
}

function PowerTopology({ health, pinging, onPing }) {
  return (
    <div className="relative my-2 flex h-[635px] w-full select-none items-center justify-center">
      <CableLines health={health} />
      <CorePdu health={health} />
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

function CableLines({ health }) {
  // PDU ports (left side x=262, right side x=378):
  //   Left:  SF@130(top), PRIMARY@178, DR@228, GIT@338
  //   Right: API@178, AI@228, L2@288, VM@338
  const pduCables = [
    { key: 'salesforce',  d: 'M 320 110 L 320 127' },
    { key: 'postgres',    d: 'M 160 168 L 212 168 L 212 178 L 262 178' },
    { key: 'dr_postgres', d: 'M 160 335 L 212 335 L 212 228 L 262 228' },
    { key: 'app',         d: 'M 480 168 L 428 168 L 428 178 L 378 178' },
    { key: 'openai',      d: 'M 480 322 L 428 322 L 428 228 L 378 228' },
    { key: 'cache',       d: 'M 480 472 L 428 472 L 428 288 L 378 288' },
    { key: 'github',      d: 'M 160 590 L 216 590 L 216 338 L 262 338' },
    { key: 'azure',       d: 'M 480 590 L 424 590 L 424 338 L 378 338' },
  ]

  const hasBoth = health.services.postgres && health.services.dr_postgres

  return (
    <svg viewBox="0 0 640 635" className="pointer-events-none absolute inset-0 z-0 h-full w-full">
      <defs>
        <style>{'@keyframes pulseLine{to{stroke-dashoffset:-20}}.line-pulse{stroke-dasharray:4 12;animation:pulseLine 1.2s linear infinite}.repl-pulse{stroke-dasharray:3 6;animation:pulseLine 0.9s linear infinite}'}</style>
      </defs>

      {/* DB Cluster bracket — groups PRIMARY and DR REPLICA */}
      <rect x="4" y="92" width="168" height="330" rx="8"
        fill="none" stroke="#F59E0B" strokeWidth="0.8"
        strokeDasharray="5 4" opacity="0.22" />
      <text x="9" y="103" fill="#F59E0B" fontSize="6" fontFamily="monospace"
        fontWeight="bold" opacity="0.45" letterSpacing="1">DATABASE CLUSTER</text>

      {/* PDU → service cables */}
      {pduCables.map(({ key, d }) => {
        const service = health.services[key]
        const color = statusTone(service?.status).hex
        return service ? (
          <g key={key}>
            <path d={d} stroke={color} strokeWidth="1.5" opacity=".25" fill="none" />
            {normalizeStatus(service.status) !== 'offline' && (
              <path d={d} stroke={color} strokeWidth="1.5" className="line-pulse" fill="none" />
            )}
          </g>
        ) : null
      })}

      {/* Replication cable — PRIMARY ↔ DR REPLICA */}
      {hasBoth && (
        <g>
          {/* Static base */}
          <path d="M 85 242 L 85 263" stroke="#F59E0B" strokeWidth="2"
            opacity="0.35" fill="none" strokeDasharray="3 2" />
          {/* Animated pulse */}
          <path d="M 85 242 L 85 263" stroke="#F59E0B" strokeWidth="1.5"
            className="repl-pulse" fill="none" />
          {/* Label */}
          <text x="92" y="255" fill="#F59E0B" fontSize="5.5"
            fontFamily="monospace" opacity="0.65">PITR CLONE</text>
        </g>
      )}
    </svg>
  )
}

function CorePdu({ health }) {
  const ports = [
    { key: 'salesforce',  label: 'SF',  x: 320, y: 127, anchor: 'middle' },
    { key: 'postgres',    label: 'PRI', x: 262, y: 178, anchor: 'start'  },
    { key: 'dr_postgres', label: 'DR',  x: 262, y: 228, anchor: 'start'  },
    { key: 'github',      label: 'GIT', x: 262, y: 338, anchor: 'start'  },
    { key: 'app',         label: 'API', x: 378, y: 178, anchor: 'end'    },
    { key: 'openai',      label: 'AI',  x: 378, y: 228, anchor: 'end'    },
    { key: 'cache',       label: 'L2',  x: 378, y: 288, anchor: 'end'    },
    { key: 'azure',       label: 'VM',  x: 378, y: 338, anchor: 'end'    },
  ]
  return (
    <svg viewBox="0 0 640 635" className="pointer-events-none absolute inset-0 z-10 h-full w-full">
      {/* PDU glow + body */}
      <rect x="258" y="124" width="124" height="240" rx="10"
        fill="none" stroke="#5E6AD2" strokeWidth="1" opacity="0.1" className="animate-pulse" />
      <rect x="262" y="127" width="116" height="234" rx="8"
        fill="#0F172A" fillOpacity="0.9" stroke="#334155" strokeWidth="1.5" />
      <rect x="264" y="129" width="112" height="230" rx="6"
        fill="none" stroke="#475569" strokeWidth="0.5" opacity="0.4" />
      <text x="320" y="143" textAnchor="middle" fill="#94A3B8"
        fontSize="7" fontWeight="bold" letterSpacing="1" fontFamily="monospace">CORE PDU v2.5</text>

      {/* DR label inside PDU between the two DB ports */}
      <text x="320" y="210" textAnchor="middle" fill="#F59E0B"
        fontSize="5" fontFamily="monospace" opacity="0.4">↕ REPL</text>

      {ports.map(({ key, label, x, y, anchor }) => {
        const color = statusTone(health.services[key]?.status).hex
        return (
          <g key={key}>
            <circle cx={x} cy={y} r="8.5" fill="#1E293B" stroke="#475569" strokeWidth="1" />
            <circle cx={x} cy={y} r="5.5" fill="#020617" />
            <circle cx={x} cy={y} r="6" fill="none" stroke={color} strokeWidth="1" opacity="0.75" />
            <circle cx={x} cy={y} r="2" fill={color} />
            {normalizeStatus(health.services[key]?.status) === 'online' && (
              <circle
                cx={x} cy={y} r="9.5"
                fill="none" stroke={color} strokeWidth="0.5"
                className="animate-ping"
                style={{ transformOrigin: `${x}px ${y}px` }}
              />
            )}
            <text
              x={anchor === 'start' ? x + 14 : anchor === 'end' ? x - 14 : x}
              y={anchor === 'middle' ? y + 16 : y + 3}
              textAnchor={anchor}
              fill="#64748B" fontSize="6.5" fontWeight="bold" fontFamily="monospace"
            >{label}</text>
          </g>
        )
      })}
    </svg>
  )
}

function TopologyNode({ serviceKey, service, pinging, onPing }) {
  const tone = statusTone(service.status)
  const isDr = serviceKey === 'dr_postgres'
  const hostLink = service.host_link || service.details?.server_url
  const recentLog = service.logs?.[0]

  return (
    <div className={clsx('absolute z-20 w-[150px]', NODE_POSITIONS[serviceKey])}>
      <div className={clsx(
        'w-full rounded-lg border bg-slate-900/95 p-2.5 shadow-xl backdrop-blur',
        tone.border,
        isDr && 'ring-1 ring-amber-500/20',
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

        {/* DR / PRIMARY badge */}
        {(isDr || serviceKey === 'postgres') && (
          <div className="mb-1.5">
            <span className={clsx(
              'inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-wider',
              isDr
                ? 'border border-amber-500/30 bg-amber-500/10 text-amber-400'
                : 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
            )}>
              {isDr ? '⚡ DR REPLICA' : '✦ PRIMARY'}
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
        </div>

        {/* Most recent log line */}
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
    <div className="si-card-premium flex h-[730px] flex-col overflow-hidden border border-zinc-800 bg-zinc-950 font-mono">
      <div className="flex shrink-0 items-center gap-2 border-b border-zinc-800 bg-zinc-900/40 px-4 py-3 text-indigo-300">
        <Terminal className="h-4 w-4 text-indigo-300" />
        <span className="text-[11px] font-bold uppercase tracking-wider">Tactical HUD Console Logs</span>
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
