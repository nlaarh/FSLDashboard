import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchGarages } from '../api'
import { MapPin, TrendingUp, Search, ChevronRight } from 'lucide-react'

export default function Dashboard() {
  const [garages, setGarages] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    fetchGarages()
      .then(setGarages)
      .catch(e => console.error('Failed to load garages:', e))
      .finally(() => setLoading(false))
  }, [])

  const filtered = garages.filter(g =>
    g.name?.toLowerCase().includes(search.toLowerCase()) ||
    g.city?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div>
      <div className="flex items-end justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white">Garage Operations</h1>
          <p className="text-slate-400 mt-1">Select a garage to view schedule, scorecard, and dispatch analysis</p>
        </div>
        <div className="text-sm text-slate-500">
          {garages.length} garages loaded
        </div>
      </div>

      {/* Search */}
      <div className="relative mb-6 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text"
          placeholder="Search garages..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full pl-10 pr-4 py-2.5 bg-slate-900 border border-slate-700 rounded-xl text-sm
                     placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/40
                     focus:border-brand-500 transition-all"
        />
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="skeleton h-28 rounded-xl" />
          ))}
        </div>
      )}

      {/* Garage grid */}
      {!loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(g => (
            <button
              key={g.id}
              onClick={() => navigate(`/garage/${g.id}`)}
              className="glass rounded-xl p-5 text-left hover:bg-slate-800/60 hover:border-brand-500/30
                         transition-all duration-200 group cursor-pointer"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-white truncate group-hover:text-brand-300 transition-colors">
                    {g.name}
                  </h3>
                  {g.city && (
                    <div className="flex items-center gap-1 mt-1 text-sm text-slate-400">
                      <MapPin className="w-3.5 h-3.5 flex-shrink-0" />
                      <span className="truncate">{g.city}{g.state ? `, ${g.state}` : ''}</span>
                    </div>
                  )}
                </div>
                <ChevronRight className="w-5 h-5 text-slate-600 group-hover:text-brand-400 transition-colors flex-shrink-0 mt-0.5" />
              </div>
              <div className="mt-3 flex items-center gap-2">
                <div className="flex items-center gap-1 px-2.5 py-1 bg-slate-800/80 rounded-lg">
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-sm font-medium text-slate-300">{g.sa_count_28d}</span>
                  <span className="text-xs text-slate-500">SAs / 28d</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="text-center py-20 text-slate-500">
          {search ? 'No garages match your search.' : 'No garages found.'}
        </div>
      )}
    </div>
  )
}
