import { useState, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { SAReportProvider } from './contexts/SAReportContext.jsx'
import Layout from './components/Layout'
import Landing from './pages/Landing'
import Dashboard from './pages/Dashboard'
import GarageDetail from './pages/GarageDetail'
import CommandCenter from './pages/CommandCenter'
import QueueBoard from './pages/QueueBoard'
import Forecast from './pages/Forecast'
import PtaAdvisor from './pages/PtaAdvisor'
import Admin from './pages/Admin'
import MatrixAdvisor from './pages/MatrixAdvisor'
import Help from './pages/Help'
import Issues from './pages/Issues'
import OnRoute from './pages/OnRoute'
import Accounting from './pages/Accounting'
import AccountingWoaDetail from './pages/AccountingWoaDetail'
import OptimizerDecoder from './pages/OptimizerDecoder'
import Reporting from './pages/Reporting'
import ContractorLayout from './pages/contractor/ContractorLayout'
import ContractorWatchlist from './pages/contractor/ContractorWatchlist'
import ContractorGarages from './pages/contractor/ContractorGarages'
import ContractorForecast from './pages/contractor/ContractorForecast'
import ContractorPta from './pages/contractor/ContractorPta'
import ContractorAccounting from './pages/contractor/ContractorAccounting'
import ContractorCallDetail from './pages/contractor/ContractorCallDetail'
import ContractorDispatch from './pages/contractor/ContractorDispatch'
import ContractorMap from './pages/contractor/ContractorMap'

/*
 * AuthApp — renders the full app when authenticated.
 * When /api/auth/me returns 401, renders <Landing /> at whatever URL the user is on.
 * After they log in, the browser lands back at / which re-runs this check.
 */
function AuthApp() {
  const [department, setDepartment] = useState(null)
  const [role, setRole] = useState(null)
  const [authed, setAuthed] = useState(null) // null=loading | true=ok | false=401

  useEffect(() => {
    fetch('/api/auth/me')
      .then(r => {
        if (!r.ok) { setAuthed(false); return null }
        return r.json()
      })
      .then(d => {
        if (!d) return
        setDepartment(d.department || '')
        setRole(d.role || '')
        setAuthed(true)
      })
      .catch(() => setAuthed(false))
  }, [])

  if (authed === null) return null        // loading — blank screen briefly
  if (authed === false) return <Landing /> // not authenticated — show landing in place

  const isFinance = department === 'finance'
  const isSupervisor = role === 'ers-supervisor' || role === 'ers-member-relations'
  const isContractor = role === 'contractor'

  if (isContractor) {
    return (
      <Routes>
        <Route element={<ContractorLayout />}>
          <Route path="/contractor/watchlist" element={<ContractorWatchlist />} />
          <Route path="/contractor/garages" element={<ContractorGarages />} />
          <Route path="/contractor/garage/:id" element={<GarageDetail />} />
          <Route path="/contractor/forecast" element={<ContractorForecast />} />
          <Route path="/contractor/pta" element={<ContractorPta />} />
          <Route path="/contractor/accounting" element={<ContractorAccounting />} />
          <Route path="/contractor/accounting/calls/:woId" element={<ContractorCallDetail />} />
          {/* UNRELEASED — backend 404s these unless FEATURE_CONTRACTOR_DISPATCH is on */}
          <Route path="/contractor/dispatch" element={<ContractorDispatch />} />
          <Route path="/contractor/map" element={<ContractorMap />} />
          <Route path="*" element={<Navigate to="/contractor/watchlist" replace />} />
        </Route>
      </Routes>
    )
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={isFinance ? <Navigate to="/accounting" replace /> : <CommandCenter />} />
        <Route path="/garages" element={isFinance ? <Navigate to="/accounting" replace /> : <Dashboard />} />
        <Route path="/garage/:id" element={isFinance ? <Navigate to="/accounting" replace /> : <GarageDetail />} />
        <Route path="/queue" element={isFinance ? <Navigate to="/accounting" replace /> : <QueueBoard />} />
        <Route path="/pta" element={isFinance ? <Navigate to="/accounting" replace /> : <PtaAdvisor />} />
        <Route path="/forecast" element={isFinance ? <Navigate to="/accounting" replace /> : <Forecast />} />
        <Route path="/onroute" element={isFinance ? <Navigate to="/accounting" replace /> : <OnRoute />} />
        <Route path="/matrix" element={isFinance ? <Navigate to="/accounting" replace /> : <MatrixAdvisor />} />
        <Route path="/accounting" element={(isFinance || isSupervisor) ? (isSupervisor ? <Navigate to="/" replace /> : <Accounting />) : <Accounting />} />
        <Route path="/accounting/woa/:woaId" element={<AccountingWoaDetail />} />
        <Route path="/data" element={<Navigate to="/help" replace />} />
        <Route path="/issues" element={isFinance ? <Navigate to="/accounting" replace /> : <Issues />} />
        <Route path="/help" element={isFinance ? <Navigate to="/accounting" replace /> : <Help />} />
        <Route path="/admin" element={
          (role === 'superadmin' || role === 'admin' || role === 'executive' || role === 'ers-director')
            ? <Admin role={role} />
            : <Navigate to="/" replace />
        } />
        <Route path="/optimizer" element={<Navigate to="/" replace />} />
        <Route path="/reporting" element={isFinance ? <Navigate to="/accounting" replace /> : <Reporting />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <SAReportProvider>
      <Routes>
        {/* Every URL goes through AuthApp — it renders Landing when not authenticated */}
        <Route path="/*" element={<AuthApp />} />
      </Routes>
    </SAReportProvider>
  )
}
