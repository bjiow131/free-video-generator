"""Deterministic Linux-compatible camera geometry and optimizer regressions."""
import itertools
import math
import unittest

from local_agent.camera_composition import preferred_focal_length
from local_agent.camera_path_planner import optimize_camera_path


class FramingTests(unittest.TestCase):
    def test_no_zoom_when_adequate(self):
        self.assertEqual(preferred_focal_length(42, 0.5), 42)

    def test_no_zoom_at_target(self):
        self.assertEqual(preferred_focal_length(42, 0.38), 42)

    def test_zoom_toward_target(self):
        self.assertAlmostEqual(preferred_focal_length(42, 0.2), 79.8)

    def test_zoom_clamped_at_maximum(self):
        self.assertEqual(preferred_focal_length(42, 0.01), 100)

    def test_custom_upper_limit(self):
        self.assertEqual(preferred_focal_length(42, 0.2, max_lens=60), 60)

    def test_zero_silhouette_keeps_fitting_lens(self):
        self.assertEqual(preferred_focal_length(42, 0), 42)

    def test_tiny_silhouette_keeps_fitting_lens(self):
        self.assertEqual(preferred_focal_length(42, 1e-6), 42)

    def test_invalid_fitting_lens(self):
        with self.assertRaises(ValueError):
            preferred_focal_length(0, 0.2)

    def test_invalid_upper_limit(self):
        with self.assertRaises(ValueError):
            preferred_focal_length(42, 0.2, max_lens=40)

    def test_invalid_target(self):
        with self.assertRaises(ValueError):
            preferred_focal_length(42, 0.2, target_fraction=1.1)

    def test_negative_subject_height(self):
        with self.assertRaises(ValueError):
            preferred_focal_length(42, -0.01)

    def test_nonfinite_height(self):
        with self.assertRaises(ValueError):
            preferred_focal_length(42, math.inf)


class PlannerRegressionTests(unittest.TestCase):
    def test_two_frames_reference_is_cheaper(self):
        self.assertEqual(
            optimize_camera_path([[(0, 0, 0), (4, 0, 0)],
                                  [(0, 0, 0), (4, 0, 0)]]),
            [(0, 0, 0), (0, 0, 0)],
        )

    def test_prefers_constant_alternative_over_jump(self):
        cases = [[(0, 0, 0), (2, 0, 0)],
                 [(30, 0, 0), (2, 0, 0)],
                 [(0, 0, 0), (2, 0, 0)],
                 [(30, 0, 0), (2, 0, 0)]]
        self.assertEqual(optimize_camera_path(cases), [(2, 0, 0)] * 4)

    def test_single_choice_vertical_tracking(self):
        choices = [[(0, 0, float(i))] for i in range(8)]
        self.assertEqual(optimize_camera_path(choices), [p[0] for p in choices])

    def test_single_choice_lateral_tracking(self):
        choices = [[(0, float(i), 0)] for i in range(8)]
        self.assertEqual(optimize_camera_path(choices), [p[0] for p in choices])

    def test_frame_with_no_candidates_has_frame_index(self):
        with self.assertRaisesRegex(ValueError, "frame 3"):
            optimize_camera_path([[(0, 0, 0)], [(1, 0, 0)], []])

    def test_infinite_weight_rejected(self):
        with self.assertRaises(ValueError):
            optimize_camera_path([[(0, 0, 0)]], acceleration_weight=math.inf)

    def test_nan_weight_rejected(self):
        with self.assertRaises(ValueError):
            optimize_camera_path([[(0, 0, 0)]], reference_weight=math.nan)

    def test_wrong_candidate_dimension_rejected(self):
        with self.assertRaises(ValueError):
            optimize_camera_path([[(0, 1)]])

    def test_non_numeric_coordinate_rejected(self):
        with self.assertRaises(ValueError):
            optimize_camera_path([[("invalid", 0, 0)]])

    def test_long_timeline_preserves_length(self):
        frames = [[(float(i), 0, 0)] for i in range(72)]
        path = optimize_camera_path(frames)
        self.assertEqual(len(path), 72)
        self.assertEqual(path[-1], (71, 0, 0))

    def test_global_optimum_against_brute_force(self):
        frames = [
            [(0, 0, 0), (2, 0, 0)],
            [(5, 0, 0), (2, 0, 0)],
            [(0, 0, 0), (2, 0, 0)],
            [(5, 0, 0), (2, 0, 0)],
        ]
        path = optimize_camera_path(frames)
        movement, acceleration, reference = 1., 4., 0.05
        def score(indices):
            pts = [frames[i][j] for i, j in enumerate(indices)]
            cost = reference * sum(j != 0 for j in indices)
            for i in range(1, len(pts)):
                cost += movement * sum((a-b)**2 for a,b in zip(pts[i],pts[i-1]))
            for i in range(2, len(pts)):
                cost += acceleration * sum((pts[i][d]-2*pts[i-1][d]+pts[i-2][d])**2 for d in range(3))
            return cost
        alternatives = list(itertools.product(range(2), repeat=len(frames)))
        minimum = min(score(ix) for ix in alternatives)
        chosen = tuple(frames[i].index(p) for i,p in enumerate(path))
        self.assertAlmostEqual(score(chosen), minimum)


if __name__ == "__main__":
    unittest.main()
