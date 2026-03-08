import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 60000 })

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
export const lookupSA = (number) => api.get(`/sa/${number}`).then(r => r.data)
export const fetchPerformance = (id, start, end) =>
  api.get(`/garages/${id}/performance?period_start=${start}&period_end=${end}`).then(r => r.data)
export const fetchMapGrids = () => api.get('/map/grids').then(r => r.data)
export const fetchMapDrivers = () => api.get('/map/drivers').then(r => r.data)
export const fetchMapWeather = () => api.get('/map/weather').then(r => r.data)
export const fetchHealth = () => api.get('/health').then(r => r.data)
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

// Daily Operations (correct PTA/ATA)
export const fetchOpsTerritories = () => api.get('/ops/territories').then(r => r.data)
export const fetchOpsTerritory = (id) => api.get(`/ops/territory/${id}`).then(r => r.data)
export const fetchOpsGarages = () => api.get('/ops/garages').then(r => r.data)
export const fetchOpsBrief = () => api.get('/ops/brief').then(r => r.data)

// Admin (PIN-protected)
const pinHeader = (pin) => ({ headers: { 'X-Admin-Pin': pin } })
export const adminVerify = (pin) => api.post('/admin/verify', null, pinHeader(pin)).then(r => r.data)
export const adminStatus = (pin) => api.get('/admin/status', pinHeader(pin)).then(r => r.data)
export const adminFlush = (pin, prefix = '') => api.post(`/admin/flush?prefix=${prefix}`, null, pinHeader(pin)).then(r => r.data)
export const adminFlushLive = (pin) => api.post('/admin/flush/live', null, pinHeader(pin)).then(r => r.data)
export const adminFlushHistorical = (pin) => api.post('/admin/flush/historical', null, pinHeader(pin)).then(r => r.data)
export const adminFlushStatic = (pin) => api.post('/admin/flush/static', null, pinHeader(pin)).then(r => r.data)

// User Management (PIN-protected)
export const adminListUsers = (pin) => api.get('/admin/users', pinHeader(pin)).then(r => r.data)
export const adminCreateUser = (pin, data) => api.post('/admin/users', data, pinHeader(pin)).then(r => r.data)
export const adminUpdateUser = (pin, username, data) => api.put(`/admin/users/${username}`, data, pinHeader(pin)).then(r => r.data)
export const adminDeleteUser = (pin, username) => api.delete(`/admin/users/${username}`, pinHeader(pin)).then(r => r.data)
export const adminListSessions = (pin) => api.get('/admin/sessions', pinHeader(pin)).then(r => r.data)
