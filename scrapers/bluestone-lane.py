"""Bluestone Lane crowd scraper.

Official locator is paginated HTML at
https://bluestonelane.com/cafe-and-coffee-shop-locations/; five official SF
pages were found, with no coordinates, so Nominatim coordinates are embedded.
FatSecret exact-brand search is paged and food.get.v2 supplies crowd nutrition.
No item spot check is applicable: the clean exact-brand harvest found zero
rows after alternate spellings, so the scraper skips the chain rather than
writing a zero-item document.
Unknown names are components; coffee drinks are drinks, meals/toast/sandwiches
are meals, and pastries are sides.
"""
import base64,datetime,hashlib,hmac,json,os,random,re,sys,time,urllib.parse,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _fatsecret import fatsecret as cached_fatsecret
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"pipeline"))
from save import save_restaurant
API="https://platform.fatsecret.com/rest/server.api";URL=f"{API}?method=foods.search&search_expression=Bluestone+Lane&max_results=50&page_number=0";TODAY=datetime.date.today().isoformat()
LOC=[("420 Folsom St, San Francisco, CA",37.7878856,-122.3938839),("3352 Steiner St, San Francisco, CA 94123",37.8004498,-122.4376347),("55 2nd St, San Francisco, CA",37.7888148,-122.400334),("562 Sutter St, San Francisco, CA 94102",37.7891926,-122.4098437),("227 Front St, San Francisco, CA",37.7937621,-122.399072)]
def fs(p):
 return cached_fatsecret(p)
def main():
 found={};brand="bluestone lane"
 for e in ("Bluestone Lane","Bluestone","Bluestone Lane Coffee"):
  for page in range(100):
   x=fs({"method":"foods.search","search_expression":e,"max_results":50,"page_number":page});z=x.get("foods",{});rows=z.get("food",[]);rows=[rows] if isinstance(rows,dict) else rows
   for r in rows:
    if (r.get("brand_name") or "").strip().casefold()==brand:found[r["food_id"]]=r
   if not rows or (page+1)*50>=int(z.get("total_results",0)):break
 out=[]
 for fid,r in found.items():
  x=fs({"method":"food.get.v2","food_id":fid})
  if "food" not in x:continue
  f=x["food"];ss=f["servings"]["serving"];ss=[ss] if isinstance(ss,dict) else ss;s=ss[0];n=r["food_name"];l=n.casefold();c="drink" if any(k in l for k in ("coffee","tea","latte","espresso","cappuccino")) else "meal" if any(k in l for k in ("toast","sandwich","salad","bowl","wrap")) else "side" if any(k in l for k in ("pastry","cake","cookie","muffin")) else "component";num=lambda v:None if v in (None,"") else float(v);print(f"  [{c}] {n}");out.append({"id":re.sub(r"[^a-z0-9]+","-",l).strip("-")+"-"+fid,"name":n,"description":None,"category":c,"calories":num(s.get("calories")),"protein_g":num(s.get("protein")),"carbs_g":num(s.get("carbohydrate")),"fat_g":num(s.get("fat")),"fiber_g":num(s.get("fiber")),"sodium_mg":num(s.get("sodium")),"serving_note":f"per {s['serving_description']} (crowd-submitted; Bluestone Lane publishes no nutrition)","is_estimate":True,"source":{"type":"crowd","url":f["food_url"]}})
 if not out:
  target=Path(__file__).resolve().parent.parent/"data/restaurants/bluestone-lane.json"
  target.unlink(missing_ok=True)
  print("bluestone-lane: skipped; clean exact-brand harvest returned zero rows")
  return
 save_restaurant({"id":"bluestone-lane","name":"Bluestone Lane","website":"https://bluestonelane.com","nutrition_source":{"type":"crowd","url":URL,"vendor":"fatsecret","retrieved":TODAY},"locations":[{"address":a,"lat":la,"lng":lo,"neighborhood":None} for a,la,lo in LOC],"items":out})
if __name__=="__main__":main()
