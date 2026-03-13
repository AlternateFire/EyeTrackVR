"""
World camera video recorder. Records from an external webcam when Main recording is active.
Uses ffmpeg subprocess for capture + encoding - leverages hardware acceleration (VideoToolbox
on Mac, etc.) for smooth recording. Falls back to OpenCV if ffmpeg unavailable.
"""

import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import cv2
except ImportError:
    cv2 = None


def _parse_camera_source(source: str):
    """Parse camera source string to int index or str. Returns None if invalid/empty."""
    if not source or not str(source).strip():
        return None
    s = str(source).strip()
    try:
        return int(s)
    except ValueError:
        if s.startswith("http") or s.startswith("/dev") or ".mp4" in s:
            return s
        if " " in s:
            return s
        if len(s) > 5 and "http" not in s:
            return f"http://{s}/"
        return s


def _check_ffmpeg() -> bool:
    """Return True if ffmpeg is available."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=2,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


class VideoRecorder:
    """
    Records world camera footage. Uses ffmpeg subprocess (hardware encode) when available,
    else falls back to OpenCV (software encode).
    """

    def __init__(self, camera_source: str = "0"):
        self.camera_source_raw = camera_source
        self.camera_source = _parse_camera_source(camera_source)
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._opencv_recorder: Optional["_OpenCVRecorder"] = None
        self._lock = threading.Lock()
        self.is_recording = False
        self._main_recording_count = 0

    def notify_main_recording_started(self, session_folder: str) -> None:
        self._main_recording_count += 1
        if self._main_recording_count == 1:
            if not self.start_recording(session_folder):
                self._main_recording_count -= 1

    def notify_main_recording_stopped(self) -> None:
        if self._main_recording_count > 0:
            self._main_recording_count -= 1
        if self._main_recording_count == 0:
            self.stop_recording()

    def start_recording(self, session_folder: str) -> bool:
        if self.camera_source is None:
            return False

        with self._lock:
            if self.is_recording:
                return True

            Path(session_folder).mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

            success = False
            if _check_ffmpeg() and isinstance(self.camera_source, int) and sys.platform == "darwin":
                success = self._start_ffmpeg(session_folder, timestamp)
            if not success:
                # OpenCV fallback (Windows, no ffmpeg, or URL camera)
                success = self._start_opencv(session_folder, timestamp)

            if success:
                self.is_recording = True
                return True
            return False

    def _start_ffmpeg(self, session_folder: str, timestamp: str) -> bool:
        """Start ffmpeg subprocess - uses hardware encoding on Mac/Windows."""
        output_path = os.path.join(session_folder, f"{timestamp}_world_camera.mp4")

        if sys.platform == "darwin":
            # macOS: avfoundation + h264_videotoolbox (hardware) - uses camera index
            cmd = [
                "ffmpeg",
                "-y",
                "-f", "avfoundation",
                "-framerate", "30",
                "-i", str(self.camera_source),  # video device index
                "-c:v", "h264_videotoolbox",
                "-vf", "scale=1280:720",
                "-r", "24",
                output_path,
            ]
        else:
            # Windows/Linux: dshow/v4l2 need device names; use OpenCV fallback
            return False

        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # Brief check if it failed immediately
            time.sleep(0.3)
            if self._ffmpeg_process.poll() is not None:
                stderr = self._ffmpeg_process.stderr.read().decode() if self._ffmpeg_process.stderr else ""
                print(f"\033[91m[ERROR] ffmpeg failed: {stderr[:200]}\033[0m")
                return False
            print(f"\033[92m[INFO] World camera recording (ffmpeg) to {output_path}\033[0m")
            return True
        except Exception as e:
            print(f"\033[91m[ERROR] ffmpeg start failed: {e}\033[0m")
            return False

    def _start_opencv(self, session_folder: str, timestamp: str) -> bool:
        """Fallback: OpenCV capture + encode (no ffmpeg)."""
        if cv2 is None:
            print("\033[91m[ERROR] OpenCV not available for world camera fallback\033[0m")
            return False
        self._opencv_recorder = _OpenCVRecorder(self.camera_source)
        return self._opencv_recorder.start(session_folder, timestamp)

    def stop_recording(self) -> bool:
        with self._lock:
            if not self.is_recording:
                return True

            if self._ffmpeg_process is not None:
                try:
                    self._ffmpeg_process.terminate()
                    self._ffmpeg_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._ffmpeg_process.kill()
                except Exception:
                    pass
                self._ffmpeg_process = None

            if self._opencv_recorder is not None:
                self._opencv_recorder.stop()
                self._opencv_recorder = None

            self.is_recording = False
            print("\033[92m[INFO] World camera recording stopped\033[0m")
            return True

    def update_camera_source(self, source: str) -> None:
        self.camera_source_raw = source
        self.camera_source = _parse_camera_source(source)


class _OpenCVRecorder:
    """Fallback when ffmpeg unavailable - OpenCV capture + MJPEG encode."""

    TARGET_WIDTH = 1280
    TARGET_HEIGHT = 720
    RECORD_FPS = 24.0

    def __init__(self, camera_source):
        self.camera_source = camera_source
        self._capture_thread: Optional[threading.Thread] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._cancellation = threading.Event()
        self._frame_queue: queue.Queue = queue.Queue(maxsize=3)
        self._cv2_camera = None
        self._video_writer = None

    def start(self, session_folder: str, timestamp: str) -> bool:
        output_path = os.path.join(session_folder, f"{timestamp}_world_camera.avi")
        self._cv2_camera = cv2.VideoCapture()
        if not self._cv2_camera.open(self.camera_source):
            self._cv2_camera.release()
            return False
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self._video_writer = cv2.VideoWriter(
            output_path, fourcc, self.RECORD_FPS,
            (self.TARGET_WIDTH, self.TARGET_HEIGHT)
        )
        if not self._video_writer.isOpened():
            self._release()
            return False
        self._cancellation.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._capture_thread.start()
        self._writer_thread.start()
        print(f"\033[92m[INFO] World camera recording (OpenCV) to {output_path}\033[0m")
        return True

    def stop(self):
        self._cancellation.set()
        # Join capture first so it stops using the camera before we release
        for t in (self._capture_thread, self._writer_thread):
            if t and t.is_alive():
                t.join(timeout=2)
        # Release only after both threads have fully exited (avoids use-after-free segfault)
        self._release()

    def _release(self):
        if self._video_writer:
            try:
                self._video_writer.release()
            except Exception:
                pass
            self._video_writer = None
        if self._cv2_camera:
            try:
                self._cv2_camera.release()
            except Exception:
                pass
            self._cv2_camera = None

    def _capture_loop(self):
        while not self._cancellation.is_set() and self._cv2_camera:
            ret, frame = self._cv2_camera.read()
            if not ret or frame is None:
                time.sleep(0.005)
                continue
            small = cv2.resize(frame, (self.TARGET_WIDTH, self.TARGET_HEIGHT), interpolation=cv2.INTER_LINEAR)
            try:
                self._frame_queue.put_nowait(small)
            except queue.Full:
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._frame_queue.put_nowait(small)
                except queue.Full:
                    pass

    def _writer_loop(self):
        interval = 1.0 / self.RECORD_FPS
        last = 0.0
        while not self._cancellation.is_set() and self._video_writer:
            try:
                frame = self._frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            now = time.time()
            if now - last >= interval and frame is not None:
                try:
                    self._video_writer.write(frame)
                    last = now
                except Exception:
                    break
        # Do NOT call _release here - stop() does it after both threads join.
        # Releasing while capture_loop may still be in read() causes use-after-free segfault.
