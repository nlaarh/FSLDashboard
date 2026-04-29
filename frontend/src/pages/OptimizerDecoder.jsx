import { useState, useEffect } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import OptimizerTimeline from '../components/OptimizerTimeline'
import OptimizerRunDetail from '../components/OptimizerRunDetail'
import OptimizerChat from '../components/OptimizerChat'
import { optimizerGetStatus } from '../api'

function PreviewBanner({ status, onDismiss }) {
  if (!status?.is_test_data) return null
  return (
    <div
      role="alert"
      className="relative flex items-center gap-3 px-4 py-3 mb-3 rounded-xl border-2 shadow-lg"
      style={{
        background: 'linear-gradient(90deg, rgba(245,158,11,0.18) 0%, rgba(239,68,68,0.18) 100%)',
        borderColor: '#f59e0b',
        boxShadow: '0 0 24px rgba(245,158,11,0.25)',
      }}
    >
      <div
        className="flex items-center justify-center rounded-full shrink-0"
        style={{ width: 36, height: 36, background: 'rgba(245,158,11,0.25)' }}
      >
        <AlertTriangle size={20} color="#fbbf24" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="font-bold text-xs tracking-wider px-2 py-0.5 rounded"
            style={{ background: '#f59e0b', color: '#1c1917', letterSpacing: '0.1em' }}
          >
            PREVIEW · COMING SOON
          </span>
          <span className="font-bold text-amber-300 text-sm uppercase tracking-wide">
            ⚠️ Test Data — Do Not Use For Decisions
          </span>
        </div>
        <div className="text-amber-100/80 text-xs mt-1.5 leading-relaxed">
          This page is a feature preview using <span className="font-semibold text-amber-200">synthetic seed data</span> (288 simulated runs over 3 days, territory 076DO) so the UI can be evaluated before real Salesforce data is wired in.
          <span className="text-amber-200 font-medium"> Numbers shown are NOT real dispatch decisions.</span> Live data integration is in progress.
        </div>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-amber-300/60 hover:text-amber-200 shrink-0 p-1"
          title="Dismiss for this session"
        >
          <X size={16} />
        </button>
      )}
    </div>
  )
}

export default function OptimizerDecoder() {
  const [selectedRun, setSelectedRun] = useState(null)
  const [selectedId, setSelectedId]   = useState(null)
  const [chatContext, setChatContext]  = useState(null)
  const [status, setStatus]           = useState(null)
  const [bannerDismissed, setBannerDismissed] = useState(false)

  useEffect(() => {
    optimizerGetStatus().then(setStatus).catch(() => {})
  }, [])

  const handleSelectRun = (run) => {
    setSelectedId(run.id)
    setSelectedRun(run)
  }

  const handleAskAI = (run) => {
    setChatContext({
      run_id:         run.id,
      run_name:       run.name || run.id,
      territory_name: run.territory_name,
      run_at:         run.run_at,
    })
  }

  const showBanner = status?.is_test_data && !bannerDismissed
  const heightOffset = showBanner ? 130 : 56
  return (
    <div className="flex flex-col gap-0">
      {showBanner && <PreviewBanner status={status} onDismiss={() => setBannerDismissed(true)} />}
      <div
        className="flex gap-0 overflow-hidden rounded-xl border border-slate-700/40 bg-slate-900/30"
        style={{ height: `calc(100vh - ${heightOffset}px - 48px)` }}
      >
        {/* Timeline sidebar */}
        <div className="w-52 border-r border-slate-700/50 flex flex-col shrink-0 overflow-hidden">
          <OptimizerTimeline onSelectRun={handleSelectRun} selectedId={selectedId} />
        </div>

        {/* Run detail — SA decisions table */}
        <div className="flex-1 flex flex-col overflow-hidden border-r border-slate-700/50">
          <OptimizerRunDetail run={selectedRun} onAskAI={handleAskAI} />
        </div>

        {/* AI Chat */}
        <div className="w-80 flex flex-col overflow-hidden shrink-0">
          <OptimizerChat runContext={chatContext} />
        </div>
      </div>
    </div>
  )
}
