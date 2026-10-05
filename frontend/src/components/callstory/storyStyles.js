/** Call Story — shared labels and colours. Times reuse the report card's Eastern formatting. */
export { fmtTime, fmtMin, fmtSpan } from '../reportcard/reportCardStyles'

export const SEVERITY = {
  OK:       { label: 'Normal',   cls: 'bg-slate-700/40 text-slate-300 border-slate-600/50', bar: '#334155' },
  SLOW:     { label: 'Slow',     cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30', bar: '#f59e0b' },
  STUCK:    { label: 'Stuck',    cls: 'bg-orange-500/15 text-orange-300 border-orange-500/30', bar: '#f97316' },
  CRITICAL: { label: 'Critical', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30', bar: '#f43f5e' },
}

export const SEGMENT_LABEL = {
  S1: 'Waiting for a garage or driver', S2: 'Assigned, not released', S3: 'Dispatched, not accepted',
  S4: 'Accepted, not rolling', S5: 'Driving', S6: 'On scene', S7: 'Rejected or declined, nobody acting',
  S8: 'Parked in SPOT', S9: 'In a grid zone, no garage',
}

export const EVENT_LABEL = {
  E01_sa_created: 'Call created', E02_first_garage: 'First garage', E04_assigned: 'Assigned',
  E06_dispatched: 'Dispatched', E07_accepted: 'Accepted', E07_declined: 'Declined', E07_rejected: 'Rejected',
  E09_garage_change: 'Garage changed', E10_pullback: 'Pulled back', E11_en_route: 'En route',
  E11_on_location: 'On location', E12_pta: 'PTA changed', E13_jeopardy: 'Jeopardy', E14_address: 'Address changed',
  E15_note: 'Note added', E17_end: 'Ended', E00_status: 'Status', E99_other: 'Other change',
}

export const ACTOR_LABEL = {
  FSL_ENGINE: 'FSL optimizer', FSL_AUTO_SCHEDULE: 'FSL auto-schedule', INTEGRATION: 'Integration',
  HUMAN: 'AAA dispatcher', GARAGE_DISPATCHER: 'Garage dispatcher', DRIVER: 'Driver', TOWBOOK_SYNC: 'Towbook',
  CALL_TAKER: 'Call taker', OTHER: 'Other',
}

export const LADDER_STATE = {
  final:          { label: 'Final garage', cls: 'text-emerald-300' },
  tried:          { label: 'Tried', cls: 'text-slate-200' },
  declined:       { label: 'Declined', cls: 'text-amber-300' },
  rejected:       { label: 'Driver rejected', cls: 'text-rose-300' },
  skipped_closed: { label: 'Closed (inferred)', cls: 'text-slate-400' },
  not_reached:    { label: 'Not reached', cls: 'text-slate-500' },
}
