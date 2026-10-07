# ComfyUI integration

ComfyUI is an optional local provider. The existing Agnes provider remains unchanged.

## Current state

workflows/comfyui/workflow.json is an API-format scaffold, not a verified production workflow. The graph shape is conventional text-to-image, but the checkpoint and exact graph have not been verified on a real ComfyUI installation.

## Prepare ComfyUI

1. Start ComfyUI. Default local API: http://127.0.0.1:8188
2. Install the checkpoint/model required by the graph.
3. Build or import the desired graph.
4. Execute it once manually and confirm an image is produced.
5. Export API-format JSON from ComfyUI.
6. Replace workflows/comfyui/workflow.json with that exported JSON.
7. Remove scaffold metadata fields beginning with underscore.
8. Configure node bindings.

Environment variables:
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_PATH=C:\\free-video-generator\\workflows\\comfyui\\workflow.json
COMFYUI_PROMPT_NODE=6
COMFYUI_PROMPT_INPUT=text
COMFYUI_SEED_NODE=3
COMFYUI_SEED_INPUT=seed
COMFYUI_WIDTH_NODE=5
COMFYUI_WIDTH_INPUT=width
COMFYUI_HEIGHT_NODE=5
COMFYUI_HEIGHT_INPUT=height

The node ids above match the repository scaffold only and must be changed for the exported graph.

## API behavior

The integration submits the graph to POST /prompt, receives prompt_id, then polls GET /history/{prompt_id} until completion or timeout.

## Verification

Provider client: IMPLEMENTED
Workflow loader/binding: IMPLEMENTED
Real ComfyUI connection: NOT VERIFIED
Real model/checkpoint: NOT VERIFIED
Manual successful generation: NOT VERIFIED
Production workflow export: NOT VERIFIED
