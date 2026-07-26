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
type SortKey = 'name' | 'calories' | 'protein_g' | 'carbs_g' | 'fat_g'
type SortDirection = 'asc' | 'desc'

const defaultFilters = { minCalories: '0', maxCalories: '2000', minProtein: '0', unofficial: false, search: '' }
const presets = [
  { label: 'Cutting 400–700 · 30g+', minCalories: '400', maxCalories: '700', minProtein: '30' },
  { label: 'Standard 700–900 · 40g+', minCalories: '700', maxCalories: '900', minProtein: '40' },
  { label: 'Bulking 900–1300 · 50g+', minCalories: '900', maxCalories: '1300', minProtein: '50' },
]

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

function formatNumber(value: number, isEstimate: boolean) {
  return `${isEstimate ? '~' : ''}${value}`
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
      aria-label={`Sort by ${label.toLowerCase()}`}
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
  const [filters, setFilters] = useState(defaultFilters)
  const [selectedRestaurant, setSelectedRestaurant] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('protein_g')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

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
        const left = sortKey === 'name'
          ? a.name
          : a[sortKey]
        const right = sortKey === 'name'
          ? b.name
          : b[sortKey]
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
  const updateSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')
      return
    }
    setSortKey(key)
    setSortDirection('desc')
  }

  return (
    <main className="app-shell">
      <header className="filter-bar">
        <div className="brand">SF MEAL FINDER</div>
        <label>Search<input aria-label="Search meals or restaurants" className="search-input" type="search" placeholder="salad, Chipotle" value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} /></label>
        <label>Calories min<input aria-label="Minimum calories" type="number" min="0" value={filters.minCalories} onChange={(event) => updateNumber('minCalories', event.target.value)} /></label>
        <label>Calories max<input aria-label="Maximum calories" type="number" min="0" value={filters.maxCalories} onChange={(event) => updateNumber('maxCalories', event.target.value)} /></label>
        <label>Protein min<input aria-label="Minimum protein in grams" type="number" min="0" value={filters.minProtein} onChange={(event) => updateNumber('minProtein', event.target.value)} /></label>
        <label className="check-label"><span>Include estimates</span><input aria-label="Include unofficial estimates" type="checkbox" checked={filters.unofficial} onChange={(event) => setFilters((current) => ({ ...current, unofficial: event.target.checked }))} /></label>
        <div className="readout"><strong>{visibleRestaurantIds.size}</strong> restaurants <span>·</span> <strong>{filteredMeals.length}</strong> results</div>
        <div className="presets" aria-label="Filter presets">
          {presets.map((preset) => <button key={preset.label} type="button" onClick={() => setFilters((current) => ({ ...current, minCalories: preset.minCalories, maxCalories: preset.maxCalories, minProtein: preset.minProtein }))}>{preset.label}</button>)}
        </div>
      </header>
      <section className="workspace">
        <div className="results-panel">
          <div className="column-head" role="row">
            <div role="columnheader">MEAL</div>
            <div aria-sort={sortKey === 'calories' ? sortDirection === 'asc' ? 'ascending' : 'descending' : 'none'} role="columnheader">
              <SortHeader activeKey={sortKey} direction={sortDirection} label="Cal" sortKey="calories" onSort={updateSort} />
            </div>
            <div aria-sort={sortKey === 'protein_g' ? sortDirection === 'asc' ? 'ascending' : 'descending' : 'none'} role="columnheader">
              <SortHeader activeKey={sortKey} direction={sortDirection} label="Protein" sortKey="protein_g" onSort={updateSort} />
            </div>
            <div aria-sort={sortKey === 'carbs_g' ? sortDirection === 'asc' ? 'ascending' : 'descending' : 'none'} role="columnheader">
              <SortHeader activeKey={sortKey} direction={sortDirection} label="Carbs" sortKey="carbs_g" onSort={updateSort} />
            </div>
            <div aria-sort={sortKey === 'fat_g' ? sortDirection === 'asc' ? 'ascending' : 'descending' : 'none'} role="columnheader">
              <SortHeader activeKey={sortKey} direction={sortDirection} label="Fat" sortKey="fat_g" onSort={updateSort} />
            </div>
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
                  <span className="number">{formatNumber(meal.calories, meal.is_estimate)}</span><span className="number protein">{formatNumber(meal.protein_g, meal.is_estimate)}g</span><span className="number">{formatNumber(meal.carbs_g, meal.is_estimate)}g</span><span className="number">{formatNumber(meal.fat_g, meal.is_estimate)}g</span>
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
