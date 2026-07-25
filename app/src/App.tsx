import { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './tokens.css'
import './styles.css'

const rootStyle = getComputedStyle(document.documentElement)
const accentColor = rootStyle.getPropertyValue('--accent').trim() || '#2563eb'
const proteinColor = rootStyle.getPropertyValue('--protein').trim() || '#047857'

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

function App() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([])
  const [meals, setMeals] = useState<Meal[]>([])
  const [filters, setFilters] = useState(defaultFilters)
  const [selectedRestaurant, setSelectedRestaurant] = useState<string | null>(null)

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
      .sort((a, b) => b.protein_g - a.protein_g)
  }, [filters, meals, restaurantById])
  const visibleRestaurantIds = new Set(filteredMeals.map((meal) => meal.restaurant_id))
  const totalMeals = meals.filter((meal) => meal.category === 'meal').length

  const updateNumber = (key: 'minCalories' | 'maxCalories' | 'minProtein', value: string) => {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  return (
    <main className="app-shell">
      <header className="filter-bar">
        <div className="brand">SF MEAL FINDER</div>
        <label>Search meals or restaurants<input className="search-input" type="search" placeholder="e.g. salad, Chipotle" value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} /></label>
        <label>Calories min<input type="number" min="0" value={filters.minCalories} onChange={(event) => updateNumber('minCalories', event.target.value)} /></label>
        <label>Calories max<input type="number" min="0" value={filters.maxCalories} onChange={(event) => updateNumber('maxCalories', event.target.value)} /></label>
        <label>Protein min (g)<input type="number" min="0" value={filters.minProtein} onChange={(event) => updateNumber('minProtein', event.target.value)} /></label>
        <label className="check-label"><input type="checkbox" checked={filters.unofficial} onChange={(event) => setFilters((current) => ({ ...current, unofficial: event.target.checked }))} /> include unofficial estimates</label>
        <div className="readout"><strong>{visibleRestaurantIds.size}</strong> restaurants <span>·</span> <strong>{filteredMeals.length}</strong> results</div>
        <div className="presets" aria-label="Filter presets">
          {presets.map((preset) => <button key={preset.label} type="button" onClick={() => setFilters((current) => ({ ...current, minCalories: preset.minCalories, maxCalories: preset.maxCalories, minProtein: preset.minProtein }))}>{preset.label}</button>)}
        </div>
      </header>
      <section className="workspace">
        <div className="results-panel">
          <div className="column-head"><span>MEAL</span><span>CAL</span><span>PROTEIN</span><span>CARBS</span><span>FAT</span></div>
          <div className="result-list">
            {filteredMeals.map((meal) => {
              const restaurant = restaurantById.get(meal.restaurant_id)
              return (
                <button className={`meal-row ${selectedRestaurant === meal.restaurant_id ? 'selected' : ''}`} key={`${meal.restaurant_id}-${meal.id}`} onClick={() => setSelectedRestaurant(meal.restaurant_id)}>
                  <div className="meal-info"><strong>{meal.name}</strong><span>{restaurant?.name ?? meal.restaurant_id}{meal.serving_note ? ` · ${meal.serving_note}` : ''}</span><div className="badges">{meal.is_estimate && <em>estimate</em>}<small>{meal.source_type}</small></div></div>
                  <span className="number">{formatNumber(meal.calories, meal.is_estimate)}</span><span className="number protein">{formatNumber(meal.protein_g, meal.is_estimate)}g</span><span className="number">{formatNumber(meal.carbs_g, meal.is_estimate)}g</span><span className="number">{formatNumber(meal.fat_g, meal.is_estimate)}g</span>
                </button>
              )
            })}
            {filteredMeals.length === 0 && <p className="empty">No meals match these filters.</p>}
          </div>
          <footer className="results-footer">{restaurants.length} restaurants · {totalMeals} meals · data validated 9·fat+4·carbs+4·protein</footer>
        </div>
        <div className="map-panel">
          <MapContainer center={[37.7749, -122.4194]} zoom={13} scrollWheelZoom className="map">
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <FocusRestaurant restaurantId={selectedRestaurant} restaurants={restaurants} />
            {restaurants.flatMap((restaurant) => restaurant.locations.map((location, index) => {
              const selected = restaurant.id === selectedRestaurant
              const matched = visibleRestaurantIds.has(restaurant.id)
              return (
                <CircleMarker key={`${restaurant.id}-${index}`} center={[location.lat, location.lng]} radius={selected ? 9 : 7} pathOptions={{ color: selected ? proteinColor : accentColor, fillColor: selected ? proteinColor : accentColor, fillOpacity: matched ? 0.9 : 0.25, opacity: matched ? 1 : 0.35 }}>
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
