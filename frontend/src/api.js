import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 60000 })

// Retry transient failures (network errors, 502/503/504) up to 2 times
api.interceptors.response.use(
  res => res,
  async err => {
    const config = err.config
    if (!config) return Promise.reject(err)
    config._retryCount = config._retryCount || 0
    const status = err.response?.status
    const isRetryable = !status || status === 502 || status === 503 || status === 504
    if (isRetryable && config._retryCount < 2 && config.method === 'get') {
      config._retryCount += 1
      await new Promise(r => setTimeout(r, 1000 * config._retryCount))
      return api(config)
    }
    // Redirect to login on 401 (expired session or not logged in)
    if (status === 401 && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export const fetchGarages = () => api.get('/garages').then(r => r.data)
export const fetchSchedule = (id, { weeks = 4, startDate, endDate } = {}) => {
  const params = new URLSearchParams({ weeks })
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  return api.get(`/garages/${id}/schedule?${params}`).then(r => r.data)
}
export const fetchScorecard = (id, weeks = 4) => api.get(`/garages/${id}/scorecard?weeks=${weeks}`).then(r => r.data)
export const fetchAppointments = (id, date) => api.get(`/garages/${id}/appointments?date=${date}`).then(r => r.data)
export const fetchSimulation = (id, date) => api.get(`/garages/${id}/simulate?date=${date}`).then(r => r.data)
export const fetchScore = (id, weeks = 4) => api.get(`/garages/${id}/score?weeks=${weeks}`).then(r => r.data)
export const fetchCommandCenter = (hours = 24) => api.get(`/command-center?hours=${hours}`).then(r => r.data)
export const fetchSchedulerInsights = () => api.get('/scheduler-insights').then(r => r.data)
export const lookupSA = (number) => api.get(`/sa/${number}`).then(r => r.data)
export const fetchSAReport = (number) => api.get(`/sa/${number}/report`).then(r => r.data)
export const fetchPerformance = (id, start, end) =>
  api.get(`/garages/${id}/performance?period_start=${start}&period_end=${end}`).then(r => r.data)
export const fetchMapGrids = () => api.get('/map/grids').then(r => r.data)
export const fetchMapDrivers = () => api.get('/map/drivers').then(r => r.data)
export const fetchMapWeather = () => api.get('/map/weather').then(r => r.data)
export const fetchHealth = () => api.get('/health').then(r => r.data)
export const fetchGpsHealth = () => api.get('/gps-health').then(r => r.data)
export const fetchDbStatus = () => api.get('/db/status').then(r => r.data)
export const triggerSync = () => api.post('/sync').then(r => r.data)

// Dispatch Optimization
export const fetchQueue = () => api.get('/dispatch/queue').then(r => r.data)
export const fetchRecommend = (saId) => api.get(`/dispatch/recommend/${saId}`).then(r => r.data)
export const fetchCascade = (territoryId) => api.get(`/dispatch/cascade/${territoryId}`).then(r => r.data)
export const fetchDecomposition = (id, start, end) =>
  api.get(`/garages/${id}/decomposition?period_start=${start}&period_end=${end}`).then(r => r.data)
export const fetchForecast = (territoryId, weeks = 8) =>
  api.get(`/territory/${territoryId}/forecast?weeks_history=${weeks}`).then(r => r.data)

// Garage Performance Scorecard
export const fetchGarageScorecard = (id, startDate, endDate) =>
  api.get(`/garages/${id}/performance-scorecard?start_date=${startDate}&end_date=${endDate}`).then(r => r.data)
export const fetchGarageAiSummary = (id, startDate, endDate) =>
  api.get(`/garages/${id}/performance-scorecard/ai-summary?start_date=${startDate}&end_date=${endDate}`).then(r => r.data)
export const fetchDriverSAs = (id, driverName, saType = 'completed', startDate, endDate) =>
  api.get(`/garages/${id}/driver-sas?driver_name=${encodeURIComponent(driverName)}&sa_type=${saType}&start_date=${startDate}&end_date=${endDate}`).then(r => r.data)
export const fetchGarageDriverSAs = (garageName, month, driverName, saType = 'completed') =>
  api.get(`/insights/satisfaction/garage/${encodeURIComponent(garageName)}/driver-sas?month=${month}&driver=${encodeURIComponent(driverName)}&sa_type=${saType}`).then(r => r.data)

export const exportGarageScorecard = (id, startDate, endDate) => {
  const url = `/api/garages/${id}/performance-scorecard/export?start_date=${startDate}&end_date=${endDate}`
  const a = document.createElement('a')
  a.href = url
  a.download = `garage_scorecard_${startDate}_to_${endDate}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
}

export const emailGarageReport = (id, to, startDate, endDate, garageName) =>
  api.post(`/garages/${id}/performance-scorecard/email`, { to, start_date: startDate, end_date: endDate, garage_name: garageName }).then(r => r.data)

// Dispatch Insights Drill-Down (lazy, on-demand)
export const fetchReassignmentDetail = () => api.get('/insights/reassignment-detail').then(r => r.data)
export const fetchDispatcherDetail = (name) => api.get(`/insights/dispatcher-detail/${encodeURIComponent(name)}`).then(r => r.data)
export const fetchDriverDetail = (name) => api.get(`/insights/driver-detail/${encodeURIComponent(name)}`).then(r => r.data)
export const fetchCancelDetail = (reason) => api.get(`/insights/cancel-detail/${encodeURIComponent(reason)}`).then(r => r.data)
export const fetchDeclineDetail = (reason) => api.get(`/insights/decline-detail/${encodeURIComponent(reason)}`).then(r => r.data)
export const fetchStatusDetail = (status) => api.get(`/insights/status-detail/${encodeURIComponent(status)}`).then(r => r.data)
export const fetchCapacityDetail = (name) => api.get(`/insights/capacity-detail/${encodeURIComponent(name)}`).then(r => r.data)
export const fetchGpsDetail = (bucket) => api.get(`/insights/gps-detail/${encodeURIComponent(bucket)}`).then(r => r.data)
export const fetchHumanIntervention = () => api.get('/insights/human-intervention').then(r => r.data)
export const fetchClosestDriverDetail = () => api.get('/insights/closest-driver-detail').then(r => r.data)
export const fetchTrends = () => api.get('/insights/trends').then(r => r.data)
export const forceTrendsRefresh = () => api.get('/insights/trends/refresh').then(r => r.data)
export const fetchMonthTrends = (month) => api.get(`/insights/trends/month?month=${month}`).then(r => r.data)
export const refreshMonthTrends = (month) => api.get(`/insights/trends/month/refresh?month=${month}`).then(r => r.data)

// Satisfaction Score Analysis
export const fetchSatisfactionOverview = (month) => api.get(`/insights/satisfaction/overview?month=${month}`).then(r => r.data)
export const refreshSatisfactionOverview = (month) => api.get(`/insights/satisfaction/refresh?month=${month}`).then(r => r.data)
export const fetchSatisfactionGarage = (name, month) => api.get(`/insights/satisfaction/garage/${encodeURIComponent(name)}?month=${month}`).then(r => r.data)
export const fetchSatisfactionDetail = (name, date) => api.get(`/insights/satisfaction/detail/${encodeURIComponent(name)}/${date}`).then(r => r.data)
export const fetchSatisfactionDetailAI = (name, date) => api.get(`/insights/satisfaction/detail/${encodeURIComponent(name)}/${date}/ai-summary`).then(r => r.data)
export const fetchSatisfactionDay = (date) => api.get(`/insights/satisfaction/day/${date}`).then(r => r.data)
export const fetchSatisfactionScorecard = () => api.get('/insights/satisfaction/scorecard').then(r => r.data)

// Daily Operations (correct PTA/ATA)
export const fetchOpsTerritories = () => api.get('/ops/territories').then(r => r.data)
export const fetchOpsTerritory = (id) => api.get(`/ops/territory/${id}`).then(r => r.data)
export const fetchOpsGarages = () => api.get('/ops/garages').then(r => r.data)
export const fetchOpsBrief = () => api.get('/ops/brief').then(r => r.data)

// PTA Advisor
export const fetchPtaAdvisor = () => api.get('/pta-advisor').then(r => r.data)
export const refreshPtaAdvisor = (pin) => api.post('/pta-advisor/refresh', null, pinHeader(pin)).then(r => r.data)
export const adminGetSettings = (pin) => api.get('/admin/settings', pinHeader(pin)).then(r => r.data)
export const adminUpdateSettings = (pin, data) => api.put('/admin/settings', data, pinHeader(pin)).then(r => r.data)

// Matrix Advisor
export const fetchMatrixHealth = (period = 'last_month') =>
  api.get(`/matrix/health?period=${period}`).then(r => r.data)

// Data Quality
export const fetchDataQuality = () => api.get('/data-quality').then(r => r.data)
export const refreshDataQuality = () => api.post('/data-quality/refresh').then(r => r.data)

// Admin (PIN-protected)
const pinHeader = (pin) => ({ headers: { 'X-Admin-Pin': pin } })
export const adminVerify = (pin) => api.post('/admin/verify', null, pinHeader(pin)).then(r => r.data)
export const adminStatus = (pin) => api.get('/admin/status', pinHeader(pin)).then(r => r.data)
export const adminFlush = (pin, prefix = '') => api.post(`/admin/flush?prefix=${prefix}`, null, pinHeader(pin)).then(r => r.data)
export const adminFlushLive = (pin) => api.post('/admin/flush/live', null, pinHeader(pin)).then(r => r.data)
export const adminFlushHistorical = (pin) => api.post('/admin/flush/historical', null, pinHeader(pin)).then(r => r.data)
export const adminFlushStatic = (pin) => api.post('/admin/flush/static', null, pinHeader(pin)).then(r => r.data)

// Issue Reporting & Management
export const submitIssue = (data) => api.post('/issues', data).then(r => r.data)
export const fetchIssues = (state = 'open') => api.get(`/issues?state=${state}`).then(r => r.data)
export const fetchIssue = (num) => api.get(`/issues/${num}`).then(r => r.data)
export const addIssueComment = (num, comment, name) => api.post(`/issues/${num}/comments`, { comment, name }).then(r => r.data)
export const updateIssueStatus = (pin, num, status) => api.patch(`/issues/${num}`, { status }, pinHeader(pin)).then(r => r.data)
export const triageIssues = (pin) => api.post('/issues/triage', null, pinHeader(pin)).then(r => r.data)

// Feature Flags
export const fetchFeatures = () => api.get('/features').then(r => r.data)

// Accounting — Work Order Adjustments
export const fetchWOAdjustments = (status = 'open', page = 0, pageSize = 50, product = '', rec = '', q = '', sortCol = 'created_date', sortDir = 'desc', startDate = '', endDate = '') =>
  api.get(`/accounting/wo-adjustments?status=${status}&page=${page}&page_size=${pageSize}&product_filter=${product}&rec_filter=${rec}&q=${encodeURIComponent(q)}&sort_col=${sortCol}&sort_dir=${sortDir}&start_date=${startDate}&end_date=${endDate}`).then(r => r.data)
export const fetchWOAAudit = (woaId) =>
  api.get(`/accounting/wo-adjustments/${woaId}/audit`).then(r => r.data)
export const fetchWOAAiAnalysis = (woaId) =>
  api.get(`/accounting/wo-adjustments/${woaId}/ai-analysis`).then(r => r.data)
export const fetchWOARecommendations = (ids) =>
  api.get(`/accounting/wo-adjustments/recommendations?ids=${ids.join(',')}`).then(r => r.data)
export const recalculateWOAAudit = (woaId) =>
  api.post(`/accounting/wo-adjustments/${woaId}/recalculate`).then(r => r.data)
export const fetchWOAReviewStatuses = (ids) =>
  api.get(`/accounting/wo-adjustments/review-statuses?ids=${ids.join(',')}`).then(r => r.data)
export const setWOAReview = (woaId, status, note = '', reviewer = '') =>
  api.post(`/accounting/wo-adjustments/${woaId}/review`, { status, note, reviewer }).then(r => r.data)

// Live Dispatch Board + SA Watchlist
export const fetchLiveDispatch = () => api.get('/live-dispatch').then(r => r.data)
export const fetchWatchlist = () => api.get('/watchlist').then(r => r.data)
export const fetchWatchlistManual = () => api.get('/watchlist/manual').then(r => r.data)
export const fetchDispatchAssist = (saId, hints = {}) => {
  const params = new URLSearchParams({ sa_id: saId })
  if (hints.territory) params.append('territory', hints.territory)
  if (hints.lat) params.append('lat', hints.lat)
  if (hints.lon) params.append('lon', hints.lon)
  if (hints.work_type_id) params.append('work_type_id', hints.work_type_id)
  return api.get(`/watchlist/dispatch-assist?${params}`).then(r => r.data)
}
export const followSA = (sa_number, sa_id = '', added_by = '') => api.post('/watchlist/follow', { sa_number, sa_id, added_by }).then(r => r.data)
export const unfollowSA = (sa_number) => api.delete(`/watchlist/follow/${sa_number}`).then(r => r.data)

// On-Route Tracking
export const fetchOnRoute = () => api.get('/onroute').then(r => r.data)
export const createTrackingLink = (saId) => api.post('/track/create', { sa_id: saId }).then(r => r.data)

// AI Insights
export const fetchInsights = (category) =>
  api.get(`/insights/${category}`).then(r => r.data)

// Chatbot
export const fetchChatbotModels = () => api.get('/chatbot/models').then(r => r.data)
export const askChatbot = (question, complexity = 'mid', history = []) =>
  api.post('/chat', { question, complexity, history }, { timeout: 90000 }).then(r => r.data)

// User Management (PIN-protected)
export const adminListUsers = (pin) => api.get('/admin/users', pinHeader(pin)).then(r => r.data)
export const adminCreateUser = (pin, data) => api.post('/admin/users', data, pinHeader(pin)).then(r => r.data)
export const adminUpdateUser = (pin, username, data) => api.put(`/admin/users/${username}`, data, pinHeader(pin)).then(r => r.data)
export const adminDeleteUser = (pin, username) => api.delete(`/admin/users/${username}`, pinHeader(pin)).then(r => r.data)
export const adminListSessions = (pin) => api.get('/admin/sessions', pinHeader(pin)).then(r => r.data)
export const adminGetBonusTiers = (pin) => api.get('/admin/bonus-tiers', pinHeader(pin)).then(r => r.data)
export const adminSetBonusTiers = (pin, tiers) => api.put('/admin/bonus-tiers', tiers, pinHeader(pin)).then(r => r.data)
export const adminGetActivityLog = (pin, limit = 100) => api.get(`/admin/activity-log?limit=${limit}`, pinHeader(pin)).then(r => r.data)
export const adminGetActivityStats = (pin) => api.get('/admin/activity-stats', pinHeader(pin)).then(r => r.data)
export const adminClearActivityLog = (pin) => api.delete('/admin/activity-log', pinHeader(pin)).then(r => r.data)
// No PIN required — Admin.jsx guards the page; endpoint is read-only audit data
export const adminGetOptimizerSyncAudit = (limit = 50) => api.get(`/optimizer/admin/sync-audit?limit=${limit}`).then(r => r.data)
export const adminGetAccountingRates = (pin) => api.get('/admin/accounting-rates', pinHeader(pin)).then(r => r.data)
export const adminSetAccountingRate = (pin, code, value) => api.put(`/admin/accounting-rates/${code}`, { value }, pinHeader(pin)).then(r => r.data)
export const fetchAccountingRates = () => api.get('/accounting/rates').then(r => r.data)
export const fetchAccountingAnalytics = (status = 'open') => api.get(`/accounting/analytics?status=${status}`).then(r => r.data)
export const fetchAccountingAiInsights = (status = 'open') => api.get(`/accounting/analytics/ai-insights?status=${status}`).then(r => r.data)
export const fetchAccountingAging = (status = 'open') => api.get(`/accounting/analytics/aging?status=${status}`).then(r => r.data)

// Optimizer Decoder
export const optimizerGetStatus = () => api.get('/optimizer/status').then(r => r.data)
export const optimizerGetRuns = (params = {}) => api.get('/optimizer/runs', { params }).then(r => r.data)
export const optimizerGetRun = (runId) => api.get(`/optimizer/runs/${runId}`).then(r => r.data)
export const optimizerGetSA = (saNumber, limit = 5, runId = null) =>
  api.get(`/optimizer/sa/${saNumber}`, { params: runId ? { run_id: runId } : { limit } }).then(r => r.data)
export const optimizerGetDriver = (driverName, days = 7) => api.get(`/optimizer/driver/${encodeURIComponent(driverName)}?days=${days}`).then(r => r.data)
export const optimizerGetUnscheduled = (runId) => api.get(`/optimizer/runs/${runId}/unscheduled`).then(r => r.data)
export const optimizerGetPatterns = (territory, days = 7) => api.get('/optimizer/patterns', { params: { territory, days } }).then(r => r.data)
export const optimizerListFiles = (date = null) =>
  api.get('/optimizer/files', { params: date ? { date } : {} }).then(r => r.data)
export const optimizerLatestDate = () =>
  api.get('/optimizer/files/latest-date').then(r => r.data)
export const optimizerRunHealth = (runId) => api.get(`/optimizer/runs/${runId}/health`).then(r => r.data)
export const optimizerDriverDay = (runId, driverId) =>
  api.get(`/optimizer/runs/${runId}/driver/${driverId}/day`).then(r => r.data)
// Build absolute URL so the browser handles the download (auth cookie auto-attached)
export const optimizerRunZipUrl = (runId) => `/api/optimizer/files/${runId}/download`
export const optimizerDateZipUrl = (date) => `/api/optimizer/files/by-date/${date}/download`
export const optimizerChat = (messages, runContext = null) =>
  api.post('/optimizer/chat', { messages, run_context: runContext }).then(r => r.data)

// Garage Driver Revenue
export const fetchDriverRevenue = (id, startDate, endDate, bust = false) =>
  api.get(`/garages/${id}/driver-revenue?start_date=${startDate}&end_date=${endDate}${bust ? '&bust=true' : ''}`, { timeout: 120000 }).then(r => r.data)
export const fetchDriverRevenueDaily = (id, driverName, startDate, endDate) =>
  api.get(`/garages/${id}/driver-revenue/${encodeURIComponent(driverName)}/daily?start_date=${startDate}&end_date=${endDate}`, { timeout: 120000 }).then(r => r.data)
export const exportDriverRevenue = (id, startDate, endDate, garageName) => {
  const a = document.createElement('a')
  a.href = `/api/garages/${id}/driver-revenue/export?start_date=${startDate}&end_date=${endDate}&garage_name=${encodeURIComponent(garageName || '')}`
  a.download = `driver_revenue_${startDate}_${endDate}.xlsx`
  document.body.appendChild(a); a.click(); a.remove()
}
export const emailDriverRevenue = (id, to, startDate, endDate, garageName) =>
  api.post(`/garages/${id}/driver-revenue/email`, { to, start_date: startDate, end_date: endDate, garage_name: garageName }).then(r => r.data)

// Reporting
export const fetchReportSummary = (garageIds, startDate, endDate) => {
  const params = new URLSearchParams()
  garageIds.forEach(id => params.append('garage_ids', id))
  params.set('start_date', startDate)
  params.set('end_date', endDate)
  return api.get(`/reporting/garage-summary?${params}`).then(r => r.data)
}

export const exportReportSummary = (garageIds, startDate, endDate) => {
  const params = new URLSearchParams()
  garageIds.forEach(id => params.append('garage_ids', id))
  params.set('start_date', startDate)
  params.set('end_date', endDate)
  const a = document.createElement('a')
  a.href = `/api/reporting/garage-summary/export?${params}`
  a.download = `garage_report_${startDate}_to_${endDate}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
}
