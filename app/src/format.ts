import type { Meal, SortKey } from './types'

export function formatNumber(value: number, isEstimate: boolean, decimals: number) {
  const factor = 10 ** decimals
  const rounded = Math.round((value + Number.EPSILON) * factor) / factor
  const fixed = rounded.toFixed(decimals)
  const display = fixed.includes('.') ? fixed.replace(/0+$/, '').replace(/\.$/, '') : fixed
  return `${isEstimate ? '~' : ''}${display}`
}
export function proteinPercent(meal: Meal) { return meal.calories > 0 ? (meal.protein_g * 4 / meal.calories) * 100 : 0 }
export function sortValue(meal: Meal, sortKey: SortKey): number | string {
  if (sortKey === 'name') return meal.name
  if (sortKey === 'protein_pct') return proteinPercent(meal)
  return meal[sortKey]
}
export function parseFilterValue(value: string, emptyValue: number, invalidValue: number) {
  if (value.trim() === '') return emptyValue
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : invalidValue
}
export function isHttpUrl(value: string) {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch { return false }
}
