import { useEffect, useMemo } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression } from 'leaflet'
import type { Restaurant } from '../types'

function FocusRestaurant({ restaurantId, restaurantById }: { restaurantId: string | null; restaurantById: Map<string, Restaurant> }) {
  const map = useMap()
  const restaurant = useMemo(() => restaurantId ? restaurantById.get(restaurantId) : undefined, [restaurantById, restaurantId])
  useEffect(() => { if (restaurant && restaurant.locations.length > 0) { const bounds: LatLngBoundsExpression = restaurant.locations.map((location) => [location.lat, location.lng]); map.fitBounds(bounds, { padding: [32, 32], maxZoom: 14, animate: true }) } }, [map, restaurant])
  return null
}
export function MapPanel({ restaurants, restaurantById, selectedRestaurant, visibleRestaurantIds, estimateRestaurantIds }: { restaurants: Restaurant[]; restaurantById: Map<string, Restaurant>; selectedRestaurant: string | null; visibleRestaurantIds: Set<string>; estimateRestaurantIds: Set<string> }) {
  const accentColor = useMemo(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#20f', [])
  return <div className="map-panel" aria-label="Meal locations map" role="region"><MapContainer center={[37.7749, -122.4194]} zoom={13} scrollWheelZoom className="map"><TileLayer attribution="&copy; OpenStreetMap contributors &copy; CARTO" url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" /><FocusRestaurant restaurantId={selectedRestaurant} restaurantById={restaurantById} />{restaurants.flatMap((restaurant) => restaurant.locations.map((location, index) => { const selected = restaurant.id === selectedRestaurant; const matched = visibleRestaurantIds.has(restaurant.id); const estimateOnly = estimateRestaurantIds.has(restaurant.id); return <CircleMarker key={`${restaurant.id}-${index}`} center={[location.lat, location.lng]} radius={selected ? 6 : 3.5} pathOptions={{ color: accentColor, fillColor: accentColor, fillOpacity: selected ? 0.85 : estimateOnly ? 0 : matched ? 0.5 : 0.12, opacity: selected ? 1 : matched ? 0.7 : 0.28, weight: selected ? 2 : estimateOnly ? 1.5 : 1 }}><Popup><strong>{restaurant.name}</strong><br /><span className="popup-address">{location.address}</span></Popup></CircleMarker> }))}</MapContainer></div>
}
