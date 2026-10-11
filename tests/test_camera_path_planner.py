"""Deterministic tests for the Blender-independent camera path planner."""
import unittest

from local_agent.camera_path_planner import optimize_camera_path


class CameraPlannerTests(unittest.TestCase):
    def test_single_frame(self):
        self.assertEqual(optimize_camera_path([[(1, 2, 3)]]), [(1, 2, 3)])

    def test_no_frames(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            optimize_camera_path([])

    def test_impossible_frame(self):
        with self.assertRaisesRegex(ValueError, "frame 2"):
            optimize_camera_path([[(0, 0, 0)], []])

    def test_nonfinite_candidate(self):
        with self.assertRaises(ValueError):
            optimize_camera_path([[(float("nan"), 0, 0)]])

    def test_smooth_path_beats_jumping_preferred(self):
        choices = [
            [(0, 0, 0), (1, 0, 0)],
            [(10, 0, 0), (1, 0, 0)],
            [(0, 0, 0), (1, 0, 0)],
            [(10, 0, 0), (1, 0, 0)],
        ]
        path = optimize_camera_path(choices)
        self.assertEqual(path, [(1.0, 0.0, 0.0)] * 4)

    def test_one_valid_choice_per_frame(self):
        choices = [[(float(i), 0, 0)] for i in range(10)]
        self.assertEqual(optimize_camera_path(choices), [v[0] for v in choices])

    def test_negative_weight(self):
        with self.assertRaises(ValueError):
            optimize_camera_path([[(0, 0, 0)]], movement_weight=-1)


if __name__ == "__main__":
    unittest.main()
