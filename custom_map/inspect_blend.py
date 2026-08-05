"""Dump the structure of Sketchbook's world.blend so we can see exactly what
makes the demo scene work: scenarios, spawn points, paths, custom properties,
collections, parent/child relationships, the ground mesh, etc.
"""
import bpy

BLEND = "/home/eeg/Sketchbook/src/blend/world.blend"


def dump_obj(o, indent=0):
    pad = "  " * indent
    custom = {k: o[k] for k in o.keys() if k not in ('_RNA_UI',)} if hasattr(o, "keys") else {}
    print(f"{pad}- {o.type} '{o.name}' loc={tuple(round(v,2) for v in o.location)} parent={o.parent.name if o.parent else None} custom={custom}")
    if o.type == 'MESH':
        mats = [s.material.name if s.material else None for s in o.material_slots]
        print(f"{pad}    mesh: {o.data.name}, mats={mats}, verts={len(o.data.vertices)}")
    for child in o.children:
        dump_obj(child, indent + 1)


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    print("=== COLLECTIONS ===")
    for c in bpy.data.collections:
        print(f"  {c.name}: {len(c.objects)} objects")
    print("=== SCENE ROOT OBJECTS ===")
    scene = bpy.context.scene
    roots = [o for o in scene.objects if o.parent is None]
    for o in roots:
        dump_obj(o)
    print("=== ALL SCENARIOS (objects with data='scenario') ===")
    for o in bpy.data.objects:
        if 'data' in o.keys() and o['data'] == 'scenario':
            custom = {k: o[k] for k in o.keys() if k not in ('_RNA_UI',)}
            print(f"  scenario '{o.name}' custom={custom}")
            for c in o.children:
                cc = {k: c[k] for k in c.keys() if k not in ('_RNA_UI',)}
                print(f"    child {c.type} '{c.name}' loc={tuple(round(v,2) for v in c.location)} custom={cc}")
    print("=== PATHS (objects with data='path') ===")
    for o in bpy.data.objects:
        if 'data' in o.keys() and o['data'] == 'path':
            print(f"  path '{o.name}' children={len(o.children)}")
            for c in o.children:
                cc = {k: c[k] for k in c.keys() if k not in ('_RNA_UI',)}
                print(f"    node {c.name} loc={tuple(round(v,2) for v in c.location)} custom={cc}")


if __name__ == "__main__":
    main()