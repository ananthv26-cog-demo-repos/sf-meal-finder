import { useEffect, useRef } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { Filters } from '../types'
import { CALORIE_MAX, CALORIE_STEP } from '../urlState'

export function FilterBar({ filters, setFilters, visibleRestaurantCount, filteredMealCount }: { filters: Filters; setFilters: Dispatch<SetStateAction<Filters>>; visibleRestaurantCount: number; filteredMealCount: number }) {
  const searchRef = useRef<HTMLInputElement>(null)
  const shortcutLabel = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K'
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  const updateCaloriesRange = (key: 'minCalories' | 'maxCalories', value: string) => {
    const next = Number(value)
    setFilters((current) => {
      const other = Number(key === 'minCalories' ? current.maxCalories : current.minCalories)
      const clamped = key === 'minCalories' ? Math.min(next, other) : Math.max(next, other)
      return { ...current, [key]: String(clamped) }
    })
  }
  const updateProtein = (value: string) => setFilters((current) => ({ ...current, minProtein: value }))
  const stepProtein = (amount: number) => {
    const current = Number(filters.minProtein)
    updateProtein(String(Math.max(0, (Number.isFinite(current) ? current : 0) + amount)))
  }
  return <header className="filter-bar">
    <div className="filter-top">
      <label className="search-control">
        <span className="field-label">Search</span>
        <div className="search-wrap">
          <input ref={searchRef} className="search-input" type="search" placeholder="salad, Chipotle" value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} />
          <span className="search-hint">{shortcutLabel}</span>
        </div>
      </label>
      <div className="result-summary" aria-live="polite">
        <strong>{filteredMealCount}</strong>
        <span>RESULTS · {visibleRestaurantCount} RESTAURANTS</span>
      </div>
    </div>
    <div className="filter-bottom">
      <div className="range-field">
        <div className="range-heading"><span className="field-label">Calories</span><output className="range-value">{filters.minCalories}–{filters.maxCalories} kcal</output></div>
        <div className="range-slider"><div className="range-track" /><div className="range-fill" style={{ left: `calc(${Number(filters.minCalories) / CALORIE_MAX} * (100% - var(--slider-thumb)) + var(--slider-thumb) / 2)`, right: `calc(${1 - Number(filters.maxCalories) / CALORIE_MAX} * (100% - var(--slider-thumb)) + var(--slider-thumb) / 2)` }} />
          <input aria-label="Minimum calories" className={`range-input range-min ${Number(filters.maxCalories) - Number(filters.minCalories) <= CALORIE_STEP && Number(filters.maxCalories) > CALORIE_MAX / 2 ? 'range-min-front' : ''}`} type="range" min="0" max={CALORIE_MAX} step={CALORIE_STEP} value={filters.minCalories} onChange={(event) => updateCaloriesRange('minCalories', event.target.value)} />
          <input aria-label="Maximum calories" className="range-input range-max" type="range" min="0" max={CALORIE_MAX} step={CALORIE_STEP} value={filters.maxCalories} onChange={(event) => updateCaloriesRange('maxCalories', event.target.value)} />
        </div>
      </div>
      <div className="protein-field">
        <span className="field-label">Protein min</span>
        <span className="protein-stepper">
          <button type="button" aria-label="Decrease minimum protein by 5 grams" onClick={() => stepProtein(-5)}>−</button>
          <span className="protein-value"><input aria-label="Minimum protein in grams" type="number" min="0" step="5" value={filters.minProtein} onChange={(event) => updateProtein(event.target.value)} /><span>g</span></span>
          <button type="button" aria-label="Increase minimum protein by 5 grams" onClick={() => stepProtein(5)}>+</button>
        </span>
      </div>
      <label className="check-label"><span className="field-label">Include estimates</span><input aria-label="Include unofficial estimates" type="checkbox" checked={filters.unofficial} onChange={(event) => setFilters((current) => ({ ...current, unofficial: event.target.checked }))} /></label>
    </div>
  </header>
}
