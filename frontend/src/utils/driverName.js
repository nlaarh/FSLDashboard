/** A driver's name as people say it: Salesforce adds the garage's truck number to it ("Marcus Gibson 100", "Ann Lee 12A"). */
export const shortDriverName = name => String(name ?? '').replace(/\s+\d{2,3}[A-Z]{0,2}$/, '')
