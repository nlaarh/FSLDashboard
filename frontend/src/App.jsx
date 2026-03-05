import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import GarageDetail from './pages/GarageDetail'
import CommandCenter from './pages/CommandCenter'
import MapPage from './pages/MapPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/garage/:id" element={<GarageDetail />} />
        <Route path="/command-center" element={<CommandCenter />} />
        <Route path="/map" element={<MapPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
