// True when FleetPulse is shown inside another page (Salesforce Canvas iframe).
// Embed sessions come from POST /embed/canvas, not the password login.
export function isEmbedded() {
  if (new URLSearchParams(window.location.search).get('embed')) return true
  try { return window.self !== window.top } catch { return true }
}
