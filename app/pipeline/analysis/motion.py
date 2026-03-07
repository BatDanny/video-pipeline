"""OpenCV motion analysis module — compute motion intensity and camera dynamics.

Analyzes optical flow and frame differences to score clips by motion intensity.
High motion = action shots (snowboarding, biking). Low motion = scenic/static shots.
Also detects camera shake vs smooth motion for quality assessment.
"""

import os
import logging
import subprocess
import tempfile
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _extract_frames_cv2(video_path: str, start_sec: float, duration_sec: float,
                         target_fps: float = 5.0) -> list:
    """Extract frames using OpenCV at a reduced framerate for analysis."""
    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV not available for motion analysis")
        return []

    frames = []
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        logger.error(f"Cannot open video: {video_path}")
        return []

    try:
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = int(start_sec * source_fps)
        total_frames = int(duration_sec * source_fps)
        sample_interval = max(1, int(source_fps / target_fps))

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        frame_count = 0
        while frame_count < total_frames:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_count % sample_interval == 0:
                # Resize for faster processing
                small = cv2.resize(frame, (320, 180))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                frames.append(gray)

            frame_count += 1

            # Cap at 100 frames for analysis
            if len(frames) >= 100:
                break

    finally:
        cap.release()

    return frames


def analyze_motion(video_path: str, start_sec: float, end_sec: float) -> dict:
    """Analyze motion characteristics of a clip segment.

    Returns:
        Dict with:
        - motion_score: 0.0 (static) to 1.0 (extreme motion)
        - camera_shake: 0.0 (smooth) to 1.0 (very shaky)
        - dominant_motion: 'static', 'slow', 'moderate', 'fast', 'extreme'
        - motion_variance: how much motion changes (high = dynamic action)
        - audio_energy: estimated from frame analysis (placeholder for actual audio)
    """
    duration = end_sec - start_sec
    frames = _extract_frames_cv2(video_path, start_sec, duration)

    if len(frames) < 3:
        return {
            'motion_score': 0.5,
            'camera_shake': 0.0,
            'dominant_motion': 'unknown',
            'motion_variance': 0.0,
            'audio_energy': 0.5,
        }

    try:
        import cv2

        # --- Optical Flow Analysis ---
        flow_magnitudes = []
        flow_angles = []

        for i in range(1, len(frames)):
            flow = cv2.calcOpticalFlowFarneback(
                frames[i - 1], frames[i],
                None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2,
                flags=0
            )

            # Compute magnitude and angle
            mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])

            # Average magnitude across frame (normalized by frame size)
            avg_mag = np.mean(mag)
            flow_magnitudes.append(avg_mag)

            # Dominant direction
            flow_angles.append(np.mean(ang))

        flow_magnitudes = np.array(flow_magnitudes)

        # --- Motion Score ---
        # Normalize: typical GoPro action footage has avg magnitude 2-15
        avg_motion = np.mean(flow_magnitudes)
        motion_score = min(1.0, avg_motion / 12.0)

        # --- Camera Shake Detection ---
        # High frequency oscillation in flow direction = shake
        if len(flow_angles) > 2:
            angle_diffs = np.diff(flow_angles)
            shake_metric = np.std(angle_diffs)
            camera_shake = min(1.0, shake_metric / 1.5)
        else:
            camera_shake = 0.0

        # --- Motion Variance ---
        # High variance = dynamic action (accelerating/decelerating)
        motion_variance = float(np.std(flow_magnitudes) / (np.mean(flow_magnitudes) + 1e-6))
        motion_variance = min(1.0, motion_variance)

        # --- Frame Difference (complementary to optical flow) ---
        frame_diffs = []
        for i in range(1, len(frames)):
            diff = cv2.absdiff(frames[i - 1], frames[i])
            frame_diffs.append(np.mean(diff))

        avg_diff = np.mean(frame_diffs) if frame_diffs else 0
        # Normalize: typical range 5-40
        diff_score = min(1.0, avg_diff / 30.0)

        # --- Combine into final motion score ---
        # Weighted blend of optical flow and frame difference
        combined_motion = 0.7 * motion_score + 0.3 * diff_score

        # --- Classify dominant motion ---
        if combined_motion < 0.15:
            dominant = 'static'
        elif combined_motion < 0.35:
            dominant = 'slow'
        elif combined_motion < 0.60:
            dominant = 'moderate'
        elif combined_motion < 0.80:
            dominant = 'fast'
        else:
            dominant = 'extreme'

        # --- Audio energy estimate (from visual dynamics as proxy) ---
        # Real audio energy would come from analyzing the audio stream
        audio_energy = min(1.0, combined_motion * 1.2 + 0.1)

        return {
            'motion_score': round(float(combined_motion), 4),
            'camera_shake': round(float(camera_shake), 4),
            'dominant_motion': dominant,
            'motion_variance': round(float(motion_variance), 4),
            'audio_energy': round(float(audio_energy), 4),
        }

    except Exception as e:
        logger.error(f"Motion analysis error: {e}")
        return {
            'motion_score': 0.5,
            'camera_shake': 0.0,
            'dominant_motion': 'unknown',
            'motion_variance': 0.0,
            'audio_energy': 0.5,
        }


def analyze_motion_for_job(job_id: str, progress_callback=None):
    """Run motion analysis on all clips in a job. Called by the orchestrator."""
    from app.models.database import get_session_factory
    from app.models.clip import Clip
    from app.models.video import Video

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        logger.info(f"Running motion analysis on {len(clips)} clips for job {job_id}")

        total = len(clips)
        for i, clip in enumerate(clips):
            if progress_callback:
                pct = 65.0 + (9.0 * (i + 1) / total)  # motion = 65% to 74%
                progress_callback({
                    "stage": "analyzing",
                    "sub_stage": "motion",
                    "message": f"Analyzing motion in clip {i + 1}/{total}...",
                    "progress_pct": round(pct, 1),
                    "file_progress_pct": ((i + 1) / total) * 100,
                    "file_name": f"Clip {i + 1}/{total}"
                })

            video = db.query(Video).filter(Video.id == clip.video_id).first()
            if not video:
                continue

            result = analyze_motion(video.filepath, clip.start_sec, clip.end_sec)

            clip.motion_score = result['motion_score']
            clip.audio_energy = result['audio_energy']

            logger.debug(
                f"Clip {clip.id[:8]}: motion={result['motion_score']:.2f} "
                f"({result['dominant_motion']}), shake={result['camera_shake']:.2f}"
            )

        db.commit()
        logger.info(f"Motion analysis complete for job {job_id}")

    finally:
        db.close()
