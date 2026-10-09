import json
from pathlib import Path

from local_agent.manifest import ProjectManifest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "local_video_agent"


def test_all_example_manifests_validate():
    expected_counts = {
        "two_scene_demo.json": 2,
        "ten_scene_demo.json": 10,
        "one_hundred_scene_demo.json": 100,
    }
    for filename, count in expected_counts.items():
        data = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
        manifest = ProjectManifest.from_dict(data)
        assert len(manifest.scenes) == count
        assert manifest.project_name
        assert all(scene.duration_seconds == 5 for scene in manifest.scenes)
        assert all(scene.aspect_ratio == "9:16" for scene in manifest.scenes)
