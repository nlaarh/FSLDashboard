/**
 * AcceptanceDetailModal.jsx
 *
 * Drill-down for the 3 Operations metric boxes (GarageOperations).
 * Lazily fetches the underlying ServiceAppointments for both sides of a box and
 * shows them in two tabs:
 *   - 1st Call Acceptance:   Accepted vs Not Accepted
 *   - 2nd+ Call Acceptance:  Accepted vs Not Accepted
 *   - Completion of Accepted: Completed vs Not Completed
 *
 * Buckets are fetched from GET /api/garages/{territory_id}/acceptance-detail.
 */

import { useState, useEffect } from 'react'
import { X, Loader2, ExternalLink } from 'lucide-react'
import { fetchAcceptanceDetail } from '../api'

const SF_BASE = 'https://aaawcny.lightning.force.com'

// Each metric box -> its two buckets + tab labels.
export const ACCEPTANCE_VIEWS = {
  first_call: {
    title: '1st Call Acceptance',
    tabs: [
      { key: 'first_call_accepted', label: 'Accepted', accent: '#10b981' },
      { key: 'first_call_declined', label: 'Not Accepted', accent: '#ef4444', showDecline: true },
    ],
  },
  second_call: {
    title: '2nd+ Call Acceptance',
    tabs: [
      { key: 'second_call_accepted', label: 'Accepted', accent: '#10b981' },
      { key: 'second_call_declined', label: 'Not Accepted', accent: '#ef4444', showDecline: true },
    ],
  },
  completion_accepted: {
    title: 'Completion of Accepted',
    tabs: [
      { key: 'completion_completed', label: 'Completed', accent: '#10b981' },
      { key: 'completion_not_completed', label: 'Not Completed', accent: '#f59e0b' },
    ],
  },
}

export default function AcceptanceDetailModal({ view, territoryId, startDate, endDate, onClose }) {
  const cfg = ACCEPTANCE_VIEWS[view]
  const [activeTab, setActiveTab] = useState(0)
  const [data, setData] = useState({})       // bucketKey -> { rows, count }
  const [loading, setLoading] = useState({})  // bucketKey -> bool
  const [errors, setErrors] = useState({})    // bucketKey -> string

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Fetch both buckets up front (counts shown on both tab headers).
  useEffect(() => {
    if (!cfg) return
    let ignore = false
    cfg.tabs.forEach(tab => {
      setLoading(p => ({ ...p, [tab.key]: true }))
      fetchAcceptanceDetail(territoryId, tab.key, startDate, endDate)
        .then(d => { if (!ignore) setData(p => ({ ...p, [tab.key]: d })) })
        .catch(e => { if (!ignore) setErrors(p => ({ ...p, [tab.key]: e.response?.data?.detail || e.message || 'Failed to load' })) })
        .finally(() => { if (!ignore) setLoading(p => ({ ...p, [tab.key]: false })) })
    })
    return () => { ignore = true }
  }, [view, territoryId, startDate, endDate])

  if (!cfg) return null
  const tab = cfg.tabs[activeTab]
  const tabData = data[tab.key]
  const tabLoading = loading[tab.key]
  const tabError = errors[tab.key]
  const rows = tabData?.rows || []

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'flex-start',
      justifyContent: 'center', overflowY: 'auto', padding: '24px 16px',
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        width: '100%', maxWidth: 760, background: '#0b1120',
        borderRadius: 12, border: '1px solid #1e293b',
        boxShadow: '0 24px 64px rgba(0,0,0,0.8)',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px',
                      borderBottom: '1px solid #1e293b' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>{cfg.title}</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{startDate} – {endDate}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
            <X size={20} color="#64748b" />
          </button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 8, padding: '12px 20px 0' }}>
          {cfg.tabs.map((t, i) => {
            const cnt = data[t.key]?.count
            const active = i === activeTab
            return (
              <button key={t.key} onClick={() => setActiveTab(i)}
                style={{
                  flex: 1, padding: '8px 12px', borderRadius: '8px 8px 0 0', cursor: 'pointer',
                  border: '1px solid', borderBottom: 'none',
                  background: active ? '#0f172a' : 'transparent',
                  borderColor: active ? '#1e293b' : 'transparent',
                  color: active ? t.accent : '#94a3b8', fontSize: 12, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: t.accent }} />
                {t.label}
                <span style={{ color: '#64748b', fontWeight: 400 }}>
                  ({loading[t.key] ? '…' : (cnt ?? 0)})
                </span>
              </button>
            )
          })}
        </div>

        {/* Body */}
        <div style={{ padding: '16px 20px 20px', minHeight: 160 }}>
          {tabLoading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b',
                          justifyContent: 'center', padding: '40px 0' }}>
              <Loader2 size={18} className="animate-spin" /> Loading…
            </div>
          )}
          {!tabLoading && tabError && (
            <div style={{ color: '#ef4444', padding: '24px', textAlign: 'center', fontSize: 13 }}>{tabError}</div>
          )}
          {!tabLoading && !tabError && rows.length === 0 && (
            <div style={{ color: '#64748b', padding: '32px', textAlign: 'center', fontSize: 13 }}>
              No service appointments in this bucket for the selected period.
            </div>
          )}
          {!tabLoading && !tabError && rows.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ color: '#64748b', borderBottom: '1px solid #1e293b', textAlign: 'left' }}>
                    <th style={{ padding: '6px 8px' }}>WO #</th>
                    <th style={{ padding: '6px 8px' }}>Work Type</th>
                    <th style={{ padding: '6px 8px' }}>Status</th>
                    {tab.showDecline && <th style={{ padding: '6px 8px' }}>Decline Reason</th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.sa_id} style={{ borderBottom: '1px solid #1e293b22' }}>
                      <td style={{ padding: '6px 8px' }}>
                        {r.wo_id ? (
                          <a href={`${SF_BASE}/${r.wo_id}`} target="_blank" rel="noopener noreferrer"
                            style={{ color: '#818cf8', textDecoration: 'none', display: 'inline-flex',
                                     alignItems: 'center', gap: 4 }}>
                            {r.wo_number || r.sa_number || 'View'}
                            <ExternalLink size={11} />
                          </a>
                        ) : (
                          <span style={{ color: '#94a3b8' }}>{r.sa_number || '—'}</span>
                        )}
                      </td>
                      <td style={{ padding: '6px 8px', color: '#cbd5e1' }}>{r.work_type || '—'}</td>
                      <td style={{ padding: '6px 8px', color: '#cbd5e1' }}>{r.status || '—'}</td>
                      {tab.showDecline && (
                        <td style={{ padding: '6px 8px', color: '#fca5a5' }}>{r.decline_reason || '—'}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
