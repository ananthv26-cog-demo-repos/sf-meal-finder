"""Extract the shared Veggie Grill / Next Level Burger nutrition PDF."""
from __future__ import annotations
import datetime,io,re,sys,urllib.request
from pathlib import Path
import pdfplumber
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"pipeline"))
from save import save_restaurant
URL="https://media-cdn.getbento.com/accounts/0879d48e96f07deb9c3248ba98650536/media/8bZYDfc2Q4mY44qC1X25_VG%20Nutrition%20Info_4.6.24.pdf"

def parse():
 data=urllib.request.urlopen(URL,timeout=120).read()
 items=[];section="component";seen=set();seen_accomp=set();last_platter=None
 mapping={"Burgers":"meal","Sandwiches":"meal","Wraps":"meal","Bowls":"meal","Salads":"meal","Mas Veggies":"meal","Kids Menu":"meal","Shareables":"side","Sides":"side"}
 with pdfplumber.open(io.BytesIO(data)) as pdf:
  for page in pdf.pages:
   words=page.extract_words(); by_y={}
   for w in words:
    top=w["top"]; key=next((k for k in by_y if abs(k-top)<=2.2),round(top))
    by_y.setdefault(key,[]).append(w)
   nums=[w for w in words if re.fullmatch(r"\d+(?:\.\d+)?",w["text"]) and w["top"]>150]
   xs=sorted((w["x0"]+w["x1"])/2 for w in nums); clusters=[]
   for x in xs:
    if not clusters or x-clusters[-1][-1]>12: clusters.append([x])
    else: clusters[-1].append(x)
   headers=[sum(c)/len(c) for c in clusters]
   if len(headers)!=13: continue
   for top in sorted(by_y):
    row=by_y[top]; text=" ".join(w["text"] for w in row)
    if text in mapping: section=mapping[text]; continue
    names=[w["text"] for w in row if w["x0"]<180 and not re.fullmatch(r"\d+(?:\.\d+)?",w["text"])]
    if not names: continue
    name=" ".join(names).strip()
    if "tenders" in name.lower():
     last_platter=name
    vals={}
    for w in row:
     if not re.fullmatch(r"\d+(?:\.\d+)?",w["text"]): continue
     c=min(range(13),key=lambda i:abs((w["x0"]+w["x1"])/2-headers[i]))
     if abs((w["x0"]+w["x1"])/2-headers[c])<16: vals[c]=float(w["text"])
    if len(vals)<10 or 0 not in vals: continue
    low=name.lower(); cat=section
    if low.startswith(("with ","add ","buffalo sauce","bbq sauce","ranch dressing","celery stick","orange glaze sauce")): cat="condiment" if "sauce" in low or "dressing" in low else "component"
    if "fries" in low or "mac n cheese" in low or "soup side" in low or "mango" in low: cat="side"
    accompaniment = low.startswith(("buffalo sauce","bbq sauce","ranch dressing","celery stick"))
    signature=(vals[0],vals.get(2),vals.get(4),vals.get(5),vals.get(8))
    if accompaniment and signature in seen_accomp:
     continue
    if accompaniment:
     seen_accomp.add(signature)
    if accompaniment and last_platter:
     name=f"{name} (with {last_platter})"
     low=name.lower()
    base=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")
    iid=f"{section}-{base}".strip("-")
    if iid in seen:
     continue
    seen.add(iid)
    items.append({"id":iid,"name":name,"description":None,"category":cat,"calories":vals[0],"protein_g":vals.get(8,0),
     "carbs_g":vals.get(5,0),"fat_g":vals.get(2,0),"fiber_g":vals.get(6),"sodium_mg":vals.get(4),"serving_note":"per listed serving",
     "is_estimate":False,"source":{"type":"published","url":URL}})
 return items

def main():
 save_restaurant({"id":"next-level-burger","name":"Next Level Burger","website":"https://www.nextlevelburger.com",
  "nutrition_source":{"type":"published","url":URL,"vendor":None,"retrieved":datetime.date.today().isoformat()},
  "locations":[{"address":"450 Rhode Island St, San Francisco, CA 94107","lat":37.7643298,"lng":-122.4027236,"neighborhood":"Mission Bay"}],"items":parse()})
if __name__=="__main__":main()
