# Mia reference proportion fit v1

The previous static review constructed a fixed procedural model. It now fits ten bounded shape parameters to the outer contours of the approved front, side and back reference images. This is an independent implementation of the multi-view silhouette fitting principle demonstrated in https://pytorch3d.org/tutorials/fit_textured_mesh . It does not copy that tutorial's code or require PyTorch3D.

## Scope and safeguards

- Runs through the existing no-argument mia_model_review operation and local Blender permission.
- Canonical reference SHA-256 remains 7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383.
- Masks reject the gray backdrop and black letterbox and check their bounds and consistent view scale.
- Camera geometry is inferred approximately as orthographic; these are outer-contour profile losses, not full rasterized silhouette losses.
- Smooth, positive, bounded cage scales preserve vertex count and topology; they do not guarantee animation-ready topology or prevent every surface intersection.
- At most 241 evaluations, deterministic sampling; accepted changes are checked on all mesh vertices.
- Retain only improvements above 0.2 percent, with no individual contour error worsening more than 3 percent. Otherwise keep original geometry.
- Preserve before_fit.blend and before_front.png, masks, a detailed fit_report.json and final .blend.
- Before/after comparison keeps materials unchanged. Side camera faces the reference's direction.
- This changes proportions, not facial identity, hairstyle reconstruction, rigging or hidden surfaces. production_ready and identity_verified remain false.
- Updates affect only blender_workflow.py, preserving newer unrelated advisor and mailbox code. The trusted updater backs up and tests the installation.

## Validation

Five local tests passed: recovery of a known synthetic deformation; preservation of matching geometry; bounds/nonfinite input and monotonic vertical deformation; letterbox segmentation; actual private reference segmentation. The actual reference stays outside the source repository. Tests extract the exact shipped bundled helpers. Blender is not installed in the development container; runtime validation was performed by the Windows agent.

Real task: mia-reference-fit-test-20261013T213025Z
Mailbox evidence: https://github.com/bjiow131/local-agent-mailbox/blob/main/queue/results/mia-reference-fit-test-20261013T213025Z.json
Agent outcome: completed.
Vertices: 206555. Evaluations: 187.
Mean aggregate outer-contour RMS error reduction: 29.75 percent. This is NOT a likeness score.

| View | Before RMS / height | After RMS / height |
| --- | --- | --- |
| Front | 0.038369017167756855 | 0.027643856170863415 |
| Side | 0.032570908592554106 | 0.021703745558991985 |
| Back | 0.03705974476331243 | 0.02651881627728834 |

Telegram photo delivery reported delivered for front, three_quarter, side and back. Visual acceptance remains pending. Dropbox reports only copying to a local sync folder; remote synchronization is unverified.
