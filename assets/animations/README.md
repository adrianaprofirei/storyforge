# Animation library

Put motion-capture files here (`.fbx`, `.bvh`, `.glb`/`.gltf`), e.g. Mixamo clips downloaded
"Without Skin" or CMU BVH conversions. They are git-ignored: only `license_manifest.yaml`
is committed. Every file is retargeted once onto StoryForge's canonical humanoid (Mixamo, CMU,
Unreal mannequin, Rigify and VRoid bone names are detected automatically) and cached.

A clip whose tag matches a story action (`wave`, `talk`, `walk`, `idle`, `jump`, ...) replaces the
built-in procedural clip for that action. Run `storyforge assets` to export the built-in clips as
BVH to `data/library/clips/` if you want to inspect or edit them in another tool.
