import { useEffect, useMemo, useState } from 'react'
import { MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet'
import type { LatLngExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './tokens.css'
import './styles.css'

type Location = { address: string; lat: number; lng: number; neighborhood?: string | null }
type Restaurant = { id: string; name: string; website: string; locations: Location[] }
type Meal = {
  id: string; restaurant_id: string; name: string; description?: string | null
  category: string; calories: number; protein_g: number; carbs_g: number; fat_g: number
  fiber_g?: number | null; sodium_mg?: number | null; serving_note?: string | null
  is_estimate: boolean; source_type: string; source_url: string
}

const defaultFilters = { minCalories: 0, maxCalories: 2000, minProtein: 0, unofficial: false }

function FocusRestaurant({ restaurantId, restaurants }: { restaurantId: string | null; restaurants: Restaurant[] }) {
  const map = useMap()
  const restaurant = restaurants.find((item) => item.id === restaurantId)
  useEffect(() => {
    if (restaurant) {
    const first = restaurant.locations[0]
    if (first) map.flyTo([first.lat, first.lng], 14, { duration: 0.5 })
    }
  }, [map, restaurant])
  return null
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
  const filteredMeals = useMemo(() => [...meals]
    .filter((meal) => meal.category === 'meal')
    .filter((meal) => meal.calories >= filters.minCalories && meal.calories <= filters.maxCalories)
    .filter((meal) => meal.protein_g >= filters.minProtein)
    .filter((meal) => filters.unofficial || !meal.is_estimate)
    .sort((a, b) => b.protein_g - a.protein_g), [filters, meals])
  const visibleRestaurantIds = new Set(filteredMeals.map((meal) => meal.restaurant_id))

  const updateNumber = (key: 'minCalories' | 'maxCalories' | 'minProtein', value: string) => {
    const parsed = Number(value)
    setFilters((current) => ({ ...current, [key]: Number.isFinite(parsed) ? parsed : 0 }))
  }

  return (
    <main className="app-shell">
      <header className="filter-bar">
        <div className="brand">SF MEAL FINDER</div>
        <label>Calories min<input type="number" min="0" value={filters.minCalories} onChange={(event) => updateNumber('minCalories', event.target.value)} /></label>
        <label>Calories max<input type="number" min="0" value={filters.maxCalories} onChange={(event) => updateNumber('maxCalories', event.target.value)} /></label>
        <label>Protein min (g)<input type="number" min="0" value={filters.minProtein} onChange={(event) => updateNumber('minProtein', event.target.value)} /></label>
        <label className="check-label"><input type="checkbox" checked={filters.unofficial} onChange={(event) => setFilters((current) => ({ ...current, unofficial: event.target.checked }))} /> include unofficial estimates</label>
        <div className="readout"><strong>{visibleRestaurantIds.size}</strong> restaurants <span>·</span> <strong>{filteredMeals.length}</strong> results</div>
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
                  <span className="number">{meal.calories}</span><span className="number protein">{meal.protein_g}g</span><span className="number">{meal.carbs_g}g</span><span className="number">{meal.fat_g}g</span>
                </button>
              )
            })}
            {filteredMeals.length === 0 && <p className="empty">No meals match these filters.</p>}
          </div>
        </div>
        <div className="map-panel">
          <MapContainer center={[37.7749, -122.4194]} zoom={13} scrollWheelZoom className="map">
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <FocusRestaurant restaurantId={selectedRestaurant} restaurants={restaurants} />
            {restaurants.flatMap((restaurant) => restaurant.locations.map((location, index) => (
              <Marker key={`${restaurant.id}-${index}`} position={[location.lat, location.lng] as LatLngExpression} opacity={visibleRestaurantIds.has(restaurant.id) ? 1 : 0.45}>
                <Popup><strong>{restaurant.name}</strong><br />{location.address}</Popup>
              </Marker>
            )))}
          </MapContainer>
        </div>
      </section>
    </main>
  )
}

export default App
