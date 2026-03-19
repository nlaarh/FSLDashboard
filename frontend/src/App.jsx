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

export default function App() {
  return (
    <SAReportProvider>
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<CommandCenter />} />
        <Route path="/garages" element={<Dashboard />} />
        <Route path="/garage/:id" element={<GarageDetail />} />
        <Route path="/queue" element={<QueueBoard />} />
        <Route path="/pta" element={<PtaAdvisor />} />
        <Route path="/forecast" element={<Forecast />} />
        <Route path="/onroute" element={<OnRoute />} />
        <Route path="/matrix" element={<MatrixAdvisor />} />
        <Route path="/data" element={<Navigate to="/help" replace />} />
        <Route path="/issues" element={<Issues />} />
        <Route path="/help" element={<Help />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
    </SAReportProvider>
  )
}
