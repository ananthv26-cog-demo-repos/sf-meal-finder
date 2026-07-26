import { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './tokens.css'
import './styles.css'

const rootStyle = getComputedStyle(document.documentElement)
const accentColor = rootStyle.getPropertyValue('--accent').trim() || '#2563eb'

type Location = { address: string; lat: number; lng: number; neighborhood?: string | null }
type Restaurant = { id: string; name: string; website: string; locations: Location[] }
type Meal = {
  id: string
  restaurant_id: string
  name: string
  description?: string | null
  category: string
  calories: number
  protein_g: number
  carbs_g: number
  fat_g: number
  fiber_g?: number | null
  sodium_mg?: number | null
  serving_note?: string | null
  is_estimate: boolean
  source_type: string
  source_url: string
}
type SortKey = 'name' | 'calories' | 'protein_g' | 'protein_pct' | 'carbs_g' | 'fat_g'
type SortDirection = 'asc' | 'desc'

const defaultFilters = { minCalories: '0', maxCalories: '2000', minProtein: '0', unofficial: false, search: '' }
const presets = [
  { label: 'Cutting 400–700 · 30g+', minCalories: '400', maxCalories: '700', minProtein: '30' },
  { label: 'Standard 700–900 · 40g+', minCalories: '700', maxCalories: '900', minProtein: '40' },
  { label: 'Bulking 900–1300 · 50g+', minCalories: '900', maxCalories: '1300', minProtein: '50' },
]
const sortKeys: SortKey[] = ['name', 'calories', 'protein_g', 'protein_pct', 'carbs_g', 'fat_g']

function readUrlState() {
  const params = new URLSearchParams(window.location.search)
  const readNumber = (name: string, fallback: string, maximum?: number) => {
    const raw = params.get(name)
    const parsed = raw === null ? Number.NaN : Number(raw)
    if (!Number.isFinite(parsed)) return fallback
    const bounded = Math.max(0, maximum === undefined ? parsed : Math.min(maximum, parsed))
    return String(bounded)
  }
  const validSort = params.get('sort')
  const sortKey = validSort && sortKeys.includes(validSort as SortKey) ? validSort as SortKey : 'protein_g'
  const direction = params.get('dir') === 'asc' ? 'asc' : 'desc'
  const filters = {
    minCalories: readNumber('min', defaultFilters.minCalories, 2000),
    maxCalories: readNumber('max', defaultFilters.maxCalories, 2000),
    minProtein: readNumber('protein', defaultFilters.minProtein),
    unofficial: params.get('est') === '1',
    search: params.get('q') ?? defaultFilters.search,
  }
  if (Number(filters.minCalories) > Number(filters.maxCalories)) {
    ;[filters.minCalories, filters.maxCalories] = [filters.maxCalories, filters.minCalories]
  }
  return { filters, sortKey, sortDirection: direction as SortDirection }
}

function replaceUrlState(filters: typeof defaultFilters, sortKey: SortKey, sortDirection: SortDirection) {
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

function FocusRestaurant({ restaurantId, restaurants }: { restaurantId: string | null; restaurants: Restaurant[] }) {
  const map = useMap()
  const restaurant = restaurants.find((item) => item.id === restaurantId)
  useEffect(() => {
    if (restaurant && restaurant.locations.length > 0) {
      const bounds: LatLngBoundsExpression = restaurant.locations.map((location) => [location.lat, location.lng])
      map.fitBounds(bounds, { padding: [32, 32], maxZoom: 14, animate: true })
    }
  }, [map, restaurant])
  return null
}

function formatNumber(value: number, isEstimate: boolean, decimals: number) {
  const factor = 10 ** decimals
  const rounded = Math.round((value + Number.EPSILON) * factor) / factor
  const fixed = rounded.toFixed(decimals)
  const display = fixed.includes('.') ? fixed.replace(/0+$/, '').replace(/\.$/, '') : fixed
  return `${isEstimate ? '~' : ''}${display}`
}

function proteinPercent(meal: Meal) {
  return meal.calories > 0 ? (meal.protein_g * 4 / meal.calories) * 100 : 0
}

function sortValue(meal: Meal, sortKey: SortKey) {
  if (sortKey === 'name') return meal.name
  if (sortKey === 'protein_pct') return proteinPercent(meal)
  return meal[sortKey]
}

function parseFilterValue(value: string, emptyValue: number, invalidValue: number) {
  if (value.trim() === '') return emptyValue
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : invalidValue
}

function isHttpUrl(value: string) {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

function SortHeader({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
}: {
  label: string
  sortKey: SortKey
  activeKey: SortKey
  direction: SortDirection
  onSort: (key: SortKey) => void
}) {
  const active = sortKey === activeKey
  return (
    <button
      aria-label={active
        ? `Sort by ${label.toLowerCase()}, currently sorted ${direction === 'asc' ? 'ascending' : 'descending'}`
        : `Sort by ${label.toLowerCase()}`}
      className={`sort-button ${active ? 'active' : ''}`}
      type="button"
      onClick={() => onSort(sortKey)}
    >
      {label}{active && <span aria-hidden="true">{direction === 'asc' ? '↑' : '↓'}</span>}
    </button>
  )
}

function App() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([])
  const [meals, setMeals] = useState<Meal[]>([])
  const [initialState] = useState(readUrlState)
  const [filters, setFilters] = useState(initialState.filters)
  const [selectedRestaurant, setSelectedRestaurant] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>(initialState.sortKey)
  const [sortDirection, setSortDirection] = useState<SortDirection>(initialState.sortDirection)

  useEffect(() => {
    Promise.all([
      fetch('/data/restaurants.json').then((response) => response.json() as Promise<Restaurant[]>),
      fetch('/data/meals.json').then((response) => response.json() as Promise<Meal[]>),
    ]).then(([restaurantList, mealList]) => {
      setRestaurants(restaurantList)
      setMeals(mealList)
    })
  }, [])

  const restaurantById = useMemo(() => new Map(restaurants.map((item) => [item.id, item])), [restaurants])
  const filteredMeals = useMemo(() => {
    const query = filters.search.trim().toLowerCase()
    const minCalories = parseFilterValue(filters.minCalories, 0, 0)
    const maxCalories = parseFilterValue(filters.maxCalories, Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY)
    const minProtein = parseFilterValue(filters.minProtein, 0, 0)
    return [...meals]
      .filter((meal) => meal.category === 'meal')
      .filter((meal) => meal.calories >= minCalories && meal.calories <= maxCalories)
      .filter((meal) => meal.protein_g >= minProtein)
      .filter((meal) => filters.unofficial || !meal.is_estimate)
      .filter((meal) => {
        if (!query) return true
        const restaurantName = restaurantById.get(meal.restaurant_id)?.name ?? meal.restaurant_id
        return `${meal.name} ${restaurantName}`.toLowerCase().includes(query)
      })
      .sort((a, b) => {
        const left = sortValue(a, sortKey)
        const right = sortValue(b, sortKey)
        const comparison = typeof left === 'string' && typeof right === 'string'
          ? left.localeCompare(right)
          : Number(left) - Number(right)
        return sortDirection === 'asc' ? comparison : -comparison
      })
  }, [filters, meals, restaurantById, sortDirection, sortKey])
  const visibleRestaurantIds = new Set(filteredMeals.map((meal) => meal.restaurant_id))
  const totalMeals = meals.filter((meal) => meal.category === 'meal').length

  const updateNumber = (key: 'minCalories' | 'maxCalories' | 'minProtein', value: string) => {
    setFilters((current) => ({ ...current, [key]: value }))
  }
  const updateCaloriesRange = (key: 'minCalories' | 'maxCalories', value: string) => {
    const next = Number(value)
    const other = Number(key === 'minCalories' ? filters.maxCalories : filters.minCalories)
    const clamped = key === 'minCalories' ? Math.min(next, other) : Math.max(next, other)
    const nextFilters = { ...filters, [key]: String(clamped) }
    setFilters(nextFilters)
    replaceUrlState(nextFilters, sortKey, sortDirection)
  }
  const updateSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')
      return
    }
    setSortKey(key)
    setSortDirection('desc')
  }
  useEffect(() => {
    replaceUrlState(filters, sortKey, sortDirection)
  }, [filters, sortDirection, sortKey])

  return (
    <main className="app-shell">
      <header className="filter-bar">
        <div className="brand">SF MEAL FINDER</div>
        <label>Search<input aria-label="Search meals or restaurants" className="search-input" type="search" placeholder="salad, Chipotle" value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} /></label>
        <div className="range-field">
          <span className="field-label">Calories</span>
          <output className="range-value">{filters.minCalories}–{filters.maxCalories} kcal</output>
          <div className="range-slider">
            <div className="range-track" />
            <div className="range-fill" style={{ left: `${Number(filters.minCalories) / 20}%`, right: `${100 - Number(filters.maxCalories) / 20}%` }} />
            <input aria-label="Minimum calories" className={`range-input range-min ${Number(filters.maxCalories) - Number(filters.minCalories) <= 10 && Number(filters.maxCalories) > 1000 ? 'range-min-front' : ''}`} type="range" min="0" max="2000" step="10" value={filters.minCalories} onChange={(event) => updateCaloriesRange('minCalories', event.target.value)} />
            <input aria-label="Maximum calories" className="range-input range-max" type="range" min="0" max="2000" step="10" value={filters.maxCalories} onChange={(event) => updateCaloriesRange('maxCalories', event.target.value)} />
          </div>
        </div>
        <label>Protein min<input aria-label="Minimum protein in grams" type="number" min="0" value={filters.minProtein} onChange={(event) => updateNumber('minProtein', event.target.value)} /></label>
        <label className="check-label"><span>Include estimates</span><input aria-label="Include unofficial estimates" type="checkbox" checked={filters.unofficial} onChange={(event) => setFilters((current) => ({ ...current, unofficial: event.target.checked }))} /></label>
        <div className="readout"><span className="field-label">Results</span><div><strong>{visibleRestaurantIds.size}</strong> restaurants <span>·</span> <strong>{filteredMeals.length}</strong> results</div></div>
        <div className="presets" aria-label="Filter presets">
          {presets.map((preset) => <button key={preset.label} type="button" onClick={() => setFilters((current) => ({ ...current, minCalories: preset.minCalories, maxCalories: preset.maxCalories, minProtein: preset.minProtein }))}>{preset.label}</button>)}
        </div>
      </header>
      <section className="workspace">
        <div className="results-panel">
          <div className="column-head">
            <span>MEAL</span>
            <SortHeader activeKey={sortKey} direction={sortDirection} label="Cal" sortKey="calories" onSort={updateSort} />
            <SortHeader activeKey={sortKey} direction={sortDirection} label="Protein" sortKey="protein_g" onSort={updateSort} />
            <SortHeader activeKey={sortKey} direction={sortDirection} label="P%" sortKey="protein_pct" onSort={updateSort} />
            <SortHeader activeKey={sortKey} direction={sortDirection} label="Carbs" sortKey="carbs_g" onSort={updateSort} />
            <SortHeader activeKey={sortKey} direction={sortDirection} label="Fat" sortKey="fat_g" onSort={updateSort} />
          </div>
          <div className="result-list">
            {filteredMeals.map((meal) => {
              const restaurant = restaurantById.get(meal.restaurant_id)
              const sourceChip = isHttpUrl(meal.source_url)
                ? <a className="source-chip" href={meal.source_url} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>{meal.source_type}</a>
                : <span className="source-chip">{meal.source_type}</span>
              return (
                <div
                  aria-label={`Focus ${restaurant?.name ?? meal.restaurant_id} on map`}
                  className={`meal-row ${selectedRestaurant === meal.restaurant_id ? 'selected' : ''}`}
                  key={`${meal.restaurant_id}-${meal.id}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedRestaurant(meal.restaurant_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setSelectedRestaurant(meal.restaurant_id)
                    }
                  }}
                >
                  <div className="meal-info"><strong>{meal.name}</strong><span>{restaurant?.name ?? meal.restaurant_id}{meal.serving_note ? ` · ${meal.serving_note}` : ''}</span><div className="badges">{meal.is_estimate && <em>~est</em>}{sourceChip}</div></div>
                  <span className="number">{formatNumber(meal.calories, meal.is_estimate, 0)}</span><span className="number protein">{formatNumber(meal.protein_g, meal.is_estimate, 1)}g</span><span className="number">{formatNumber(proteinPercent(meal), meal.is_estimate, 0)}%</span><span className="number">{formatNumber(meal.carbs_g, meal.is_estimate, 1)}g</span><span className="number">{formatNumber(meal.fat_g, meal.is_estimate, 1)}g</span>
                </div>
              )
            })}
            {filteredMeals.length === 0 && <p className="empty">No meals match these filters.</p>}
          </div>
          <footer className="results-footer">{restaurants.length} restaurants · {totalMeals} meals · data validated 9·fat+4·carbs+4·protein</footer>
        </div>
        <div className="map-panel">
          <MapContainer center={[37.7749, -122.4194]} zoom={13} scrollWheelZoom className="map">
            <TileLayer attribution="&copy; OpenStreetMap contributors &copy; CARTO" url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" />
            <FocusRestaurant restaurantId={selectedRestaurant} restaurants={restaurants} />
            {restaurants.flatMap((restaurant) => restaurant.locations.map((location, index) => {
              const selected = restaurant.id === selectedRestaurant
              const matched = visibleRestaurantIds.has(restaurant.id)
              return (
                <CircleMarker key={`${restaurant.id}-${index}`} center={[location.lat, location.lng]} radius={selected ? 6 : 3.5} pathOptions={{ color: accentColor, fillColor: accentColor, fillOpacity: selected ? 0.85 : matched ? 0.5 : 0.12, opacity: selected ? 1 : matched ? 0.7 : 0.28, weight: selected ? 2 : 1 }}>
                  <Popup><strong>{restaurant.name}</strong><br />{location.address}</Popup>
                </CircleMarker>
              )
            }))}
          </MapContainer>
        </div>
      </section>
    </main>
  )
}

export default App
