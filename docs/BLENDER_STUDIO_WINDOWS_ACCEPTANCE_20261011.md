# Blender Studio — reproducible Windows acceptance (11 October 2026)

## Exact source and current evidence

- Repository: `bjiow131/free-video-generator`.
- Integration branch: `feature/blender-studio-ui-20261011`; **do not merge into main before acceptance**.
- The canonical path in that branch is `studio_server.py` + `studio_jobs.py` + `studio_blender_scene.py`. The separate local `studio_executor.py` overlay is not installed over it.
- All existing Studio code is local. The current Blender renderer handles only a conspicuously marked procedural test actor, **not Mia or real rigged passports**.
- The current conversation's **39 passed, 3 deselected** was an independent partial-overlay run, *not* the exact GitHub integration branch. Full Windows branch tests and the Blender acceptance below **remain unverified**.
- The GitHub branch's added cancellation/stale-clip/live tests have been committed but no matching completed CI jobs have been observed.

## Safe test without touching the user's workspace

Use PowerShell from a fresh checkout/copy of the integration branch. Do not overwrite
`C:\AI-Agent` or `C:\AI-Agent-Workspace` during this acceptance. The disposable temporary
workspace is created inside Python's system temp by the live test.

```powershell
cd C:\AI-Agent-Studio-Stage
git branch --show-current
git rev-parse HEAD
py -3.11 -m compileall -q local_agent
py -3.11 -m unittest discover -s tests -p test_prompt_pipeline.py -v
py -3.11 -m unittest discover -s tests -p test_studio.py -v
py -3.11 -m unittest discover -s tests -p test_studio_assembly.py -v
py -3.11 -m unittest discover -s tests -p test_studio_jobs_cancellation.py -v
node --check local_agent\studio_static\app.js
```

Check Blender and FFmpeg:

```powershell
where.exe ffmpeg
where.exe ffprobe
# If automatic Blender discovery fails, supply the exact installed executable:
# $env:BLENDER_EXECUTABLE = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$env:STUDIO_LIVE_BLENDER = '1'
py -3.11 -m unittest discover -s tests -p test_studio_live_blender.py -v
Remove-Item Env:\STUDIO_LIVE_BLENDER
```

An actual pass requires `scene.blend`, 18 individual PNG frames with **at least two different frame hashes**, and a 360x640 H.264 MP4 containing at least 18 decoded video frames. The live test intentionally creates only a synthetic test actor. It must not pass by relying on the fixed `multiscene_cli.py` demo.

If the real Blender test fails, preserve the failure, `blender.log` and
`ffmpeg.log` from the test's temporary folder before the test exits (or reproduce
using the Studio UI and its persistent `studio_jobs` output). Do not assert Windows/GPU
acceptance without the actual test output.

## Post-acceptance update and rollback

Stop the old Studio. Use a release ZIP sourced from the **same tested commit**, not
the independent local overlay, and unpack it to `C:\AI-Agent-Studio-Update`.
Before running any install script review its `$Names` manifest and ensure all listed
files are present. Then:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI-Agent-Studio-Update\install_blender_studio.ps1 -Target C:\AI-Agent
```

The script writes a uniquely named `backup-studio-YYYYMMDD-HHMMSS-XXXXXXXX`
directory inside the target and prints the path. Roll back with:

```powershell
powershell -ExecutionPolicy Bypass -File C:\AI-Agent\rollback_blender_studio.ps1 -Target C:\AI-Agent -Backup 'C:\AI-Agent\backup-studio-YYYYMMDD-HHMMSS-XXXXXXXX'
```

Those PowerShell installers and rollback were not exercised on this Linux container;
test them against a disposable installation before using them on the real copy.
Keep `C:\AI-Agent-Workspace` and project assets backed up separately.

## Supported vs blocked

| Capability | Current branch |
|---|---|
| Russian command interpreter | Deterministic limited vocabulary; code integrated, no general LLM |
| Test actor translation, turn, simple mouth, camera | Implemented in Blender script; live verification required |
| Project MP4 concat | Implemented; synthetic FFmpeg test in older Work session |
| Stale scene rejection and cancellation | Fixes + regressions committed; exact branch tests pending |
| Real Mia/other character 3D animation | Blocked: compatible rig/animations not available |
| 2D PNG as 3D rig | Explicitly not supported |
| Arbitrary singing, riding, prop interaction | Not implemented without rig/asset adapter |
| Windows 5.2.2 / RTX 4060 end-to-end | Unverified |

Never treat a passing syntax check or mocked Python test as proof of real Blender render.
