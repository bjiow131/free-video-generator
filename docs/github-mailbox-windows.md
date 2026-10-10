# Подключение GitHub mailbox на Windows

## Что обнаружено и исправлено в этой ветке

В local_agent/poller.py был ранний return: функция сразу сообщала, что GitHub mailbox отключён, и возвращала код 2. Ниже оставался код опроса, но отсутствовали импорты GitHub-клиента, конфигурации, сетевой ошибки и локального outbox.

Исправление добавляет недостающие импорты и оставляет GitHub-опрос выключенным по умолчанию. Отдельный файл run_github_mailbox_agent.bat включает режим явно. Обычный run_blender_agent.bat остаётся локальным.

## 1. Установить отдельную среду

Выполните setup_github_mailbox_agent.bat. Он создаёт отдельное окружение Python в %LOCALAPPDATA%\BlenderWorkAgent\github-venv и устанавливает только requests, который нужен GitHub REST-клиенту. Обычная локальная среда Blender не меняется.

## 2. Подготовить доступ

GitHub CLI для этого mailbox не требуется: клиент использует GitHub REST API и Windows Credential Manager.

1. В GitHub создайте fine-grained personal access token с доступом только к приватному репозиторию bjiow131/local-agent-mailbox.
2. Дайте минимально необходимые права Contents: Read and write. Чтение нужно для queue/desired_task.json, запись — для queue/results/<task_id>.json.
3. В PowerShell из корня репозитория выполните:

    & "$env:LOCALAPPDATA\BlenderWorkAgent\github-venv\Scripts\python.exe" -m local_agent.credentials_cli set

4. Введите токен дважды. Ввод скрыт; токен сохраняется в Windows Credential Manager и не печатается.
5. Проверьте наличие учётных данных:

    & "$env:LOCALAPPDATA\BlenderWorkAgent\github-venv\Scripts\python.exe" -m local_agent.credentials_cli status

Не помещайте токен в исходники, .env, JSON, командную строку или логи. Не обходите проверки GitHub и SMS-верификацию.

## 3. Проверить соединение без выполнения удалённой задачи

Выполните:

    & "$env:LOCALAPPDATA\BlenderWorkAgent\github-venv\Scripts\python.exe" scripts/check_github_connection.py

Скрипт проверяет доступ к приватному репозиторию и записывает безвредный результат проверки в queue/results/connection-check-<UTC-время>.json. Он не читает и не выполняет queue/desired_task.json. При успехе будет status=connected; при ошибке выводятся только тип ошибки и короткое сообщение.

## 4. Запуск mailbox-агента

Дважды нажмите run_github_mailbox_agent.bat. Опросчик должен сообщить, что опрашивает приватный GitHub mailbox.

Запускатель задаёт значения по умолчанию:
- LOCAL_AGENT_GITHUB_REPO=bjiow131/local-agent-mailbox
- LOCAL_AGENT_GITHUB_REF=main
- LOCAL_AGENT_GITHUB_MANIFEST=queue/desired_task.json (значение клиента по умолчанию)

Ранее заданные переменные окружения имеют приоритет. Убедитесь, что они указывают на нужный приватный репозиторий и ветку. При каждой новой задаче агент требует локального подтверждения вводом YES. Не подтверждайте неизвестную задачу.

## 5. Локальная очередь результатов

Результат задачи сначала сохраняется в .local_agent/pending_results. После успешного ответа GitHub он записывается в queue/results/<task_id>.json. При сетевой ошибке локальный файл остаётся и будет повторно отправлен; сбой публикации не должен сам по себе приводить к повторному выполнению задачи.

## Статус проверки

Эта ветка исправляет подтверждённые причины отключения, добавляет явный запуск и безопасную проверку соединения. Реальная авторизация Windows, live round-trip и запуск Blender в этой среде не выполнялись. Перед использованием требуется прогнать тесты и проверить соединение на компьютере.
