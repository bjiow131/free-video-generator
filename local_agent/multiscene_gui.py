"""Small Windows desktop launcher for the opt-in multiscene prototype."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def main() -> None:
    root = tk.Tk()
    root.title("Blender AI Agent — Multi-scene")
    root.geometry("720x400")
    workspace = Path(os.environ.get("LOCAL_AGENT_WORKSPACE", r"C:\AI-Agent-Workspace"))
    source = tk.StringVar(value=str(workspace / "test2" / "object_animation_test.blend"))
    output = tk.StringVar(value=str(workspace / "multiscene_gui_test"))
    lens = tk.StringVar(value="42")
    status = tk.StringVar(value="Готов к запуску. Используется фиксированный тестовый таймлайн.")
    events: queue.Queue[tuple[str, str]] = queue.Queue()

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Многосценная анимация (тестовый режим)", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 14))

    def add_path(label: str, variable: tk.StringVar, directory: bool = False) -> None:
        ttk.Label(frame, text=label).pack(anchor="w")
        line = ttk.Frame(frame)
        line.pack(fill="x", pady=(3, 12))
        ttk.Entry(line, textvariable=variable).pack(side="left", fill="x", expand=True)
        def browse() -> None:
            selected = (filedialog.askdirectory() if directory
                        else filedialog.askopenfilename(filetypes=[("Blender projects", "*.blend")]))
            if selected:
                variable.set(selected)
        ttk.Button(line, text="Обзор", command=browse).pack(side="left", padx=(8, 0))

    add_path("Исходный проект Blender", source)
    add_path("Новая папка результата (не должна существовать)", output, directory=False)
    ttk.Label(frame, text="Фокусное расстояние камеры (18–100 мм)").pack(anchor="w")
    ttk.Entry(frame, textvariable=lens, width=10).pack(anchor="w", pady=(3, 12))

    button = ttk.Button(frame, text="Создать видео")
    button.pack(anchor="w", pady=(0, 12))
    ttk.Label(frame, textvariable=status, wraplength=650).pack(anchor="w")
    ttk.Label(frame, text="Фиксированный сценарий из трёх участков. Текстовые промпты пока не поддерживаются.", wraplength=650).pack(anchor="w", pady=(12, 0))

    def run() -> None:
        src = Path(source.get()).expanduser()
        dst = Path(output.get()).expanduser()
        try:
            focal = float(lens.get())
            if not 18 <= focal <= 100:
                raise ValueError
        except ValueError:
            messagebox.showerror("Параметры", "Фокусное расстояние должно быть от 18 до 100 мм.")
            return
        if not src.is_file() or src.suffix.lower() != ".blend":
            messagebox.showerror("Исходный проект", "Выбери существующий файл .blend.")
            return
        if dst.exists():
            messagebox.showerror("Папка результата", "Выбери новое имя папки, которой ещё не существует.")
            return
        button.configure(state="disabled")
        status.set("Blender выполняет рендер. Окно останется доступным.")
        command = [sys.executable, "-m", "local_agent.multiscene_cli",
                   "--source", str(src), "--output", str(dst),
                   "--camera-lens-mm", str(focal)]
        def worker() -> None:
            try:
                proc = subprocess.run(command, capture_output=True, text=True,
                                      timeout=2400, check=False)
                if proc.returncode:
                    events.put(("error", (proc.stderr or proc.stdout)[-3500:]))
                else:
                    events.put(("done", str(dst / "multiscene.mp4")))
            except (OSError, subprocess.TimeoutExpired) as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll() -> None:
        try:
            kind, value = events.get_nowait()
        except queue.Empty:
            pass
        else:
            button.configure(state="normal")
            if kind == "done":
                status.set("Видео готово: " + value)
                messagebox.showinfo("Готово", "Видео сохранено:\n" + value)
            else:
                status.set("Ошибка генерации. Проверь детали сообщения.")
                messagebox.showerror("Ошибка Blender / FFmpeg", value)
        root.after(250, poll)

    button.configure(command=run)
    root.after(250, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
