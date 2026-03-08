"""FCPXML 1.11 builder — generates Final Cut Pro / DaVinci Resolve compatible timelines."""

import math
import logging
from typing import Optional
from lxml import etree

logger = logging.getLogger(__name__)


def _seconds_to_rational(seconds: float, fps: float = 30.0) -> str:
    """Convert seconds to FCPXML rational time format.

    Frame-accurate timecodes: e.g., 83291/24000s for 24fps content.
    """
    if fps <= 0:
        fps = 30.0

    # Common frame rate bases
    if abs(fps - 23.976) < 0.01:
        timebase = 24000
        frame_dur = 1001
    elif abs(fps - 29.97) < 0.01:
        timebase = 30000
        frame_dur = 1001
    elif abs(fps - 59.94) < 0.01:
        timebase = 60000
        frame_dur = 1001
    elif abs(fps - 119.88) < 0.01:
        timebase = 120000
        frame_dur = 1001
    else:
        # Integer frame rates
        timebase = int(fps) * 1000
        frame_dur = 1000

    total_frames = int(round(seconds * fps))
    ticks = total_frames * frame_dur

    return f"{ticks}/{timebase}s"


def _fps_code(fps: float) -> str:
    """Return FCP-style fps code (e.g. 2997, 5994, 11988, 30)."""
    if abs(fps - int(fps)) < 0.01:
        return str(int(fps))
    return f"{fps:.2f}".replace(".", "")


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
                fmt_name = f"FFVideoFormat{width}x{height}p{_fps_code(fps)}"
                etree.SubElement(resources, "format",
                    id=fmt_id,
                    name=fmt_name,
                    width=str(width),
                    height=str(height),
                    frameDuration=_seconds_to_rational(1.0 / fps, fps),
                )

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

        sequence = etree.SubElement(project, "sequence",
            duration=_seconds_to_rational(total_duration, primary_fps),
            format=primary_format,
            tcStart="0/1s",
            tcFormat="NDF",
        )

        spine = etree.SubElement(sequence, "spine")

        # --- Add clips to spine ---
        timeline_offset = 0.0

        for idx, cd in enumerate(clips_data):
            clip = cd.get("clip")
            video = cd.get("video")
            if not clip or not video:
                continue

            asset_id = video_assets.get(video.id, "r1")
            fps = video.fps or 30.0

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
                trans_dur = _seconds_to_rational(self.transition_duration_sec, fps)

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

            # Add asset-clip
            asset_clip = etree.SubElement(spine, "asset-clip",
                ref=asset_id,
                offset=_seconds_to_rational(timeline_offset, fps),
                name=clip_name,
                start=_seconds_to_rational(clip.start_sec, fps),
                duration=_seconds_to_rational(clip.duration_sec, fps),
                tcFormat="NDF",
            )

            timeline_offset += clip.duration_sec

        # Generate XML string
        doctype = '<!DOCTYPE fcpxml>'
        xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>'
        xml_body = etree.tostring(root, pretty_print=True, encoding="unicode")

        return f"{xml_declaration}\n{doctype}\n{xml_body}"
