import type { ReactNode } from 'react'
import { DRINK_PROTEIN_MIN } from '../types'
import type { Meal, Restaurant, SortDirection, SortKey } from '../types'
import { formatNumber, isHttpUrl, proteinPercent } from '../format'

function SortHeader({ label, sortKey, activeKey, direction, onSort }: { label: string; sortKey: SortKey; activeKey: SortKey; direction: SortDirection; onSort: (key: SortKey) => void }) {
  const active = sortKey === activeKey
  return <button aria-label={active ? `Sort by ${label.toLowerCase()}, currently sorted ${direction === 'asc' ? 'ascending' : 'descending'}` : `Sort by ${label.toLowerCase()}`} className={`sort-button ${active ? 'active' : ''}`} type="button" onClick={() => onSort(sortKey)}>{label}{active && <span aria-hidden="true">{direction === 'asc' ? '↑' : '↓'}</span>}</button>
}
export function ResultsPanel({ filteredMeals, restaurantById, restaurantsCount, totalEligibleMeals, selectedRestaurant, onSelectRestaurant, sortKey, sortDirection, onSort, error }: { filteredMeals: Meal[]; restaurantById: Map<string, Restaurant>; restaurantsCount: number; totalEligibleMeals: number; selectedRestaurant: string | null; onSelectRestaurant: (restaurantId: string) => void; sortKey: SortKey; sortDirection: SortDirection; onSort: (key: SortKey) => void; error: string | null }) {
  return <div className="results-panel"><div className="column-head"><span>Meal</span><SortHeader activeKey={sortKey} direction={sortDirection} label="Cal" sortKey="calories" onSort={onSort} /><SortHeader activeKey={sortKey} direction={sortDirection} label="Protein" sortKey="protein_g" onSort={onSort} /><SortHeader activeKey={sortKey} direction={sortDirection} label="P%" sortKey="protein_pct" onSort={onSort} /><SortHeader activeKey={sortKey} direction={sortDirection} label="Carbs" sortKey="carbs_g" onSort={onSort} /><SortHeader activeKey={sortKey} direction={sortDirection} label="Fat" sortKey="fat_g" onSort={onSort} /></div>
    <div className="result-list">{filteredMeals.map((meal) => <MealRow key={`${meal.restaurant_id}-${meal.id}`} meal={meal} restaurant={restaurantById.get(meal.restaurant_id)} selected={selectedRestaurant === meal.restaurant_id} onSelect={onSelectRestaurant} />)}{filteredMeals.length === 0 && <p className="empty">{error ?? 'No meals match these filters.'}</p>}</div>
    <footer className="results-footer">{restaurantsCount} restaurants · {totalEligibleMeals} eligible items · data validated 9·fat+4·carbs+4·protein</footer>
  </div>
}
function MealRow({ meal, restaurant, selected, onSelect }: { meal: Meal; restaurant?: Restaurant; selected: boolean; onSelect: (restaurantId: string) => void }) {
  const restaurantName = restaurant?.name ?? meal.restaurant_id
  const sourceChip: ReactNode = isHttpUrl(meal.source_url) ? <a className="source-chip" href={meal.source_url} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>{meal.source_type}</a> : <span className="source-chip">{meal.source_type}</span>
  return <div aria-label={`${meal.name}, ${restaurantName}, ${formatNumber(meal.calories, false, 0)} calories, ${formatNumber(meal.protein_g, false, 1)} grams protein${meal.is_estimate ? ' estimated' : ''} — focus on map`} className={`meal-row ${selected ? 'selected' : ''}`} role="button" tabIndex={0} onClick={() => onSelect(meal.restaurant_id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(meal.restaurant_id) } }}>
    <div className="meal-info"><strong>{meal.name}</strong><span>{restaurantName}{meal.serving_note ? ` · ${meal.serving_note}` : ''}</span><div className="badges">{meal.category === 'drink' && meal.protein_g >= DRINK_PROTEIN_MIN && <em className="drink-badge">DRINK</em>}{meal.is_estimate && <em>~est</em>}{sourceChip}</div></div><span className="number">{formatNumber(meal.calories, meal.is_estimate, 0)}</span><span className="number protein">{formatNumber(meal.protein_g, meal.is_estimate, 1)}g</span><span className="number">{formatNumber(proteinPercent(meal), meal.is_estimate, 0)}%</span><span className="number">{formatNumber(meal.carbs_g, meal.is_estimate, 1)}g</span><span className="number">{formatNumber(meal.fat_g, meal.is_estimate, 1)}g</span>
  </div>
}
