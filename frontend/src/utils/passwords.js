export const PASSWORD_LENGTH = 12
export const PASSWORD_SPECIAL = "!@#$%^&*()_+-=[]{}|;:',.<>?/`~"
export const FORM_PASSWORD_COPY_KEY = '__form_password__'
export const EMPTY_USER_FORM = {
  username: '',
  password: '',
  passwordConfirm: '',
  name: '',
  role: 'viewer',
  email: '',
  phone: '',
  department: '',
  territories: [],
}

function shuffle(chars) {
  const arr = [...chars]
  for (let i = arr.length - 1; i > 0; i--) {
    const j = randomIndex(i + 1)
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr.join('')
}

function randomIndex(max) {
  if (globalThis.crypto?.getRandomValues) {
    const values = new Uint32Array(1)
    globalThis.crypto.getRandomValues(values)
    return values[0] % max
  }
  return Math.floor(Math.random() * max)
}

export function generatePassword() {
  const upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
  const lower = 'abcdefghjkmnpqrstuvwxyz'
  const digits = '23456789'
  const all = upper + lower + digits + PASSWORD_SPECIAL
  let password = ''
  password += upper[randomIndex(upper.length)]
  password += lower[randomIndex(lower.length)]
  password += digits[randomIndex(digits.length)]
  password += PASSWORD_SPECIAL[randomIndex(PASSWORD_SPECIAL.length)]
  for (let i = 4; i < PASSWORD_LENGTH; i++) {
    password += all[randomIndex(all.length)]
  }
  return shuffle(password)
}

export function passwordChecks(password = '') {
  return [
    { key: 'length', label: `${PASSWORD_LENGTH}+ characters`, ok: password.length >= PASSWORD_LENGTH },
    { key: 'upper', label: 'Uppercase letter', ok: /[A-Z]/.test(password) },
    { key: 'lower', label: 'Lowercase letter', ok: /[a-z]/.test(password) },
    { key: 'number', label: 'Number', ok: /[0-9]/.test(password) },
    { key: 'special', label: 'Special character', ok: [...PASSWORD_SPECIAL].some(ch => password.includes(ch)) },
  ]
}

export function passwordIssues(password = '') {
  return passwordChecks(password)
    .filter(check => !check.ok)
    .map(check => check.label.toLowerCase())
}
