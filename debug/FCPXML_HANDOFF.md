# FCPXML Export — Debug Handoff

## What We're Trying To Do

Export highlight reels from the video pipeline as `.fcpxml` files that Final Cut Pro
can import without errors. The source footage is GoPro 4K UHD (3840×2160) shot at
**119.88fps**. We want FCP to open the timeline with clips in the right order, at the
right in/out points.

---

## Root Cause (Confirmed)

**FCP does not support 119.88fps as a sequence frame rate.**

The original code emitted `frameDuration="1001/120000s"` for the sequence format —
FCP rejects any sequence format with a frame rate > 60fps.

---

## What We've Tried

### Fix 1 — Wrong approach (orphaned format)
Created a second `<format>` element at 59.94fps and pointed the `<sequence>` at it,
but the assets still referenced the original 119.88fps format. FCP rejected it with:

```
Encountered an unexpected value. (format="r7": ...sequence[1]/@format)
```

FCP apparently requires the sequence format to be **used by at least one asset**,
and/or to be **declared before assets** in `<resources>`.

### Fix 2 — Current code (committed, still failing)
Restructured `build()` so:
- The **sequence format is created first** (`r0` in `<resources>`)
- **All assets reference the same sequence format** (`format="r0"`)
- Format: `name="FFVideoFormat4K5994"`, `frameDuration="1001/60000s"` (59.94fps)
- FCPXML `version="1.11"`

Generated file structure (confirmed correct by inspection):
```xml
<fcpxml version="1.11">
  <resources>
    <format id="r0" name="FFVideoFormat4K5994" width="3840" height="2160"
            frameDuration="1001/60000s"/>
    <asset id="r1" ... format="r0">...</asset>
    <asset id="r2" ... format="r0">...</asset>
  </resources>
  <library>
    <event ...>
      <project ...>
        <sequence format="r0" ...>
```

FCP still rejects with:
```
Encountered an unexpected value. (format="r0": ...sequence[1]/@format)
```

---

## Current Theory

`FFVideoFormat4K5994` may not be a recognized format name in the installed FCP
version, OR the format name is correct but requires additional attributes (e.g.
`colorSpace`, `fieldOrder`) that we're not providing.

---

## Diagnostic Test Files

Three test FCPXMLs are in `test_artifacts/` — import each into FCP to isolate the issue:

| File | Tests |
|------|-------|
| `test_A_v111_named5994.fcpxml` | version=1.11 + `FFVideoFormat4K5994` name |
| `test_B_v19_noname5994.fcpxml` | version=1.9 + **no format name** (custom 59.94fps) |
| `test_C_v19_2997.fcpxml` | version=1.9 + `FFVideoFormat4K2997` (known-good name, used as **sequence** format) |

**The answer we need:** which of A, B, C does FCP accept? That tells us:
- If **A works** → just needed version=1.11, ship it
- If **B works** → format name is wrong; use a nameless custom format
- If **C works but A/B don't** → 59.94fps sequences aren't supported; fall back to 29.97fps
- If **none work** → structural issue unrelated to fps/name

---

## Key Files

- Export code: `app/export/fcpxml.py`
- Fix documentation: `FCPXML_FIX_COMPLETE-3.md`
- Debug journal: `debug/journal.md`
- Export route: `app/api/routes_highlights.py` → `GET /highlights/{id}/export/fcpxml`

---

## Next Steps (pending test results above)

1. Run the three test files through FCP and report which succeed
2. Update `get_sequence_format_name()` in `fcpxml.py` based on result
3. Re-export a real highlight reel and confirm clean import
