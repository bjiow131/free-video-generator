    # P7: 参数校验
    _validate_video_dimensions(video_width, video_height)
    if chaining_mode not in ("independent", "ti2vid", "keyframes"):
        raise HTTPException(status_code=422, detail="Неподдерживаемый режим связности сцен")
    if len(idea) > 10000:
        raise HTTPException(status_code=422, detail="Идея может содержать не более 10000 символов")
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(status_code=422, detail="Источник длительности должен быть ручным или заданным в промпте")
    if duration_source == "manual":
        if scene_count < 1 or scene_count > 30:
            raise HTTPException(status_code=422, detail="Количество сцен должно быть от 1 до 30")
        # 解析场景时长 JSON
        try:
            scene_durations = json.loads(scene_durations_json)
            if not isinstance(scene_durations, list):
                raise ValueError("not a list")
            if len(scene_durations) != scene_count:
                raise ValueError("length mismatch")
        except Exception:
            raise HTTPException(status_code=422, detail="Параметры длительности сцен должны быть массивом JSON")
        # 校验每个时长
        for i, d in enumerate(scene_durations):
            if not isinstance(d, (int, float)) or d < 2 or d > 30:
                raise HTTPException(status_code=422, detail=f"Длительность сцены {i+1} должна быть от 2 до 30 секунд")
    else:
        scene_durations = []

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"video_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    state = CreativeVideoTask(
        task_id=task_id,
        creative_name=name,
        idea=idea,
        style=style,
        negative_prompt=negative_prompt,
        include_characters=include_characters,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        video_duration=5,
        duration_source=duration_source,
        scene_count=scene_count,
        uniform_duration=uniform_duration,
        scene_durations=scene_durations,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    logger.info(
        f"[Pipeline] Scene config: source={duration_source}, "
        f"scenes={scene_count}, durations={scene_durations}, uniform={uniform_duration}"
    )

    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".png"
        os.makedirs(get_upload_dir(), exist_ok=True)
        upload_path = os.path.join(get_upload_dir(), f"{task_id}_ref{ext}")
        with open(upload_path, "wb") as f:
            f.write(await reference_image.read())
        state.reference_image = upload_path

    # P3: 处理自定义尾帧图片上传
    if use_custom_end_frames and end_frame_images:
        saved_paths = []
        for idx, ef_file in enumerate(end_frame_images):
            if ef_file and ef_file.filename:
                ext = os.path.splitext(ef_file.filename)[1] or ".png"
                upload_path = os.path.join(get_upload_dir(), f"{task_id}_end_{idx}{ext}")
                with open(upload_path, "wb") as f:
                    f.write(await ef_file.read())
                saved_paths.append(upload_path)
        if saved_paths:
            state.end_frame_images = saved_paths
            logger.info(f"[Pipeline] Saved {len(saved_paths)} custom end frame images for task {task_id}")

    pipeline = _create_pipeline_for_type(TaskType.CREATIVE, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Creative] Task created: {task_id}, idea={idea[:40]}... (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/manuscript")
async def create_manuscript_task(
    request: Request,
    manuscript_text: str = Form(...),
    video_style: str = Form(""),
    negative_prompt: str = Form(""),
    creative_name: str = Form(""),
    video_width: int = Form(1152),
    video_height: int = Form(648),
    video_duration: int = Form(10),
    # v2.0 音频配置
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("ru-RU-SvetlanaNeural"),
    audio_rate: str = Form("+0%"),
    # v3.0 字幕独立配置
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建稿件长视频任务（类型 3）。"""

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    _validate_video_dimensions(video_width, video_height)
    if not manuscript_text.strip():
        raise HTTPException(status_code=400, detail="Текст сценария не может быть пустым")
    # P7: 文本长度上限
    if len(manuscript_text) > 50000:
        raise HTTPException(status_code=422, detail="Текст сценария может содержать не более 50000 символов")

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"manuscript_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    state = ManuscriptVideoTask(
        task_id=task_id,
        creative_name=name,
        manuscript_text=manuscript_text.strip(),
        video_style=video_style.strip(),
        negative_prompt=negative_prompt.strip(),
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    pipeline = _create_pipeline_for_type(TaskType.MANUSCRIPT, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Manuscript] Task created: {task_id}, text_len={len(manuscript_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/anchor")
async def create_anchor_task(
    request: Request,
    anchor_prompt: str = Form(""),
    anchor_reference_image: UploadFile = File(None),
    script_text: str = Form(...),
    negative_prompt: str = Form(""),
    audio_source: str = Form("post_stitch"),
    video_width: int = Form(768),
    video_height: int = Form(1344),
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("ru-RU-SvetlanaNeural"),
    audio_rate: str = Form("+0%"),
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(42),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建数字人口播任务（类型 4 / Phase 3）。"""

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    if not script_text.strip():
        raise HTTPException(status_code=400, detail="Текст для озвучки не может быть пустым")
    if len(script_text) > 50000:
        raise HTTPException(status_code=422, detail="Текст для озвучки может содержать не более 50000 символов")

    task_id = uuid.uuid4().hex[:12]
    name = f"anchor_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    # 处理参考图上传
    ref_image_path = ""
    if anchor_reference_image and anchor_reference_image.filename:
        ext = os.path.splitext(anchor_reference_image.filename)[1] or ".png"
        os.makedirs(get_upload_dir(), exist_ok=True)
        upload_path = os.path.join(get_upload_dir(), f"{task_id}_ref{ext}")
        with open(upload_path, "wb") as f:
            f.write(await anchor_reference_image.read())
        ref_image_path = upload_path

    state = AnchorVideoTask(
        task_id=task_id,
        creative_name=name,
        anchor_prompt=anchor_prompt,
        anchor_reference_image=ref_image_path,
        script_text=script_text.strip(),
        negative_prompt=negative_prompt.strip(),
        audio_source=audio_source,
        video_width=video_width,
        video_height=video_height,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    pipeline = _create_pipeline_for_type(TaskType.ANCHOR, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Anchor] Task created: {task_id}, script_len={len(script_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


# ═══════════════════════════════════════════════════
# 向后兼容：旧的 POST /api/tasks → 映射到 creative
# ═══════════════════════════════════════════════════


@app.post("/api/tasks")
async def create_task_legacy(
    request: Request,
    idea: str = Form(...),
    creative_name: str = Form(""),
    user_requirement: str = Form("3个场景，每个场景10秒，电影质感"),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(1152),
    video_height: int = Form(648),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(True),
):
    """向后兼容旧端点，映射到 create_creative_task。"""
    return await create_creative_task(
        request=request,
        idea=f"{idea}\n{user_requirement}",
        creative_name=creative_name,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        reference_image=reference_image,
        end_frame_images=end_frame_images,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        duration_source="prompt",
        scene_count=3,
        scene_durations_json="[5,5,5]",
        audio_enabled=False,
        audio_voice="ru-RU-SvetlanaNeural",
        audio_rate="+0%",
        subtitle_enabled=True,
        subtitle_font="STHeitiMedium.ttc",
        subtitle_color="white",
        subtitle_fontsize=48,
        subtitle_position="bottom",
        subtitle_stroke_color="black",
        subtitle_stroke_width=2,
        subtitle_bg_color="black@0.5",
    )


# ═══════════════════════════════════════════════════
# 任务恢复 + 停止
# ═══════════════════════════════════════════════════


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str, request: Request):
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    # 关键段串行化：check 与 insert 之间存在多个 await 让出点，快速重复 resume
    # 会让两次请求都通过 "task not in active_pipelines" 检查并各自启动 pipeline，
    # 导致同任务双重运行、状态文件交叉写入。
    async with _get_pipeline_lock(task_id):
        if task_id in active_pipelines:
            existing = active_pipelines[task_id]
            if existing._stop_event.is_set():
                logger.info(f"[Resume] Replacing stopped pipeline for task {task_id}")
                del active_pipelines[task_id]
            else:
                raise HTTPException(status_code=400, detail="Задача уже выполняется")

        dir_name = _find_dir_name(task_id)
        tm = TaskManager(task_id, dir_name=dir_name)
        state = tm.load()
        if not state:
            raise HTTPException(status_code=404, detail="Задача не найдена")

        if state.status == StepStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Задача уже завершена")

        logger.info(f"[Resume] Starting resume for task {task_id}, type={state.task_type}, status={state.status}")

        # v2.0：根据 task_type 选择对应的 Pipeline
        pipeline = _create_pipeline_for_type(state.task_type, api_key, task_id, dir_name)
        active_pipelines[task_id] = pipeline

        if task_id in active_connections:
            logger.info(f"[Resume] Binding existing WebSocket for task {task_id}")
            pipeline.progress_callback = _make_progress_callback(task_id)

        _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str, request: Request):
    if task_id not in active_pipelines and task_id not in _queued_tasks:
        raise HTTPException(status_code=400, detail="Задача не выполняется")

    # 停止运行中的 pipeline
    if task_id in active_pipelines:
        pipeline = active_pipelines[task_id]
        pipeline.stop()

    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if state and state.status in (StepStatus.RUNNING, StepStatus.QUEUED):
        tm.update_state(status=StepStatus.PENDING)
        logger.info(f"[Stop] Task {task_id} status -> pending")

    logger.info(f"[Stop] Task {task_id} stop requested")
    return {"ok": True, "task_id": task_id}


# ═══════════════════════════════════════════════════
# 并发状态接口
# ═══════════════════════════════════════════════════


@app.get("/api/concurrency")
async def get_concurrency_status(request: Request):
    """返回当前并发控制状态：已用权重、上限、排队任务列表。"""
    running_tasks = []
    for tid, pl in active_pipelines.items():
        if tid not in _queued_tasks:
            # 真正在运行的（已获取信号量）
            running_tasks.append({
                "task_id": tid,
                "type": getattr(pl, '_task_type', 'unknown'),
            })

    queued = [
        {"task_id": tid, "weight": w}
        for tid, w in _queued_tasks.items()
    ]

    return {
        "ok": True,
        "max_weight": _pipeline_semaphore.max_weight,
        "current_weight": _pipeline_semaphore.current,
        "utilization": round(_pipeline_semaphore.utilization, 2),
        "running_count": len(running_tasks),
        "queued_count": len(queued),
        "queued_tasks": queued,
        "rate_limit_per_min": _AGNES_RATE_LIMIT,
        "task_weights": {k.value: v for k, v in TASK_TYPE_WEIGHTS.items()},
    }


# ═══════════════════════════════════════════════════
# 回归测试清理
# ═══════════════════════════════════════════════════

@app.post("/api/cleanup-regression")
async def cleanup_regression(request: Request):
    """安全清理回归测试产物（报告、日志、任务目录）。

    只删除产物清单中记录的内容，不影响用户原有任务数据。
    """
    working_dir = get_working_dir()
    manifest_path = os.path.join(working_dir, ".regression_manifest.json")

    if not os.path.exists(manifest_path):
        raise HTTPException(
            status_code=404,
            detail="Список результатов тестирования не найден. Возможно, тестирование ещё не выполнялось")

    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"读取清单失败: {e}")

    removed_dirs = 0
    removed_files = 0
    errors: list = []
    project_root = os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(working_dir, "uploads")

    # 1. 清理任务目录
    for dir_name in manifest.get("task_dirs", []):
        dir_path = os.path.join(working_dir, dir_name)
        if os.path.isdir(dir_path):
            try:
                shutil.rmtree(dir_path)
                removed_dirs += 1
            except OSError as e:
                errors.append(f"删除目录失败 {dir_name}: {e}")

    # 2. 清理上传文件
    for fname in manifest.get("uploads", []):
        fpath = os.path.join(upload_dir, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除上传文件失败 {fname}: {e}")

    # 3. 清理报告文件
    for rel_path in manifest.get("reports", []):
        abs_path = os.path.join(project_root, rel_path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除报告失败 {rel_path}: {e}")

    # 4. 清理服务器日志
    log_rel = manifest.get("server_log", "")
    if log_rel:
        log_path = os.path.join(project_root, log_rel)
        if os.path.isfile(log_path):
            try:
                os.remove(log_path)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除日志失败: {e}")

    # 5. 清理清单本身
    try:
        os.remove(manifest_path)
        removed_files += 1
    except OSError as e:
        errors.append(f"删除清单失败: {e}")

    scenarios_cleaned = len(manifest.get("scenarios", {}))
    logger.info(
        f"[Cleanup] 回归清理完成: {removed_dirs} 目录, "
        f"{removed_files} 文件, {scenarios_cleaned} 场景")

    return {
        "ok": len(errors) == 0,
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "scenarios_cleaned": scenarios_cleaned,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════


if __name__ == "__main__":
    import uvicorn

    config = uvicorn.Config(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8765")), log_level="info")
    server = uvicorn.Server(config)

    original_handle_exit = server.handle_exit

    def _handle_exit(sig, frame):
        if shutdown_event.is_set():
            logger.warning("Force exiting...")
            os._exit(1)
        logger.info("Shutting down gracefully (Ctrl+C again to force)...")
        shutdown_event.set()
        if callable(original_handle_exit):
            original_handle_exit(sig, frame)

    server.handle_exit = _handle_exit

    server.run()
