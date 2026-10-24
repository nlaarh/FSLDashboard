// Pending-change logic for the Access screen (kept free of React so it can be tested).

const sameList = (a, b) => a.length === b.length && a.every(x => b.includes(x))

/** Features whose edited role list differs from the saved one: { key: [roles] }. */
export function diffFeatures(original, edited) {
  const out = {}
  for (const [key, roles] of Object.entries(edited)) if (!sameList(roles, original[key] || [])) out[key] = roles
  return out
}

export const userRoleList = u => [u.primary, ...u.extra]

/** Tick or untick `role` for a user {primary, extra}. Never touches a restricted role (see blockedReason). */
export function toggleUserRole(u, role, exclusive) {
  const roles = userRoleList(u)
  if (roles.includes(role)) return role === u.primary ? u : { ...u, extra: u.extra.filter(r => r !== role) }
  if (blockedReason(u, role, exclusive)) return u
  return { ...u, extra: [...u.extra, role] }
}

/** Why a cell cannot be ticked, or '' if it can. Restricted roles (contractor, ers-supervisor, ers-member-relations)
 *  are never added to a user, never added next to one, and never replaced from this screen. */
export function blockedReason(u, role, exclusive) {
  const roles = userRoleList(u)
  if (roles.includes(role)) return ''
  if (exclusive.includes(role)) return `${role} is a restricted role and cannot be added here`
  const held = roles.find(r => exclusive.includes(r))
  return held ? `${held} is a restricted role: change it in Users & Sessions` : ''
}

/** Make a ticked role the primary one; the old primary stays as an extra. */
export const makePrimary = (u, role) =>
  role === u.primary || !u.extra.includes(role) ? u : { primary: role, extra: [u.primary, ...u.extra.filter(r => r !== role)] }

/** Users whose roles changed: [{username, primary, extra}]. */
export function diffUsers(original, edited) {
  return Object.entries(edited)
    .filter(([name, u]) => u.primary !== original[name].primary || !sameList(u.extra, original[name].extra))
    .map(([username, u]) => ({ username, primary: u.primary, extra: u.extra }))
}

/** Set (not toggle) a role for a user, so a drag over mixed cells ends up all alike. Blocked or primary cells stay as they are. */
export function setUserRole(u, role, value, exclusive) {
  if (userRoleList(u).includes(role) === value) return u
  return toggleUserRole(u, role, exclusive)
}
