import { MapPinOff, Inbox, UserX, Hourglass, Shuffle, MessageSquareOff, MessageSquareWarning, Ban, Undo2, Truck, Clock, Route, AlertTriangle, XCircle } from 'lucide-react'

/** The icon key the backend sends with each explanation (wo_explain.py) -> the icon drawn for it. */
export const EXPLAIN_ICONS = {
  zone: MapPinOff, spot: Inbox, owner: UserX, hourglass: Hourglass, shuffle: Shuffle, text_off: MessageSquareOff, text_late: MessageSquareWarning,
  no_service: Ban, reject: UserX, decline: XCircle, pullback: Undo2, truck: Truck, clock: Clock, route: Route,
}
export const iconFor = key => EXPLAIN_ICONS[key] || AlertTriangle
