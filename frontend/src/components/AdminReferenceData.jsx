import { useState, useEffect, useCallback } from 'react'
import { Table2, Plus, Download, Upload, Save, X, Trash2, Loader2, CheckCircle2, Edit2 } from 'lucide-react'
import { adminRefTables, adminRefRows, adminRefAddRow, adminRefUpdateRow, adminRefDeleteRow, adminRefExportUrl } from '../api'
import { clsx } from 'clsx'

export default function AdminReferenceData({ pin }) {
  const [tables, setTables] = useState([])
  const [activeTable, setActiveTable] = useState(null)
  const [tableData, setTableData] = useState(null)   // { columns, rows, pk }
  const [loading, setLoading] = useState(false)
  const [editingPk, setEditingPk] = useState(null)
  const [editVals, setEditVals] = useState({})
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [addVals, setAddVals] = useState({})
  const [addSaving, setAddSaving] = useState(false)
  const [feedback, setFeedback] = useState('')

  useEffect(() => {
    adminRefTables(pin).then(t => {
      setTables(t)
      if (t.length > 0) setActiveTable(t[0].key)
    }).catch(() => {})
  }, [pin])

  const loadTable = useCallback(async (key) => {
    if (!key) return
    setLoading(true)
    setEditingPk(null)
    setShowAdd(false)
    setConfirmDelete(null)
    try {
      const data = await adminRefRows(pin, key)
      setTableData(data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [pin])

  useEffect(() => {
    if (activeTable) loadTable(activeTable)
  }, [activeTable, loadTable])

  const flash = (msg) => { setFeedback(msg); setTimeout(() => setFeedback(''), 2500) }

  const startEdit = (row, pkVal) => {
    setEditingPk(pkVal)
    setEditVals({ ...row })
    setConfirmDelete(null)
  }

  const saveEdit = async (pkVal) => {
    setSaving(true)
    try {
      await adminRefUpdateRow(pin, activeTable, pkVal, editVals)
      setEditingPk(null)
      await loadTable(activeTable)
      flash('Saved')
    } catch { flash('Save failed') }
    finally { setSaving(false) }
  }

  const deleteRow = async (pkVal) => {
    setDeleting(pkVal)
    try {
      await adminRefDeleteRow(pin, activeTable, pkVal)
      await loadTable(activeTable)
      flash('Deleted')
    } catch { flash('Delete failed') }
    finally { setDeleting(null); setConfirmDelete(null) }
  }

  const saveAdd = async () => {
    setAddSaving(true)
    try {
      await adminRefAddRow(pin, activeTable, addVals)
      setShowAdd(false)
      setAddVals({})
      await loadTable(activeTable)
      flash('Row added')
    } catch { flash('Add failed') }
    finally { setAddSaving(false) }
  }

  const handleImport = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    try {
      const headers = pin ? { 'X-Admin-Pin': pin } : {}
      const res = await fetch(`/api/admin/reference/${activeTable}/import`, {
        method: 'POST',
        headers,
        body: form,
      })
      const data = await res.json()
      flash(`Imported ${data.imported} rows`)
      await loadTable(activeTable)
    } catch { flash('Import failed') }
    e.target.value = ''
  }

  const cols = tableData?.columns || []
  const rows = tableData?.rows || []
  const pk = tableData?.pk

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
        <Table2 className="w-4 h-4 text-indigo-400" />
        <h2 className="text-sm font-semibold text-white">Reference Data</h2>
        <span className="text-[10px] text-slate-500 ml-1">Manage lookup tables stored in Postgres</span>
        {feedback && (
          <span className="ml-auto text-[10px] text-emerald-400 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />{feedback}
          </span>
        )}
      </div>

      {/* Table tabs */}
      <div className="flex items-center gap-1 px-4 pt-3 border-b border-slate-800/50 -mb-px">
        {tables.map(t => (
          <button key={t.key} onClick={() => setActiveTable(t.key)}
            className={clsx('px-3 py-1.5 text-xs font-medium border-b-2 transition-colors -mb-px',
              activeTable === t.key
                ? 'border-indigo-400 text-indigo-300'
                : 'border-transparent text-slate-500 hover:text-slate-300')}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="p-4">
        {/* Toolbar */}
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xs text-slate-500 flex-1">
            {loading ? 'Loading…' : `${rows.length} rows`}
          </span>
          {activeTable && (
            <a href={adminRefExportUrl(activeTable, pin)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-[11px] text-slate-400 hover:text-white transition-all">
              <Download className="w-3 h-3" />Export
            </a>
          )}
          <label className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-[11px] text-slate-400 hover:text-white transition-all cursor-pointer">
            <Upload className="w-3 h-3" />Import
            <input type="file" accept=".xlsx" className="hidden" onChange={handleImport} />
          </label>
          <button onClick={() => { setShowAdd(true); setAddVals({}) }}
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-[11px] text-white font-medium transition-all">
            <Plus className="w-3 h-3" />Add Row
          </button>
        </div>

        {/* Table */}
        {tableData && (
          <div className="overflow-x-auto rounded-lg border border-slate-700/50">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-slate-800/50 border-b border-slate-700/50">
                  {cols.map(c => (
                    <th key={c.key} className="text-left px-3 py-2 text-[10px] uppercase tracking-wider text-slate-500 font-medium">
                      {c.label}
                    </th>
                  ))}
                  <th className="px-3 py-2 w-20"></th>
                </tr>
              </thead>
              <tbody>
                {/* Add row form */}
                {showAdd && (
                  <tr className="bg-indigo-900/10 border-b border-slate-700/30">
                    {cols.map(c => (
                      <td key={c.key} className="px-2 py-1.5">
                        {c.readonly ? (
                          <span className="text-slate-600 text-[10px]">auto</span>
                        ) : c.type === 'boolean' ? (
                          <input type="checkbox"
                            checked={addVals[c.key] ?? c.default ?? false}
                            onChange={e => setAddVals(v => ({ ...v, [c.key]: e.target.checked }))}
                            className="w-4 h-4" />
                        ) : (
                          <input
                            type={c.type === 'number' ? 'number' : 'text'}
                            value={addVals[c.key] ?? ''}
                            onChange={e => setAddVals(v => ({ ...v, [c.key]: c.type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value }))}
                            placeholder={c.label}
                            className="w-full bg-slate-800 border border-indigo-500/40 rounded px-2 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-indigo-500/40"
                          />
                        )}
                      </td>
                    ))}
                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1">
                        <button onClick={saveAdd} disabled={addSaving}
                          className="p-1 text-emerald-400 hover:text-emerald-300 disabled:opacity-50">
                          {addSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                        </button>
                        <button onClick={() => setShowAdd(false)} className="p-1 text-slate-500 hover:text-slate-300">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )}

                {/* Data rows */}
                {rows.map((row, i) => {
                  const pkVal = row[pk]
                  const isEditing = editingPk === pkVal
                  return (
                    <tr key={i} className={clsx(
                      'border-b border-slate-800/40 transition-colors',
                      isEditing ? 'bg-slate-800/50' : 'hover:bg-slate-800/20'
                    )}>
                      {cols.map(c => (
                        <td key={c.key} className="px-2 py-1.5">
                          {isEditing && !c.readonly ? (
                            c.type === 'boolean' ? (
                              <input type="checkbox"
                                checked={editVals[c.key] ?? false}
                                onChange={e => setEditVals(v => ({ ...v, [c.key]: e.target.checked }))}
                                className="w-4 h-4" />
                            ) : (
                              <input
                                type={c.type === 'number' ? 'number' : 'text'}
                                value={editVals[c.key] ?? ''}
                                onChange={e => setEditVals(v => ({ ...v, [c.key]: c.type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value }))}
                                className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-0.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-indigo-500/40"
                              />
                            )
                          ) : (
                            <span className={clsx('text-slate-300', c.readonly && 'text-slate-500 font-mono text-[10px]')}>
                              {c.type === 'boolean'
                                ? (row[c.key] ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">✗</span>)
                                : String(row[c.key] ?? '')}
                            </span>
                          )}
                        </td>
                      ))}
                      <td className="px-2 py-1.5">
                        <div className="flex items-center gap-1">
                          {isEditing ? (
                            <>
                              <button onClick={() => saveEdit(pkVal)} disabled={saving}
                                className="p-1 text-emerald-400 hover:text-emerald-300 disabled:opacity-50">
                                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                              </button>
                              <button onClick={() => setEditingPk(null)} className="p-1 text-slate-500 hover:text-slate-300">
                                <X className="w-3.5 h-3.5" />
                              </button>
                            </>
                          ) : confirmDelete === pkVal ? (
                            <>
                              <button onClick={() => deleteRow(pkVal)} disabled={deleting === pkVal}
                                className="text-[10px] text-red-400 hover:text-red-300 px-1 disabled:opacity-50">
                                {deleting === pkVal ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Yes'}
                              </button>
                              <button onClick={() => setConfirmDelete(null)} className="text-[10px] text-slate-500 hover:text-slate-300 px-1">
                                No
                              </button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => startEdit(row, pkVal)} className="p-1 text-slate-500 hover:text-indigo-400 transition-colors">
                                <Edit2 className="w-3 h-3" />
                              </button>
                              <button onClick={() => setConfirmDelete(pkVal)} className="p-1 text-slate-600 hover:text-red-400 transition-colors">
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
