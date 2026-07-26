import { useEffect, useMemo, useState } from 'react'
import 'leaflet/dist/leaflet.css'
import './tokens.css'
import './styles.css'
import { FilterBar } from './components/FilterBar'
import { MapPanel } from './components/MapPanel'
import { ResultsPanel } from './components/ResultsPanel'
import { parseFilterValue, sortValue } from './format'
import { isEligibleResult } from './types'
import type { Meal, Restaurant, SortDirection, SortKey } from './types'
import { readUrlState, replaceUrlState } from './urlState'

function App() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([])
  const [meals, setMeals] = useState<Meal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
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
    }).catch(() => setError('Unable to load meal data.')).finally(() => setLoading(false))
  }, [])

  const restaurantById = useMemo(() => new Map(restaurants.map((item) => [item.id, item])), [restaurants])
  const filteredMeals = useMemo(() => {
    const query = filters.search.trim().toLowerCase()
    const minCalories = parseFilterValue(filters.minCalories, 0, 0)
    const maxCalories = parseFilterValue(filters.maxCalories, Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY)
    const minProtein = parseFilterValue(filters.minProtein, 0, 0)
    return meals.filter((meal) => {
      if (!isEligibleResult(meal) || meal.calories < minCalories || meal.calories > maxCalories || meal.protein_g < minProtein || (!filters.unofficial && meal.is_estimate)) return false
      if (!query) return true
      const restaurantName = restaurantById.get(meal.restaurant_id)?.name ?? meal.restaurant_id
      return `${meal.name} ${restaurantName}`.toLowerCase().includes(query)
    }).sort((a, b) => {
      const left = sortValue(a, sortKey)
      const right = sortValue(b, sortKey)
      const comparison = typeof left === 'string' && typeof right === 'string' ? left.localeCompare(right) : Number(left) - Number(right)
      return sortDirection === 'asc' ? comparison : -comparison
    })
  }, [filters, meals, restaurantById, sortDirection, sortKey])
  const visibleRestaurantIds = useMemo(() => new Set(filteredMeals.map((meal) => meal.restaurant_id)), [filteredMeals])
  const totalEligibleMeals = useMemo(() => meals.filter(isEligibleResult).length, [meals])
  const estimateRestaurantIds = useMemo(() => {
    const mealEntries = meals.filter(isEligibleResult)
    const estimated = new Set(mealEntries.filter((meal) => meal.is_estimate).map((meal) => meal.restaurant_id))
    const published = new Set(mealEntries.filter((meal) => !meal.is_estimate).map((meal) => meal.restaurant_id))
    return new Set([...estimated].filter((restaurantId) => !published.has(restaurantId)))
  }, [meals])

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

  return <main className="app-shell">
    <FilterBar filters={filters} setFilters={setFilters} visibleRestaurantCount={visibleRestaurantIds.size} filteredMealCount={filteredMeals.length} loading={loading} />
    <section className="workspace">
      <ResultsPanel filteredMeals={filteredMeals} restaurantById={restaurantById} restaurantsCount={restaurants.length} totalEligibleMeals={totalEligibleMeals} selectedRestaurant={selectedRestaurant} onSelectRestaurant={setSelectedRestaurant} sortKey={sortKey} sortDirection={sortDirection} onSort={updateSort} loading={loading} error={error} />
      <MapPanel restaurants={restaurants} restaurantById={restaurantById} selectedRestaurant={selectedRestaurant} visibleRestaurantIds={visibleRestaurantIds} estimateRestaurantIds={estimateRestaurantIds} />
    </section>
  </main>
}

export default App
