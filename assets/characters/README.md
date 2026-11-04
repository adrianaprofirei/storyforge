# Custom characters

Put your own rigged characters here (`.blend`, `.fbx`, `.glb`/`.gltf`) and reference them from a
cast entry (`data/projects/<series>/cast/<id>.yaml` or the Cast page in the web UI):

```yaml
id: robo
name: Robo
kind: imported
import:
  file: robo/robo.glb      # relative to assets/characters
  scale: 1.0               # optional, auto-fit to the cast height otherwise
  bone_map: {}             # optional {canonical_bone: your_bone}; Mixamo, Rigify, VRoid,
                           # Unreal mannequin and CMU names are detected automatically
  face: {}                 # optional {expression_or_viseme: shape_key_name}
look: {height: 1.0}
voice: {provider: openai, voice: onyx}
```

Imported characters are driven through a hidden canonical proxy rig and baked, so every
mocap clip, gesture, prop hold, foot lock and look-at works on them. Shape keys named after
visemes (`A`..`H`, `X`) and expressions (`happy`, `sad`, ...) drive the face when present.

Only use characters you made or have the rights to; never commit them (git-ignored), and record
the source and license in `license_manifest.yaml`.
