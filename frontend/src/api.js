import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

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

// Daily Operations (correct PTA/ATA)
export const fetchOpsTerritories = () => api.get('/ops/territories').then(r => r.data)
export const fetchOpsTerritory = (id) => api.get(`/ops/territory/${id}`).then(r => r.data)
export const fetchOpsGarages = () => api.get('/ops/garages').then(r => r.data)
