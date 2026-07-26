export type Location = { address: string; lat: number; lng: number; neighborhood?: string | null }
export type Restaurant = { id: string; name: string; website: string; locations: Location[] }
export type Meal = {
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
export type SortKey = 'name' | 'calories' | 'protein_g' | 'protein_pct' | 'carbs_g' | 'fat_g'
export type SortDirection = 'asc' | 'desc'
export type Filters = { minCalories: string; maxCalories: string; minProtein: string; unofficial: boolean; search: string }
