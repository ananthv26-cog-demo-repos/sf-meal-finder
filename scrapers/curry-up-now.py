"""Curry Up Now crowd scraper.

The old consolidated locator is dead (GET /store and /locations return 404).
The current sitemap and official https://www.curryupnow.com/sf-valencia page
provide one SF city-proper location, geocoded with Nominatim. FatSecret exact
brand rows are queried with paged foods.search and food.get.v2; all nutrition is
crowd/estimated because the chain publishes no nutrition. Spot check: Chicken
Tikka Masala Burrito parses as 707 kcal, 10 g fat, 120 g carbs, and 33 g
protein.
TRAPS: the old embedded Yext key returns invalid_api_key; use current pages,
and classify burritos/thali/tikka masala as meals, drinks as drinks, sauces as
condiments, and unknowns as components.
"""
import base64,datetime,hashlib,hmac,json,os,random,re,sys,time,urllib.parse,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _fatsecret import fatsecret as cached_fatsecret
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"pipeline"))
from save import save_restaurant
API="https://platform.fatsecret.com/rest/server.api"; URL=f"{API}?method=foods.search&search_expression=Curry+Up+Now&max_results=50&page_number=0"; TODAY=datetime.date.today().isoformat()
def fs(p):
 return cached_fatsecret(p)
def main():
 found={};brand="curry up now"
 for e in ("Curry Up Now","CurryUpNow","Curry burrito"):
  for page in range(100):
   x=fs({"method":"foods.search","search_expression":e,"max_results":50,"page_number":page});z=x.get("foods",{});rows=z.get("food",[]);rows=[rows] if isinstance(rows,dict) else rows
   for r in rows:
    if (r.get("brand_name") or "").strip().casefold()==brand:found[r["food_id"]]=r
   if not rows or (page+1)*50>=int(z.get("total_results",0)):break
 out=[]
 for fid,r in sorted(found.items(),key=lambda x:x[1].get("food_name","")):
  x=fs({"method":"food.get.v2","food_id":fid})
  if "food" not in x:continue
  f=x["food"];ss=f["servings"]["serving"];ss=[ss] if isinstance(ss,dict) else ss;s=next((v for v in ss if "100g" not in v.get("serving_description","").lower()),ss[0]);n=r["food_name"];l=n.casefold();c="meal" if any(k in l for k in ("burrito","thali","tikka","chaat","bowl","wrap")) else "drink" if any(k in l for k in ("lassi","chai","juice","drink")) else "condiment" if any(k in l for k in ("sauce","chutney","dressing")) else "component";print(f"  [{c}] {n}");num=lambda v:None if v in (None,"") else float(v);out.append({"id":re.sub(r"[^a-z0-9]+","-",l).strip("-")+"-"+fid,"name":n,"description":None,"category":c,"calories":num(s.get("calories")),"protein_g":num(s.get("protein")),"carbs_g":num(s.get("carbohydrate")),"fat_g":num(s.get("fat")),"fiber_g":num(s.get("fiber")),"sodium_mg":num(s.get("sodium")),"serving_note":f"per {s['serving_description']} (crowd-submitted; Curry Up Now publishes no nutrition)","is_estimate":True,"source":{"type":"crowd","url":f["food_url"]}})
 save_restaurant({"id":"curry-up-now","name":"Curry Up Now","website":"https://www.curryupnow.com","nutrition_source":{"type":"crowd","url":URL,"vendor":"fatsecret","retrieved":TODAY},"locations":[{"address":"659 Valencia St, San Francisco, CA 94110","lat":37.7622411,"lng":-122.4213894,"neighborhood":"Mission"}],"items":out})
if __name__=="__main__":main()
