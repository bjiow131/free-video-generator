# OCTAVA STUDIO — Source-first Blender asset recovery

Effective 2026-10-14. Experimental recovery branch only; no main modifications.

## Mandatory procedure before new modeling

1. Search existing .blend assets, compare silhouettes, facial topology, body proportions, age, clothing and rig features to the approved three-view Mia.
2. Check exact asset price, accessibility, author and modification/commercial license (CC0/CC-BY preferred). A website advertising "free assets" does not mean that a specific "Full Plan" asset is free.
3. Download only from known official source into a quarantine cache; store source URL, SHA-256, download time and license attribution in the asset passport. Never use binary content from untrusted sites or execute embedded Blender scripts on import.
4. Inspect quarantined .blend using a separate Blender process with --disable-autoexec and --offline-mode. Record mesh count, hashes of mesh coordinates per object, number of vertices, facial topology and shape keys, armature/bone mapping, textures, dependency paths and Blender compatibility.
5. Extract only licensed reusable components. Rigs, face meshes, eye systems, outfit meshes, and hair should be evaluated separately. Reuse is not identity.
6. Reconstruct missing anatomy as necessary, retarget rig after geometry is accepted, and run multi-view visual + pose QA.
7. Publish a preview to Telegram only when meaningfully changed from recent attempts. Never mark ready on Blender subprocess success alone.
8. If two consecutive new iterations fail to change the image or mesh meaningfully, halt the loop and debug source/algorithm rather than sending dozens of near identical photos.

## Verified discovery records (NOT declarations of completed downloads)

- Spring Rig: https://studio.blender.org/characters/spring/v1/
  Free CC-BY. Legacy Blender 2.8-era rig, BlenRig setup. A prior Windows report indicates 2259 Spring bones transferred to Mia draft meshes, but did not verify new Mia identity or facial animation.
- Rain Rig v3: https://studio.blender.org/characters/rain/v3/
  Free CC-BY from Blender Studio, updated for Blender 4.1+ with facial controls. Found online, NOT downloaded or tested on the target PC.
- Panda Girl full Blender rig: https://sketchfab.com/3d-models/panda-girl-stylizedfree-blender-rig-40c2bbc4c79d4ed8b8da5f0381d97168
  Stated CC Attribution. Found online, NOT downloaded or tested. Only a rig construction reference; not visually similar to Mia.
- Stylized Cartoon Child Girl Rigify: https://www.blendkit.com/asset-gallery-detail/239bdaa8-459d-4ee6-a267-edcb90aa99d4/
  Child body candidate but site identifies Full Plan access, so DO NOT treat as a verified freely downloadable source.

## Root-cause evidence (GitHub code plus live mailbox)

- local_agent/blender_workflow.py, _mia_reference_model_script(): procedural modeling with fixed random.seed(268). It does not reconstruct Mia face from input image.
- Approved reference is packed as an image, used for material projection and bounded outer silhouette optimization. Hair structure, eye shape, cheeks and facial features are not fitted. identity_verified=False is explicit.
- In the 2026-10-13 mailbox, a Mia rebuild task reported status=completed while production_ready=false and identity_verified=false; the comparison used an outer-contour-only metric.
- A Spring rig transfer task reported pose_test_passed=true for 2259 bones, with caveats about proximity weights and missing facial rig topology. This is NOT Mia likeness verification.
- Telegram sender previously sent 4 static views per completed draft without across-task novelty check.

## Quality gate

Release requires immutable Mia reference digest, explicit source .blend provenance, per-object mesh coordinate change report, neutral pose and face controls, three-view and face closeup visual comparison, and targeted real Windows Blender validation. A low contour RMS alone cannot approve a character. Do not repeat 100-pass loops until upstream mesh generation and identity validation are repaired.
