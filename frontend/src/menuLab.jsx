import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import SchedulerReportCard from './pages/SchedulerReportCard'
import './index.css'
// Dev-only: the REAL app menu (Layout) with the two report pages, for the stub test server. Delete when done.
const go = new URLSearchParams(location.search).get('go') || '/replay'
createRoot(document.getElementById('root')).render(
  <MemoryRouter initialEntries={[go]}>
    <Routes><Route element={<Layout />}>
      <Route path="/report-card" element={<SchedulerReportCard />} />
      <Route path="/replay" element={<SchedulerReportCard view="replay" />} />
      <Route path="*" element={<div />} />
    </Route></Routes>
  </MemoryRouter>)
