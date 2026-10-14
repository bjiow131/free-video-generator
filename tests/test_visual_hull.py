import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from local_agent.visual_hull import VisualHullError, build_visual_hull


class VisualHullTests(unittest.TestCase):
    def test_two_calibrated_silhouettes_create_donor_independent_obj(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            front = Image.new("L", (64, 80), 0)
            ImageDraw.Draw(front).rectangle((18, 8, 45, 70), fill=255)
            side = Image.new("L", (64, 80), 0)
            ImageDraw.Draw(side).rectangle((24, 8, 39, 70), fill=255)
            front_path, side_path = root / "front.png", root / "side.png"
            front.save(front_path); side.save(side_path)
            output = root / "character_hull.obj"
            result = build_visual_hull([
                {"name": "front", "mask_path": str(front_path), "horizontal_axis": "x", "vertical_axis": "z"},
                {"name": "side", "mask_path": str(side_path), "horizontal_axis": "y", "vertical_axis": "z"},
            ], {"x": [-0.5, 0.5], "y": [-0.4, 0.4], "z": [0, 2]}, output, grid_size=32)
            self.assertEqual(result["status"], "completed")
            self.assertFalse(result["production_ready"])
            self.assertGreater(result["surface_faces"], 0)
            self.assertIn("o ReferenceVisualHull", output.read_text())
            self.assertTrue(output.read_text().count("\nf ") > 0)

    def test_blocks_one_view_and_empty_intersection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mask = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(mask).rectangle((16, 16, 48, 48), fill=255)
            path = root / "mask.png"
            mask.save(path)
            one_view = [{"name": "front", "mask_path": str(path), "horizontal_axis": "x", "vertical_axis": "z"}]
            with self.assertRaisesRegex(VisualHullError, "at_least_two"):
                build_visual_hull(one_view, {"x": [-1, 1], "y": [-1, 1], "z": [0, 2]}, root / "one.obj")

            miss = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(miss).rectangle((52, 52, 62, 62), fill=255)
            miss_path = root / "miss.png"
            miss.save(miss_path)
            with self.assertRaisesRegex(VisualHullError, "empty_intersection|too_small"):
                build_visual_hull([
                    one_view[0],
                    {"name": "side", "mask_path": str(miss_path), "horizontal_axis": "y", "vertical_axis": "z"},
                ], {"x": [-1, 1], "y": [-1, 1], "z": [0, 2]}, root / "miss.obj", grid_size=32)


if __name__ == "__main__":
    unittest.main()
