/**
 * SAReportContext.jsx
 *
 * Global context for opening the SA History Report modal from anywhere in the app.
 *
 * Provider: wrap <App> with <SAReportProvider>
 * Consumer: use the SALink component, or call ctx.open(number) directly
 */

import { createContext, useState, useCallback } from 'react'
import SAReportModal from '../components/SAReportModal'

export const SAReportContext = createContext(null)

export function SAReportProvider({ children }) {
  const [saNumber, setSaNumber] = useState(null)

  const open  = useCallback((number) => setSaNumber(number), [])
  const close = useCallback(() => setSaNumber(null), [])

  return (
    <SAReportContext.Provider value={{ open, close }}>
      {children}
      {saNumber && <SAReportModal saNumber={saNumber} onClose={close} />}
    </SAReportContext.Provider>
  )
}
