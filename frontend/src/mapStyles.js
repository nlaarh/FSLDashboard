// Map tile styles — shared across all map components
// Preference saved in localStorage, changeable from Admin page

// Preview tile: Buffalo area at zoom 9, tile x=150, y=187
function previewUrl(baseUrl) {
  return baseUrl
    .replace('{s}', 'a')
    .replace('{z}', '9')
    .replace('{x}', '150')
    .replace('{y}', '187')
    .replace('{r}', '')
}

export const MAP_STYLES = {
  apple_dark: {
    name: 'Apple Dark',
    description: 'Clean dark, muted tones',
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    filter: 'invert(1) hue-rotate(180deg) brightness(0.92) contrast(1.05) saturate(0.3)',
    dark: true,
  },
  dark_matter: {
    name: 'Dark Matter',
    description: 'Classic dark, bright labels',
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    filter: '',
    dark: true,
  },
  voyager_dark: {
    name: 'Voyager Dark',
    description: 'Google dark mode style',
    url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
    filter: 'invert(1) hue-rotate(180deg) brightness(0.85) contrast(1.1) saturate(0.4)',
    dark: true,
  },
  voyager: {
    name: 'Voyager',
    description: 'Colorful, Google-like',
    url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
    filter: '',
    dark: false,
  },
  apple_light: {
    name: 'Apple Light',
    description: 'Clean light, minimal',
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    filter: 'saturate(0.4) brightness(1.02)',
    dark: false,
  },
  positron: {
    name: 'Positron',
    description: 'Light grey, minimal',
    url: 'https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png',
    filter: '',
    dark: false,
  },
  satellite: {
    name: 'Satellite',
    description: 'Aerial imagery (ESRI)',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    filter: '',
    dark: true,
    noSubdomains: true,
  },
  topo: {
    name: 'Topo',
    description: 'Topographic terrain',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    filter: '',
    dark: false,
  },
}

// Generate preview URLs
Object.keys(MAP_STYLES).forEach(key => {
  MAP_STYLES[key].preview = previewUrl(MAP_STYLES[key].url)
})

const STORAGE_KEY = 'fslapp_map_style'
const DEFAULT_STYLE = 'apple_dark'

export function getMapStyle() {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_STYLE
  } catch {
    return DEFAULT_STYLE
  }
}

export function setMapStyle(key) {
  try {
    localStorage.setItem(STORAGE_KEY, key)
  } catch { /* ignore */ }
}

export function getMapConfig() {
  const key = getMapStyle()
  return MAP_STYLES[key] || MAP_STYLES[DEFAULT_STYLE]
}
