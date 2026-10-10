"""Desktop GUI for the local-only Blender Work Agent.

Uses Tkinter from Python's standard library. All task execution is local and
allowlisted; the prompt is never executed as Python or shell code.
"""
from __future__ import annotations

import json
import os
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
from local_agent.update_manager import apply_update_folder, UpdateError

APP_VERSION = "0.2.0"
APP_TITLE = "Blender Work Agent"
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
        self.geometry("1060x760")
        self.minsize(850, 620)
        self.configure(bg="#eef1f4")
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
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#eef1f4")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("TLabel", background="#eef1f4", foreground="#263341", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 19), foreground="#152536")
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground="#617080")
        style.configure("PanelTitle.TLabel", background="#ffffff", font=("Segoe UI Semibold", 11), foreground="#233445")
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(16, 9))
        style.configure("TNotebook", background="#eef1f4", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Segoe UI Semibold", 10), padding=(18, 10))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(22, 18, 22, 12))
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="Blender Work Agent", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Локальная рабочая среда для создания и доработки сцен Blender", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        self.project_badge = ttk.Label(header, text="Проект не открыт", style="Subtitle.TLabel")
        self.project_badge.pack(side="right", anchor="e", padx=(10, 0))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.task_tab = ttk.Frame(self.tabs, padding=18)
        self.library_tab = ttk.Frame(self.tabs, padding=18)
        self.update_tab = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(self.task_tab, text="Задание")
        self.tabs.add(self.library_tab, text="Персонажи и референсы")
        self.tabs.add(self.update_tab, text="Обновление")
        self._build_task_tab()
        self._build_library_tab()
        self._build_update_tab()
        footer = ttk.Frame(self, padding=(20, 0, 20, 14))
        footer.pack(fill="x")
        self.status_var = tk.StringVar(value="")
        ttk.Label(footer, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Label(footer, text="Локально · без удалённой очереди и без передачи файлов", style="Subtitle.TLabel").pack(side="right")

    def _build_task_tab(self) -> None:
        project = ttk.Frame(self.task_tab, style="Panel.TFrame", padding=14)
        project.pack(fill="x", pady=(0, 12))
        ttk.Label(project, text="Текущий проект", style="PanelTitle.TLabel").pack(anchor="w")
        row = ttk.Frame(project, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 2))
        self.project_label_var = tk.StringVar(value="Новый проект: задание будет обработано как создание сцены.")
        ttk.Label(row, textvariable=self.project_label_var, background="#ffffff").pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Открыть готовый проект…", command=self._open_project).pack(side="right")
        ttk.Button(row, text="Сбросить проект", command=self._clear_project).pack(side="right", padx=(0, 8))

        prompt_panel = ttk.Frame(self.task_tab, style="Panel.TFrame", padding=14)
        prompt_panel.pack(fill="both", expand=True)
        ttk.Label(prompt_panel, text="Задание", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(prompt_panel, text="Вставьте сюда задачу. При открытом проекте она относится к нему, а не запускает создание новой сцены.", background="#ffffff", wraplength=900).pack(anchor="w", pady=(4, 8))
        self.prompt = tk.Text(prompt_panel, height=12, wrap="word", font=("Segoe UI", 11), undo=True, relief="solid", bd=1, padx=10, pady=10)
        self.prompt.pack(fill="both", expand=True)
        self.prompt.insert("1.0", "Например: создай три красных куба и синюю сферу, вертикально 9:16")
        self.prompt.bind("<KeyRelease>", self._update_prompt_count)
        bottom = ttk.Frame(prompt_panel, style="Panel.TFrame")
        bottom.pack(fill="x", pady=(10, 0))
        self.prompt_count = ttk.Label(bottom, text=f"0 / {PROMPT_LIMIT}", background="#ffffff")
        self.prompt_count.pack(side="left")
        self.create_btn = ttk.Button(bottom, text="Создать / выполнить задание", style="Accent.TButton", command=self._submit_task)
        self.create_btn.pack(side="right")
        ttk.Label(prompt_panel, text="Важно: текущий прототип понимает ограниченный набор операций. Неподдерживаемые задания не будут выданы за выполненные.", background="#ffffff", foreground="#687788", wraplength=900).pack(anchor="w", pady=(9, 0))

    def _build_library_tab(self) -> None:
        top = ttk.Frame(self.library_tab)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="Карточки персонажей и референсов", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Добавить карточку", command=self._add_character).pack(side="right")
        split = ttk.Panedwindow(self.library_tab, orient="horizontal")
        split.pack(fill="both", expand=True)
        left = ttk.Frame(split, padding=(0, 0, 10, 0))
        right = ttk.Frame(split, padding=(10, 0, 0, 0))
        split.add(left, weight=1)
        split.add(right, weight=2)
        self.character_tree = ttk.Treeview(left, columns=("type",), show="tree headings", selectmode="browse")
        self.character_tree.heading("#0", text="Имя")
        self.character_tree.heading("type", text="Тип")
        self.character_tree.column("#0", width=180)
        self.character_tree.column("type", width=100)
        self.character_tree.pack(fill="both", expand=True)
        self.character_tree.bind("<<TreeviewSelect>>", self._select_character)
        self.character_detail = tk.Text(right, height=12, wrap="word", font=("Segoe UI", 10), relief="solid", bd=1, padx=10, pady=10)
        self.character_detail.pack(fill="both", expand=True)
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Добавить изображение-референс…", command=self._add_reference).pack(side="left")
        ttk.Button(actions, text="Открыть изображение", command=self._open_reference).pack(side="left", padx=8)
        ttk.Button(actions, text="Изменить описание", command=self._edit_character).pack(side="left")
        ttk.Button(actions, text="Удалить карточку", command=self._delete_character).pack(side="right")
        ttk.Label(right, text=f"Файлы хранятся локально: {CHARACTER_DIR}", wraplength=650).pack(anchor="w", pady=(8, 0))
        self._refresh_characters()

    def _build_update_tab(self) -> None:
        panel = ttk.Frame(self.update_tab, style="Panel.TFrame", padding=18)
        panel.pack(fill="x", anchor="n")
        ttk.Label(panel, text="Обновление отдельными файлами", style="Title.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Обновление устанавливается из локальной папки: агент создаёт резервные копии изменяемых файлов, проверяет пути и не удаляет проекты. После обновления приложение нужно перезапустить.", background="#ffffff", wraplength=850).pack(anchor="w", pady=(8, 12))
        ttk.Label(panel, text=f"Версия интерфейса: {APP_VERSION}", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Ожидаемая структура папки обновления: update_manifest.json и файлы внутри payload/. В манифесте перечислены только новые или заменяемые файлы.", background="#ffffff", wraplength=850).pack(anchor="w", pady=(6, 12))
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
            self.prompt_count.configure(foreground="#617080")

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
        self.project_badge.configure(text=f"Редактирование: {project.name}")
        self._set_status("Проект выбран. Следующее задание будет обработано как доработка этого проекта.")
        if messagebox.askyesno("Открыть проект", "Открыть выбранный проект в графическом интерфейсе Blender сейчас?", parent=self):
            try:
                subprocess.Popen([blender_info["path"], str(project)], cwd=str(project.parent), shell=False, close_fds=True)
            except OSError as exc:
                messagebox.showerror("Ошибка запуска Blender", f"Не удалось открыть Blender: {exc}", parent=self)

    def _clear_project(self) -> None:
        self.active_project = None
        self.project_label_var.set("Новый проект: задание будет обработано как создание сцены.")
        self.project_badge.configure(text="Проект не открыт")
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
        mode = "доработка открытого проекта" if self.active_project else "создание нового проекта"
        if not self._ask_confirm(f"Режим: {mode}\n\n{prompt}"):
            self._set_status("Задание отменено.")
            return
        self._busy = True
        self.create_btn.configure(state="disabled")
        self._set_status("Выполняю локальную задачу в Blender…")
        threading.Thread(target=self._run_task, args=(prompt, self.active_project), daemon=True).start()

    def _run_task(self, prompt: str, existing: Path | None) -> None:
        try:
            blender_info = discover_blender()
            if not blender_info.get("available"):
                raise RuntimeError("Blender не найден. Проверьте настройки запуска.")
            if existing:
                result = edit_existing_scene(prompt, existing, blender_info["path"], self.workspace)
            else:
                staging_name = f"agent_draft_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
                result = create_scene_from_prompt(prompt, staging_name)
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

    def _selected_card(self) -> dict | None:
        selected = self.character_tree.selection()
        if not selected:
            return None
        return next((card for card in self._load_characters() if card.get("id") == selected[0]), None)

    def _select_character(self, _event=None) -> None:
        card = self._selected_card()
        self.character_detail.delete("1.0", "end")
        if card:
            refs = "\n".join(f"• {p}" for p in card.get("references", [])) or "Референсы пока не добавлены."
            self.character_detail.insert("1.0", f"Имя: {card.get('name','')}\nТип: {card.get('kind','Персонаж')}\n\nОписание:\n{card.get('description','')}\n\nРеференсы:\n{refs}\n")
        self.character_detail.configure(state="normal")

    def _add_character(self) -> None:
        name = simpledialog.askstring("Новая карточка", "Имя персонажа или референса:", parent=self)
        if not name:
            return
        name = name.strip()
        if len(name) > 80:
            messagebox.showerror("Слишком длинное имя", "Максимум 80 символов.", parent=self); return
        description = simpledialog.askstring("Описание", "Описание внешности, одежды, особенностей и постоянных деталей:", parent=self) or ""
        kind = simpledialog.askstring("Тип карточки", "Введите «Персонаж» или «Референс»:", initialvalue="Персонаж", parent=self) or "Персонаж"
        kind = "Референс" if kind.casefold().startswith("реф") else "Персонаж"
        card = {"id": f"card_{int(time.time() * 1000)}", "name": name, "kind": kind, "description": description, "references": [], "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        data = self._load_characters(); data.append(card); self._save_characters(data); self._refresh_characters(card["id"])

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
        self._refresh_characters()
        self.character_detail.delete("1.0", "end")

    def _apply_update(self) -> None:
        folder = filedialog.askdirectory(title="Выберите папку с update_manifest.json", parent=self)
        if not folder: return
        if not messagebox.askyesno("Установить обновление", "Будут заменены только перечисленные файлы агента. Перед заменой создаются резервные копии. Продолжить?", parent=self): return
        try:
            result = apply_update_folder(Path(folder), Path(__file__).resolve().parents[1])
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
