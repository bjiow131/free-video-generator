"""Desktop GUI for the local-only Blender Work Agent.

Uses Tkinter from Python's standard library. All task execution is local and
allowlisted; the prompt is never executed as Python or shell code.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from local_agent.blender_workflow import discover_blender
from local_agent.scene_request import SceneRequestError, create_scene_from_prompt
from local_agent.scene_edit import SceneEditError, edit_existing_scene
from local_agent.video_export import PRESETS as VIDEO_PRESETS, VideoExportError, export_animation_to_mp4
from local_agent.update_manager import apply_update_archive, UpdateError

APP_VERSION = "0.6.0"
APP_TITLE = "Blender Work Agent Studio"
DEFAULT_WORKSPACE = Path(os.environ.get("LOCAL_AGENT_WORKSPACE", str(Path.home() / "BlenderAgentProjects")))
CHARACTER_DIR = Path(os.environ.get("LOCAL_AGENT_CHARACTER_LIBRARY", str(Path.home() / "BlenderAgentLibrary")))
CHARACTER_DB = CHARACTER_DIR / "characters.json"
PROMPT_LIMIT = 1200


def _safe_name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 64 or any(ch in value for ch in '<>:"/\\|?*'):
        raise ValueError("Название должно содержать от 1 до 64 символов без \\ / : * ? \" < > |.")
    if value.endswith(".") or value.endswith(" "):
        raise ValueError("Название не должно заканчиваться точкой или пробелом.")
    return value


class BlenderAgentApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE} · {APP_VERSION}")
        self.geometry("1180x820")
        self.minsize(940, 700)
        self.configure(bg="#F3F5FA")
        self.workspace = DEFAULT_WORKSPACE.expanduser()
        self.workspace.mkdir(parents=True, exist_ok=True)
        CHARACTER_DIR.mkdir(parents=True, exist_ok=True)
        self.active_project: Path | None = None
        self._busy = False
        self._build_styles()
        self._build_header()
        self._build_tabs()
        self._set_status("Готов к работе. Выберите проект или введите новое задание.")
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_styles(self) -> None:
        # Calm editorial studio palette: ink, porcelain and a restrained violet accent.
        self.colors = {
            "canvas": "#F3F5FA", "surface": "#FFFFFF", "surface_alt": "#F8F9FD",
            "ink": "#182238", "muted": "#69758B", "line": "#E2E7F0",
            "accent": "#6558E8", "accent_hover": "#5145D2", "accent_soft": "#EEECFF",
            "success": "#16836B", "danger": "#C64C5B", "header": "#171D32",
        }
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        palette = self.colors
        self.configure(bg=palette["canvas"])
        style.configure(".", font=("Segoe UI", 10), foreground=palette["ink"])
        style.configure("TFrame", background=palette["canvas"])
        style.configure("Panel.TFrame", background=palette["surface"])
        style.configure("Inset.TFrame", background=palette["surface_alt"])
        style.configure("TLabel", background=palette["canvas"], foreground=palette["ink"], font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 22), foreground=palette["ink"])
        style.configure("Subtitle.TLabel", font=("Segoe UI", 9), foreground=palette["muted"])
        style.configure("PanelTitle.TLabel", background=palette["surface"], font=("Segoe UI Semibold", 11), foreground=palette["ink"])
        style.configure("PanelHero.TLabel", background=palette["surface"], font=("Segoe UI Semibold", 18), foreground=palette["ink"])
        style.configure("Eyebrow.TLabel", background=palette["surface"], foreground=palette["accent"], font=("Segoe UI Semibold", 9))
        style.configure("Header.TFrame", background=palette["header"])
        style.configure("HeaderTitle.TLabel", background=palette["header"], foreground="#FFFFFF", font=("Segoe UI Semibold", 19))
        style.configure("HeaderSubtitle.TLabel", background=palette["header"], foreground="#B8C0D4", font=("Segoe UI", 9))
        style.configure("Badge.TLabel", background="#282F49", foreground="#E5E8F5", padding=(12, 7), font=("Segoe UI Semibold", 9))
        style.configure("TButton", font=("Segoe UI Semibold", 9), padding=(12, 8), background=palette["surface"], foreground=palette["ink"], bordercolor=palette["line"], focusthickness=0)
        style.map("TButton", background=[("active", palette["accent_soft"]), ("pressed", palette["accent_soft"])], foreground=[("active", palette["accent"])])
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(16, 10), background=palette["accent"], foreground="#FFFFFF", bordercolor=palette["accent"], focusthickness=0)
        style.map("Accent.TButton", background=[("active", palette["accent_hover"]), ("pressed", palette["accent_hover"]), ("disabled", "#B7B3E9")], foreground=[("disabled", "#FFFFFF")])
        style.configure("TNotebook", background=palette["canvas"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", font=("Segoe UI Semibold", 10), padding=(20, 12), background=palette["canvas"], foreground=palette["muted"], borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", palette["surface"]), ("active", palette["accent_soft"])], foreground=[("selected", palette["accent"]), ("active", palette["ink"])], expand=[("selected", (0, 0, 0, 1))])
        style.configure("Treeview", rowheight=34, font=("Segoe UI", 10), background=palette["surface"], fieldbackground=palette["surface"], foreground=palette["ink"], borderwidth=0, relief="flat")
        style.map("Treeview", background=[("selected", palette["accent_soft"])], foreground=[("selected", palette["ink"])])
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background=palette["surface_alt"], foreground=palette["muted"], padding=(8, 9), borderwidth=0)
        style.configure("TCombobox", padding=(8, 7), fieldbackground=palette["surface"], background=palette["surface"], foreground=palette["ink"], arrowcolor=palette["accent"])
        style.map("TCombobox", fieldbackground=[("readonly", palette["surface"])], selectbackground=[("readonly", palette["surface"])], selectforeground=[("readonly", palette["ink"])])
        style.configure("TEntry", padding=(9, 8), fieldbackground=palette["surface"], foreground=palette["ink"], bordercolor=palette["line"])
        style.configure("TSeparator", background=palette["line"])

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(28, 20, 28, 20))
        header.pack(fill="x")
        left = ttk.Frame(header, style="Header.TFrame")
        left.pack(side="left", fill="x", expand=True)
        brand = ttk.Frame(left, style="Header.TFrame")
        brand.pack(anchor="w")
        ttk.Label(brand, text="BLENDER", style="HeaderSubtitle.TLabel").pack(side="left")
        ttk.Label(brand, text="  /  STUDIO", style="HeaderSubtitle.TLabel").pack(side="left")
        ttk.Label(left, text="Blender Work Agent", style="HeaderTitle.TLabel").pack(anchor="w", pady=(5, 1))
        ttk.Label(left, text="Локальная среда производства сцен, персонажей и анимации", style="HeaderSubtitle.TLabel").pack(anchor="w")
        self.project_badge = ttk.Label(header, text="●  ПРОЕКТ НЕ ОТКРЫТ", style="Badge.TLabel")
        self.project_badge.pack(side="right", anchor="center", padx=(16, 0))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.task_tab = ttk.Frame(self.tabs, padding=18)
        self.library_tab = ttk.Frame(self.tabs, padding=18)
        self.update_tab = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(self.task_tab, text="  Сцена  ")
        self.tabs.add(self.library_tab, text="  Библиотека  ")
        self.tabs.add(self.update_tab, text="  Обновление  ")
        self._build_task_tab()
        self._build_library_tab()
        self._build_update_tab()
        footer = ttk.Frame(self, padding=(20, 0, 20, 14))
        footer.pack(fill="x")
        self.status_var = tk.StringVar(value="")
        ttk.Label(footer, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Label(footer, text="STUDIO WORKSPACE   ·   Локальные проекты и референсы", style="Subtitle.TLabel").pack(side="right")

    def _build_task_tab(self) -> None:
        project = ttk.Frame(self.task_tab, style="Panel.TFrame", padding=14)
        project.pack(fill="x", pady=(0, 12))
        ttk.Label(project, text="Текущий проект", style="PanelTitle.TLabel").pack(anchor="w")
        row = ttk.Frame(project, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 2))
        self.project_label_var = tk.StringVar(value="Новый проект: задание будет обработано как создание сцены.")
        ttk.Label(row, textvariable=self.project_label_var, background=self.colors["surface"], foreground=self.colors["ink"]).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Открыть готовый проект…", command=self._open_project).pack(side="right")
        ttk.Button(row, text="Сбросить проект", command=self._clear_project).pack(side="right", padx=(0, 8))
        ttk.Button(row, text="Экспортировать видео…", command=self._export_video).pack(side="right", padx=(0, 8))

        prompt_panel = ttk.Frame(self.task_tab, style="Panel.TFrame", padding=22)
        prompt_panel.pack(fill="both", expand=True)
        prompt_heading = ttk.Frame(prompt_panel, style="Panel.TFrame")
        prompt_heading.pack(fill="x")
        ttk.Label(prompt_heading, text="СОЗДАНИЕ СЦЕНЫ", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(prompt_heading, text="Опиши, что должно произойти", style="PanelHero.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(prompt_heading, text="Укажи действие, окружение, стиль, движение камеры и нужные референсы персонажей.", background=self.colors["surface"], foreground=self.colors["muted"], wraplength=920).pack(anchor="w", pady=(0, 12))

        settings_row = ttk.Frame(prompt_panel, style="Panel.TFrame")
        settings_row.pack(fill="x", pady=(0, 12))
        ttk.Label(settings_row, text="Визуальный режим", style="PanelTitle.TLabel").pack(side="left", padx=(0, 12))
        self.visual_mode_var = tk.StringVar(value="Стилизованная 3D-сцена")
        self.visual_mode_combo = ttk.Combobox(settings_row, textvariable=self.visual_mode_var, state="readonly", width=27,
            values=("Стилизованная 3D-сцена", "Реалистичная сцена", "Свободный стиль"))
        self.visual_mode_combo.pack(side="left")
        ttk.Label(settings_row, text="Режим задаёт направление проекта; доступная детализация зависит от текущего генератора.", background=self.colors["surface"], foreground=self.colors["muted"]).pack(side="left", padx=(12, 0))

        character_panel = ttk.Frame(prompt_panel, style="Inset.TFrame", padding=12)
        character_panel.pack(fill="x", pady=(0, 12))
        character_head = ttk.Frame(character_panel, style="Inset.TFrame")
        character_head.pack(fill="x")
        ttk.Label(character_head, text="ПЕРСОНАЖИ СЦЕНЫ", background=self.colors["surface_alt"], foreground=self.colors["accent"], font=("Segoe UI Semibold", 9)).pack(side="left")
        ttk.Label(character_head, text="Можно не выбирать вручную — поиск по именам в задании включён", background=self.colors["surface_alt"], foreground=self.colors["muted"], font=("Segoe UI", 9)).pack(side="right")
        self.character_selection_list = tk.Listbox(character_panel, selectmode="extended", height=3, exportselection=False,
            font=("Segoe UI", 10), relief="flat", bd=0, highlightthickness=1,
            highlightbackground=self.colors["line"], highlightcolor=self.colors["accent"],
            bg=self.colors["surface"], fg=self.colors["ink"], selectbackground=self.colors["accent_soft"],
            selectforeground=self.colors["ink"], activestyle="none")
        self.character_selection_list.pack(side="left", fill="x", expand=True, pady=(9, 0))
        selection_actions = ttk.Frame(character_panel, style="Inset.TFrame")
        selection_actions.pack(side="right", fill="y", padx=(12, 0), pady=(9, 0))
        ttk.Button(selection_actions, text="Обновить", command=self._refresh_character_choices).pack(fill="x")
        ttk.Button(selection_actions, text="Библиотека персонажей", command=lambda: self.tabs.select(self.library_tab)).pack(fill="x", pady=(7, 0))
        self.character_selection_list.bind("<Double-Button-1>", self._open_selected_character_card)

        ttk.Label(prompt_panel, text="ТЕКСТ ЗАДАНИЯ", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 6))
        self.prompt = tk.Text(prompt_panel, height=9, wrap="word", font=("Segoe UI", 11), undo=True,
            relief="flat", bd=0, padx=14, pady=12, highlightthickness=1,
            highlightbackground=self.colors["line"], highlightcolor=self.colors["accent"],
            bg=self.colors["surface_alt"], fg=self.colors["ink"], insertbackground=self.colors["accent"],
            selectbackground=self.colors["accent_soft"], selectforeground=self.colors["ink"])
        self.prompt.pack(fill="both", expand=True)
        self.prompt.insert("1.0", "Например: В сцене участвуют Мия (референсы №2 и №3) и Степа (референс «Профиль справа»). Они встречают друг друга на лесной тропе. Камера плавно приближается. Вертикально 9:16.")
        self.prompt.bind("<KeyRelease>", self._update_prompt_count)
        bottom = ttk.Frame(prompt_panel, style="Panel.TFrame")
        bottom.pack(fill="x", pady=(10, 0))
        self.prompt_count = ttk.Label(bottom, text=f"0 / {PROMPT_LIMIT}", background=self.colors["surface"], foreground=self.colors["muted"])
        self.prompt_count.pack(side="left")
        self.create_btn = ttk.Button(bottom, text="Создать / выполнить задание", style="Accent.TButton", command=self._submit_task)
        self.create_btn.pack(side="right")
        ttk.Label(prompt_panel, text="Поддерживаются описания сцен, окружения, композиции, света, движения и формата кадра. Референсы нумеруются в порядке списка карточки; можно указать номер или точную метку позы. Если точная 3D-модель по референсам ещё не построена, агент сохранит связь с исходными изображениями, но не будет выдавать простую модель за точную копию.", background=self.colors["surface"], foreground=self.colors["muted"], wraplength=920).pack(anchor="w", pady=(10, 0))

    def _build_library_tab(self) -> None:
        top = ttk.Frame(self.library_tab)
        top.pack(fill="x", pady=(0, 16))
        title_block = ttk.Frame(top)
        title_block.pack(side="left", fill="x", expand=True)
        ttk.Label(title_block, text="БИБЛИОТЕКА АССЕТОВ", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(title_block, text="Персонажи и референсы", style="Title.TLabel").pack(anchor="w", pady=(3, 3))
        ttk.Label(title_block, text="Независимые карточки героев для любых будущих проектов — мультфильмов, животных, существ и реалистичных сцен.", foreground=self.colors["muted"]).pack(anchor="w")
        ttk.Button(top, text="+  Новая карточка", style="Accent.TButton", command=self._add_character).pack(side="right", padx=(14, 0))
        split = ttk.Panedwindow(self.library_tab, orient="horizontal")
        split.pack(fill="both", expand=True)
        left = ttk.Frame(split, padding=(0, 0, 10, 0))
        right = ttk.Frame(split, padding=(10, 0, 0, 0))
        split.add(left, weight=1)
        split.add(right, weight=2)
        ttk.Label(left, text="КАРТОЧКИ ПЕРСОНАЖЕЙ", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 8))
        gallery_wrap = ttk.Frame(left, style="Inset.TFrame", padding=5)
        gallery_wrap.pack(fill="both", expand=True)
        self.character_gallery_canvas = tk.Canvas(gallery_wrap, bg=self.colors["surface_alt"], highlightthickness=0, bd=0)
        gallery_scroll = ttk.Scrollbar(gallery_wrap, orient="vertical", command=self.character_gallery_canvas.yview)
        self.character_gallery_canvas.configure(yscrollcommand=gallery_scroll.set)
        gallery_scroll.pack(side="right", fill="y")
        self.character_gallery_canvas.pack(side="left", fill="both", expand=True)
        self.character_gallery_frame = tk.Frame(self.character_gallery_canvas, bg=self.colors["surface_alt"])
        self.character_gallery_window = self.character_gallery_canvas.create_window((0, 0), window=self.character_gallery_frame, anchor="nw")
        self.character_gallery_frame.bind("<Configure>", lambda _e: self.character_gallery_canvas.configure(scrollregion=self.character_gallery_canvas.bbox("all")))
        self.character_gallery_canvas.bind("<Configure>", lambda e: self.character_gallery_canvas.itemconfigure(self.character_gallery_window, width=e.width))
        self.character_gallery_canvas.bind_all("<MouseWheel>", self._scroll_character_gallery, add="+")
        # Keep an internal selection model compatible with the reference-tab workflow.
        self.character_tree = ttk.Treeview(left, columns=("type",), show="tree headings", selectmode="browse")
        self.character_tree.bind("<<TreeviewSelect>>", self._select_character)
        self.character_tree.bind("<Double-Button-1>", self._open_character_references)
        self.character_detail = tk.Text(right, height=12, wrap="word", font=("Segoe UI", 10), relief="flat", bd=0, padx=14, pady=14,
            highlightthickness=1, highlightbackground=self.colors["line"], highlightcolor=self.colors["accent"],
            bg=self.colors["surface"], fg=self.colors["ink"], insertbackground=self.colors["accent"])
        self.character_detail.pack(fill="both", expand=True)
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Добавить изображение-референс…", command=self._add_reference).pack(side="left")
        ttk.Button(actions, text="Открыть изображение", command=self._open_reference).pack(side="left", padx=8)
        ttk.Button(actions, text="Изменить описание", command=self._edit_character).pack(side="left")
        ttk.Button(actions, text="Удалить карточку", command=self._delete_character).pack(side="right")
        ttk.Label(right, text=f"Файлы хранятся локально: {CHARACTER_DIR}", wraplength=650).pack(anchor="w", pady=(8, 0))
        self.reference_tabs: dict[str, ttk.Frame] = {}
        self._refresh_characters()

    def _build_update_tab(self) -> None:
        panel = ttk.Frame(self.update_tab, style="Panel.TFrame", padding=18)
        panel.pack(fill="x", anchor="n")
        ttk.Label(panel, text="Обновление отдельными файлами", style="Title.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Обновление устанавливается из ZIP-пакета: агент проверяет хеши и пути, создаёт резервные копии и не удаляет проекты. После обновления приложение нужно перезапустить.", background="#ffffff", wraplength=850).pack(anchor="w", pady=(8, 12))
        ttk.Label(panel, text=f"Версия интерфейса: {APP_VERSION}", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Выбери ZIP-пакет обновления с update_manifest.json и файлами внутри payload/. В манифесте перечислены только новые или заменяемые файлы.", background="#ffffff", wraplength=850).pack(anchor="w", pady=(6, 12))
        ttk.Button(panel, text="Установить обновление из папки…", command=self._apply_update).pack(anchor="w")
        ttk.Button(panel, text="Открыть папку агента", command=self._open_agent_folder).pack(anchor="w", pady=(8, 0))
        ttk.Label(self.update_tab, text="Обновление кода не требует переустановки Python/Blender. Не закрывайте приложение до завершения резервного копирования.", wraplength=850).pack(anchor="w", pady=(14, 0))

    def _set_status(self, value: str) -> None:
        if hasattr(self, "status_var"):
            self.status_var.set(value)

    def _update_prompt_count(self, _event=None) -> None:
        value = self.prompt.get("1.0", "end-1c")
        self.prompt_count.configure(text=f"{len(value)} / {PROMPT_LIMIT}")
        if len(value) > PROMPT_LIMIT:
            self.prompt_count.configure(foreground="#b42318")
        else:
            self.prompt_count.configure(foreground=self.colors["muted"])

    def _ask_confirm(self, operation: str) -> bool:
        return messagebox.askyesno("Подтверждение задания", f"Перед запуском проверьте задачу:\n\n{operation}\n\nПродолжить?", parent=self)

    def _open_project(self) -> None:
        path = filedialog.askopenfilename(title="Выберите готовый проект Blender", filetypes=[("Blender project", "*.blend"), ("All files", "*.*")], parent=self)
        if not path:
            return
        project = Path(path).expanduser().resolve()
        if not project.is_file() or project.suffix.lower() != ".blend":
            messagebox.showerror("Не удалось открыть проект", "Выберите существующий файл .blend.", parent=self)
            return
        blender_info = discover_blender()
        if not blender_info.get("available"):
            messagebox.showerror("Blender не найден", "Проверьте путь к Blender в run_blender_agent.bat.", parent=self)
            return
        self.active_project = project
        self.project_label_var.set(f"Открыт проект: {project}")
        self.project_badge.configure(text=f"●  ПРОЕКТ  /  {project.name}")
        self._set_status("Проект выбран. Следующее задание будет обработано как доработка этого проекта.")
        if messagebox.askyesno("Открыть проект", "Открыть выбранный проект в графическом интерфейсе Blender сейчас?", parent=self):
            try:
                subprocess.Popen([blender_info["path"], str(project)], cwd=str(project.parent), shell=False, close_fds=True)
            except OSError as exc:
                messagebox.showerror("Ошибка запуска Blender", f"Не удалось открыть Blender: {exc}", parent=self)

    def _choose_video_preset(self) -> str | None:
        window = tk.Toplevel(self)
        window.title("Формат видео")
        window.transient(self)
        window.grab_set()
        window.resizable(False, False)
        panel = ttk.Frame(window, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Выберите площадку для экспорта:").pack(anchor="w", pady=(0, 8))
        selected = tk.StringVar(value="YouTube Shorts")
        combo = ttk.Combobox(panel, textvariable=selected, values=list(VIDEO_PRESETS), state="readonly", width=28)
        combo.pack(fill="x", pady=(0, 12))
        result = {"value": None}
        def accept():
            result["value"] = selected.get()
            window.destroy()
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Отмена", command=window.destroy).pack(side="right")
        ttk.Button(buttons, text="Продолжить", command=accept).pack(side="right", padx=(0, 8))
        window.wait_window()
        return result["value"]

    def _export_video(self) -> None:
        project = self.active_project
        if not project or not project.is_file():
            chosen = filedialog.askopenfilename(title="Выберите анимированный проект Blender", filetypes=[("Blender project", "*.blend")], parent=self)
            if not chosen:
                return
            project = Path(chosen).expanduser().resolve()
        preset = self._choose_video_preset()
        if not preset:
            return
        details = VIDEO_PRESETS[preset]
        default_name = project.stem + "_" + preset.lower().replace(" ", "_") + ".mp4"
        destination = filedialog.asksaveasfilename(title="Сохранить готовое видео", defaultextension=".mp4", initialfile=default_name, filetypes=[("MP4 video", "*.mp4")], parent=self)
        if not destination:
            return
        output = Path(destination).expanduser().resolve()
        if output.exists():
            messagebox.showerror("Файл уже существует", "Выберите другое имя, чтобы не перезаписать готовое видео.", parent=self)
            return
        if not self._ask_confirm(f"Платформа: {preset}\nРазрешение: {details['resolution'][0]} × {details['resolution'][1]}\nПроект: {project}\nВидео: {output}"):
            return
        self._busy = True
        self.create_btn.configure(state="disabled")
        self._set_status("Рендер видео выполняется в Blender…")
        threading.Thread(target=self._run_video_export, args=(project, output, preset), daemon=True).start()

    def _run_video_export(self, project: Path, output: Path, preset: str) -> None:
        try:
            blender_info = discover_blender()
            if not blender_info.get("available"):
                raise VideoExportError("Blender не найден. Проверьте настройки запуска.")
            result = export_animation_to_mp4(project, output, preset, blender_info["path"])
            self.after(0, lambda: self._video_export_success(result))
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.after(0, lambda msg=message: self._video_export_failed(msg))

    def _video_export_success(self, result: dict) -> None:
        self._busy = False
        self.create_btn.configure(state="normal")
        self._set_status("Видео экспортировано: " + result["output_path"])
        messagebox.showinfo("Видео готово", f'Платформа: {result["preset"]}\nФайл: {result["output_path"]}\nРазрешение: {result["resolution"][0]} × {result["resolution"][1]}\nFPS: {result["fps"]}\nЛог: {result["log_path"]}', parent=self)

    def _video_export_failed(self, message: str) -> None:
        self._busy = False
        self.create_btn.configure(state="normal")
        self._set_status("Экспорт видео не выполнен.")
        messagebox.showerror("Не удалось экспортировать видео", message, parent=self)

    def _clear_project(self) -> None:
        self.active_project = None
        self.project_label_var.set("Новый проект: задание будет обработано как создание сцены.")
        self.project_badge.configure(text="●  НОВАЯ СЦЕНА")
        self._set_status("Режим нового проекта. Следующее задание будет рассматриваться как создание сцены.")

    def _submit_task(self) -> None:
        if self._busy:
            return
        prompt = self.prompt.get("1.0", "end-1c").strip()
        if not prompt:
            messagebox.showwarning("Нет задания", "Вставьте задание в текстовое поле.", parent=self)
            return
        if len(prompt) > PROMPT_LIMIT:
            messagebox.showwarning("Слишком длинное задание", f"Максимум {PROMPT_LIMIT} символов в этой версии.", parent=self)
            return
        selected_characters = self._resolve_character_cards_from_prompt(prompt)
        mentioned = [card["name"] for card in selected_characters]
        if len(selected_characters) > 8:
            messagebox.showwarning("Слишком много персонажей", "Для одной сцены пока можно использовать не более 8 персонажей.", parent=self)
            return
        character_summary = ""
        if selected_characters:
            character_summary = "\n\nПерсонажи из карточек: " + ", ".join(mentioned)
        visual_mode = self.visual_mode_var.get() if not self.active_project and hasattr(self, "visual_mode_var") else "Свободный стиль"
        mode = "доработка открытого проекта" if self.active_project else f"создание новой сцены · {visual_mode}"
        if not self._ask_confirm(f"Режим: {mode}{character_summary}\n\n{prompt}"):
            self._set_status("Задание отменено.")
            return
        self._busy = True
        self.create_btn.configure(state="disabled")
        self._set_status("Выполняю локальную задачу в Blender…")
        threading.Thread(target=self._run_task, args=(prompt, self.active_project, selected_characters, visual_mode), daemon=True).start()

    def _run_task(self, prompt: str, existing: Path | None, character_cards: list[dict] | None = None, visual_mode: str = "Свободный стиль") -> None:
        try:
            blender_info = discover_blender()
            if not blender_info.get("available"):
                raise RuntimeError("Blender не найден. Проверьте настройки запуска.")
            if existing:
                result = edit_existing_scene(prompt, existing, blender_info["path"], self.workspace)
            else:
                staging_name = f"agent_draft_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
                result = create_scene_from_prompt(prompt, staging_name, character_cards=character_cards, visual_mode=visual_mode)
            self.after(0, lambda: self._task_success(result, prompt, existing))
        except Exception as exc:
            details = f"{type(exc).__name__}: {exc}"
            self.after(0, lambda msg=details: self._task_failed(msg))

    def _task_success(self, result: dict, prompt: str, existing: Path | None) -> None:
        self._busy = False
        self.create_btn.configure(state="normal")
        if result.get("status") != "completed":
            messagebox.showwarning("Задача не выполнена", json.dumps(result, ensure_ascii=False, indent=2), parent=self)
            self._set_status("Задача не завершена.")
            return
        messagebox.showinfo("Задача выполнена", "Blender сообщил об успешном выполнении и проверке файлов результата. Теперь выберите место и имя сохранения.", parent=self)
        source_blend = Path(result["blend_path"])
        source_preview = Path(result["preview_path"])
        default_name = (existing.stem + "_edited" if existing else "blender_project") + ".blend"
        destination = filedialog.asksaveasfilename(title="Сохранить готовый проект как…", defaultextension=".blend", initialfile=default_name, filetypes=[("Blender project", "*.blend")], parent=self)
        if not destination:
            self._set_status(f"Проект сохранён как черновик: {source_blend}")
            messagebox.showinfo("Черновик сохранён", f"Вы отменили выбор конечного места. Черновик не удалён:\n{source_blend}", parent=self)
            return
        dest = Path(destination).expanduser().resolve()
        if dest.suffix.lower() != ".blend":
            dest = dest.with_suffix(".blend")
        if existing and dest == existing.resolve():
            messagebox.showerror("Защита исходного проекта", "Исходный проект не перезаписывается. Выберите другое имя.", parent=self)
            return
        if dest.exists() and not messagebox.askyesno("Файл уже существует", f"{dest}\n\nПерезаписать этот файл?", parent=self):
            self._set_status("Сохранение отменено; черновик сохранён.")
            return
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_blend, dest)
            preview_dest = dest.with_name(dest.stem + "_preview.png")
            shutil.copy2(source_preview, preview_dest)
            manifest_dest = dest.with_name(dest.stem + "_result.json")
            manifest = dict(result)
            manifest["blend_path"] = str(dest)
            manifest["preview_path"] = str(preview_dest)
            manifest["source_prompt"] = prompt
            manifest["mode"] = "edit_existing" if existing else "new_scene"
            manifest_dest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Ошибка сохранения", f"Не удалось скопировать результат: {exc}\nЧерновик сохранён в {source_blend}", parent=self)
            self._set_status("Не удалось сохранить в выбранное место; черновик сохранён.")
            return
        self.active_project = dest
        self.project_label_var.set(f"Открыт проект: {dest}")
        self.project_badge.configure(text=f"Редактирование: {dest.name}")
        self._set_status(f"Готово. Проект: {dest}")
        messagebox.showinfo("Проект сохранён", f"Проект:\n{dest}\n\nПредпросмотр:\n{preview_dest}\n\nИсходный проект не изменён.", parent=self)

    def _task_failed(self, message: str) -> None:
        self._busy = False
        self.create_btn.configure(state="normal")
        self._set_status("Задача не выполнена.")
        messagebox.showerror("Задача не выполнена", message, parent=self)

    def _load_characters(self) -> list[dict]:
        try:
            data = json.loads(CHARACTER_DB.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_characters(self, data: list[dict]) -> None:
        tmp = CHARACTER_DB.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, CHARACTER_DB)

    def _scroll_character_gallery(self, event) -> None:
        if not hasattr(self, "character_gallery_canvas"):
            return
        self.character_gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _choose_character_card(self, card_id: str, double: bool = False) -> None:
        if self.character_tree.exists(card_id):
            self.character_tree.selection_set(card_id)
            self.character_tree.focus(card_id)
        self._select_character()
        for other_id, parts in getattr(self, "character_card_tiles", {}).items():
            selected = other_id == card_id
            parts["tile"].configure(highlightbackground=self.colors["accent"] if selected else self.colors["line"])
            parts["stripe"].configure(bg=self.colors["accent"] if selected else self.colors["line"])
            parts["refs"].configure(fg=self.colors["accent"] if selected else self.colors["muted"])
        if double:
            self._open_character_references()

    def _refresh_character_gallery(self, selected_id: str | None = None) -> None:
        if not hasattr(self, "character_gallery_frame"):
            return
        self.character_card_tiles = {}
        for widget in self.character_gallery_frame.winfo_children():
            widget.destroy()
        cards = [card for card in self._load_characters() if card.get("kind", "Персонаж") != "Референс"]
        if not cards:
            empty = tk.Label(self.character_gallery_frame, text="Библиотека пока пуста\n\nСоздай карточку первого героя.", justify="center",
                bg=self.colors["surface_alt"], fg=self.colors["muted"], font=("Segoe UI", 10), padx=16, pady=32)
            empty.pack(fill="x")
            return
        for card in cards:
            is_selected = card.get("id") == selected_id
            tile = tk.Frame(self.character_gallery_frame, bg=self.colors["surface"],
                highlightthickness=1, highlightbackground=self.colors["accent"] if is_selected else self.colors["line"], bd=0)
            tile.pack(fill="x", padx=3, pady=4)
            stripe = tk.Frame(tile, bg=self.colors["accent"] if is_selected else self.colors["line"], width=4)
            stripe.pack(side="left", fill="y")
            body = tk.Frame(tile, bg=self.colors["surface"], padx=11, pady=10)
            body.pack(side="left", fill="both", expand=True)
            name = tk.Label(body, text=card.get("name", "Без имени"), bg=self.colors["surface"], fg=self.colors["ink"],
                font=("Segoe UI Semibold", 10), anchor="w")
            name.pack(fill="x")
            category = card.get("profile_type", "Человек")
            style_name = card.get("visual_style", "Стилизованный 3D")
            meta = tk.Label(body, text=f"{category}  ·  {style_name}", bg=self.colors["surface"], fg=self.colors["muted"],
                font=("Segoe UI", 8), anchor="w")
            meta.pack(fill="x", pady=(3, 2))
            refs = tk.Label(body, text=f"{len(card.get('references', []))} референсов  ·  двойной щелчок — открыть", bg=self.colors["surface"],
                fg=self.colors["accent"] if is_selected else self.colors["muted"], font=("Segoe UI", 8), anchor="w")
            refs.pack(fill="x")
            self.character_card_tiles[card["id"]] = {"tile": tile, "stripe": stripe, "refs": refs}
            for widget in (tile, stripe, body, name, meta, refs):
                widget.bind("<Button-1>", lambda _e, cid=card["id"]: self._choose_character_card(cid))
                widget.bind("<Double-Button-1>", lambda _e, cid=card["id"]: self._choose_character_card(cid, True))

    def _refresh_characters(self, select_id: str | None = None) -> None:
        if not hasattr(self, "character_tree"):
            return
        for item in self.character_tree.get_children():
            self.character_tree.delete(item)
        for card in self._load_characters():
            self.character_tree.insert("", "end", iid=card["id"], text=card.get("name", "Без имени"), values=(card.get("kind", "Персонаж"),))
        if select_id and self.character_tree.exists(select_id):
            self.character_tree.selection_set(select_id)
            self.character_tree.focus(select_id)
            self._select_character()
        elif not select_id:
            selection = self.character_tree.selection()
            if selection:
                self.character_tree.selection_remove(*selection)
                self.character_detail.configure(state="normal")
                self.character_detail.delete("1.0", "end")
                self.character_detail.configure(state="disabled")
        self._refresh_character_gallery(select_id or (self.character_tree.selection()[0] if self.character_tree.selection() else None))
        self._refresh_character_choices(select_id)
        for card in self._load_characters():
            frame = self.reference_tabs.get(card.get("id"))
            if frame is not None and frame.winfo_exists():
                self.tabs.tab(frame, text=f"Референсы: {card.get('name', 'Персонаж')}"[:32])
                self._refresh_reference_tab(card)

    def _refresh_character_choices(self, select_id: str | None = None) -> None:
        if not hasattr(self, "character_selection_list"):
            return
        selected_ids = {self._character_choice_ids[i] for i in self.character_selection_list.curselection()
                        if i < len(getattr(self, "_character_choice_ids", []))}
        if select_id:
            selected_ids.add(select_id)
        cards = [card for card in self._load_characters() if card.get("kind", "Персонаж") != "Референс"]
        self._character_choice_ids = []
        self.character_selection_list.delete(0, "end")
        for card in cards:
            self._character_choice_ids.append(card["id"])
            self.character_selection_list.insert("end", card.get("name", "Без имени"))
        for index, card_id in enumerate(self._character_choice_ids):
            if card_id in selected_ids:
                self.character_selection_list.selection_set(index)

    def _selected_character_cards(self) -> list[dict]:
        ids = [self._character_choice_ids[i] for i in self.character_selection_list.curselection()
               if i < len(self._character_choice_ids)]
        by_id = {card.get("id"): card for card in self._load_characters()}
        return [by_id[card_id] for card_id in ids if card_id in by_id]

    def _resolve_character_cards_from_prompt(self, prompt: str) -> list[dict]:
        """Use card names mentioned in the task, plus explicit manual selections."""
        if self.active_project:
            return []
        chosen = {card.get("id"): card for card in self._selected_character_cards()}
        normalized_prompt = prompt.casefold()
        for card in self._load_characters():
            if card.get("kind", "Персонаж") == "Референс":
                continue
            name = str(card.get("name", "")).strip().casefold()
            if not name:
                continue
            name_pattern = r"(?<![\w])" + re.escape(name)
            if len(name) >= 5:
                # Match common inflections without confusing unrelated short names.
                name_pattern = r"(?<![\w])(?:" + re.escape(name) + r"|" + re.escape(name[:-1]) + r"[а-яё]{0,3})(?![\w])"
            if re.search(name_pattern, normalized_prompt):
                chosen[card.get("id")] = card
        return list(chosen.values())

    def _open_selected_character_card(self, _event=None) -> None:
        cards = self._selected_character_cards()
        if not cards:
            return
        self.tabs.select(self.library_tab)
        self._refresh_characters(cards[0]["id"])
        if len(cards) == 1:
            self._open_character_references()

    def _open_character_references(self, _event=None) -> None:
        card = self._selected_card()
        if not card:
            return
        card_id = card["id"]
        existing = self.reference_tabs.get(card_id)
        if existing is not None and existing.winfo_exists():
            self.tabs.select(existing)
            self._refresh_reference_tab(card)
            return
        frame = ttk.Frame(self.tabs, padding=18)
        self.reference_tabs[card_id] = frame
        self.tabs.add(frame, text=f"Референсы: {card.get('name', 'Персонаж')}"[:32])
        heading = ttk.Frame(frame)
        heading.pack(fill="x", pady=(0, 10))
        ttk.Label(heading, text=f"Референсы персонажа «{card.get('name', '')}»", style="Title.TLabel").pack(side="left")
        ttk.Button(heading, text="Добавить референсы…", command=lambda cid=card_id: self._add_reference_to_card(cid)).pack(side="right")
        tree = ttk.Treeview(frame, columns=("pose", "path"), show="headings", selectmode="browse")
        tree.heading("pose", text="Поза / вид")
        tree.heading("path", text="Файл")
        tree.column("pose", width=220, stretch=False)
        tree.column("path", width=650)
        tree.pack(fill="both", expand=True)
        tree.bind("<Double-Button-1>", lambda _event, cid=card_id: self._open_reference_from_tab(cid))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Открыть выбранный", command=lambda cid=card_id: self._open_reference_from_tab(cid)).pack(side="left")
        ttk.Button(actions, text="Назвать позу…", command=lambda cid=card_id: self._label_reference_pose(cid)).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Открыть карточку", command=lambda cid=card_id: self._select_card_in_library(cid)).pack(side="left", padx=(8, 0))
        setattr(frame, "reference_tree", tree)
        self._refresh_reference_tab(card)
        self.tabs.select(frame)

    def _refresh_reference_tab(self, card: dict) -> None:
        frame = self.reference_tabs.get(card["id"])
        if frame is None or not frame.winfo_exists():
            return
        tree = getattr(frame, "reference_tree", None)
        if tree is None:
            return
        for iid in tree.get_children():
            tree.delete(iid)
        labels = card.get("reference_labels", {})
        if not isinstance(labels, dict):
            labels = {}
        for index, path in enumerate(card.get("references", [])):
            p = Path(path)
            label = labels.get(str(path)) or (p.stem.split("_", 1)[1] if "_" in p.stem else p.stem)
            tree.insert("", "end", iid=str(index), values=(label, str(p)))

    def _label_reference_pose(self, card_id: str) -> None:
        frame = self.reference_tabs.get(card_id)
        tree = getattr(frame, "reference_tree", None) if frame is not None else None
        selected = tree.selection() if tree is not None else ()
        if not selected:
            messagebox.showinfo("Выберите референс", "Выберите изображение, для которого нужно задать название позы.", parent=self)
            return
        data = self._load_characters()
        card = next((item for item in data if item.get("id") == card_id), None)
        if not card:
            return
        try:
            path = str(card.get("references", [])[int(selected[0])])
        except (IndexError, ValueError, TypeError):
            return
        saved_labels = card.get("reference_labels", {})
        if not isinstance(saved_labels, dict):
            saved_labels = {}
        current = saved_labels.get(path, Path(path).stem)
        label = simpledialog.askstring("Название позы", "Например: Фронт, Профиль слева, Вид сзади, Бег, Едет на самокате:", initialvalue=current, parent=self)
        if label is None:
            return
        label = label.strip()[:80]
        if not label:
            messagebox.showwarning("Пустое название", "Название позы не может быть пустым.", parent=self)
            return
        card.setdefault("reference_labels", {})[path] = label
        self._save_characters(data)
        self._refresh_reference_tab(card)
        self._refresh_characters(card_id)

    def _select_card_in_library(self, card_id: str) -> None:
        self.tabs.select(self.library_tab)
        self._refresh_characters(card_id)

    def _add_reference_to_card(self, card_id: str) -> None:
        card = next((item for item in self._load_characters() if item.get("id") == card_id), None)
        if not card:
            return
        paths = filedialog.askopenfilenames(title=f"Добавить референсы для «{card['name']}»",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff")], parent=self)
        if not paths:
            return
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
        folder = CHARACTER_DIR / card_id
        folder.mkdir(parents=True, exist_ok=True)
        added = []
        for raw in paths:
            src = Path(raw)
            try:
                if src.suffix.lower() not in allowed or src.stat().st_size > 30 * 1024 * 1024:
                    continue
                index = len(card.get("references", [])) + len(added) + 1
                destination = folder / f"{index:02d}_{src.name}"
                if destination.exists():
                    destination = folder / f"{index:02d}_{int(time.time())}_{src.name}"
                shutil.copy2(src, destination)
                added.append(str(destination))
            except OSError:
                continue
        if not added:
            messagebox.showwarning("Нет добавленных файлов", "Не удалось добавить изображения. Поддерживаются изображения до 30 МБ.", parent=self)
            return
        data = self._load_characters()
        for item in data:
            if item.get("id") == card_id:
                item.setdefault("references", []).extend(added)
        self._save_characters(data)
        updated = next(item for item in data if item.get("id") == card_id)
        self._refresh_reference_tab(updated)
        self._refresh_characters(card_id)
        self._set_status(f"Добавлено референсов: {len(added)} для {card['name']}.")

    def _open_reference_from_tab(self, card_id: str) -> None:
        frame = self.reference_tabs.get(card_id)
        tree = getattr(frame, "reference_tree", None) if frame is not None else None
        selected = tree.selection() if tree is not None else ()
        if not selected:
            messagebox.showinfo("Выберите референс", "Сначала выберите изображение в списке.", parent=self)
            return
        card = next((item for item in self._load_characters() if item.get("id") == card_id), None)
        try:
            path = Path(card["references"][int(selected[0])]) if card else None
        except (IndexError, ValueError, TypeError):
            path = None
        if path is None or not path.is_file():
            messagebox.showerror("Файл не найден", "Изображение референса отсутствует на диске.", parent=self)
            return
        try:
            if sys.platform == "win32": os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin": subprocess.Popen(["open", str(path)], shell=False)
            else: subprocess.Popen(["xdg-open", str(path)], shell=False)
        except OSError as exc:
            messagebox.showerror("Не удалось открыть изображение", str(exc), parent=self)

    def _selected_card(self) -> dict | None:
        selected = self.character_tree.selection()
        if not selected:
            return None
        return next((card for card in self._load_characters() if card.get("id") == selected[0]), None)

    def _select_character(self, _event=None) -> None:
        card = self._selected_card()
        self.character_detail.configure(state="normal")
        self.character_detail.delete("1.0", "end")
        if card:
            labels = card.get("reference_labels", {})
            if not isinstance(labels, dict):
                labels = {}
            refs = "\n".join(
                f"{index:02d}  {labels.get(str(path), Path(path).stem)}  ·  {Path(path).name}"
                for index, path in enumerate(card.get("references", []), 1)
            ) or "Референсы пока не добавлены. Добавь фронтальный вид, профиль, вид сзади и ключевые позы."
            category = card.get("profile_type", "Человек")
            style = card.get("visual_style", "Стилизованный 3D")
            self.character_detail.insert("1.0",
                f"{card.get('name','')}\n{'━' * min(38, max(12, len(card.get('name',''))))}\n"
                f"КАТЕГОРИЯ     {category}\nВИЗУАЛЬНЫЙ СТИЛЬ     {style}\n"
                f"РЕФЕРЕНСЫ     {len(card.get('references', []))}\n\n"
                f"ПОСТОЯННЫЕ ОСОБЕННОСТИ\n{card.get('description','') or 'Описание пока не заполнено.'}\n\n"
                f"БИБЛИОТЕКА РЕФЕРЕНСОВ · НУМЕРАЦИЯ СОХРАНЯЕТСЯ\n{refs}\n")
        self.character_detail.configure(state="disabled")

    def _add_character(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Новая карточка персонажа")
        dialog.transient(self)
        dialog.configure(bg=self.colors["canvas"])
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=24, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(frame, text="БИБЛИОТЕКА ПЕРСОНАЖЕЙ", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Новая карточка", style="Title.TLabel").pack(anchor="w", pady=(4, 5))
        ttk.Label(frame, text="Карточка не привязана к конкретному мультфильму. Создавай любых героев и меняй состав проекта.", background=self.colors["surface"], foreground=self.colors["muted"], wraplength=440).pack(anchor="w", pady=(0, 18))

        fields = ttk.Frame(frame, style="Panel.TFrame")
        fields.pack(fill="x")
        ttk.Label(fields, text="Имя персонажа", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
        name_var = tk.StringVar()
        name_entry = ttk.Entry(fields, textvariable=name_var, width=52)
        name_entry.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(fields, text="Категория", style="PanelTitle.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 5))
        type_var = tk.StringVar(value="Человек")
        ttk.Combobox(fields, textvariable=type_var, state="readonly", width=49,
            values=("Человек", "Животное", "Фантастическое существо", "Объект / предмет")).grid(row=3, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(fields, text="Визуальный стиль", style="PanelTitle.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 5))
        style_var = tk.StringVar(value="Стилизованный 3D")
        ttk.Combobox(fields, textvariable=style_var, state="readonly", width=49,
            values=("Стилизованный 3D", "Реалистичный", "По референсам / смешанный")).grid(row=5, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(fields, text="Постоянные особенности внешности", style="PanelTitle.TLabel").grid(row=6, column=0, sticky="w", pady=(0, 5))
        description = tk.Text(fields, height=5, width=52, wrap="word", font=("Segoe UI", 10),
            relief="flat", bd=0, padx=10, pady=9, highlightthickness=1,
            highlightbackground=self.colors["line"], highlightcolor=self.colors["accent"],
            bg=self.colors["surface_alt"], fg=self.colors["ink"], insertbackground=self.colors["accent"])
        description.grid(row=7, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(fields, text="Добавь референсы после создания карточки. Их номера и подписи будут использоваться в заданиях.", background=self.colors["surface"], foreground=self.colors["muted"], wraplength=440).grid(row=8, column=0, sticky="w", pady=(0, 16))

        buttons = ttk.Frame(frame, style="Panel.TFrame")
        buttons.pack(fill="x")
        def save_card() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Нужно имя", "Введи имя персонажа.", parent=dialog)
                name_entry.focus_set()
                return
            if len(name) > 80:
                messagebox.showerror("Слишком длинное имя", "Максимум 80 символов.", parent=dialog)
                return
            card = {
                "id": f"card_{int(time.time() * 1000)}", "name": name, "kind": "Персонаж",
                "profile_type": type_var.get(), "visual_style": style_var.get(),
                "description": description.get("1.0", "end-1c").strip()[:2400],
                "references": [], "reference_labels": {},
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            data = self._load_characters()
            data.append(card)
            self._save_characters(data)
            self._refresh_characters(card["id"])
            dialog.destroy()
            self._set_status(f"Карточка «{name}» добавлена в библиотеку.")
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Создать карточку", style="Accent.TButton", command=save_card).pack(side="right", padx=(0, 8))
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + max(20, (self.winfo_width()-dialog.winfo_width())//2)}+{self.winfo_rooty() + max(20, (self.winfo_height()-dialog.winfo_height())//2)}")
        dialog.grab_set()
        name_entry.focus_set()

    def _edit_character(self) -> None:
        card = self._selected_card()
        if not card:
            messagebox.showwarning("Выберите карточку", "Сначала выберите карточку.", parent=self); return
        description = simpledialog.askstring("Изменить описание", f"Описание карточки «{card['name']}»:", initialvalue=card.get("description", ""), parent=self)
        if description is None: return
        data = self._load_characters()
        for item in data:
            if item["id"] == card["id"]: item["description"] = description
        self._save_characters(data); self._refresh_characters(card["id"])

    def _add_reference(self) -> None:
        card = self._selected_card()
        if not card:
            messagebox.showwarning("Выберите карточку", "Сначала выберите карточку.", parent=self); return
        path = filedialog.askopenfilename(title="Добавить изображение-референс", filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")], parent=self)
        if not path: return
        src = Path(path)
        if src.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"} or src.stat().st_size > 30 * 1024 * 1024:
            messagebox.showerror("Недопустимый файл", "Поддерживаются изображения до 30 МБ.", parent=self); return
        folder = CHARACTER_DIR / card["id"]; folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"{len(card.get('references', [])) + 1:02d}_{src.name}"
        shutil.copy2(src, destination)
        data = self._load_characters()
        for item in data:
            if item["id"] == card["id"]: item.setdefault("references", []).append(str(destination))
        self._save_characters(data); self._refresh_characters(card["id"])

    def _open_reference(self) -> None:
        card = self._selected_card()
        if not card or not card.get("references"):
            messagebox.showinfo("Нет референсов", "Добавьте изображение в карточку.", parent=self); return
        paths = card["references"]
        path = paths[-1] if len(paths) == 1 else filedialog.askopenfilename(title="Выберите референс", initialdir=str(Path(paths[0]).parent), filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff")], parent=self)
        if path and Path(path).is_file():
            try:
                if sys.platform == "win32": os.startfile(path)  # type: ignore[attr-defined]
                elif sys.platform == "darwin": subprocess.Popen(["open", path], shell=False)
                else: subprocess.Popen(["xdg-open", path], shell=False)
            except OSError as exc: messagebox.showerror("Не удалось открыть", str(exc), parent=self)

    def _delete_character(self) -> None:
        card = self._selected_card()
        if not card: return
        if not messagebox.askyesno("Удалить карточку", f"Удалить карточку «{card['name']}»? Изображения останутся на диске.", parent=self): return
        self._save_characters([item for item in self._load_characters() if item["id"] != card["id"]])
        frame = self.reference_tabs.pop(card["id"], None)
        if frame is not None and frame.winfo_exists():
            self.tabs.forget(frame)
            frame.destroy()
        self._refresh_characters()

    def _apply_update(self) -> None:
        archive = filedialog.askopenfilename(title="Выберите ZIP-пакет обновления", filetypes=[("Agent update ZIP", "*.zip")], parent=self)
        if not archive: return
        if not messagebox.askyesno("Установить обновление", "Будут заменены только перечисленные файлы агента. Перед заменой создаются резервные копии. Продолжить?", parent=self): return
        try:
            result = apply_update_archive(Path(archive), Path(__file__).resolve().parents[1])
        except (UpdateError, OSError) as exc:
            messagebox.showerror("Обновление отклонено", str(exc), parent=self); return
        messagebox.showinfo("Обновление установлено", f"Файлов обновлено: {result['updated_count']}\nРезервные копии: {result['backup_dir']}\nПерезапустите агент.", parent=self)

    def _open_agent_folder(self) -> None:
        path = Path(__file__).resolve().parents[1]
        try:
            if sys.platform == "win32": os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin": subprocess.Popen(["open", str(path)], shell=False)
            else: subprocess.Popen(["xdg-open", str(path)], shell=False)
        except OSError as exc: messagebox.showerror("Не удалось открыть папку", str(exc), parent=self)

    def _close(self) -> None:
        if self._busy and not messagebox.askyesno("Задача выполняется", "Закрыть окно во время выполнения? Blender может продолжить работу.", parent=self):
            return
        self.destroy()


def main() -> int:
    try:
        app = BlenderAgentApp()
        app.mainloop()
        return 0
    except Exception:
        log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BlenderWorkAgent"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "gui_startup_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
