import unittest

from local_agent.reference_to_model import (
    ReferenceToModelError,
    characterize_ambiguity,
    parse_spec,
    residual_vector,
)


class ReferenceToModelTests(unittest.TestCase):
    def spec_data(self):
        return {
            "schema_version": 1,
            "character_name": "Мия — зимний комплект",
            "coordinate_convention": "camera_frame_bottom_left_normalized",
            "reference_sha256": "a" * 64,
            "views": [
                {"name": "front", "camera_name": "Front_Camera", "landmarks": [
                    {"name": "left_eye", "object_name": "Head", "vertex_index": 0,
                     "target": [0.4, 0.6], "confidence": 1.0}],
                 "silhouette": [[0.3, 0.3], [0.7, 0.3]]},
            ],
            "controls": [{"name": "head_width", "kind": "shape_key", "object_name": "Head",
                          "property_name": "Wide", "initial": 0.0, "lower": -0.2,
                          "upper": 0.2, "regularization": 0.1}],
        }

    def test_parse_hash_pinned_generic_character_and_losses(self):
        spec = parse_spec(self.spec_data(), expected_sha256="a" * 64)
        residuals = residual_vector(spec, {("front", "left_eye"): [0.5, 0.6]}, {"head_width": 0.1},
                                    {"front": [[0.3, 0.3], [0.7, 0.3]]})
        self.assertAlmostEqual(residuals[0], 0.1 / 2 ** 0.5)
        self.assertAlmostEqual(residuals[-1], 0.01)
        self.assertTrue(all(abs(v) < 1e-12 for v in residuals[2:-1]))

    def test_rejects_mismatched_digest_and_missing_contour_projection(self):
        with self.assertRaisesRegex(ReferenceToModelError, "mismatch"):
            parse_spec(self.spec_data(), expected_sha256="b" * 64)
        spec = parse_spec(self.spec_data())
        with self.assertRaisesRegex(ReferenceToModelError, "contour_projection_missing"):
            residual_vector(spec, {("front", "left_eye"): [0.4, 0.6]})

    def test_reports_single_view_depth_ambiguity(self):
        self.assertEqual(characterize_ambiguity(1)["depth_confidence"], "underconstrained")
        self.assertEqual(characterize_ambiguity(3)["depth_confidence"], "multi_view_supported")


if __name__ == "__main__":
    unittest.main()
