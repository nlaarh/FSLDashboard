/**
 * SALink.jsx
 *
 * Wrap any SA number to make it clickable — opens the SA History Report modal.
 *
 * Usage:
 *   <SALink number="SA-717120">SA-717120</SALink>
 *   <SALink number={sa.number} />          ← renders the number as the label
 *   <SALink number={sa.number} className="text-xs" />
 *
 * Requires SAReportProvider to be mounted above in the tree (see App.jsx).
 */

import { useContext } from 'react'
import { SAReportContext } from '../contexts/SAReportContext.jsx'

export default function SALink({ number, children, style, className }) {
  const ctx = useContext(SAReportContext)
  if (!number) return children ?? null

  const label = children ?? number

  const handleClick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    ctx?.open(number)
  }

  return (
    <button
      onClick={handleClick}
      title={`View SA History Report for ${number}`}
      style={{
        background: 'none',
        border: 'none',
        padding: 0,
        cursor: 'pointer',
        color: '#818cf8',
        fontWeight: 600,
        textDecoration: 'underline',
        textDecorationStyle: 'dotted',
        textUnderlineOffset: 2,
        fontFamily: 'inherit',
        fontSize: 'inherit',
        ...style,
      }}
      className={className}
    >
      {label}
    </button>
  )
}
