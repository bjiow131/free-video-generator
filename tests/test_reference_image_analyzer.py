import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from local_agent.reference_image_analyzer import ReferenceImageError, analyze_views
from local_agent.reference_to_model import parse_spec


class ReferenceImageAnalyzerTests(unittest.TestCase):
    def test_alpha_reference_creates_hash_pinned_map_and_review_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "front.png"
            image = Image.new("RGBA", (128, 160), (0, 0, 0, 0))
            ImageDraw.Draw(image).ellipse((35, 20, 93, 80), fill=(225, 175, 150, 255))
            image.save(image_path)
            out = root / "analysis"

            result = analyze_views([("front", image_path)], out, sample_count=32)

            self.assertEqual(result["status"], "ready_for_review")
            self.assertFalse(result["fit_ready"])
            self.assertTrue(result["views"][0]["requires_mask_review"])
            self.assertTrue((out / "mask_front.png").is_file())
            data = parse_spec(json.loads((out / "reference_map.json").read_text()))
            self.assertEqual(len(data.views[0].contour), 32)
            self.assertEqual(data.views[0].observations, ())

    def test_opaque_flat_background_is_segmented_and_nonuniform_background_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            solid = Image.new("RGB", (96, 96), "white")
            ImageDraw.Draw(solid).rectangle((28, 12, 68, 88), fill=(30, 90, 160))
            source = root / "front.jpg"
            solid.save(source)
            result = analyze_views([("front", source)], root / "ok", sample_count=32)
            self.assertEqual(result["views"][0]["segmentation_method"], "estimated_flat_border")

            noisy = np.zeros((96, 96, 3), dtype=np.uint8)
            rng = np.random.default_rng(10)
            noisy[:] = rng.integers(0, 255, size=(96, 96, 3), dtype=np.uint8)
            noisy_path = root / "noisy.png"
            Image.fromarray(noisy).save(noisy_path)
            with self.assertRaisesRegex(ReferenceImageError, "background_not_uniform"):
                analyze_views([("back", noisy_path)], root / "blocked", sample_count=32)


if __name__ == "__main__":
    unittest.main()
