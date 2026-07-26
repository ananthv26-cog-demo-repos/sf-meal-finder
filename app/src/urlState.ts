import type { Filters, SortDirection, SortKey } from './types'

export const CALORIE_MAX = 2000
export const CALORIE_STEP = 10
export const defaultFilters: Filters = { minCalories: '0', maxCalories: String(CALORIE_MAX), minProtein: '0', unofficial: false, search: '' }
export const presets = [
  { label: 'Cutting 400–700 · 30g+', minCalories: '400', maxCalories: '700', minProtein: '30' },
  { label: 'Standard 700–900 · 40g+', minCalories: '700', maxCalories: '900', minProtein: '40' },
  { label: 'Bulking 900–1300 · 50g+', minCalories: '900', maxCalories: '1300', minProtein: '50' },
]
export const sortKeys: SortKey[] = ['name', 'calories', 'protein_g', 'protein_pct', 'carbs_g', 'fat_g']
export function isSortKey(value: string | null): value is SortKey { return value !== null && sortKeys.some((key) => key === value) }
export function readUrlState() {
  const params = new URLSearchParams(window.location.search)
  const readNumber = (name: string, fallback: string, maximum?: number) => {
    const raw = params.get(name)
    const parsed = raw === null ? Number.NaN : Number(raw)
    if (!Number.isFinite(parsed)) return fallback
    return String(Math.max(0, maximum === undefined ? parsed : Math.min(maximum, parsed)))
  }
  const sortParam = params.get('sort')
  const sortKey: SortKey = isSortKey(sortParam) ? sortParam : 'protein_g'
  const sortDirection: SortDirection = params.get('dir') === 'asc' ? 'asc' : 'desc'
  const filters: Filters = {
    minCalories: readNumber('min', defaultFilters.minCalories, CALORIE_MAX),
    maxCalories: readNumber('max', defaultFilters.maxCalories, CALORIE_MAX),
    minProtein: readNumber('protein', defaultFilters.minProtein),
    unofficial: params.get('est') === '1',
    search: params.get('q') ?? defaultFilters.search,
  }
  if (Number(filters.minCalories) > Number(filters.maxCalories)) [filters.minCalories, filters.maxCalories] = [filters.maxCalories, filters.minCalories]
  return { filters, sortKey, sortDirection }
}
export function replaceUrlState(filters: Filters, sortKey: SortKey, sortDirection: SortDirection) {
  const params = new URLSearchParams()
  if (filters.minCalories !== defaultFilters.minCalories) params.set('min', filters.minCalories)
  if (filters.maxCalories !== defaultFilters.maxCalories) params.set('max', filters.maxCalories)
  if (filters.minProtein !== defaultFilters.minProtein) params.set('protein', filters.minProtein)
  if (filters.search) params.set('q', filters.search)
  if (filters.unofficial) params.set('est', '1')
  if (sortKey !== 'protein_g') params.set('sort', sortKey)
  if (sortDirection !== 'desc') params.set('dir', sortDirection)
  const query = params.toString()
  window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`)
}
