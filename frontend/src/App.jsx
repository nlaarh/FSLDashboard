import { useState, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { SAReportProvider } from './contexts/SAReportContext.jsx'
import Layout from './components/Layout'
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
// Optimizer hidden until live SF data is wired in
// import OptimizerDecoder from './pages/OptimizerDecoder'

export default function App() {
  const [department, setDepartment] = useState(null)

  useEffect(() => {
    fetch('/api/auth/me').then(r => r.json()).then(d => setDepartment(d.department || '')).catch(() => setDepartment(''))
  }, [])

  const isFinance = department === 'finance'
  // While loading, render null so routes aren't mounted with wrong guard
  if (department === null) return null

  return (
    <SAReportProvider>
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
        <Route path="/accounting" element={<Accounting />} />
        <Route path="/data" element={<Navigate to="/help" replace />} />
        <Route path="/issues" element={isFinance ? <Navigate to="/accounting" replace /> : <Issues />} />
        <Route path="/help" element={isFinance ? <Navigate to="/accounting" replace /> : <Help />} />
        <Route path="/admin" element={isFinance ? <Navigate to="/accounting" replace /> : <Admin />} />
        {/* Optimizer disabled until live SF data is wired — redirect to home */}
        <Route path="/optimizer" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
    </SAReportProvider>
  )
}
