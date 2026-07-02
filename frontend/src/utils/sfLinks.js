// Salesforce record links.
//
// Internal staff use Lightning (aaawcny.lightning.force.com). Contractors have
// NO Lightning access — they can only reach records through the Experience Cloud
// community site. Use the contractor* helpers on any contractor-facing page.
//
// The community record URLs Salesforce generates end with a SEO name slug
// (e.g. /workorder/{id}/bowens-ers-wo-20260629), but the router resolves records
// by the 15/18-char record Id alone and redirects to the canonical slugged URL —
// so we only need the Id.

export const SF_LIGHTNING_BASE = 'https://aaawcny.lightning.force.com'

// Experience Cloud community site (contractor portal)
export const SF_COMMUNITY_BASE = 'https://aaawcny.my.site.com/aaawcnyspp/s'

/** Contractor community link to a Work Order record. */
export const contractorWoLink = (id) => (id ? `${SF_COMMUNITY_BASE}/workorder/${id}` : '')

/** Contractor community link to a Service Appointment record. */
export const contractorSaLink = (id) => (id ? `${SF_COMMUNITY_BASE}/serviceappointment/${id}` : '')
