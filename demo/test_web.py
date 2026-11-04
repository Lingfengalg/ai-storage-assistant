"""Web routing checks with synthetic images and a mocked worker, not a model test."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app as prototype


class FakeWorker:
    def poll(self):
        return None


def image_file():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(buf, format="JPEG")
    buf.seek(0)
    return buf


class WebSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = patch.object(prototype, "JOBS", Path(self.temp.name))
        self.jobs.start()
        self.process = patch.object(prototype, "active_process", None)
        self.process.start()
        self.client = prototype.app.test_client()

    def tearDown(self):
        self.process.stop()
        self.jobs.stop()
        self.temp.cleanup()

    def test_home_and_disabled_detection(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/detect").status_code, 501)

    def test_validates_image_count_and_job_id(self):
        self.assertEqual(self.client.post("/reconstruct").status_code, 400)
        self.assertEqual(self.client.get("/reconstruct/not-a-job").status_code, 404)

    @patch.object(prototype.subprocess, "Popen", return_value=FakeWorker())
    def test_upload_creates_job_without_running_model(self, popen):
        result = self.client.post(
            "/reconstruct",
            data={"photos": [(image_file(), "a.jpg"), (image_file(), "b.jpg")]},
            content_type="multipart/form-data",
        )
        self.assertEqual(result.status_code, 200)
        job = Path(self.temp.name) / result.json["job"]
        self.assertEqual(len(list((job / "images").glob("*.jpg"))), 2)
        self.assertEqual(json.loads((job / "status.json").read_text(encoding="utf-8"))["state"], "running")
        self.assertEqual(self.client.get(f"/reconstruct/{job.name}").status_code, 200)
        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
