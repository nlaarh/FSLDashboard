import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import SchedulerReportCard from './pages/SchedulerReportCard'
import './index.css'
// Dev-only: the Report Card page without the login shell, for the stub test server. Delete when done.
createRoot(document.getElementById('root')).render(<BrowserRouter><SchedulerReportCard /></BrowserRouter>)
