"""FCPXML 1.11 builder - generates Final Cut Pro / DaVinci Resolve compatible timelines."""

import logging
from lxml import etree

logger = logging.getLogger(__name__)


# ================================================================
# FCPX-SUPPORTED SEQUENCE FORMATS
# ================================================================

FCPX_SEQUENCE_FORMATS = {
    # 1080p formats
    (1920, 1080): {
        23.976: "FFVideoFormat1080p2398",
        24.0:   "FFVideoFormat1080p24",
        25.0:   "FFVideoFormat1080p25",
        29.97:  "FFVideoFormat1080p2997",
        30.0:   "FFVideoFormat1080p30",
        50.0:   "FFVideoFormat1080p50",
        59.94:  "FFVideoFormat1080p5994",
        60.0:   "FFVideoFormat1080p60",
    },
    # 4K UHD formats
    (3840, 2160): {
        23.976: "FFVideoFormat4K2398",
        24.0:   "FFVideoFormat4K24",
        25.0:   "FFVideoFormat4K25",
        29.97:  "FFVideoFormat4K2997",
        30.0:   "FFVideoFormat4K30",
        50.0:   "FFVideoFormat4K50",
        59.94:  "FFVideoFormat4K5994",
        60.0:   "FFVideoFormat4K60",
    },
    # 720p formats
    (1280, 720): {
        23.976: "FFVideoFormat720p2398",
        24.0:   "FFVideoFormat720p24",
        25.0:   "FFVideoFormat720p25",
        29.97:  "FFVideoFormat720p2997",
        30.0:   "FFVideoFormat720p30",
        50.0:   "FFVideoFormat720p50",
        59.94:  "FFVideoFormat720p5994",
        60.0:   "FFVideoFormat720p60",
    },
    # 5K formats
    (5120, 2880): {
        23.976: "FFVideoFormat5K2398",
        24.0:   "FFVideoFormat5K24",
        25.0:   "FFVideoFormat5K25",
        29.97:  "FFVideoFormat5K2997",
        30.0:   "FFVideoFormat5K30",
        50.0:   "FFVideoFormat5K50",
        59.94:  "FFVideoFormat5K5994",
        60.0:   "FFVideoFormat5K60",
    },
}

MAX_SEQUENCE_FPS = 60.0


def get_supported_sequence_fps(source_fps: float) -> float:
    """Return the closest FCPX-supported sequence frame rate.

    FCPX does NOT support frame rates > 60fps for sequences.
    For 119.88fps GoPro footage, use 59.94fps sequence.
    """
    standard_rates = [23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0]
    if source_fps <= MAX_SEQUENCE_FPS:
        closest = min(standard_rates, key=lambda x: abs(x - source_fps))
        if abs(closest - source_fps) < 0.5:
            return closest
        return source_fps
    # For high frame rates (>60fps), downconvert to 59.94fps
    return 59.94


def get_sequence_format_name(width: int, height: int, fps: float) -> str:
    """Return the FCPX format name for a resolution/fps combo, or a fallback."""
    resolution_key = (width, height)
    formats = FCPX_SEQUENCE_FORMATS.get(resolution_key)
    if formats:
        for supported_fps, format_name in formats.items():
            if abs(fps - supported_fps) < 0.01:
                return format_name
        # Unknown fps for known resolution — fall back to 59.94
        return formats[59.94]
    # Unknown resolution — return None so the caller omits the name attribute
    return None


def get_timebase(fps: float) -> int:
    """Return the timebase denominator for a given frame rate."""
    if abs(fps - 23.976) < 0.01:
        return 24000
    elif abs(fps - 29.97) < 0.01:
        return 30000
    elif abs(fps - 59.94) < 0.01:
        return 60000
    else:
        return int(round(fps))


def get_ticks_per_frame(fps: float) -> int:
    """Return ticks per frame (1001 for NTSC drop-frame rates, 1 otherwise)."""
    if abs(fps - 23.976) < 0.01 or abs(fps - 29.97) < 0.01 or abs(fps - 59.94) < 0.01:
        return 1001
    return 1


def get_exact_fps(fps: float) -> float:
    """Return the exact fractional frame rate for NTSC rates."""
    if abs(fps - 23.976) < 0.01:
        return 24000 / 1001
    elif abs(fps - 29.97) < 0.01:
        return 30000 / 1001
    elif abs(fps - 59.94) < 0.01:
        return 60000 / 1001
    return fps


def seconds_to_rational(seconds: float, fps: float) -> str:
    """Convert seconds to a frame-aligned FCPXML rational time string."""
    timebase = get_timebase(fps)
    ticks_per_frame = get_ticks_per_frame(fps)
    exact_fps = get_exact_fps(fps)
    frames = int(round(seconds * exact_fps))
    ticks = frames * ticks_per_frame
    return f"{ticks}/{timebase}s"


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
        root = etree.Element("fcpxml", version="1.11")
        resources = etree.SubElement(root, "resources")

        video_assets = {}  # video_id -> asset_id
        _res_counter = 0

        def next_rid():
            nonlocal _res_counter
            rid = f"r{_res_counter}"
            _res_counter += 1
            return rid

        # Determine sequence fps (downconvert >60fps sources for FCPX compatibility)
        first_video = clips_data[0].get("video") if clips_data else None
        source_fps = first_video.fps if first_video else 30.0
        sequence_fps = get_supported_sequence_fps(source_fps)
        logger.info(f"Source FPS: {source_fps}, Sequence FPS: {sequence_fps}")

        # Get resolution from first video
        width, height = 1920, 1080
        if first_video and first_video.resolution and "x" in first_video.resolution:
            parts = first_video.resolution.split("x")
            try:
                width, height = int(parts[0]), int(parts[1])
            except ValueError:
                pass

        sequence_timebase = get_timebase(sequence_fps)
        sequence_ticks_per_frame = get_ticks_per_frame(sequence_fps)
        sequence_exact_fps = get_exact_fps(sequence_fps)

        # CRITICAL: sequence format goes FIRST in <resources> and all assets reference it.
        # FCP rejects a sequence whose format is not declared before assets or is unused.
        sequence_format_id = next_rid()
        sequence_format_name = get_sequence_format_name(width, height, sequence_fps)
        fmt_attribs = {
            "id": sequence_format_id,
            "width": str(width),
            "height": str(height),
            "frameDuration": seconds_to_rational(1.0 / sequence_fps, sequence_fps),
        }
        if sequence_format_name:
            fmt_attribs["name"] = sequence_format_name
        etree.SubElement(resources, "format", **fmt_attribs)

        # Emit <asset> resources — all referencing the sequence format
        for i, cd in enumerate(clips_data):
            video = cd.get("video")
            if not video or video.id in video_assets:
                continue

            asset_id = next_rid()
            video_assets[video.id] = asset_id

            duration_rational = seconds_to_rational(video.duration_sec or 0, sequence_fps)
            asset = etree.SubElement(resources, "asset",
                id=asset_id,
                name=video.filename if video.filename else f"Asset {i+1}",
                start="0/1s",
                duration=duration_rational,
                hasVideo="1",
                hasAudio="1",
                format=sequence_format_id,
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

        total_duration = sum(cd["clip"].duration_sec for cd in clips_data if cd.get("clip"))

        sequence = etree.SubElement(project, "sequence",
            duration=seconds_to_rational(total_duration, sequence_fps),
            format=sequence_format_id,
            tcStart="0/1s",
            tcFormat="NDF",
        )

        spine = etree.SubElement(sequence, "spine")

        # --- Add clips to spine ---
        timeline_offset_frames = 0

        for idx, cd in enumerate(clips_data):
            clip = cd.get("clip")
            video = cd.get("video")
            if not clip or not video:
                continue

            asset_id = video_assets.get(video.id)

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
                trans_frames = int(round(self.transition_duration_sec * sequence_exact_fps))
                trans_ticks = trans_frames * sequence_ticks_per_frame
                trans_dur = f"{trans_ticks}/{sequence_timebase}s"

                if self.transition_type == "crossfade":
                    etree.SubElement(spine, "transition",
                        name="Cross Dissolve",
                        duration=trans_dur,
                    )
                elif self.transition_type == "dip_to_black":
                    etree.SubElement(spine, "transition",
                        name="Dip to Black",
                        duration=trans_dur,
                    )

            # Calculate in FRAMES first for alignment, then convert to ticks
            clip_duration_frames = int(round(clip.duration_sec * sequence_exact_fps))
            offset_frames = timeline_offset_frames
            start_frames = int(round(clip.start_sec * sequence_exact_fps))

            offset_ticks = offset_frames * sequence_ticks_per_frame
            duration_ticks = clip_duration_frames * sequence_ticks_per_frame
            start_ticks = start_frames * sequence_ticks_per_frame

            etree.SubElement(spine, "asset-clip",
                ref=asset_id,
                offset=f"{offset_ticks}/{sequence_timebase}s",
                name=clip_name,
                start=f"{start_ticks}/{sequence_timebase}s",
                duration=f"{duration_ticks}/{sequence_timebase}s",
                tcFormat="NDF",
            )

            timeline_offset_frames += clip_duration_frames

        # Generate XML string
        doctype = '<!DOCTYPE fcpxml>'
        xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>'
        xml_body = etree.tostring(root, pretty_print=True, encoding="unicode")

        return f"{xml_declaration}\n{doctype}\n{xml_body}"
