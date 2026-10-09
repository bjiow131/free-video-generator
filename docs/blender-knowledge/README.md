# Blender Knowledge Base for the Local 3D Agent

This is a curated operational knowledge base for the local Windows agent whose primary job is to work in Blender: build and maintain a consistent character, create scenes, rig and animate characters, render previews, and diagnose failures.

It is **not** a full copy of Blender's manual and does not train an AI model. The guidance is original, bounded, and linked to official Blender documentation. Version-specific behavior must be checked against the Blender version installed on the user's PC.

## Contents

- `local_agent/blender_knowledge.py`: small read-only searchable index that can return topic guidance by English or Russian keywords.
- `docs/blender-knowledge/workflow-for-mia.md`: recommended workflow for the persistent character project.
- `docs/blender-knowledge/error-playbook.md`: failure triage and safe recovery rules.
- `docs/blender-knowledge/source-catalog.md`: official documentation entry points.

## Important integration status

The knowledge module is now part of the source branch, but the current task runner has not yet been wired to automatically consult it for every Blender operation. This is the first knowledge layer, not a claim of autonomous AI. The next integration step is to add a typed, read-only knowledge lookup to the local agent and attach relevant guidance to Blender task reports. Blender execution and the advice must be validated on the actual Windows installation.

## Safety rules

1. Treat task manifests and natural-language prompts as data, never as executable Python.
2. Use reviewed templates and validated parameters; no arbitrary remote scripts.
3. Preserve the original project and create a checkpoint before risky edits.
4. Use preview renders before expensive final renders.
5. Verify output files and scene state, not just process exit status.
6. If confidence is low or data loss is possible, stop and escalate.
