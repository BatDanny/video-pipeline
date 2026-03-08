"""FCPXML 1.11 builder — generates Final Cut Pro / DaVinci Resolve compatible timelines."""

import math
import logging
from typing import Optional
from lxml import etree

logger = logging.getLogger(__name__)


def _get_timebase(fps: float) -> int:
    """Get the timebase denominator for a given frame rate.
    
    This is used for rational time calculations.
    """
    if abs(fps - 23.976) < 0.01:
        return 24000
    elif abs(fps - 29.97) < 0.01:
        return 30000
    elif abs(fps - 59.94) < 0.01:
        return 60000
    elif abs(fps - 119.88) < 0.01:
        return 120000
    else:
        return int(round(fps))


def _get_ticks_per_frame(fps: float) -> int:
    """Get ticks per frame for frame alignment.
    
    For NTSC frame rates, each frame is 1001 ticks.
    For integer frame rates, each frame is 1 tick.
    """
    if abs(fps - 23.976) < 0.01:
        return 1001
    elif abs(fps - 29.97) < 0.01:
        return 1001
    elif abs(fps - 59.94) < 0.01:
        return 1001
    elif abs(fps - 119.88) < 0.01:
        return 1001
    else:
        return 1


def _get_exact_fps(fps: float) -> float:
    """Get the exact frame rate value for calculations.
    
    NTSC frame rates are actually X/1001 Hz, not the rounded values.
    """
    if abs(fps - 23.976) < 0.01:
        return 24000 / 1001  # 23.976023...
    elif abs(fps - 29.97) < 0.01:
        return 30000 / 1001  # 29.970029...
    elif abs(fps - 59.94) < 0.01:
        return 60000 / 1001  # 59.940059...
    elif abs(fps - 119.88) < 0.01:
        return 120000 / 1001  # 119.880119...
    else:
        return fps


def _seconds_to_rational(seconds: float, fps: float = 30.0) -> str:
    """Convert seconds to FCPXML rational time format with FRAME ALIGNMENT.

    CRITICAL: All tick values must be aligned to frame boundaries.
    For NTSC frame rates, this means ticks must be multiples of 1001.
    
    The formula is:
    1. Convert seconds to FRAMES (round to nearest frame)
    2. Multiply frames by ticks_per_frame (1001 for NTSC, 1 for integer fps)
    """
    if fps <= 0:
        fps = 30.0

    timebase = _get_timebase(fps)
    ticks_per_frame = _get_ticks_per_frame(fps)
    exact_fps = _get_exact_fps(fps)

    # STEP 1: Calculate total frames (round to nearest frame)
    total_frames = int(round(seconds * exact_fps))
    
    # STEP 2: Convert frames to ticks (this ensures frame alignment)
    ticks = total_frames * ticks_per_frame

    return f"{ticks}/{timebase}s"


def _fps_code(fps: float) -> str:
    """Return FCP-style fps code (e.g. 2997, 5994, 11988, 30)."""
    if abs(fps - int(fps)) < 0.01:
        return str(int(fps))
    return f"{fps:.2f}".replace(".", "")


def _get_format_name(width: int, height: int, fps: float) -> Optional[str]:
    """Generate FCPX-compatible format name.

    FCPX recognizes specific format name patterns:
    - FFVideoFormat1080p{fps} for 1920x1080
    - FFVideoFormat720p{fps} for 1280x720
    - FFVideoFormat4K{fps} for 3840x2160
    - FFVideoFormat5K{fps} for 5120x2880

    DO NOT use format names like "FFVideoFormat3840x2160p11988".
    If the FPS is higher than 60, we omit the predefined name entirely,
    forcing Final Cut Pro to create a custom format that won't fail DTD validation.
    """
    if fps > 60.01:
        return None

    fps_code = _fps_code(fps)

    if height == 1080 and width == 1920:
        return f"FFVideoFormat1080p{fps_code}"
    elif height == 2160 and width == 3840:
        return f"FFVideoFormat4K{fps_code}"
    elif height == 720 and width == 1280:
        return f"FFVideoFormat720p{fps_code}"
    elif height == 2880 and width == 5120:
        return f"FFVideoFormat5K{fps_code}"
    else:
        # For non-standard resolutions, don't use FFVideoFormat prefix
        return None


class FCPXMLBuilder:
    """Build FCPXML 1.11 documents for Final Cut Pro and DaVinci Resolve."""

    def __init__(
        self,
        reel_name: str = "Highlight Reel",
        job_name: str = "AI Highlights",
        transition_type: str = "cut",
        transition_duration_sec: float = 0.5,
    ):
        self.reel_name = reel_name
        self.job_name = job_name
        self.transition_type = transition_type
        self.transition_duration_sec = transition_duration_sec

    def build(self, clips_data: list[dict]) -> str:
        """Build the FCPXML document.

        Args:
            clips_data: List of dicts with 'clip' (Clip ORM) and 'video' (Video ORM)

        Returns:
            FCPXML XML string
        """
        root = etree.Element("fcpxml", version="1.9")

        # --- Resources ---
        resources = etree.SubElement(root, "resources")

        # Track unique source videos and create asset/format resources.
        # All resources share one sequential counter (r1, r2, ...) — no collisions.
        video_assets = {}  # video_id -> asset_id
        format_ids = {}    # format_key -> format_id
        _res_counter = 0

        def _next_rid() -> str:
            nonlocal _res_counter
            _res_counter += 1
            return f"r{_res_counter}"

        # First pass: collect unique formats and emit <format> resources
        for cd in clips_data:
            video = cd.get("video")
            if not video:
                continue

            width, height = 1920, 1080
            if video.resolution and "x" in video.resolution:
                parts = video.resolution.split("x")
                try:
                    width, height = int(parts[0]), int(parts[1])
                except ValueError:
                    pass

            fps = video.fps or 30.0
            fmt_key = f"{width}x{height}@{fps}"

            if fmt_key not in format_ids:
                fmt_id = _next_rid()
                format_ids[fmt_key] = fmt_id
                fmt_name = _get_format_name(width, height, fps)
                attribs = {
                    "id": fmt_id,
                    "width": str(width),
                    "height": str(height),
                    "frameDuration": _seconds_to_rational(1.0 / fps, fps),
                }
                if fmt_name:
                    attribs["name"] = fmt_name
                    
                etree.SubElement(resources, "format", **attribs)

        # Second pass: emit <asset> resources
        for i, cd in enumerate(clips_data):
            video = cd.get("video")
            if not video or video.id in video_assets:
                continue

            asset_id = _next_rid()
            video_assets[video.id] = asset_id

            width, height = 1920, 1080
            if video.resolution and "x" in video.resolution:
                parts = video.resolution.split("x")
                try:
                    width, height = int(parts[0]), int(parts[1])
                except ValueError:
                    pass

            fps = video.fps or 30.0
            fmt_key = f"{width}x{height}@{fps}"

            duration_rational = _seconds_to_rational(video.duration_sec or 0, fps)
            asset = etree.SubElement(resources, "asset",
                id=asset_id,
                name=video.filename if video.filename else f"Asset {i+1}",
                start="0/1s",
                duration=duration_rational,
                hasVideo="1",
                hasAudio="1",
                format=format_ids[fmt_key],
            )

            etree.SubElement(asset, "media-rep",
                kind="original-media",
                src=f"file://{video.filepath}",
            )

        # --- Library / Event / Project ---
        library = etree.SubElement(root, "library")
        event = etree.SubElement(library, "event",
            name=f"AI Highlights - {self.job_name}")
        project = etree.SubElement(event, "project",
            name=self.reel_name)

        # Calculate total duration
        total_duration = sum(cd["clip"].duration_sec for cd in clips_data if cd.get("clip"))

        # Determine primary format (from first clip)
        primary_format = list(format_ids.values())[0] if format_ids else "r1"
        primary_fps = clips_data[0]["video"].fps if clips_data and clips_data[0].get("video") else 30.0
        # FIX #2: Get primary timebase for all spine elements
        primary_timebase = _get_timebase(primary_fps)
        primary_ticks_per_frame = _get_ticks_per_frame(primary_fps)

        sequence = etree.SubElement(project, "sequence",
            duration=_seconds_to_rational(total_duration, primary_fps),
            format=primary_format,
            tcStart="0/1s",
            tcFormat="NDF",
        )

        spine = etree.SubElement(sequence, "spine")

        # --- Add clips to spine ---
        timeline_offset_frames = 0  # Track in FRAMES, not seconds

        for idx, cd in enumerate(clips_data):
            clip = cd.get("clip")
            video = cd.get("video")
            if not clip or not video:
                continue

            asset_id = video_assets.get(video.id, "r1")
            fps = video.fps or 30.0
            clip_timebase = _get_timebase(fps)
            clip_ticks_per_frame = _get_ticks_per_frame(fps)
            clip_exact_fps = _get_exact_fps(fps)

            # Build clip name with tags and score
            top_tags = ""
            if clip.tags:
                tag_names = [t.get("tag", "") for t in clip.tags[:3]]
                top_tags = ", ".join(tag_names)

            clip_name = f"Clip {idx + 1:02d}"
            if top_tags:
                clip_name += f" - {top_tags}"
            clip_name += f" (score: {clip.effective_score:.0f})"

            # Add transition before clip (if not first and not "cut")
            if idx > 0 and self.transition_type != "cut":
                trans_frames = int(round(self.transition_duration_sec * _get_exact_fps(primary_fps)))
                trans_ticks = trans_frames * primary_ticks_per_frame
                trans_dur = f"{trans_ticks}/{primary_timebase}s"

                if self.transition_type == "crossfade":
                    transition = etree.SubElement(spine, "transition",
                        name="Cross Dissolve",
                        duration=trans_dur,
                    )
                elif self.transition_type == "dip_to_black":
                    transition = etree.SubElement(spine, "transition",
                        name="Dip to Black",
                        duration=trans_dur,
                    )

            # FIX #2 & #3: Calculate in FRAMES first, then convert to ticks
            # This ensures frame alignment for ALL values
            
            # Clip duration in frames (primary sequence timebase)
            clip_duration_frames = int(round(clip.duration_sec * _get_exact_fps(primary_fps)))
            
            # Offset on timeline (already in frames)
            offset_frames = timeline_offset_frames
            
            # Start position in source asset (in clip's timebase)
            start_frames = int(round(clip.start_sec * clip_exact_fps))
            
            # Convert to ticks
            offset_ticks = offset_frames * primary_ticks_per_frame
            duration_ticks = clip_duration_frames * primary_ticks_per_frame
            start_ticks = start_frames * clip_ticks_per_frame

            asset_clip = etree.SubElement(spine, "asset-clip",
                ref=asset_id,
                offset=f"{offset_ticks}/{primary_timebase}s",  # PRIMARY timebase, frame-aligned
                name=clip_name,
                start=f"{start_ticks}/{clip_timebase}s",  # ASSET timebase, frame-aligned
                duration=f"{duration_ticks}/{primary_timebase}s",  # PRIMARY timebase, frame-aligned
                tcFormat="NDF",
            )

            # Update timeline offset (in frames)
            timeline_offset_frames += clip_duration_frames

        # Generate XML string
        doctype = '<!DOCTYPE fcpxml>'
        xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>'
        xml_body = etree.tostring(root, pretty_print=True, encoding="unicode")

        return f"{xml_declaration}\n{doctype}\n{xml_body}"
