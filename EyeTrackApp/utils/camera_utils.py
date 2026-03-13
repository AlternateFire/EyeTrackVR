"""
Enumerate available webcams for the world camera dropdown.
Uses ffmpeg for human-readable names when available, OpenCV as fallback.
"""

import re
import subprocess
import sys
from typing import List, Tuple

try:
    import cv2
except ImportError:
    cv2 = None


def list_available_cameras() -> List[Tuple[str, str]]:
    """
    Return list of (display_name, source_value) for available cameras.
    display_name: shown in dropdown (e.g. "Logitech Webcam C930e (1)")
    source_value: passed to VideoCapture (e.g. "1" or "Logitech Webcam C930e" on Windows)
    First item is always ("Disabled", "").
    """
    results: List[Tuple[str, str]] = [("Disabled", "")]

    # Try ffmpeg first for nice names
    ffmpeg_cameras = _list_cameras_ffmpeg()
    if ffmpeg_cameras:
        results.extend(ffmpeg_cameras)
        return results

    # Fallback: OpenCV probe (no names, just indices)
    opencv_cameras = _list_cameras_opencv()
    results.extend(opencv_cameras)
    return results


def _list_cameras_ffmpeg() -> List[Tuple[str, str]]:
    """Use ffmpeg to list cameras with names. Returns empty list if ffmpeg unavailable."""
    cameras: List[Tuple[str, str]] = []
    try:
        if sys.platform == "darwin":
            cameras = _parse_avfoundation()
        elif sys.platform == "win32":
            cameras = _parse_dshow()
        else:
            # Linux: ffmpeg formats vary, use OpenCV fallback
            cameras = _list_cameras_opencv()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return cameras


def _parse_avfoundation() -> List[Tuple[str, str]]:
    """Parse ffmpeg -f avfoundation -list_devices (macOS). Video devices only."""
    cameras: List[Tuple[str, str]] = []
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=5,
        )
        stderr = result.stderr or ""
        # Format: [AVFoundation indev @ 0x...] [0] FaceTime HD Camera
        # Stop at "AVFoundation audio devices" - we only want video
        pattern = re.compile(r"\[\s*(\d+)\s*\]\s+(.+)")
        in_video = False
        for line in stderr.splitlines():
            if "AVFoundation video devices" in line:
                in_video = True
                continue
            if "AVFoundation audio devices" in line:
                break
            if in_video:
                match = pattern.search(line)
                if match:
                    idx, name = match.groups()
                    name = name.strip()
                    display = f"{name} ({idx})"
                    cameras.append((display, idx))
    except Exception:
        pass
    return cameras


def _parse_dshow() -> List[Tuple[str, str]]:
    """Parse ffmpeg -f dshow -list_devices (Windows). Uses indices for OpenCV compatibility."""
    cameras: List[Tuple[str, str]] = []
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "dshow", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=5,
        )
        stderr = result.stderr or ""
        # Format: "Integrated Camera" or "Logitech Webcam C930e" - in enumeration order
        in_video = False
        idx = 0
        for line in stderr.splitlines():
            if "DirectShow video devices" in line:
                in_video = True
                continue
            if in_video and "DirectShow audio" in line:
                break
            if in_video:
                match = re.search(r'"([^"]+)"', line)
                if match:
                    name = match.group(1)
                    cameras.append((f"{name} ({idx})", str(idx)))
                    idx += 1
    except Exception:
        pass
    return cameras


def _list_cameras_opencv() -> List[Tuple[str, str]]:
    """Probe indices 0-9 with OpenCV. No names, just Camera 0, Camera 1, etc."""
    if cv2 is None:
        return []
    cameras: List[Tuple[str, str]] = []
    for i in range(10):
        cap = cv2.VideoCapture(i)
        try:
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    cameras.append((f"Camera {i}", str(i)))
        except Exception:
            pass
        finally:
            cap.release()
    return cameras
