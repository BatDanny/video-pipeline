# Clip Export vs. FCPXML — Decision Handoff

## The Problem We're Solving

The video pipeline's primary output is a highlight reel: AI selects the best scored
clips from GoPro footage and assembles them into a watchable sequence for the user to
bring into Final Cut Pro for final editing.

The current approach is FCPXML export — a structured XML timeline that FCP imports
directly as a pre-assembled edit. **This has been broken across multiple sessions.**

---

## Why FCPXML Has Been a Persistent Problem

### The Root Issue

Source footage is GoPro 4K at **119.88fps**. FCP does not support 119.88fps as a
*sequence* frame rate. The sequence must be downconverted to 59.94fps in the XML.
This is legitimate, but it creates a chain of fragile requirements:

- Sequence `<format>` must use exactly the right FCP format name string (e.g. `FFVideoFormat4K5994`)
- All time values (offsets, durations, starts) must be rational fractions aligned to the
  sequence's frame grid — integer division errors break FCP's importer silently
- Asset `<format>` attributes must reference the correct format resource
- FCP's error messages are cryptic (`Encountered an unexpected value`) and don't say
  which attribute is wrong

### What's Been Tried (See `debug/FCPXML_HANDOFF.md`)

Three separate fix attempts across commits:
1. Added a second 59.94fps format — FCP rejected because it wasn't used by any asset
2. Made all assets share the sequence format — FCP still rejected (`format="r0"`)
3. Diagnostic test files created (A/B/C) — **still awaiting FCP test results**

The current `Highlight_Reel38348pm-6.fcpxml` in the repo root has a *different*
structure again: assets use `format="r2"` (119.88fps raw), sequence uses `format="r1"`
(59.94fps named). This contradicts the fix docs, suggesting the code path that generated
it diverged from the fix commits.

**Bottom line: the FCPXML approach has consumed 3+ sessions and is still not confirmed
working end-to-end.**

---

## The Alternative: Export Individual Video Clips

Instead of an XML timeline, export each selected clip as a discrete `.mp4` file cut
from the source footage using ffmpeg. The user downloads a zip (or individual files)
and drags them into FCP as media. FCP auto-detects their frame rate, resolution, and
codec. No format metadata, no rational time math, no FCP version compatibility issues.

### The Core Command

```bash
ffmpeg -ss {clip.start_sec} \
       -i {video.filepath} \
       -t {clip.duration_sec} \
       -c copy \
       -map 0:v:0 -map 0:a:0 \
       output.mp4
```

- `-ss` before `-i`: fast seek to nearest keyframe (no re-encode)
- `-c copy`: lossless stream copy, preserves original 4K HEVC quality
- `-map`: include video + audio, skip GoPro telemetry streams

---

## Arguments FOR Clip Export (away from FCPXML)

1. **It works today.** ffmpeg is already in the container (used by `ingest.py`). No new
   dependencies. No FCP-specific format strings to get right.

2. **Universal output.** `.mp4` files import into FCP, DaVinci Resolve, Premiere,
   iMovie, or anything else. FCPXML is FCP-only (Resolve support is partial).

3. **No time math.** FCPXML requires converting float seconds → rational fractions
   aligned to a sequence frame grid. One off-by-one breaks the import silently.
   ffmpeg's `-ss` and `-t` just take seconds.

4. **No format name guessing.** The FCPXML approach requires knowing FCP's internal
   format name strings (`FFVideoFormat4K5994`) and getting them exactly right.
   ffmpeg doesn't care.

5. **Simpler code.** The FCPXML builder is ~400 lines. A clip exporter is ~60 lines.
   Less surface area for bugs.

6. **GoPro 119.88fps is preserved.** Exported clips stay at 119.88fps natively.
   FCP imports them and the user chooses how to use them (normal speed or slow-mo at
   50% = 59.94fps). FCPXML forces a 59.94fps sequence, making that decision for them.

7. **Practical workflow.** The user gets a folder of named, numbered clips
   (`01_snowboarding_score59.mp4`, etc.). They can preview in Finder, discard any
   they don't want, then batch-import to FCP. This is a cleaner handoff than hoping
   an XML timeline parses cleanly.

8. **Near-instant, zero quality loss.** Stream copy runs at read/write speed. A 30-second
   4K HEVC clip copies in under 2 seconds. No transcoding degradation.

---

## Arguments FOR Keeping FCPXML

1. **The edit is pre-assembled.** With FCPXML, FCP opens a ready-to-play timeline.
   With clip export, the user has to manually drag clips onto an FCP timeline and
   order them. For long reels (20+ clips), that's real work.

2. **Timeline metadata survives.** FCPXML carries clip names (with AI scores and tags),
   transitions (crossfade, dip to black), and ordering — all visible in FCP's timeline
   before the user edits anything. Individual files carry none of this.

3. **No disk duplication.** FCPXML references original source files on the NAS.
   Clip export creates new files — a 2-minute 4K HEVC reel at ~80 Mbps is ~1.2 GB
   of new data per export.

4. **The bugs may be close to fixed.** The FCPXML structure is architecturally sound.
   The test files (A/B/C) in `test_artifacts/` should reveal the exact issue. It may
   be one attribute change away from working.

5. **Industry standard.** FCPXML is the interchange format between NLEs. Building it
   correctly is worth the investment if the pipeline is meant to be used professionally.

---

## Recommendation for the Next Agent

### Option A — Clip Export (Recommended for Immediate Use)

Implement clip export as a **parallel export path** alongside (not replacing) FCPXML.
Add a "Download Clips" button on the highlight editor that triggers a Celery task,
runs ffmpeg cuts, zips the results, and returns a download link.

This unblocks the user immediately and doesn't delete any existing FCPXML work.

### Option B — Fix FCPXML First

Run the three test files in `test_artifacts/` through FCP, determine which XML
structure it accepts, apply that fix to `fcpxml.py`, and verify end-to-end.
If test C (`FFVideoFormat4K2997`, 29.97fps sequence) works and A/B don't, the fix
is to update `get_supported_sequence_fps()` to fall back to 29.97fps instead of 59.94.

### Option C — Both (Best Long-Term)

Fix FCPXML (for the assembled timeline workflow) AND add clip export (for universal
compatibility). They serve different use cases and can coexist.

---

## Implementation Plan — Clip Export

### Step 1 — New file: `app/export/clip_export.py`

```python
import os
import subprocess
import zipfile
import logging

logger = logging.getLogger(__name__)


def export_clips_as_files(
    clips_data: list[dict],  # [{"clip": Clip, "video": Video}, ...]
    output_dir: str,
    reel_name: str = "highlight_reel",
) -> list[str]:
    """Cut each clip from its source video using ffmpeg stream copy.
    Returns list of output file paths (skips failures)."""
    os.makedirs(output_dir, exist_ok=True)
    output_paths = []

    for idx, cd in enumerate(clips_data):
        clip = cd["clip"]
        video = cd["video"]

        tags = ""
        if clip.tags:
            tags = "_".join(t.get("tag", "") for t in clip.tags[:2])
            tags = "_" + tags.replace(" ", "-")[:30]

        filename = f"{idx+1:02d}{tags}_score{clip.effective_score:.0f}.mp4"
        output_path = os.path.join(output_dir, filename)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip.start_sec),
            "-i", video.filepath,
            "-t", str(clip.duration_sec),
            "-c", "copy",
            "-map", "0:v:0",
            "-map", "0:a:0",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"ffmpeg failed for clip {clip.id}: {result.stderr.decode()}")
            continue

        output_paths.append(output_path)
        logger.info(f"Exported {idx+1}/{len(clips_data)}: {filename}")

    return output_paths


def zip_clip_exports(output_paths: list[str], zip_path: str) -> str:
    """Zip exported clip files. Uses ZIP_STORED (no compression — video is already compressed)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for path in output_paths:
            zf.write(path, os.path.basename(path))
    return zip_path
```

### Step 2 — New Celery task in `app/pipeline/orchestrator.py`

```python
@celery_app.task(name="export_highlight_clips", bind=True)
def export_highlight_clips(self, highlight_id: str) -> dict:
    from app.export.clip_export import export_clips_as_files, zip_clip_exports
    from app.models.highlight import Highlight
    from app.models.clip import Clip
    from app.models.video import Video

    db = next(get_db())
    highlight = db.query(Highlight).filter_by(id=highlight_id).first()
    clips = [db.query(Clip).get(cid) for cid in (highlight.clip_ids or [])]
    clips = [c for c in clips if c]
    video_ids = {c.video_id for c in clips}
    videos = {v.id: v for v in db.query(Video).filter(Video.id.in_(video_ids)).all()}

    clips_data = [{"clip": c, "video": videos[c.video_id]} for c in clips if c.video_id in videos]

    output_dir = f"/app/exports/{highlight_id}"
    output_paths = export_clips_as_files(clips_data, output_dir, highlight.name or "reel")

    zip_name = (highlight.name or "highlight_reel").replace(" ", "_") + ".zip"
    zip_path = os.path.join(output_dir, zip_name)
    zip_clip_exports(output_paths, zip_path)

    return {"zip_path": zip_path, "clip_count": len(output_paths), "zip_name": zip_name}
```

### Step 3 — New API endpoints in `app/api/routes_highlights.py`

```python
@router.post("/{highlight_id}/export-clips")
def trigger_clip_export(highlight_id: str, db: Session = Depends(get_db)):
    highlight = db.query(Highlight).filter_by(id=highlight_id).first()
    if not highlight:
        raise HTTPException(404)
    task = export_highlight_clips.delay(highlight_id)
    return {"task_id": task.id}

@router.get("/{highlight_id}/export-clips/{task_id}/status")
def clip_export_status(highlight_id: str, task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "SUCCESS":
        return {"status": "done", "zip_name": result.result["zip_name"]}
    elif result.state == "FAILURE":
        return {"status": "error"}
    return {"status": "pending"}

@router.get("/{highlight_id}/export-clips/download")
def download_clips(highlight_id: str):
    import glob
    matches = glob.glob(f"/app/exports/{highlight_id}/*.zip")
    if not matches:
        raise HTTPException(404, "No export found — trigger export first")
    zip_path = matches[0]
    return FileResponse(zip_path, media_type="application/zip",
                        filename=os.path.basename(zip_path))
```

### Step 4 — UI in `app/templates/highlight_editor.html`

Add alongside the existing "Export FCPXML" button:

```html
<button id="exportClipsBtn" onclick="exportClips()">Download Clips (.zip)</button>

<script>
async function exportClips() {
  const btn = document.getElementById('exportClipsBtn');
  btn.disabled = true;
  btn.textContent = 'Exporting...';
  const r = await fetch(`/api/highlights/{{ highlight.id }}/export-clips`, {method: 'POST'});
  const {task_id} = await r.json();
  const poll = setInterval(async () => {
    const s = await fetch(`/api/highlights/{{ highlight.id }}/export-clips/${task_id}/status`);
    const {status, zip_name} = await s.json();
    if (status === 'done') {
      clearInterval(poll);
      btn.textContent = 'Download Clips (.zip)';
      btn.disabled = false;
      window.location = `/api/highlights/{{ highlight.id }}/export-clips/download`;
    } else if (status === 'error') {
      clearInterval(poll);
      btn.textContent = 'Export failed';
    }
  }, 2000);
}
</script>
```

---

## Key Technical Notes

- **Keyframe alignment**: `-ss` before `-i` snaps to the nearest keyframe. For GoPro
  footage (keyframes every ~0.5–1s at 119.88fps), cuts may be up to ~1s from the exact
  `start_sec`. Acceptable for FCP import — user trims there anyway. For frame-exact
  cuts, move `-ss` after `-i`, but this forces a full decode/re-encode (slow, lossy).

- **Disk space**: Export files live in `/app/exports/{highlight_id}/` inside the
  container. Ensure the docker volume has space. Add a cleanup job (cron or on job
  deletion) to remove exports older than 24h.

- **Audio**: GoPro files typically have 1 stereo track. `-map 0:a:0` is safe. Using
  `-map 0` would include GoPro telemetry streams, which may confuse some players.

- **Worker restart required** after adding the new Celery task:
  `docker compose restart worker`

- **No migrations needed.** No schema changes.

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `app/export/clip_export.py` | Create — ffmpeg cut + zip logic |
| `app/pipeline/orchestrator.py` | Add Celery task `export_highlight_clips` |
| `app/api/routes_highlights.py` | Add 3 endpoints (trigger, status, download) |
| `app/templates/highlight_editor.html` | Add "Download Clips" button + JS polling |
