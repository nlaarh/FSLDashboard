import { useState, useMemo, useRef, useCallback } from 'react'
import {
  Search, Filter, ArrowUpDown, Loader2, Database, Share2, X,
} from 'lucide-react'
import { clsx } from 'clsx'
import { SectionHeader } from './HelpHowItWorks'

function DictionarySection({ data }) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState('entity')
  const [sortDir, setSortDir] = useState('asc')
  const [entityFilter, setEntityFilter] = useState('all')

  const toggleSort = useCallback((key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }, [sortKey])

  const entities = useMemo(() => {
    if (!data?.entities) return []
    return data.entities.map(e => e.name).sort()
  }, [data])

  const filtered = useMemo(() => {
    if (!data?.fields) return []
    let rows = data.fields
    if (entityFilter !== 'all') rows = rows.filter(f => f.entity === entityFilter)
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(f =>
        f.entity.toLowerCase().includes(q) ||
        f.entityLabel.toLowerCase().includes(q) ||
        f.apiName.toLowerCase().includes(q) ||
        f.label.toLowerCase().includes(q) ||
        f.description.toLowerCase().includes(q) ||
        f.type.toLowerCase().includes(q) ||
        f.fleetContractor.toLowerCase().includes(q) ||
        (f.usedIn || []).some(u => u.toLowerCase().includes(q)) ||
        f.category.toLowerCase().includes(q)
      )
    }
    rows = [...rows].sort((a, b) => {
      let va, vb
      switch (sortKey) {
        case 'entity': va = a.entityLabel; vb = b.entityLabel; break
        case 'field': va = a.label; vb = b.label; break
        case 'type': va = a.type; vb = b.type; break
        case 'fleet': va = a.fleetContractor; vb = b.fleetContractor; break
        default: va = a.entityLabel; vb = b.entityLabel
      }
      const cmp = va.localeCompare(vb)
      return sortDir === 'asc' ? cmp : -cmp
    })
    return rows
  }, [data, search, sortKey, sortDir, entityFilter])

  if (!data) return <div className="flex items-center justify-center py-20 gap-3"><Loader2 className="w-5 h-5 animate-spin text-brand-400" /><span className="text-slate-500 text-sm">Loading dictionary...</span></div>
  const SortHeader = ({ k, children, className }) => (
    <th onClick={() => toggleSort(k)}
      className={clsx('text-left py-2.5 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 cursor-pointer hover:text-brand-300 select-none', className)}>
      <span className="inline-flex items-center gap-1">
        {children}
        {sortKey === k && <ArrowUpDown className="w-3 h-3 text-brand-400" />}
      </span>
    </th>
  )

  return (
    <div>
      <SectionHeader title="Data Dictionary" subtitle={`${data.fields.length} fields across ${data.entities.length} Salesforce objects — every field used in this app.`} />
      {/* Search + Entity filter */}
      <div className="flex flex-wrap gap-3 mt-4 mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search fields, descriptions, usage..."
            className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40" />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-slate-500" />
          <select value={entityFilter} onChange={e => setEntityFilter(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg text-xs text-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500/40">
            <option value="all">All Entities ({data.fields.length})</option>
            {entities.map(e => {
              const cnt = data.fields.filter(f => f.entity === e).length
              return <option key={e} value={e}>{e} ({cnt})</option>
            })}
          </select>
        </div>
      </div>
      <div className="text-[10px] text-slate-600 mb-2">
        {filtered.length} field{filtered.length !== 1 ? 's' : ''} shown
        {search && ` matching "${search}"`}
      </div>
      {/* Table */}
      <div className="glass rounded-xl overflow-hidden border border-slate-700/20">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="border-b border-slate-700/50 bg-slate-900/30">
              <tr>
                <SortHeader k="entity" className="w-[160px]">Entity</SortHeader>
                <SortHeader k="field" className="w-[180px]">Field</SortHeader>
                <SortHeader k="type" className="w-[100px]">Type</SortHeader>
                <th className="text-left py-2.5 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">Description</th>
                <SortHeader k="fleet" className="w-[110px]">Fleet / Contractor</SortHeader>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/30">
              {filtered.map((f, i) => (
                <tr key={`${f.entity}.${f.apiName}`} className={clsx('hover:bg-slate-800/20', i % 2 === 0 && 'bg-slate-900/10')}>
                  <td className="px-3 py-3 align-top">
                    <div className="font-semibold text-slate-300 text-[11px]">{f.entityLabel}</div>
                    <div className="text-[9px] text-slate-600 mt-0.5">{f.entity}</div>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <div className="font-semibold text-brand-300 text-[11px]">{f.label}</div>
                    <div className="font-mono text-[9px] text-slate-500 mt-0.5">{f.apiName}</div>
                    {f.custom && <span className="inline-block mt-1 text-[8px] bg-amber-950/30 text-amber-400 border border-amber-800/30 rounded px-1 py-0.5 font-bold">CUSTOM</span>}
                  </td>
                  <td className="px-3 py-3 align-top text-slate-400 whitespace-nowrap">{f.type}</td>
                  <td className="px-3 py-3 align-top">
                    <p className="text-slate-300 leading-relaxed">{f.description}</p>
                    {f.usedIn && f.usedIn.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {f.usedIn.map(u => (
                          <span key={u} className="px-1.5 py-0.5 bg-slate-800 text-slate-500 rounded text-[9px]">{u}</span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 align-top">
                    <span className={clsx('text-[10px] font-medium',
                      f.fleetContractor === 'Both' ? 'text-slate-400' :
                      f.fleetContractor.includes('Fleet') ? 'text-blue-400' :
                      f.fleetContractor.includes('Contractor') ? 'text-orange-400' :
                      f.fleetContractor.includes('Distinguishes') ? 'text-purple-400' :
                      'text-slate-400'
                    )}>
                      {f.fleetContractor}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length === 0 && (
          <div className="text-center py-12 text-slate-600 text-sm">No fields match your search.</div>
        )}
      </div>
    </div>
  )
}
const MODEL_ENTITIES = [
  // Row 0 — top (Work Type + Skills)
  { id: 'WorkType',           label: 'WorkType',              x: 60,  y: 10,  w: 150, h: 54, color: '#6366f1', fields: 2,  cat: 'Core' },
  { id: 'SkillReq',           label: 'SkillRequirement',      x: 400, y: 10,  w: 170, h: 54, color: '#10b981', fields: 3,  cat: 'Junction' },
  { id: 'Skill',              label: 'Skill',                 x: 700, y: 10,  w: 150, h: 54, color: '#6366f1', fields: 2,  cat: 'Fleet' },
  // Row 1 — core objects
  { id: 'WorkOrder',          label: 'WorkOrder',             x: 10,  y: 120, w: 160, h: 54, color: '#6366f1', fields: 4,  cat: 'Core' },
  { id: 'ServiceAppointment', label: 'ServiceAppointment',    x: 220, y: 100, w: 210, h: 80, color: '#8b5cf6', fields: 31, cat: 'Core', primary: true },
  { id: 'ServiceTerritory',   label: 'ServiceTerritory',      x: 490, y: 120, w: 180, h: 54, color: '#6366f1', fields: 10, cat: 'Core' },
  { id: 'Account',            label: 'Account',               x: 720, y: 120, w: 150, h: 54, color: '#64748b', fields: 3,  cat: 'Core' },
  // Row 2 — junctions + custom
  { id: 'SAHistory',          label: 'SA History',             x: 10,  y: 240, w: 160, h: 54, color: '#f59e0b', fields: 5,  cat: 'Audit' },
  { id: 'AssignedResource',   label: 'AssignedResource',       x: 220, y: 240, w: 170, h: 54, color: '#10b981', fields: 2,  cat: 'Junction' },
  { id: 'STMember',           label: 'ServiceTerritoryMember', x: 440, y: 240, w: 200, h: 54, color: '#10b981', fields: 3,  cat: 'Junction' },
  { id: 'PriorityMatrix',     label: 'ERS_Territory_Priority_Matrix__c', x: 680, y: 240, w: 200, h: 54, color: '#f97316', fields: 4, cat: 'Custom' },
  // Row 3 — fleet & resources
  { id: 'Survey',             label: 'Survey_Result__c',       x: 10,  y: 350, w: 170, h: 54, color: '#f97316', fields: 3,  cat: 'Custom' },
  { id: 'ServiceResource',    label: 'ServiceResource',        x: 280, y: 350, w: 180, h: 54, color: '#6366f1', fields: 8,  cat: 'Fleet' },
  { id: 'SRSkill',            label: 'ServiceResourceSkill',   x: 530, y: 350, w: 190, h: 54, color: '#10b981', fields: 2,  cat: 'Junction' },
  { id: 'Polygon',            label: 'FSL__Polygon__c',        x: 770, y: 350, w: 150, h: 54, color: '#64748b', fields: 5,  cat: 'Managed' },
  // Row 4 — availability + trucks
  { id: 'Asset',              label: 'Asset (ERS Truck)',      x: 10,  y: 460, w: 170, h: 54, color: '#6366f1', fields: 5,  cat: 'Fleet' },
  { id: 'Shift',              label: 'Shift',                  x: 240, y: 460, w: 150, h: 54, color: '#6366f1', fields: 6,  cat: 'Fleet' },
  { id: 'ResAbsence',         label: 'ResourceAbsence',        x: 440, y: 460, w: 180, h: 54, color: '#6366f1', fields: 5,  cat: 'Fleet' },
  { id: 'PTAConfig',          label: 'ERS_SA_PTA__c',          x: 680, y: 460, w: 170, h: 54, color: '#f97316', fields: 3,  cat: 'Custom' },
  // Row 5 — scheduling engine
  { id: 'SchedPolicy',        label: 'Scheduling_Policy__c',   x: 60,  y: 560, w: 190, h: 54, color: '#64748b', fields: 3,  cat: 'Managed' },
  { id: 'PolicyGoal',         label: 'Policy_Goal__c',         x: 300, y: 560, w: 170, h: 54, color: '#64748b', fields: 3,  cat: 'Managed' },
  { id: 'ServiceGoal',        label: 'Service_Goal__c',        x: 520, y: 560, w: 170, h: 54, color: '#64748b', fields: 2,  cat: 'Managed' },
  { id: 'PolicyRule',          label: 'Policy_Work_Rule__c',   x: 300, y: 640, w: 170, h: 54, color: '#64748b', fields: 2,  cat: 'Managed' },
  { id: 'WorkRule',            label: 'Work_Rule__c',          x: 520, y: 640, w: 170, h: 54, color: '#64748b', fields: 2,  cat: 'Managed' },
]

const MODEL_LINES = [
  // Core SA relationships
  { from: 'ServiceAppointment', to: 'ServiceTerritory',   label: 'ServiceTerritoryId', type: 'M:1' },
  { from: 'ServiceAppointment', to: 'WorkType',           label: 'WorkTypeId',         type: 'M:1' },
  { from: 'WorkOrder',          to: 'ServiceAppointment', label: 'parent',             type: '1:M' },
  { from: 'WorkOrder',          to: 'Survey',             label: 'WO Number join',     type: '1:M' },
  { from: 'AssignedResource',   to: 'ServiceAppointment', label: 'SA ↔ Driver',        type: 'M:1' },
  { from: 'AssignedResource',   to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'SAHistory',          to: 'ServiceAppointment', label: 'audit trail',        type: 'M:1' },
  // Territory relationships
  { from: 'STMember',           to: 'ServiceTerritory',   label: 'TerritoryId',        type: 'M:1' },
  { from: 'STMember',           to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'ServiceTerritory',   to: 'Account',            label: 'Facility Account',   type: 'M:1' },
  { from: 'PriorityMatrix',     to: 'ServiceTerritory',   label: 'Parent / Spotted',   type: 'M:1' },
  { from: 'Polygon',            to: 'ServiceTerritory',   label: 'Territory boundary', type: 'M:1' },
  // Skill chain
  { from: 'SRSkill',            to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'SRSkill',            to: 'Skill',              label: 'SkillId',            type: 'M:1' },
  { from: 'SkillReq',           to: 'WorkType',           label: 'RelatedRecordId',    type: 'M:1' },
  { from: 'SkillReq',           to: 'Skill',              label: 'SkillId',            type: 'M:1' },
  // Fleet availability
  { from: 'Asset',              to: 'ServiceResource',    label: 'ERS_Driver__c',      type: 'M:1' },
  { from: 'Shift',              to: 'ServiceResource',    label: 'ServiceResourceId',  type: 'M:1' },
  { from: 'Shift',              to: 'ServiceTerritory',   label: 'ServiceTerritoryId', type: 'M:1' },
  { from: 'ResAbsence',         to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'PTAConfig',          to: 'ServiceTerritory',   label: 'ERS_Service_Territory__c', type: 'M:1' },
  // Scheduling engine
  { from: 'PolicyGoal',         to: 'SchedPolicy',        label: 'Policy ref',         type: 'M:1' },
  { from: 'PolicyGoal',         to: 'ServiceGoal',        label: 'Goal ref',           type: 'M:1' },
  { from: 'PolicyRule',         to: 'SchedPolicy',        label: 'Policy ref',         type: 'M:1' },
  { from: 'PolicyRule',         to: 'WorkRule',            label: 'Rule ref',           type: 'M:1' },
]

// Map MODEL_ENTITIES id → dictionary entity name
const ENTITY_ID_TO_NAME = {
  WorkType: 'WorkType', SkillReq: 'SkillRequirement', Skill: 'Skill',
  WorkOrder: 'WorkOrder', ServiceAppointment: 'ServiceAppointment',
  ServiceTerritory: 'ServiceTerritory', Account: 'Account',
  SAHistory: 'ServiceAppointmentHistory', AssignedResource: 'AssignedResource',
  STMember: 'ServiceTerritoryMember', PriorityMatrix: 'ERS_Territory_Priority_Matrix__c',
  Survey: 'Survey_Result__c', ServiceResource: 'ServiceResource',
  SRSkill: 'ServiceResourceSkill', Polygon: 'FSL__Polygon__c',
  Asset: 'Asset', Shift: 'Shift', ResAbsence: 'ResourceAbsence',
  PTAConfig: 'ERS_Service_Appointment_PTA__c', SchedPolicy: 'FSL__Scheduling_Policy__c',
  PolicyGoal: 'FSL__Policy_Goal__c', ServiceGoal: 'FSL__Service_Goal__c',
  PolicyRule: 'FSL__Policy_Work_Rule__c', WorkRule: 'FSL__Work_Rule__c',
}
function DataModelSection({ data }) {
  const svgW = 940
  const svgH = 720
  const [selectedEntity, setSelectedEntity] = useState(null)
  const detailRef = useRef(null)

  // Build field lookup: entityName → fields[]
  const fieldsByEntity = useMemo(() => {
    if (!data?.fields) return {}
    const map = {}
    data.fields.forEach(f => {
      if (!map[f.entity]) map[f.entity] = []
      map[f.entity].push(f)
    })
    return map
  }, [data])

  // Build entity description lookup
  const entityDesc = useMemo(() => {
    if (!data?.entities) return {}
    const map = {}
    data.entities.forEach(e => { map[e.name] = e })
    return map
  }, [data])

  const getCenter = (id) => {
    const e = MODEL_ENTITIES.find(n => n.id === id)
    if (!e) return { x: 0, y: 0 }
    return { x: e.x + e.w / 2, y: e.y + e.h / 2 }
  }
  const handleEntityClick = (entityId) => {
    setSelectedEntity(prev => prev === entityId ? null : entityId)
    setTimeout(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100)
  }
  const selName = selectedEntity ? ENTITY_ID_TO_NAME[selectedEntity] : null
  const selMeta = selName ? entityDesc[selName] : null
  const selFields = selName ? (fieldsByEntity[selName] || []) : []

  return (
    <div>
      {/* Legend */}
      <div className="flex flex-wrap gap-4 mt-1 mb-4 text-[10px]">
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#8b5cf6]" /> Primary Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#6366f1]" /> Standard Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#10b981]" /> Junction Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#f97316]" /> Custom Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#64748b]" /> Supporting</span>
        <span className="text-slate-600 ml-2">Click any entity to see its fields</span>
      </div>
      {/* Diagram */}
      <div className="glass rounded-xl border border-slate-700/20 overflow-x-auto p-4">
        <div className="relative" style={{ width: svgW, height: svgH, minWidth: svgW }}>
          {/* SVG lines */}
          <svg className="absolute inset-0" width={svgW} height={svgH} style={{ pointerEvents: 'none' }}>
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="#475569" />
              </marker>
            </defs>
            {MODEL_LINES.map((line, i) => {
              const from = getCenter(line.from)
              const to = getCenter(line.to)
              const mx = (from.x + to.x) / 2
              const my = (from.y + to.y) / 2
              return (
                <g key={i}>
                  <line x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                    stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrow)" />
                  <rect x={mx - 35} y={my - 8} width={70} height={16} rx={4} fill="#0f172a" stroke="#334155" strokeWidth="0.5" />
                  <text x={mx} y={my + 3} textAnchor="middle" fill="#64748b" fontSize="8" fontFamily="monospace">
                    {line.type}
                  </text>
                </g>
              )
            })}
          </svg>
          {/* Entity boxes */}
          {MODEL_ENTITIES.map(e => {
            const isSelected = selectedEntity === e.id
            return (
              <div key={e.id}
                onClick={() => handleEntityClick(e.id)}
                className={clsx(
                  'absolute rounded-lg border-2 px-3 py-2 shadow-lg cursor-pointer transition-all hover:brightness-125',
                  e.primary && 'ring-2 ring-purple-500/30',
                  isSelected && 'ring-2 ring-brand-400/60 brightness-125'
                )}
                style={{
                  left: e.x, top: e.y, width: e.w, height: e.h,
                  backgroundColor: '#0f172a',
                  borderColor: isSelected ? '#60a5fa' : e.color + '60',
                }}>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: e.color }} />
                  <span className="font-bold text-[10px] text-white truncate">{e.label}</span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-[9px] text-slate-500">{e.cat}</span>
                  <span className="text-[9px] text-slate-600">{e.fields} fields</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
      {/* Selected entity field detail */}
      {selectedEntity && selFields.length > 0 && (
        <div ref={detailRef} className="mt-4 glass rounded-xl border border-brand-500/30 p-4">
          <div className="flex items-start justify-between mb-3">
            <div>
              <h4 className="text-sm font-bold text-white flex items-center gap-2">
                <Database className="w-4 h-4 text-brand-400" />
                {selMeta?.label || selectedEntity}
                <code className="text-[10px] font-mono text-slate-500 ml-1">{selName}</code>
              </h4>
              {selMeta?.description && (
                <p className="text-[11px] text-slate-400 mt-1 max-w-3xl leading-relaxed">{selMeta.description}</p>
              )}
            </div>
            <button onClick={() => setSelectedEntity(null)} className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-slate-700/50 bg-slate-900/30">
                <tr>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[200px]">SF Field (API Name)</th>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[140px]">Label</th>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[80px]">Type</th>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/30">
                {selFields.map((f, i) => (
                  <tr key={f.apiName} className={i % 2 === 0 ? 'bg-slate-900/10' : ''}>
                    <td className="px-3 py-2 font-mono text-brand-300 text-[11px]">
                      {f.apiName}
                      {f.custom && <span className="ml-1.5 text-[8px] bg-amber-950/30 text-amber-400 border border-amber-800/30 rounded px-1 py-0.5 font-bold">CUSTOM</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-300 text-[11px]">{f.label}</td>
                    <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{f.type}</td>
                    <td className="px-3 py-2 text-slate-400 leading-relaxed">{f.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {selectedEntity && selFields.length === 0 && (
        <div ref={detailRef} className="mt-4 glass rounded-xl border border-slate-700/20 p-4 text-center text-sm text-slate-500">
          No field data available for this entity in the dictionary.
        </div>
      )}
      {/* Relationship table */}
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mt-6 mb-2">Relationships</h4>
      <div className="glass rounded-xl overflow-hidden border border-slate-700/20">
        <table className="w-full text-xs">
          <thead className="border-b border-slate-700/50 bg-slate-900/30">
            <tr>
              <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[200px]">From</th>
              <th className="text-center py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[60px]">Type</th>
              <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[200px]">To</th>
              <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">Relationship</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/30">
            {MODEL_LINES.map((r, i) => (
              <tr key={i} className={i % 2 === 0 ? 'bg-slate-900/10' : ''}>
                <td className="px-3 py-2 font-mono text-brand-300 text-[11px]">{r.from}</td>
                <td className="px-3 py-2 text-center text-slate-500 text-[10px] font-bold">{r.type}</td>
                <td className="px-3 py-2 font-mono text-brand-300 text-[11px]">{r.to}</td>
                <td className="px-3 py-2 text-slate-400">{r.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
export default function DataSection({ data }) {
  const [tab, setTab] = useState('dictionary')
  return (
    <div>
      <SectionHeader title="Data & Model" subtitle="All Salesforce objects, fields, and relationships in one place." />
      <div className="flex gap-1 mb-5 border-b border-slate-800/50 pb-2">
        <button onClick={() => setTab('dictionary')}
          className={clsx('flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all',
            tab === 'dictionary'
              ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent'
          )}>
          <Database className="w-3.5 h-3.5" /> Dictionary
        </button>
        <button onClick={() => setTab('model')}
          className={clsx('flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all',
            tab === 'model'
              ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent'
          )}>
          <Share2 className="w-3.5 h-3.5" /> Data Model
        </button>
      </div>
      {tab === 'dictionary' ? <DictionarySection data={data} /> : <DataModelSection data={data} />}
    </div>
  )
}
