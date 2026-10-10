# Быстрый запуск Blender Work Agent на Windows

Это локальный агент для Blender. Он не запускает веб-приложение и не является готовым генератором мультфильмов. Перед каждой задачей агент попросит подтверждение в консоли Windows: нужно вручную ввести `YES`.

## Что должно быть установлено

- Windows 10/11.
- Python 3.11 с Python Launcher (`py`).
- Blender 5.2, установленный по пути `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.
- Доступ в интернет к GitHub.
- Доступ к приватному репозиторию `bjiow131/local-agent-mailbox`.

Если Blender установлен в другом месте, измените `BLENDER_EXECUTABLE` в обоих BAT-файлах: `setup_blender_agent.bat` и `run_blender_agent.bat`.

## Установка

1. Откройте [ветку blender-agent-repair](https://github.com/bjiow131/free-video-generator/tree/blender-agent-repair) и нажмите **Code → Download ZIP**. Также можно скачать архив напрямую: [ZIP этой ветки](https://github.com/bjiow131/free-video-generator/archive/refs/heads/blender-agent-repair.zip).
2. Распакуйте архив, например, в `C:\AI-Agent\free-video-generator`. Внутри этой папки должны лежать `setup_blender_agent.bat`, `run_blender_agent.bat`, папка `local_agent` и файл `requirements-local-agent.txt`.
3. Дважды щёлкните `setup_blender_agent.bat`. Он создаст отдельное Python-окружение в `%LOCALAPPDATA%\BlenderWorkAgent\venv` и установит минимальные зависимости. Скрипт не удаляет существующие файлы проекта.
4. Создайте fine-grained GitHub token только для приватного репозитория `bjiow131/local-agent-mailbox`. Дайте ему **Contents: Read and write**; **Metadata: Read-only** требуется GitHub автоматически. Не включайте доступ ко всем репозиториям и не присылайте токен в чат.
5. Откройте командную строку Windows (CMD) и выполните, подставив фактический путь к распакованному репозиторию:

   ```bat
   cd /d C:\AI-Agent\free-video-generator
   "%LOCALAPPDATA%\BlenderWorkAgent\venv\Scripts\python.exe" -m local_agent.credentials_cli set
   ```

   Вставьте токен дважды в скрытое приглашение. Токен сохраняется в Windows Credential Manager, не в файле проекта.
6. Дважды щёлкните `run_blender_agent.bat`. Окно должно остаться открытым и сообщить, что агент опрашивает приватный mailbox каждые 10 секунд.

## Остановка и безопасность

- Для остановки нажмите `Ctrl+C` в окне агента.
- Агент не должен выполнять задачу, если консоль неинтерактивна или пользователь не ввёл ровно `YES`.
- Если GitHub token был показан в чате, записан в файл или случайно опубликован, отзовите его в GitHub и создайте новый.
- Пока не проверены тесты на вашем компьютере, считайте это предварительной установкой. Сначала выполните безопасную задачу `blender_preflight`; не начинайте с генерации сцены.
- Рабочая папка по умолчанию: `C:\AI-Agent-Workspace`. Результаты и проекты создаются локально на этом компьютере.
