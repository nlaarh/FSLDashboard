import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import GarageDetail from './pages/GarageDetail'
import CommandCenter from './pages/CommandCenter'
import QueueBoard from './pages/QueueBoard'
import Forecast from './pages/Forecast'
import PtaAdvisor from './pages/PtaAdvisor'
import Admin from './pages/Admin'
// import MatrixAdvisor from './pages/MatrixAdvisor'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<CommandCenter />} />
        <Route path="/garages" element={<Dashboard />} />
        <Route path="/garage/:id" element={<GarageDetail />} />
        <Route path="/queue" element={<QueueBoard />} />
        <Route path="/pta" element={<PtaAdvisor />} />
        <Route path="/forecast" element={<Forecast />} />
        {/* <Route path="/matrix" element={<MatrixAdvisor />} /> */}
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
