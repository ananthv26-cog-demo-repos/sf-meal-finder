"""Blue Bottle Coffee crowd scraper.

Official cafe locator/search is GET https://bluebottlecoffee.com/cafes and
Cloudflare-403 from curl (also verified in Chrome/CDP); official individual
pages supplied the 13 SF addresses. Those pages expose no coordinates, so
Nominatim coordinates are embedded below. FatSecret exact-brand foods.search
(paged) and food.get.v2 supply crowd/estimated nutrition. Spot check: New
Orleans Style Iced Coffee parses as 160 kcal, 6 g fat, 21 g carbs, and 6 g
protein.
TRAPS: Cloudflare blocks the locator; retain only official individual cafe
records, classify coffee/tea drinks, sandwiches/food-case meals, pastries as
sides, and unknowns as components.
"""
import base64,datetime,hashlib,hmac,json,os,random,re,sys,time,urllib.parse,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _fatsecret import fatsecret as cached_fatsecret
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"pipeline"))
from save import save_restaurant
API="https://platform.fatsecret.com/rest/server.api";URL=f"{API}?method=foods.search&search_expression=Blue+Bottle&max_results=50&page_number=0";TODAY=datetime.date.today().isoformat()
LOC=[("315 Linden St, San Francisco, CA 94102",37.7763144,-122.4232552),("115 Sansome St, San Francisco, CA 94104",37.7914533,-122.4010654),("2 South Park, San Francisco, CA 94107",37.7824374,-122.3932644),("168 2nd St, San Francisco, CA 94105",37.7869867,-122.3989296),("2453 Fillmore St, San Francisco, CA 94115",37.7920384,-122.4347649),("1 Ferry Building #7, San Francisco, CA 94111",37.7960029,-122.3938436),("909 Montgomery St #105, San Francisco, CA 94133",37.7973778,-122.4038543),("55 S Van Ness Ave, San Francisco, CA 94103",37.7739546,-122.4186072),("705 Market St, San Francisco, CA 94103",37.7871903,-122.403701),("1385 4th St, San Francisco, CA 94158",37.7711067,-122.391072),("300 Toni Stone Xing #E, San Francisco, CA 94158",37.7754338,-122.3887262),("250 Howard St Suite 3A, San Francisco, CA 94105",37.7906275,-122.394398),("199 Sutter St, San Francisco, CA 94104",37.789741,-122.4037025)]
def fs(p):
 return cached_fatsecret(p)
def main():
 found={};brand="blue bottle coffee"
 for e in ("Blue Bottle","Blue Bottle Coffee","BlueBottle"):
  for page in range(100):
   x=fs({"method":"foods.search","search_expression":e,"max_results":50,"page_number":page});z=x.get("foods",{});rows=z.get("food",[]);rows=[rows] if isinstance(rows,dict) else rows
   for r in rows:
    if (r.get("brand_name") or "").strip().casefold()==brand:found[r["food_id"]]=r
   if not rows or (page+1)*50>=int(z.get("total_results",0)):break
 out=[]
 for fid,r in sorted(found.items(),key=lambda x:x[1].get("food_name","")):
  x=fs({"method":"food.get.v2","food_id":fid})
  if "food" not in x:continue
  f=x["food"];ss=f["servings"]["serving"];ss=[ss] if isinstance(ss,dict) else ss;s=next((v for v in ss if "100g" not in v.get("serving_description","").lower()),ss[0]);n=r["food_name"];l=n.casefold();c="drink" if any(k in l for k in ("coffee","tea","latte","espresso","cold brew","cocoa","mocha")) else "meal" if any(k in l for k in ("sandwich","toast","bowl","salad")) else "side" if any(k in l for k in ("pastry","cake","cookie","scone","muffin")) else "component";print(f"  [{c}] {n}");num=lambda v:None if v in (None,"") else float(v);out.append({"id":re.sub(r"[^a-z0-9]+","-",l).strip("-")+"-"+fid,"name":n,"description":None,"category":c,"calories":num(s.get("calories")),"protein_g":num(s.get("protein")),"carbs_g":num(s.get("carbohydrate")),"fat_g":num(s.get("fat")),"fiber_g":num(s.get("fiber")),"sodium_mg":num(s.get("sodium")),"serving_note":f"per {s['serving_description']} (crowd-submitted; Blue Bottle publishes no nutrition)","is_estimate":True,"source":{"type":"crowd","url":f["food_url"]}})
 save_restaurant({"id":"blue-bottle-coffee","name":"Blue Bottle Coffee","website":"https://bluebottlecoffee.com","nutrition_source":{"type":"crowd","url":URL,"vendor":"fatsecret","retrieved":TODAY},"locations":[{"address":a,"lat":la,"lng":lo,"neighborhood":None} for a,la,lo in LOC],"items":out})
if __name__=="__main__":main()
