# Data pipeline

All scraped restaurant data flows through `save.save_restaurant(doc)`:

```python
import sys; sys.path.insert(0, "pipeline")
from save import save_restaurant
save_restaurant(doc)  # doc shape documented in pipeline/schema.py
```

- Schema: `schema.py` (restaurant + item shape, categories, source types)
- Validation: `validate.py` (9·fat + 4·carbs + 4·protein macro check with
  asymmetric tolerance; SF-bounds check on every location; sanitization of all
  scraped text on ingest)
- Output: `data/restaurants/<id>.json` (validated), `data/rejected/<id>.json`
  (quarantined rows with reasons)
- `build_dist.py` merges everything into `data/dist/` for the app.

Rules enforced in code:
- every item tagged `meal | side | drink | condiment | component`
- every restaurant needs ALL its SF locations with lat/lng
- `crowd`/`derived` sources must set `is_estimate: true`
- exact source endpoint/file + retrieved date required
