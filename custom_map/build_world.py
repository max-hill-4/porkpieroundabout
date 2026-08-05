"""Build a Sketchbook-compatible world.glb from the fetched satellite PNG.

Coordinate convention (matches Sketchbook / three.js / glTF, Y up):
    +X = east
    +Y = up
    +Z = north
Blender uses Z up by default, but the glTF exporter with export_yup=True
converts Blender Z -> glTF Y. So in Blender:
    Blender +Z -> glTF +Y (up)
    Blender +X -> glTF +X (east)
    Blender +Y -> glTF -Z (south)
We build the plane in Blender's XY plane (Z=0) so it becomes glTF's XZ plane (Y=0).

Run with:
    blender --background --python build_world.py
"""
import bpy
import os
import math

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
SATELLITE_PNG = os.path.join(OUT_DIR, "satellite_raw.png")
WORLD_GLB = "/home/eeg/Sketchbook/build/assets/world.glb"

# Approx true ground extent of satellite_raw.png (lat 52.6, z=19, ~0.181 m/px).
TERRAIN_W_M = 1792 * 0.181   # ~324m E-W
TERRAIN_H_M = 1536 * 0.181   # ~278m N-S


def gltf_to_blender(x, y, z):
    """Convert glTF/three.js coords (Y up) to Blender coords (Z up).
    Blender_X = glTF_X, Blender_Y = -glTF_Z, Blender_Z = glTF_Y.
    """
    return (x, -z, y)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials,
                 bpy.data.images, bpy.data.textures):
        for item in list(coll):
            coll.remove(item)


def make_satellite_material(image_path):
    img = bpy.data.images.load(image_path)
    mat = bpy.data.materials.new("ground")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    uv = nodes.new("ShaderNodeUVMap")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    links.new(uv.outputs["UV"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def add_plane(name, w, h, material=None, subdiv=0):
    """Build a horizontal plane in Blender's XY (Z=0), normal +Z. After glTF
    export (yup=True) it becomes glTF's XZ plane at Y=0 with normal +Y.
    UVs: u=0 at west (-X), u=1 at east (+X), v=0 at south (-Z in glTF, +Y in Blender),
    v=1 at north (+Z in glTF, -Y in Blender). Matches the satellite image
    layout (image top = north, image left = west).
    """
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    nx = max(2, subdiv + 2)
    ny = max(2, subdiv + 2)
    verts = []
    uvs = []
    for iy in range(ny):
        for ix in range(nx):
            x = -w / 2 + (w * ix) / (nx - 1)
            y = h / 2 - (h * iy) / (ny - 1)   # iy=0 -> +Y (north in glTF after export)
            verts.append((x, y, 0.0))
            u = ix / (nx - 1)
            v = 1.0 - iy / (ny - 1)  # iy=0 -> v=1 (north, top of image)
            uvs.append((u, v))
    faces = []
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            a = iy * nx + ix
            b = iy * nx + ix + 1
            c = (iy + 1) * nx + ix + 1
            d = (iy + 1) * nx + ix
            # Winding so normal points +Z in Blender (-> +Y in glTF)
            faces.append((a, b, c, d))
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uvs[loop.vertex_index]
    if material is not None:
        obj.data.materials.append(material)
    return obj


def set_custom_props(obj, **props):
    for k, v in props.items():
        obj[k] = v


def add_empty(name, gltf_pos, parent=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = 'PLAIN_AXES'
    e.empty_display_size = 2.0
    e.location = gltf_to_blender(*gltf_pos)
    bpy.context.collection.objects.link(e)
    if parent is not None:
        e.parent = parent
    return e


def main():
    reset_scene()
    mat = make_satellite_material(SATELLITE_PNG)

    visible = add_plane("Terrain", TERRAIN_W_M, TERRAIN_H_M, material=mat, subdiv=0)
    collider = add_plane("TerrainCollider", TERRAIN_W_M, TERRAIN_H_M, subdiv=0)
    set_custom_props(collider, data="physics", type="trimesh")

    scenario = add_empty("Roundabout", (0, 0, 0))
    set_custom_props(
        scenario,
        **{
            "data": "scenario",
            "name": "Roundabout",
            "default": "true",
            "desc_title": "Roundabout",
            "desc_content": "Drive around the roundabout. Player car at the south approach.",
        }
    )

    # Player car spawn: 100m south of center, 1m up, facing north (+Z).
    # Empty's rotation: forward = -Y in Blender (which becomes +Z = north in glTF).
    # Set rotation_euler so the empty's -Y axis points to +Z in glTF.
    # Easiest: rotate the empty 180° around Blender Z (which is glTF Y).
    player_spawn = add_empty("PlayerCarSpawn", (0, 1, -100), parent=scenario)
    # In Sketchbook, vehicle.setPosition uses world position; orientation comes
    # from worldQuaternion. The empty's default forward (-Y in Blender) maps to
    # +Z in glTF (north) after export. So no rotation needed.
    set_custom_props(player_spawn, data="spawn", type="car", driver="player")

    ai_spawn = add_empty("AICarSpawn", (120, 1, 0), parent=scenario)
    set_custom_props(ai_spawn, data="spawn", type="car", driver="ai", first_node="p1")

    # AI path: loop around the roundabout center.
    path_root = add_empty("Path1", (0, 0, 0))
    set_custom_props(path_root, data="path")

    path_radius = 30.0
    n_nodes = 8
    for i in range(n_nodes):
        ang = 2 * math.pi * i / n_nodes
        x = path_radius * math.sin(ang)
        z = path_radius * math.cos(ang)
        node = add_empty(f"p{i+1}", (x, 1, z), parent=path_root)
        nxt = (i + 1) % n_nodes + 1
        prv = (i - 1) % n_nodes + 1
        set_custom_props(node, data="pathNode",
                         nextNode=f"p{nxt}",
                         previousNode=f"p{prv}")

    os.makedirs(os.path.dirname(WORLD_GLB), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=WORLD_GLB,
        export_format='GLB',
        export_apply=True,
        export_extras=True,
        export_yup=True,
    )
    print(f"exported {WORLD_GLB}")
    print(f"terrain: {TERRAIN_W_M:.1f}m x {TERRAIN_H_M:.1f}m (gltf XZ at Y=0, normal +Y)")


if __name__ == "__main__":
    main()