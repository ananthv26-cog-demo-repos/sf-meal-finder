"""Extract Everbowl's published nutrition chart."""
from __future__ import annotations
import datetime, io, re, sys, urllib.request
from pathlib import Path
import pdfplumber
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant
URL = "https://admin.everbowl.com/uploads/Nutritional_Information_Chart_091d1f7dec.pdf"

def parse():
    data = urllib.request.urlopen(URL, timeout=120).read()
    items=[]; seen=set(); category="meal"
    with pdfplumber.open(io.BytesIO(data)) as pdf:
      for page in pdf.pages:
        words=page.extract_words(); by_y={}
        for w in words:
          top=w["top"]; key=next((k for k in by_y if abs(k-top)<=2.2),round(top))
          by_y.setdefault(key,[]).append(w)
        nums=[w for w in words if re.fullmatch(r"\d+(?:\.\d+)?",w["text"]) and 250<w["top"]<720]
        xs=sorted((w["x0"]+w["x1"])/2 for w in nums); clusters=[]
        for x in xs:
          if not clusters or x-clusters[-1][-1]>12: clusters.append([x])
          else: clusters[-1].append(x)
        headers=[sum(c)/len(c) for c in clusters]
        if len(headers)!=11: continue
        current=None
        for top in sorted(by_y):
          row=by_y[top]; text=" ".join(w["text"] for w in row)
          if text in {"BOWLS","SMOOTHIES"}: category="meal"
          if text in {"BASES","BONUS BASES","FRESH FRUIT","SUPERFOODS","SUPER POWDER","FROZEN FRUIT","MILKS"}: category="component"
          names=[w["text"] for w in row if w["x0"]<100 and w["text"].lower() not in {"regular","large"}]
          if names and not any(re.fullmatch(r"\d+(?:\.\d+)?",x) for x in names):
            candidate=" ".join(names)
            if candidate not in {"NUTRITIONAL", "INFORMATION", "NUTRITIONAL INFORMATION"} and not candidate.startswith(("BOWLS","SMOOTHIES")):
              current=candidate
          size=next((w["text"].lower() for w in row if w["text"].lower() in {"regular","large"}),None)
          vals={}
          for w in row:
            if not re.fullmatch(r"\d+(?:\.\d+)?",w["text"]): continue
            c=min(range(11),key=lambda i:abs((w["x0"]+w["x1"])/2-headers[i]))
            if abs((w["x0"]+w["x1"])/2-headers[c])<12: vals[c]=float(w["text"])
          if len(vals)<9 or 0 not in vals: continue
          if not current: continue
          size = size or "portion"
          name=f"{current} ({size.title()})"; iid=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")
          if iid in seen: continue
          seen.add(iid); cat="meal" if category=="meal" else "component"
          items.append({"id":iid,"name":name,"description":None,"category":cat,
            "calories":vals[0],"protein_g":vals.get(10,0),"carbs_g":vals.get(6,0),"fat_g":vals.get(1,0),
            "fiber_g":vals.get(7),"sodium_mg":vals.get(5),"serving_note":f"per {size} bowl" if cat=="meal" else f"per {size} serving",
            "is_estimate":False,"source":{"type":"published","url":URL}})
    return items

def main():
    save_restaurant({"id":"everbowl","name":"Everbowl","website":"https://everbowl.com",
      "nutrition_source":{"type":"published","url":URL,"vendor":None,"retrieved":datetime.date.today().isoformat()},
      "locations":[{"address":"170 O'Farrell St, San Francisco, CA 94102","lat":37.7873246,"lng":-122.4075665,"neighborhood":"Union Square"}],
      "items":parse()})
if __name__=="__main__": main()
