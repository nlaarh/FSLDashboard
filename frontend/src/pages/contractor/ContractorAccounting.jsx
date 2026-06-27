import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import ContractorCalls from './ContractorCalls'
import ContractorAccountingRecs from './ContractorAccountingRecs'
import ContractorPendingWoas from './ContractorPendingWoas'
import ContractorDriverCollection from './ContractorDriverCollection'

const TABS = [
  { key: 'calls',             label: 'Work Orders' },
  { key: 'recs',              label: 'Recommendations' },
  { key: 'pending',           label: 'Work Order Adjs' },
  { key: 'driver-collection', label: 'Driver Collection' },
]

export default function ContractorAccounting() {
  const location = useLocation()
  const [activeTab, setActiveTab] = useState(location.state?.tab || 'calls')

  return (
    <div>
      {/* Page header */}
      <div className="mb-5">
        <h1 className="text-xl font-bold text-white">Accounting</h1>
        <p className="text-slate-500 text-sm mt-0.5">View your call history and submit work order adjustments</p>
      </div>

      {/* Main tabs */}
      <div className="flex gap-1 mb-5 border-b border-slate-800 pb-0">
        {TABS.map(({ key, label }) => (
          <button key={key} onClick={() => setActiveTab(key)}
            className={`px-5 py-2 text-sm font-medium transition-all border-b-2 -mb-px ${
              activeTab === key
                ? 'border-indigo-500 text-indigo-300'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'calls'   && <ContractorCalls />}
      {activeTab === 'recs'    && <ContractorAccountingRecs />}
      {activeTab === 'pending' && <ContractorPendingWoas />}
      {activeTab === 'driver-collection' && <ContractorDriverCollection />}
    </div>
  )
}
