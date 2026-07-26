import type { Dispatch, SetStateAction } from 'react'
import type { Filters } from '../types'
import { CALORIE_MAX, CALORIE_STEP, presets } from '../urlState'

export function FilterBar({ filters, setFilters, visibleRestaurantCount, filteredMealCount }: { filters: Filters; setFilters: Dispatch<SetStateAction<Filters>>; visibleRestaurantCount: number; filteredMealCount: number }) {
  const updateNumber = (key: 'minCalories' | 'maxCalories' | 'minProtein', value: string) => setFilters((current) => ({ ...current, [key]: value }))
  const updateCaloriesRange = (key: 'minCalories' | 'maxCalories', value: string) => {
    const next = Number(value)
    setFilters((current) => {
      const other = Number(key === 'minCalories' ? current.maxCalories : current.minCalories)
      const clamped = key === 'minCalories' ? Math.min(next, other) : Math.max(next, other)
      return { ...current, [key]: String(clamped) }
    })
  }
  return <header className="filter-bar">
    <div className="brand">SF MEAL FINDER</div>
    <label>Search<input className="search-input" type="search" placeholder="salad, Chipotle" value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} /></label>
    <div className="range-field">
      <span className="field-label">Calories</span><output className="range-value">{filters.minCalories}–{filters.maxCalories} kcal</output>
      <div className="range-slider"><div className="range-track" /><div className="range-fill" style={{ left: `${Number(filters.minCalories) / CALORIE_MAX * 100}%`, right: `${100 - Number(filters.maxCalories) / CALORIE_MAX * 100}%` }} />
        <input aria-label="Minimum calories" className={`range-input range-min ${Number(filters.maxCalories) - Number(filters.minCalories) <= CALORIE_STEP && Number(filters.maxCalories) > CALORIE_MAX / 2 ? 'range-min-front' : ''}`} type="range" min="0" max={CALORIE_MAX} step={CALORIE_STEP} value={filters.minCalories} onChange={(event) => updateCaloriesRange('minCalories', event.target.value)} />
        <input aria-label="Maximum calories" className="range-input range-max" type="range" min="0" max={CALORIE_MAX} step={CALORIE_STEP} value={filters.maxCalories} onChange={(event) => updateCaloriesRange('maxCalories', event.target.value)} />
      </div>
    </div>
    <label>Protein min<input type="number" min="0" value={filters.minProtein} onChange={(event) => updateNumber('minProtein', event.target.value)} /></label>
    <label className="check-label"><span>Include estimates</span><input type="checkbox" checked={filters.unofficial} onChange={(event) => setFilters((current) => ({ ...current, unofficial: event.target.checked }))} /></label>
    <div className="readout"><span className="field-label">Results</span><div aria-live="polite"><strong>{visibleRestaurantCount}</strong> restaurants <span>·</span> <strong>{filteredMealCount}</strong> results</div></div>
    <div className="presets" aria-label="Filter presets">{presets.map((preset) => <button key={preset.label} type="button" onClick={() => setFilters((current) => ({ ...current, minCalories: preset.minCalories, maxCalories: preset.maxCalories, minProtein: preset.minProtein }))}>{preset.label}</button>)}</div>
  </header>
}
