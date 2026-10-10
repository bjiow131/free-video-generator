import tempfile
import unittest
from pathlib import Path
from local_agent.reference_library import PassportError, validate_passport, select_reference, build_scene_reference_plan, write_passport

def passport():
    return {"schema_version": 1, "id": "char.mia", "name": "Мия",
            "description": "Permanent 3D character", "status": "draft",
            "references": [
                {"id": "mia.front", "view": "front", "status": "ready", "file": "assets/mia/front.png"},
                {"id": "mia.back", "view": "back", "status": "ready", "file": "assets/mia/back.png"},
            ]}

class ReferenceLibraryTests(unittest.TestCase):
    def test_camera_uses_back(self):
        self.assertEqual(select_reference(passport(), "Мия спиной к камере")["id"], "mia.back")

    def test_missing_view_is_explicit(self):
        self.assertIsNone(select_reference(passport(), "вид справа"))
        scene = {"scene_id": "scene_002", "action": "Мия идёт", "camera": "вид справа"}
        self.assertEqual(build_scene_reference_plan(scene, [passport()])["characters"][0]["reference_status"], "missing")

    def test_rejects_path_traversal(self):
        p = passport()
        p["references"][0]["file"] = "assets/../../secret.png"
        with self.assertRaises(PassportError):
            validate_passport(p)

    def test_rejects_invalid_crop(self):
        p = passport()
        p["references"][0]["box"] = [0.9, 0.1, 0.2, 0.8]
        with self.assertRaises(PassportError):
            validate_passport(p)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_passport(directory, passport())
            self.assertTrue(Path(path).is_file())
            with self.assertRaises(FileExistsError):
                write_passport(directory, passport())

if __name__ == "__main__":
    unittest.main()
