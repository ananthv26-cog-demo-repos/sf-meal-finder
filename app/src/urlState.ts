import type { Filters, SortDirection, SortKey } from './types'

export const CALORIE_MAX = 2000
export const CALORIE_STEP = 10
export const PROTEIN_MAX = 500
export const defaultFilters: Filters = { minCalories: '0', maxCalories: String(CALORIE_MAX), minProtein: '0', unofficial: false, search: '' }
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
  const sortDirection: SortDirection = (sortParam === null || isSortKey(sortParam)) && params.get('dir') === 'asc' ? 'asc' : 'desc'
  const filters: Filters = {
    minCalories: readNumber('min', defaultFilters.minCalories, CALORIE_MAX),
    maxCalories: readNumber('max', defaultFilters.maxCalories, CALORIE_MAX),
    minProtein: readNumber('protein', defaultFilters.minProtein, PROTEIN_MAX),
    unofficial: params.get('est') === '1',
    search: params.get('q') ?? defaultFilters.search,
  }
  if (Number(filters.minCalories) > Number(filters.maxCalories)) [filters.minCalories, filters.maxCalories] = [filters.maxCalories, filters.minCalories]
  return { filters, sortKey, sortDirection }
}
export function replaceUrlState(filters: Filters, sortKey: SortKey, sortDirection: SortDirection) {
  const params = new URLSearchParams(window.location.search)
  const setOrDelete = (name: string, value: string, active: boolean) => active ? params.set(name, value) : params.delete(name)
  setOrDelete('min', filters.minCalories, filters.minCalories !== defaultFilters.minCalories)
  setOrDelete('max', filters.maxCalories, filters.maxCalories !== defaultFilters.maxCalories)
  setOrDelete('protein', filters.minProtein, filters.minProtein !== defaultFilters.minProtein)
  setOrDelete('q', filters.search, filters.search !== '')
  setOrDelete('est', '1', filters.unofficial)
  setOrDelete('sort', sortKey, sortKey !== 'protein_g')
  setOrDelete('dir', sortDirection, sortDirection !== 'desc')
  const query = params.toString()
  window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`)
}
