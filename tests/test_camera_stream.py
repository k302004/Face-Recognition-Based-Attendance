"""Run with: python -m unittest discover -s tests -p test_camera_stream.py"""
import importlib.util
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch
from urllib.request import urlopen

import numpy as np

spec = importlib.util.spec_from_file_location(
    "camera_stream", Path(__file__).resolve().parents[1] / "scripts/camera_stream.py"
)
stream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stream)


class FakeCamera:
    def __init__(self):
        self.readers = set()
        self.released = False

    def read(self):
        self.readers.add(threading.get_ident())
        return True, np.zeros((120, 160, 3), dtype=np.uint8)

    def release(self):
        self.released = True


class PipelineTests(unittest.TestCase):
    def test_native_video_is_not_enlarged_but_recognition_keeps_its_analysis_resolution(self):
        native = np.zeros((480, 270, 3), dtype=np.uint8)
        self.assertIs(stream.resize_output(native, (720, 1280)), native)
        self.assertEqual(stream.resize_output(native, (135, 240)).shape, (240, 135, 3))
        rgb, sx, sy = stream.recognition_image(native)
        self.assertEqual(rgb.shape, (320, 180, 3))
        self.assertEqual((sx, sy), (1.5, 1.5))
        enlarged = np.zeros((1280, 720, 3), dtype=np.uint8)
        self.assertEqual(stream.recognition_image(enlarged)[0].shape, rgb.shape)

    def test_weak_or_ambiguous_face_matches_are_rejected(self):
        self.assertEqual(stream.select_face_match([0.44], ['A'], 0.40), (None, None))
        self.assertEqual(stream.select_face_match([0.32, 0.36], ['A', 'B'], 0.40), (None, None))
        self.assertEqual(stream.select_face_match([0.32, 0.33, 0.50], ['A', 'A', 'B'], 0.40), ('A', 0.32))

    def test_identity_requires_consecutive_matches_and_resets_on_unknown_or_multiple_faces(self):
        confirmation = stream.MatchConfirmation()
        self.assertIsNone(confirmation.update(['A'], 100))
        self.assertIsNone(confirmation.update(['A'], 100.25))
        self.assertEqual(confirmation.update(['A'], 100.5), 'A')
        self.assertIsNone(confirmation.update([None], 100.75))
        self.assertIsNone(confirmation.update(['A'], 101))
        self.assertIsNone(confirmation.update(['A', 'B'], 101.25))
        self.assertIsNone(confirmation.update(['B'], 101.5))
        self.assertIsNone(confirmation.update([], 102))

    def test_monitor_stream_survives_transient_status_timeout_but_stops_on_explicit_stop(self):
        server = SimpleNamespace(monitor_active=False)
        stream.update_monitor_gate(server, True, now=100)
        stream.update_monitor_gate(server, None, now=104)
        self.assertTrue(server.monitor_active)
        stream.update_monitor_gate(server, None, now=119)
        self.assertTrue(server.monitor_active)
        stream.update_monitor_gate(server, None, now=121)
        self.assertFalse(server.monitor_active)
        stream.update_monitor_gate(server, True, now=122)
        stream.update_monitor_gate(server, False, now=123)
        self.assertFalse(server.monitor_active)
        stream.update_monitor_gate(server, None, now=124)
        self.assertFalse(server.monitor_active)

    def test_snapshot_reuses_latest_encoded_frame_without_reading_camera(self):
        server = stream.ThreadingHTTPServer(('127.0.0.1', 0), stream.StreamHandler)
        from unittest.mock import Mock
        camera = Mock()
        server.camera = (camera, 0)
        server.pipeline = SimpleNamespace(condition=threading.Condition(), jpeg=b'\xff\xd8cached-frame')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/snapshot?test=1', timeout=2) as reply:
                self.assertEqual(reply.headers['Content-Type'], 'image/jpeg')
                self.assertEqual(reply.read(), b'\xff\xd8cached-frame')
            camera.read.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_duplicate_launch_does_not_open_the_camera(self):
        with patch.object(stream, 'parse_args', return_value=(1, 8090, 720, 1280)), \
                patch.object(stream, 'CameraHTTPServer', side_effect=OSError('port busy')), \
                patch.object(stream, 'open_camera') as camera:
            with self.assertRaises(SystemExit):
                stream.main()
        camera.assert_not_called()

    def test_native_face_calls_are_serialized_for_live_recognition_and_pose(self):
        calls = []

        def native_call(*args, **kwargs):
            calls.append(stream.FACE_ENGINE_LOCK.locked())
            return []

        engine = SimpleNamespace(face_locations=native_call, face_encodings=native_call)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        with patch.object(stream, 'FACE_RECOGNITION_AVAILABLE', True), \
                patch.object(stream, 'face_recognition', engine):
            stream.recognize_frame(frame, [], [])
            stream.detect_face_pose(frame)
        self.assertTrue(calls and all(calls))

    def test_saved_camera_overrides_legacy_startup_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'camera.config'
            config.write_text('{"id":"1"}', encoding='utf-8')
            with patch.object(stream, 'CAMERA_CONFIG_PATH', config), \
                    patch.object(stream.sys, 'argv', ['camera_stream.py', '0', '8090']):
                self.assertEqual(stream.parse_args()[0], 1)
                config.write_text('{"id":"invalid"}', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Invalid camera configuration'):
                    stream.parse_args()

    def test_unavailable_selected_camera_does_not_open_another_index(self):
        from unittest.mock import Mock
        camera = Mock()
        camera.isOpened.return_value = True
        camera.read.return_value = (False, None)
        with patch('platform.system', return_value='Linux'), \
                patch.object(stream.cv2, 'VideoCapture', return_value=camera) as capture:
            self.assertEqual(stream.open_camera(1), (None, None))
        capture.assert_called_once_with(1)
        camera.release.assert_called_once()

    def test_only_registered_photos_are_loaded_and_encodings_are_cached(self):
        def encode_image(image):
            self.assertTrue(stream.FACE_ENGINE_LOCK.locked())
            return [np.zeros(128)]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'registered.jpg').write_bytes(b'photo')
            (root / 'orphan-hash.jpg').write_bytes(b'photo')
            engine = SimpleNamespace(
                load_image_file=lambda path: np.zeros((80, 80, 3), dtype=np.uint8),
                face_encodings=encode_image,
            )
            with patch.object(stream, 'FACE_IMAGES_DIR', root), \
                    patch.object(stream, 'FACE_RECOGNITION_AVAILABLE', True), \
                    patch.object(stream, 'face_recognition', engine), \
                    patch.object(stream, 'FACE_CACHE', {}), \
                    patch.object(stream, 'load_student_details', return_value={}), \
                    patch.object(stream, 'load_student_name_map', return_value={
                        'registered.jpg': ('2026-001', 'Registered Student')
                    }), patch.object(engine, 'face_encodings', wraps=engine.face_encodings) as encode:
                self.assertEqual(stream.load_known_faces()[1], ['2026-001'])
                self.assertEqual(stream.load_known_faces()[1], ['2026-001'])
                self.assertEqual(encode.call_count, 1)
                # Deleted/archived mappings must disappear, including cached photos.
                with patch.object(stream, 'load_student_name_map', return_value={}):
                    self.assertEqual(stream.load_known_faces()[1], [])

    def test_slow_recognition_does_not_block_video_or_mutate_analysis_frame(self):
        camera = FakeCamera()
        server = SimpleNamespace(
            camera=(camera, 0), target_size=(90, 160),
            last_db_reload=time.monotonic(), current_student=None,
        )
        entered = threading.Event()
        release = threading.Event()

        def slow_recognition(frame, *args):
            entered.set()
            release.wait(3)
            self.assertFalse(frame.any(), "Overlays must not modify the analysis input")
            return [], [], [], []

        pipeline = stream.CameraPipeline(server)
        with patch.object(stream, "load_known_faces"), patch.object(stream, "FACE_RECOGNITION_AVAILABLE", True), \
                patch.object(stream, "recognize_frame", slow_recognition), \
                patch.object(stream, "detect_face_pose", return_value="none"):
            pipeline.start(use_process=False)
            try:
                self.assertTrue(entered.wait(2))
                initial = pipeline.sequence
                with pipeline.condition:
                    advanced = pipeline.condition.wait_for(
                        lambda: pipeline.sequence >= initial + 5, timeout=2
                    )
                self.assertTrue(advanced, "Video stopped while recognition was busy")
                self.assertTrue(pipeline.jpeg.startswith(b"\xff\xd8"))
            finally:
                release.set()
                pipeline.close()
        self.assertEqual(len(camera.readers), 1)
        self.assertTrue(camera.released)

    def test_multiple_viewers_share_capture_and_receive_mjpeg(self):
        camera = FakeCamera()
        server = stream.ThreadingHTTPServer(("127.0.0.1", 0), stream.StreamHandler)
        server.camera = (camera, 0)
        server.target_size = (90, 160)
        server.last_db_reload = time.monotonic()
        server.pipeline = stream.CameraPipeline(server)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        clients = []
        with patch.object(stream, "FACE_RECOGNITION_AVAILABLE", False):
            server.pipeline.start(use_process=False)
            serving.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/video_feed"
                clients = [urlopen(url, timeout=3), urlopen(url, timeout=3)]
                for client in clients:
                    self.assertEqual(client.readline(), b"--frame\r\n")
                    self.assertEqual(client.readline(), b"Content-Type: image/jpeg\r\n")
                    length = int(client.readline().split(b":")[1])
                    self.assertEqual(client.readline(), b"\r\n")
                    self.assertTrue(client.read(length).startswith(b"\xff\xd8"))
                self.assertEqual(len(camera.readers), 1)
            finally:
                for client in clients:
                    client.close()
                server.pipeline.close()
                server.shutdown()
                server.server_close()
                serving.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
