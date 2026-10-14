import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from local_agent.reference_to_model_pipeline import FirstRunError, run_first_draft


class FirstDraftPipelineTests(unittest.TestCase):
    def test_two_view_reference_creates_reviewable_map_and_obj(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "refs"
            images.mkdir()
            for filename, bounds in (("front.png", (25, 12, 70, 85)), ("side.png", (30, 12, 62, 85))):
                image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
                ImageDraw.Draw(image).ellipse(bounds, fill=(120, 170, 210, 255))
                image.save(images / filename)
            result = run_first_draft([
                {"name": "front", "image_path": images / "front.png", "horizontal_axis": "x", "vertical_axis": "z"},
                {"name": "side", "image_path": images / "side.png", "horizontal_axis": "y", "vertical_axis": "z"},
            ], {"x": [-0.5, 0.5], "y": [-0.4, 0.4], "z": [0, 2]}, root / "out", grid_size=24,
               sample_count=32)
            self.assertEqual(result["status"], "draft_ready_for_review")
            self.assertFalse(result["fit_ready"])
            self.assertFalse(result["production_ready"])
            self.assertTrue(Path(result["reference_map_file"]).is_file())
            self.assertTrue(Path(result["mesh_file"]).is_file())
            self.assertEqual(len(result["mask_files"]), 2)

    def test_rejects_views_that_leave_an_unobserved_axis(self):
        with self.assertRaisesRegex(FirstRunError, "cover_all_three"):
            run_first_draft([
                {"name": "front", "image_path": "front.png", "horizontal_axis": "x", "vertical_axis": "z"},
                {"name": "front2", "image_path": "side.png", "horizontal_axis": "x", "vertical_axis": "z"},
            ], {"x": [-1, 1], "y": [-1, 1], "z": [0, 2]}, ".", grid_size=24)


if __name__ == "__main__":
    unittest.main()
