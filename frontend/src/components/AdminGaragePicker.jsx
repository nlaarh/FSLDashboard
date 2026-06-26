import { useState, useEffect, useRef } from 'react'
import { Loader2, Search, Building2 } from 'lucide-react'
import { adminTerritoriesList } from '../api'

/**
 * Searchable multi-select checkbox list for assigning garages (ServiceTerritories) to contractor users.
 *
 * Props:
 *   pin           - Admin PIN (forwarded to territories-list endpoint)
 *   selected      - string[] of selected territory IDs
 *   onChange      - (ids: string[]) => void
 */
export default function AdminGaragePicker({ pin, selected = [], onChange }) {
  const [territories, setTerritories] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const loaded = useRef(false)

  // Load once — territories list is relatively static
  useEffect(() => {
    if (loaded.current) return
    loaded.current = true
    setLoading(true)
    adminTerritoriesList(pin)
      .then(data => setTerritories(data.territories || []))
      .catch(() => setError('Could not load garages'))
      .finally(() => setLoading(false))
  }, [pin])

  const filtered = territories.filter(t =>
    t.name.toLowerCase().includes(search.toLowerCase()) ||
    t.id.toLowerCase().includes(search.toLowerCase())
  )

  const toggle = (id) => {
    const next = selected.includes(id)
      ? selected.filter(x => x !== id)
      : [...selected, id]
    onChange(next)
  }

  const selectedCount = selected.length

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Assigned Garages</span>
        {selectedCount > 0 && (
          <span className="text-[10px] font-semibold text-fuchsia-400">
            {selectedCount} garage{selectedCount !== 1 ? 's' : ''} selected
          </span>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading garages…
        </div>
      )}

      {error && (
        <div className="text-xs text-red-400 py-1">{error}</div>
      )}

      {!loading && !error && (
        <div className="rounded-lg border border-slate-700 bg-slate-900 overflow-hidden">
          {/* Search */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-700/60">
            <Search className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search garages…"
              className="flex-1 bg-transparent text-xs text-slate-200 placeholder:text-slate-600 outline-none"
            />
          </div>

          {/* List */}
          <div className="overflow-y-auto" style={{ maxHeight: '250px' }}>
            {filtered.length === 0 && (
              <div className="py-6 text-center text-xs text-slate-600">
                {search ? 'No garages match your search' : 'No garages available'}
              </div>
            )}
            {filtered.map(t => {
              const isChecked = selected.includes(t.id)
              return (
                <label
                  key={t.id}
                  className={`flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors hover:bg-slate-800/60 border-b border-slate-800/40 last:border-0 ${
                    isChecked ? 'bg-fuchsia-950/20' : ''
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggle(t.id)}
                    className="w-3.5 h-3.5 rounded border-slate-600 accent-fuchsia-500 cursor-pointer flex-shrink-0"
                  />
                  <Building2 className={`w-3 h-3 flex-shrink-0 ${isChecked ? 'text-fuchsia-400' : 'text-slate-600'}`} />
                  <span className={`text-xs truncate ${isChecked ? 'text-fuchsia-200 font-medium' : 'text-slate-400'}`}>
                    {t.name}
                  </span>
                </label>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
