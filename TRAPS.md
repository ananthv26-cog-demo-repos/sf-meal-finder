# TRAPS

Things that cost >15 minutes on this project. Add to this whenever you get burned.

- Macro check tolerance is asymmetric on purpose (see `pipeline/validate.py`):
  computed-over-stated is usually fiber/rounding; computed-under-stated usually
  means alcohol or wrong numbers. Don't loosen it to make failures pass —
  quarantine and record.
- Check what a row is *per* (per slice vs per whole pizza, per component vs per
  serving) before saving. `serving_note` is required thinking, even if optional
  in schema.
- Ordering APIs and nutrition APIs can reuse ids for different things — spot
  check a famous item before trusting a join.
