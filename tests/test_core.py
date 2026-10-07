"""
Agnes Video Generator v2.0 — 单元测试套件

覆盖 AGENTS.md 第二层单元测试清单：
- models/task.py: 序列化/反序列化、多态 parse_task_state
- core/audio/subtitle.py: SRT 格式输出、_split_long_text 多行换行
- core/config.py: 默认配置结构、resolve_font_path CJK 回退
- core/task_manager.py: 旧数据兼容（无 task_type → CREATIVE）
- core/compositor/concatenator.py: 字幕位置解析（bottom-80/top+N）
- core/pipelines/manuscript_video.py: _step_split_text 拆段算法

用法:
    .venv/bin/python -m pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ═══════════════════════════════════════════════════
# 1. models/task.py
# ═══════════════════════════════════════════════════

class TestSubtitleStyle:
    """SubtitleStyle bg_color 验证器测试。"""

    def test_default_bg_color(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle()
        assert style.bg_color == (0, 0, 0, 128)

    def test_bg_color_with_alpha_string(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle(bg_color="black@0.5")
        assert style.bg_color == (0, 0, 0, 127)

    def test_bg_color_white_alpha(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle(bg_color="white@0.7")
        assert style.bg_color == (255, 255, 255, 178)

    def test_bg_color_transparent(self):
        from models.task import SubtitleStyle
        # SubtitleStyle.bg_color 类型为 tuple，transparent 解析为 None 会触发 Pydantic 类型错误
        with pytest.raises(Exception):
            SubtitleStyle(bg_color="transparent")

    def test_bg_color_tuple_passthrough(self):
        from models.task import SubtitleStyle
        style = SubtitleStyle(bg_color=(100, 100, 100, 200))
        assert style.bg_color == (100, 100, 100, 200)


class TestParseTaskState:
    """parse_task_state 多态反序列化测试。"""

    def test_simple_task(self):
        from models.task import parse_task_state, SimpleVideoTask, TaskType
        data = {
            "task_id": "test001",
            "task_type": TaskType.SIMPLE,
            "prompt": "test prompt",
            "creative_name": "simple_test001",
        }
        state = parse_task_state(data)
        assert isinstance(state, SimpleVideoTask)
        assert state.task_id == "test001"
        assert state.task_type == TaskType.SIMPLE

    def test_creative_task(self):
        from models.task import parse_task_state, CreativeVideoTask, TaskType
        data = {
            "task_id": "test002",
            "task_type": TaskType.CREATIVE,
            "idea": "test idea",
            "creative_name": "creative_test002",
        }
        state = parse_task_state(data)
        assert isinstance(state, CreativeVideoTask)
        assert state.task_type == TaskType.CREATIVE

    def test_manuscript_task(self):
        from models.task import parse_task_state, ManuscriptVideoTask, TaskType
        data = {
            "task_id": "test003",
            "task_type": TaskType.MANUSCRIPT,
            "manuscript_text": "测试文本",
            "creative_name": "manuscript_test003",
        }
        state = parse_task_state(data)
        assert isinstance(state, ManuscriptVideoTask)
        assert state.task_type == TaskType.MANUSCRIPT

    def test_missing_task_type_defaults_to_creative(self):
        """L6 向后兼容：旧数据没有 task_type 字段，默认识别为 CREATIVE。"""
        from models.task import parse_task_state, CreativeVideoTask
        data = {
            "task_id": "legacy001",
            "creative_name": "legacy_task",
            "idea": "legacy idea",
        }
        state = parse_task_state(data)
        assert isinstance(state, CreativeVideoTask)

    def test_serialization_roundtrip(self):
        """序列化 → 反序列化 roundtrip 测试。"""
        from models.task import parse_task_state, SimpleVideoTask, VideoMode
        original = SimpleVideoTask(
            task_id="rt001",
            creative_name="simple_rt001",
            prompt="roundtrip prompt",
            mode=VideoMode.T2V,
            duration=10,
        )
        data = original.model_dump()
        restored = parse_task_state(data)
        assert isinstance(restored, SimpleVideoTask)
        assert restored.prompt == "roundtrip prompt"
        assert restored.duration == 10


# ═══════════════════════════════════════════════════
# 2. core/audio/subtitle.py
# ═══════════════════════════════════════════════════

class TestSplitLongText:
    """_split_long_text 多行换行测试。"""

    def test_short_text_no_split(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator._split_long_text("短视频", 14) == "短视频"

    def test_empty_text(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator._split_long_text("", 14) == ""

    def test_existing_newline_passthrough(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator._split_long_text("已有\n换行", 14) == "已有\n换行"

    def test_long_cjk_split_at_punctuation(self):
        from core.audio.subtitle import SubtitleGenerator
        result = SubtitleGenerator._split_long_text("今天天气真好，我们一起去公园散步吧", 14)
        assert result == "今天天气真好，\n我们一起去公园散步吧", f"Got: {result!r}"

    def test_long_cjk_split_at_mid(self):
        from core.audio.subtitle import SubtitleGenerator
        result = SubtitleGenerator._split_long_text("这是一段比较长的中文字幕文本需要拆分显示在视频上方", 14)
        assert "\n" in result
        lines = result.split("\n")
        assert len(lines) == 2

    def test_long_english_split_at_word_boundary(self):
        from core.audio.subtitle import SubtitleGenerator
        # 需要超过 14 个单词才会拆分
        result = SubtitleGenerator._split_long_text(
            "This is a very long English subtitle text that should definitely be split into two lines when max chars is small", 8
        )
        assert "\n" in result

    def test_short_english_no_split(self):
        from core.audio.subtitle import SubtitleGenerator
        result = SubtitleGenerator._split_long_text("Short text", 14)
        assert result == "Short text"


class TestCueToSrtTime:
    """cue_to_srt_time 时间格式测试。"""

    def test_zero(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(0.0) == "00:00:00,000"

    def test_seconds_and_ms(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(2.5) == "00:00:02,500"

    def test_minutes(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(65.123) == "00:01:05,123"

    def test_hours(self):
        from core.audio.subtitle import SubtitleGenerator
        assert SubtitleGenerator.cue_to_srt_time(3661.0) == "01:01:01,000"


# ═══════════════════════════════════════════════════
# 3. core/config.py
# ═══════════════════════════════════════════════════

class TestResolveFontPath:
    """resolve_font_path CJK 回退测试。"""

    def test_non_cjk_font_fallback(self):
        from core.config import resolve_font_path, DEFAULT_CHINESE_FONT
        result = resolve_font_path("Arial")
        assert DEFAULT_CHINESE_FONT in result, f"Expected fallback, got: {result}"

    def test_non_cjk_font_case_insensitive(self):
        from core.config import resolve_font_path, DEFAULT_CHINESE_FONT
        result = resolve_font_path("arial")
        assert DEFAULT_CHINESE_FONT in result

    def test_system_font_passthrough(self):
        from core.config import resolve_font_path
        result = resolve_font_path("NotoSansCJK-Regular")
        # 不在 _NON_CJK_FONTS 里，直接返回系统字体名
        assert result == "NotoSansCJK-Regular"

    def test_absolute_path_existing_file(self):
        from core.config import resolve_font_path, font_dir, DEFAULT_CHINESE_FONT
        abs_path = os.path.join(font_dir(), DEFAULT_CHINESE_FONT)
        if os.path.exists(abs_path):
            assert resolve_font_path(abs_path) == abs_path


class TestDefaultSubtitleStyle:
    """默认字幕样式配置测试。"""

    def test_default_position_is_bottom_80(self):
        from core.config import get_default_subtitle_style
        style = get_default_subtitle_style()
        assert style.position == ("center", "bottom-80")

    def test_default_font_is_cjk(self):
        from core.config import get_default_subtitle_style, DEFAULT_CHINESE_FONT
        style = get_default_subtitle_style()
        assert style.font == DEFAULT_CHINESE_FONT

    def test_default_fontsize(self):
        from core.config import get_default_subtitle_style
        style = get_default_subtitle_style()
        assert style.fontsize == 48


# ═══════════════════════════════════════════════════
# 4. core/compositor/concatenator.py
# ═══════════════════════════════════════════════════

class TestResolveSubtitlePosition:
    """_resolve_subtitle_position 字幕位置解析测试（M1 修复验证）。"""

    def test_bottom_80_with_height(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "bottom-80"), video_height=1152
        )
        assert pos == ("center", 1072)

    def test_top_plus_50(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "top+50"), video_height=1152
        )
        assert pos == ("center", 50)

    def test_plain_bottom(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "bottom"), video_height=1152
        )
        assert pos == ("center", "bottom")

    def test_plain_top(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "top"), video_height=1152
        )
        assert pos == ("center", "top")

    def test_string_bottom(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position("bottom", video_height=1152)
        assert pos == ("center", "bottom")

    def test_string_bottom_80(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position("bottom-80", video_height=1152)
        assert pos == ("center", 1072)

    def test_string_top_plus(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position("top+100", video_height=768)
        assert pos == ("center", 100)

    def test_no_height_fallback(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", "bottom-80"), video_height=0
        )
        # 无 video_height 时，bottom-80 无法计算像素，回退到普通 bottom
        assert pos == ("center", "bottom")

    def test_numeric_position_passthrough(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(
            ("center", 500), video_height=1152
        )
        assert pos == ("center", 500)

    def test_default_position(self):
        from core.compositor.concatenator import VideoConcatenator
        pos = VideoConcatenator._resolve_subtitle_position(None, video_height=1152)
        assert pos == ("center", "bottom")


# ═══════════════════════════════════════════════════
# 5. server.py 辅助函数
# ═══════════════════════════════════════════════════

class TestParseBgColor:
    """_parse_bg_color 解析测试。"""

    def test_black_at_half(self):
        from server import _parse_bg_color
        result = _parse_bg_color("black@0.5")
        assert result == (0, 0, 0, 127)

    def test_white_at_full(self):
        from server import _parse_bg_color
        result = _parse_bg_color("white@1.0")
        assert result == (255, 255, 255, 255)

    def test_transparent(self):
        from server import _parse_bg_color
        assert _parse_bg_color("transparent") is None

    def test_tuple_passthrough(self):
        from server import _parse_bg_color
        assert _parse_bg_color((100, 100, 100, 200)) == (100, 100, 100, 200)

    def test_parenthesis_format(self):
        from server import _parse_bg_color
        result = _parse_bg_color("(50, 60, 70, 80)")
        assert result == (50, 60, 70, 80)


class TestBuildPosition:
    """_build_position 位置构建测试。"""

    def test_top(self):
        from server import _build_position
        assert _build_position("top") == ("center", "top")

    def test_bottom(self):
        from server import _build_position
        assert _build_position("bottom") == ("center", "bottom")

    def test_default_is_bottom(self):
        from server import _build_position
        assert _build_position("something_else") == ("center", "bottom")


class TestParseDuration:
    """_parse_duration 时长解析测试。"""

    def test_each_scene_seconds(self):
        from server import _parse_duration
        assert _parse_duration("3个场景，每个场景5秒") == 5

    def test_each_segment_seconds(self):
        from server import _parse_duration
        assert _parse_duration("每段10秒的视频") == 10

    def test_no_duration_defaults_to_5(self):
        from server import _parse_duration
        assert _parse_duration("一段精彩的视频") == 5


# ═══════════════════════════════════════════════════
# 6. core/pipelines/manuscript_video.py
# ═══════════════════════════════════════════════════

class TestStepSplitText:
    """稿件文本拆分测试（_step_split_text）。"""

    def _make_pipeline(self):
        """构建带 mock _state 的最小化 ManuscriptVideoPipeline 实例。"""
        from core.pipelines.manuscript_video import ManuscriptVideoPipeline
        from models.task import ManuscriptVideoTask
        pipeline = ManuscriptVideoPipeline.__new__(ManuscriptVideoPipeline)
        pipeline._state = ManuscriptVideoTask(
            task_id="test",
            creative_name="test",
            manuscript_text="",
        )
        return pipeline

    def test_short_text_single_paragraph(self):
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text("这是短句。")
        assert len(paragraphs) >= 1
        assert all(p.text.strip() for p in paragraphs)

    def test_multi_sentence_split(self):
        text = "春天来了。花开了。小鸟在唱歌。孩子们在玩耍。"
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text(text)
        assert len(paragraphs) >= 1
        combined = "".join(p.text for p in paragraphs)
        assert "春天来了" in combined

    def test_newline_split(self):
        # 使用足够长的段落确保拆分（贪心合并上限 ~12s ≈ 48 字）
        text = (
            "这是第一段内容，讲述了春天的美丽景色，花红柳绿，"
            "小鸟在树枝上唱歌，孩子们在公园里开心地玩耍。\n\n"
            "这是第二段内容，讲述了夏天的故事，阳光灸热，"
            "蝉在树上呜叫，大家在树荫下乘凉，享受着冰凉的西瓜。\n\n"
            "这是第三段内容，讲述了秋天的丰收，金黄的稻田，"
            "红艳艳的苹果挂满枝头，农民们开心地收获着一年的成果。"
        )
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text(text)
        assert len(paragraphs) >= 2

    def test_empty_text(self):
        pipeline = self._make_pipeline()
        paragraphs = pipeline._step_split_text("")
        assert len(paragraphs) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


# ═══════════════════════════════════════════════════
# 7. Local single-user server contract
# ═══════════════════════════════════════════════════

class TestLocalServerContract:
    """Local mode must not expose account/session authentication and UI routes must exist."""

    def test_no_auth_routes_or_session_dependencies(self):
        from server import app
        routes = {getattr(route, "path", "") for route in app.routes}
        assert "/api/public/login" not in routes
        assert "/api/public/register" not in routes
        assert "/api/public/guest" not in routes
        assert "/api/public/logout" not in routes
        assert "/api/login" not in routes
        assert "/api/register" not in routes

    def test_local_generation_routes_exist(self):
        from server import app
        routes = {getattr(route, "path", "") for route in app.routes}
        assert "/api/image/generate" in routes
        assert "/api/image/{task_id}" in routes
        assert "/api/image/{task_id}/download" in routes
        assert "/api/tasks/simple" in routes
        assert "/api/tasks/creative" in routes
        assert "/api/tasks/manuscript" in routes
        assert "/api/video/{task_id}" in routes
        assert "/api/video/{task_id}/download" in routes
        assert "/health" in routes


class TestTaskIdSafety:
    """Filesystem-facing task IDs must reject traversal input."""

    @pytest.mark.parametrize("value", ["../secret", "..\\secret", "/absolute", "\\\\server\\share", ""])
    def test_rejects_unsafe_task_id(self, value):
        from fastapi import HTTPException
        from server import _validate_task_id
        with pytest.raises(HTTPException) as exc:
            _validate_task_id(value)
        assert exc.value.status_code == 400

    def test_accepts_generated_style_task_id(self):
        from server import _validate_task_id
        assert _validate_task_id("a1b2c3d4e5f6") == "a1b2c3d4e5f6"


class TestLocalEntrypoints:
    def test_local_server_module_is_importable(self):
        from server import app
        assert app.title == "Agnes Video Generator"


class TestSimpleVideoPersistence:
    def test_save_task_is_atomic_and_does_not_create_shell_script(self, tmp_path):
        from core.pipelines.simple_video import SimpleVideoPipeline
        pipeline = SimpleVideoPipeline.__new__(SimpleVideoPipeline)
        pipeline.task_manager = type("TaskManagerStub", (), {"task_dir": str(tmp_path)})()
        pipeline._save_task("video-123")
        import json
        with open(tmp_path / "task.json", encoding="utf-8") as f:
            assert json.load(f)["video_id"] == "video-123"
        assert not (tmp_path / "curl.sh").exists()
        assert not (tmp_path / "task.json.tmp").exists()


class TestApiRequestDefaults:
    def test_video_request_defaults_to_landscape(self):
        from models.task import CreateSimpleTaskRequest, CreateCreativeTaskRequest, CreateManuscriptTaskRequest
        assert (CreateSimpleTaskRequest(prompt="x").video_width, CreateSimpleTaskRequest(prompt="x").video_height) == (1152, 648)
        assert (CreateCreativeTaskRequest(idea="x").video_width, CreateCreativeTaskRequest(idea="x").video_height) == (1152, 648)
        assert (CreateManuscriptTaskRequest(manuscript_text="x").video_width, CreateManuscriptTaskRequest(manuscript_text="x").video_height) == (1152, 648)


class TestSharedSubtitleDefaults:
    def test_shared_subtitle_helper_defaults_to_landscape(self):
        import inspect
        from core.pipelines import BasePipeline
        params = inspect.signature(BasePipeline.generate_subtitles_common).parameters
        assert params["video_width"].default == 1152
        assert params["video_height"].default == 648


class TestLocalWindowsContracts:
    """Windows-first local mode contract tests."""

    def test_resolution_presets_are_valid_aspect_ratios(self):
        from core.config import VIDEO_RESOLUTION_PRESETS
        assert (VIDEO_RESOLUTION_PRESETS["portrait"]["width"], VIDEO_RESOLUTION_PRESETS["portrait"]["height"]) == (768, 1152)
        assert (VIDEO_RESOLUTION_PRESETS["landscape"]["width"], VIDEO_RESOLUTION_PRESETS["landscape"]["height"]) == (1152, 648)
        assert (VIDEO_RESOLUTION_PRESETS["square"]["width"], VIDEO_RESOLUTION_PRESETS["square"]["height"]) == (1024, 1024)

    def test_start_windows_launcher_points_to_local_server(self):
        from pathlib import Path
        bat = Path("start_windows.bat").read_text(encoding="utf-8")
        assert 'set "HOST=127.0.0.1"' in bat
        assert 'set "PORT=8765"' in bat
        assert '.venv\\Scripts\\python.exe' in bat
        assert '"%PYTHON%" server.py' in bat

    def test_tts_retry_temp_path_is_defined_before_attempt(self):
        import inspect
        from core.audio.tts import EdgeTTSEngine
        source = inspect.getsource(EdgeTTSEngine.generate)
        assert source.index('tmp_path = output_path + ".tmp"') < source.index('for attempt in range(max_attempts)')


class TestTaskRecoveryNormalization:
    def test_running_state_is_reset_to_pending_on_load(self, tmp_path, monkeypatch):
        from core.task_manager import TaskManager
        from models.task import SimpleVideoTask
        monkeypatch.setattr("core.task_manager.get_working_dir", lambda: str(tmp_path))
        state = SimpleVideoTask(task_id="recover-1", status="running")
        tm = TaskManager("recover-1")
        tm.create(state)
        loaded = tm.load()
        assert loaded.status == "pending"


# ═══════════════════════════════════════════════════
# 8. Agnes current API protocol
# ═══════════════════════════════════════════════════

class TestAgnesCurrentVideoProtocol:
    """Regression tests for Agnes Video 2.5 request/poll semantics."""

    def test_modern_i2v_payload_uses_current_schema(self, monkeypatch, tmp_path):
        from core.api.agnes_video import AgnesVideoAPI

        image = tmp_path / "frame.png"
        image.write_bytes(b"fake-png")
        api = AgnesVideoAPI("test-key", model="agnes-video-2.5-flash")

        async def fake_submit(payload, mode_desc):
            assert payload["model"] == "agnes-video-2.5-flash"
            assert payload["mode"] == "img2video"
            assert payload["seconds"] == "5"
            assert payload["size"] == "720P"
            assert payload["aspect_ratio"] == "16:9"
            assert payload["n"] == 1
            assert payload["first_frame"].startswith("data:image/png;base64,")
            return "video_test"

        monkeypatch.setattr(api, "_submit_with_retry", fake_submit)

        import asyncio
        video_id = asyncio.run(
            api.submit_video(
                "cinematic motion",
                reference_image_paths=[str(image)],
                duration=5,
                width=1152,
                height=648,
            )
        )
        assert video_id == "video_test"

    def test_poll_passes_model_name_and_accepts_metadata_url(self, monkeypatch):
        from core.api.agnes_video import AgnesVideoAPI
        import asyncio

        api = AgnesVideoAPI("test-key", model="agnes-video-2.5-flash")

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "status": "completed",
                    "progress": 100,
                    "video_id": "video_test",
                    "metadata": {"url": "https://example.test/video.mp4"},
                }

        calls = []

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse()

        monkeypatch.setattr("core.api.agnes_video.requests.get", fake_get)
        monkeypatch.setattr("core.api.agnes_video.get_rate_limiter", lambda: type("Limiter", (), {"acquire": lambda self: None})())

        result = asyncio.run(api._poll_task("video_test", interval=0, max_poll_duration=5))
        assert result["status"] == "completed"
        assert calls[0][1]["params"]["video_id"] == "video_test"
        assert calls[0][1]["params"]["model_name"] == "agnes-video-2.5-flash"

        output = asyncio.run(api.wait_for_video("video_test"))
        assert output.data == "https://example.test/video.mp4"


class TestAgnesCurrentImageDefaults:
    def test_image_default_model_is_current(self):
        from core.api.agnes_image import AgnesImageAPI
        api = AgnesImageAPI("test-key")
        assert api.model == "agnes-image-2.5-flash"
        assert api.i2i_model == "agnes-image-2.5-flash"

class TestAgnesCurrentImageRequest:
    def test_legacy_pixel_size_maps_to_current_schema(self):
        from core.api.agnes_image import AgnesImageAPI
        assert AgnesImageAPI._normalize_size("1152x648") == ("1K", "16:9")
        assert AgnesImageAPI._normalize_size("768x1152") == ("1K", "9:16")
