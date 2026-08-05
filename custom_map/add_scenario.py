"""Add a new 'Hinckley Roundabout' scenario to Sketchbook's world.blend.

- Restore the demo's grass texture (which the previous script swapped).
- Add a new ground plane (satellite-textured) + trimesh collider, placed ~1km
  east of the demo scene so they don't visually overlap.
- Add a new scenario container 'Hinckley Roundabout' with a player car spawn
  on the new ground.
- Re-export world.glb. The original demo scenarios stay intact; the new one
  shows up in the right panel and can be launched to teleport there.
"""
import bpy
import math
import os

BLEND = "/home/eeg/Sketchbook/src/blend/world.blend"
SATELLITE_PNG = "/home/eeg/Sketchbook/custom_map/satellite_raw.png"
WORLD_GLB = "/home/eeg/Sketchbook/build/assets/world.glb"

# Center of the new scenario, far from the demo scene.
SCENE_OFFSET = (1500.0, 0.0, 0.0)   # 1.5km east
TERRAIN_W_M = 1792 * 0.181   # ~324m
TERRAIN_H_M = 1536 * 0.181   # ~278m


def gltf_to_blender(x, y, z):
    """glTF/three.js coords (Y up) -> Blender (Z up).
    Blender_X = glTF_X, Blender_Y = -glTF_Z, Blender_Z = glTF_Y.
    """
    return (x, -z, y)


def set_custom_props(obj, **props):
    for k, v in props.items():
        obj[k] = v


def make_satellite_material():
    img = bpy.data.images.load(SATELLITE_PNG)
    mat = bpy.data.materials.new("satellite_ground")
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


def restore_grass_texture():
    """Restore the grass material's original moss texture."""
    grass = bpy.data.materials.get("grass")
    if not grass:
        return
    # Find the original moss image
    moss = None
    for img in bpy.data.images:
        if "Moss" in img.name:
            moss = img
            break
    if moss is None:
        print("WARN: no moss image found to restore grass texture")
        return
    # Find an image-texture node and re-assign
    for n in grass.node_tree.nodes:
        if n.type == 'TEX_IMAGE':
            print(f"restoring grass texture -> {moss.name}")
            n.image = moss
            return
    print("WARN: no image-texture node in grass material to restore")


def add_plane(name, w, h, location_gltf, material=None, subdiv=0):
    """Plane in Blender's XY (Z=0). After glTF export (yup=True) it becomes
    glTF's XZ at Y=0 with normal +Y. UVs map image top -> +Z (north).
    location_gltf is in glTF/three.js coords (Y up) and applied to the object.
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
            y = h / 2 - (h * iy) / (ny - 1)
            verts.append((x, y, 0.0))
            u = ix / (nx - 1)
            v = 1.0 - iy / (ny - 1)
            uvs.append((u, v))
    faces = []
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            a = iy * nx + ix
            b = iy * nx + ix + 1
            c = (iy + 1) * nx + ix + 1
            d = (iy + 1) * nx + ix
            faces.append((a, b, c, d))
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uvs[loop.vertex_index]
    if material is not None:
        obj.data.materials.append(material)
    obj.location = gltf_to_blender(*location_gltf)
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
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    restore_grass_texture()

    mat = make_satellite_material()

    cx, cy, cz = SCENE_OFFSET
    visible = add_plane("HinckleyTerrain", TERRAIN_W_M, TERRAIN_H_M, (cx, 0, cz), material=mat)
    collider = add_plane("HinckleyTerrainCollider", TERRAIN_W_M, TERRAIN_H_M, (cx, 0, cz))
    set_custom_props(collider, data="physics", type="trimesh")

    # Scenario container at the new ground's center
    scenario = add_empty("HinckleyRoundabout", (cx, 0, cz))
    set_custom_props(
        scenario,
        **{
            "data": "scenario",
            "name": "Hinckley Roundabout",
            "desc_title": "Hinckley Roundabout",
            "desc_content": "Drive around the roundabout near Hinckley, UK.",
        }
    )

    # Player car spawn: 100m south of the new ground center, 1m up.
    player_spawn = add_empty("HinckleyPlayerSpawn", (cx, 1, cz - 100), parent=scenario)
    set_custom_props(player_spawn, data="spawn", type="car", driver="player")

    # AI car spawn + path around the roundabout (radius ~30m at the new center)
    ai_spawn = add_empty("HinckleyAISpawn", (cx + 120, 1, cz), parent=scenario)
    set_custom_props(ai_spawn, data="spawn", type="car", driver="ai", first_node="h_p1")

    path_root = add_empty("HinckleyPath", (cx, 0, cz))
    set_custom_props(path_root, data="path")
    path_radius = 30.0
    n_nodes = 8
    for i in range(n_nodes):
        ang = 2 * math.pi * i / n_nodes
        x = cx + path_radius * math.sin(ang)
        z = cz + path_radius * math.cos(ang)
        node = add_empty(f"h_p{i+1}", (x, 1, z), parent=path_root)
        nxt = (i + 1) % n_nodes + 1
        prv = (i - 1) % n_nodes + 1
        set_custom_props(node, data="pathNode",
                         nextNode=f"h_p{nxt}",
                         previousNode=f"h_p{prv}")

    bpy.ops.export_scene.gltf(
        filepath=WORLD_GLB,
        export_format='GLB',
        export_apply=True,
        export_extras=True,
        export_yup=True,
    )
    print(f"exported {WORLD_GLB}")
    print(f"new scenario at glTF ({cx}, {cy}, {cz}) — {TERRAIN_W_M:.0f}m x {TERRAIN_H_M:.0f}m ground")


if __name__ == "__main__":
    main()