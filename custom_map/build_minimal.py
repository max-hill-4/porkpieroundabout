"""Minimal world.glb: just a satellite-textured ground + one player car spawn.
Nothing else. No demo terrain, no AI, no other scenarios.
"""
import bpy
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
SATELLITE_PNG = os.path.join(OUT_DIR, "satellite_raw.png")
META_JSON = os.path.join(OUT_DIR, "satellite_meta.json")
WORLD_GLB = "/home/eeg/Sketchbook/build/assets/world.glb"

# Ground extent comes from the fetch script's metadata file — keeps the
# terrain plane sized to whatever the satellite image actually covers.
with open(META_JSON) as f:
    _meta = json.load(f)
TERRAIN_W_M = _meta["ground_w_m"]
TERRAIN_H_M = _meta["ground_h_m"]


def gltf_to_blender(x, y, z):
    return (x, -z, y)


def set_custom_props(obj, **props):
    for k, v in props.items():
        obj[k] = v


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials,
                 bpy.data.images, bpy.data.textures):
        for item in list(coll):
            coll.remove(item)


def make_satellite_material():
    img = bpy.data.images.load(SATELLITE_PNG)
    mat = bpy.data.materials.new("ground")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    # Unlit: Emission shader as the only surface output → glTF exporter emits
    # KHR_materials_unlit → three.js loads as MeshBasicMaterial (no scene lights).
    emi = nodes.new("ShaderNodeEmission")
    uv = nodes.new("ShaderNodeUVMap")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    links.new(uv.outputs["UV"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], emi.inputs["Color"])
    emi.inputs["Strength"].default_value = 1.0
    links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return mat


def add_plane(name, w, h, material=None):
    """Plane in Blender XY (Z=0) -> glTF XZ at Y=0 after export."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    nx = ny = 2
    verts = []
    uvs = []
    for iy in range(ny):
        for ix in range(nx):
            x = -w / 2 + (w * ix) / (nx - 1)
            y = h / 2 - (h * iy) / (ny - 1)
            verts.append((x, y, 0.0))
            u = ix / (nx - 1)
            v = 1.0 - iy / (ny - 1)
            uvs.append((u, v))
    faces = [(0, 2, 3, 1)]  # CCW from +Z → +Z normal in Blender → +Y up in glTF
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uvs[loop.vertex_index]
    if material is not None:
        obj.data.materials.append(material)
    return obj


def add_empty(name, gltf_pos, parent=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = 'PLAIN_AXES'
    e.empty_display_size = 4.0
    e.location = gltf_to_blender(*gltf_pos)
    bpy.context.collection.objects.link(e)
    if parent is not None:
        e.parent = parent
    return e


def main():
    reset_scene()
    mat = make_satellite_material()

    add_plane("Terrain", TERRAIN_W_M, TERRAIN_H_M, material=mat)
    collider = add_plane("TerrainCollider", TERRAIN_W_M, TERRAIN_H_M)
    set_custom_props(collider, data="physics", type="trimesh")

    scenario = add_empty("Roundabout", (0, 0, 0))
    set_custom_props(
        scenario,
        **{
            "data": "scenario",
            "name": "Hinckley Roundabout",
            "default": "true",
            "desc_title": "Hinckley Roundabout",
            "desc_content": "Drive around.",
            "camera_angle": 0,
        }
    )

    player = add_empty("PlayerCarSpawn", (0, 1, 0), parent=scenario)
    set_custom_props(player, data="spawn", type="car", driver="player")

    bpy.ops.export_scene.gltf(
        filepath=WORLD_GLB,
        export_format='GLB',
        export_apply=True,
        export_extras=True,
        export_yup=True,
    )
    print(f"exported {WORLD_GLB}")
    print(f"terrain: {TERRAIN_W_M:.0f}m x {TERRAIN_H_M:.0f}m, player at glTF (0,1,0)")


if __name__ == "__main__":
    main()