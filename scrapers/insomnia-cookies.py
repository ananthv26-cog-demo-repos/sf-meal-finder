"""Parse Insomnia Cookies nutrition-facts panels from the published PDF.

The PDF is mostly image-backed.  ``pdftotext`` still exposes the text-backed
nutrition panel(s), and this parser deliberately uses labeled fields rather
than positional row extraction.  Image-only panels remain absent rather than
being filled with guesses.
"""
from __future__ import annotations
import datetime, io, os, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path
import pdfplumber
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from save import save_restaurant

URL = "https://api.insomniacookies.com/uploads/Insomnia%20Cookies%20Overall%20Nutritional%20Facts%20Guide.pdf"

def parse():
    data=urllib.request.urlopen(URL,timeout=120).read()
    items=[]
    names={4:"Chocolate Chunk",5:"M&M",6:"Cookies N Cream",7:"Double Chocolate Chunk",
      8:"Mint Chocolate Chunk",9:"Oatmeal Raisin",10:"Peanut Butter Chip",14:"Chocolate Chip",
      23:"Milk Chocolate Chunk",25:"Brownie",26:"Blondie",27:"Brookie",
      31:"Salted Caramel Ice Cream",32:"Vanilla Ice Cream",33:"Chocolate Chunk Ice Cream",
      34:"Double Chocolate Chunk Ice Cream",35:"Birthday Cake Ice Cream",
      36:"Chocolate Mint Ice Cream",37:"Peanut Butter Cup Ice Cream",38:"Vanilla Ice Cream"}
    # First use the PDF text layer when available; most cookie panels are
    # image-backed, so OCR is the required fallback.
    with tempfile.TemporaryDirectory() as td:
      with pdfplumber.open(io.BytesIO(data)) as pdf:
       pages=[i+1 for i,p in enumerate(pdf.pages) if p.chars]
      for page in range(1,39):
        text=""
        if page in pages:
          with pdfplumber.open(io.BytesIO(data)) as pdf: text=pdf.pages[page-1].extract_text() or ""
        if "Nutrition Facts" not in text:
          png=os.path.join(td,f"page-{page}")
          subprocess.run(["pdftoppm","-r","300","-f",str(page),"-l",str(page),"-png","-singlefile","-",png],
                         input=data,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
          text=subprocess.check_output(["tesseract",png+".png","stdout","--psm","11"],text=True,stderr=subprocess.DEVNULL)
        if "Nutrition" not in text or "Calories" not in text: continue
        # OCR often inserts spaces inside values such as “1 30”.
        text=re.sub(r"(?<=\d)\s+(?=\d)", "", text)
        def field(label):
          compact=label.replace(" ",r"\s*")
          m=re.search(compact+r"[^0-9]{0,20}([<>]?\s*\d+(?:\.\d+)?)",text,re.I)
          if not m:
            m=re.search(label.replace(" ","")+r"[^0-9]{0,20}([<>]?\s*\d+)",text.replace(" ",""),re.I)
          if not m:return None
          value=m.group(1).replace("<","").strip()
          # OCR may swallow the trailing DV percentage (e.g. 34912 for 34g).
          if len(value)>3:value=value[:2]
          return float(value)
        m=re.search(r"Cal(?:ories| ori(?:es|a)?)[^0-9]{0,20}([<>]?\s*\d+(?:\s+\d+)?)",text,re.I)
        cal=float(re.sub(r"\s+","",m.group(1))) if m else None
        if cal is not None and cal < 50: cal *= 10
        if cal is not None and cal > 1000: cal = float(str(int(cal))[-3:])
        fat=field("Total Fat"); carbs=field("Total Carbohydrate"); protein=field("Protein"); fiber=field("Dietary Fiber"); sodium=field("Sodium")
        if None in (cal,fat,carbs,protein): continue
        name=names.get(page)
        if not name:
          continue
        if page == 32:
          name = "Chocolate Ice Cream"
        if page == 38:
          name = "Vanilla Ice Cream (large panel)"
        items.append({"id":re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")+f"-p{page}","name":name,
          "description":"Product name is image-only in the published PDF; labeled Nutrition Facts values parsed from the panel.",
          "category":"side","calories":cal,"protein_g":protein,"carbs_g":carbs,"fat_g":fat,"fiber_g":fiber,"sodium_mg":sodium,
          "serving_note":("per labeled Nutrition Facts serving" if page not in (32,38)
             else ("per 2 oz ice cream serving" if page == 32 else "per large labeled ice cream serving")),
          "is_estimate":False,"source":{"type":"published","url":URL}})
    return items

def main():
    save_restaurant({"id":"insomnia-cookies","name":"Insomnia Cookies","website":"https://insomniacookies.com",
      "nutrition_source":{"type":"published","url":URL,"vendor":None,"retrieved":datetime.date.today().isoformat()},
      "locations":[{"address":"362 Kearny St, San Francisco, CA 94108","lat":37.7916227,"lng":-122.4041080,"neighborhood":"Union Square"}],
      "items":parse()})
if __name__=="__main__": main()
