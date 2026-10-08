# UI Inventory

Scope: `static/` on branch `design/redesign`, audited from the current working branch. This inventory covers the application UI and the static entry/support files; binary assets are not treated as UI components.

## Static surface

- `static/ai-studio.html` — primary application shell and all currently implemented app screens.
- `static/index.html` — static entry/redirect surface.
- `static/test_video.html` — standalone video test surface.
- `static/manifest.webmanifest` — PWA metadata.
- `static/sw.js` — service-worker shell.
- `static/favicon.ico`, `static/icon.png` — application identity assets.

## Application shell

- Brand / application identity: AGNES VIDEO.
- Persistent sidebar navigation.
- Top status bar.
- Agnes AI/API status and credit indicator.
- Main content viewport.
- Toast notification layer.
- Modal styles are present in the shared UI vocabulary; no active modal markup is currently mounted in the primary screen.
- Responsive mobile navigation treatment.

## Screens / tabs

1. **Обзор / Home**
   - Hero/intro area.
   - Capability cards: images, video, references, Agnes AI connection.
   - Navigation shortcuts into creation.

2. **Создать / Create**
   - Media type selector: image/video.
   - Model picker.
   - Selected-model information panel.
   - Dynamic media parameters.
   - Prompt textarea.
   - Reference image upload.
   - Generate / clear actions.
   - Generation status.
   - Generated result panel.
   - Image result preview + download.
   - Video task launch + history hand-off.

3. **Мультфильм / Film**
   - Film name.
   - Story/idea textarea.
   - Visual style.
   - Scene count.
   - Scene duration.
   - Output format.
   - Character reference upload.
   - Audio toggle.
   - Voice selection.
   - Subtitle toggle.
   - Generate / clear actions.
   - Film status.
   - Production progress panel.
   - Scene completion progress.
   - Story/character/final-video readiness indicators.
   - Final MP4 video player + download.

4. **История / History**
   - Task list.
   - Task type/name.
   - Task ID.
   - Status chip.
   - Open-result action.
   - Empty state.

5. **Кредиты / Credits**
   - Agnes AI connection explanation.
   - Current internal-credit state.
   - API-access/limit explanation.

## Creation controls / modes

The current primary creation flow has four practical modes/states represented by the UI:

1. Image text-to-image.
2. Image generation with an optional reference image (image input/reference state).
3. Video text-to-video.
4. Video image-to-video when a reference image is supplied.

The Film screen is a separate production workflow layered on top of the task system.

## Creation parameter surfaces

### Image generation

- Model selection.
- Aspect ratio: 1:1, 9:16, 16:9, 3:4, 4:3.
- Quality: 1K, 2K, 3K, 4K.
- Prompt.
- Optional reference image.
- Generate action.
- Result image and download.

### Video generation

- Model selection.
- Aspect ratio: 16:9, 9:16, 1:1.
- Quality: 720P.
- Duration: 4, 5, 6, 8, 10, 12 seconds.
- Prompt.
- Optional reference image.
- T2V/I2V mode is derived from reference presence.
- Task launch.
- Task status / history result.

### Film production

- Story generation input.
- Character/reference input.
- Scene planning controls.
- Scene duration controls.
- Portrait/landscape output.
- Audio and voice.
- Subtitle toggle.
- Background production progress.
- Final video player.

## Feedback / system components

- Primary, secondary/ghost actions.
- Form labels.
- Inputs, textareas and selects.
- Model cards.
- Status text.
- Status chips/tags.
- Toasts.
- Result containers.
- Progress panel.
- Video player.
- Download links.
- Empty state.
- Responsive layout.

## Requested design-system coverage

The redesign system must cover, without changing backend contracts:

- API-key/status bar.
- Four creation modes and their parameter controls.
- Image generation.
- Task list/history.
- Progress panel.
- Video player.
- Workspace settings.
- Watermark toggle when exposed by the active workspace/settings surface.
- Buttons, inputs, textarea, select, segmented controls, toggles, sliders, tabs, cards, chips, tooltips, modals, toasts, progress, skeletons and empty states.

## i18n compatibility audit

No standalone locale dictionary, translation bundle, or seven-language selector is present under the audited `static/` directory on this branch. The redesign therefore avoids fixed-width text assumptions and uses flexible controls, wrapping, logical sizing and content-driven layout so an existing/upstream seven-language layer can remain intact. No language hook or locale API was removed.
