"""Build world.glb: satellite-textured ground + scenario + imported buildings.

Imports roundabout.glb (exported from Google Earth via RenderDoc) and offsets
all building geometry by X_OFFSET/Z_OFFSET so it sits on top of the satellite
plane. Iterate the offsets by eye in the browser until buildings align with
satellite imagery; re-run this script after each change.
"""
import bpy
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
SATELLITE_PNG = os.path.join(OUT_DIR, "satellite_raw.png")
META_JSON = os.path.join(OUT_DIR, "satellite_meta.json")
BUILDINGS_GLB = "/home/eeg/tmp/roundabout.glb"
WORLD_GLB = "/home/eeg/Sketchbook/build/assets/world.glb"

# Iterative alignment: tweak these until buildings sit on top of the satellite
# imagery in the browser. Units are meters in glTF space.
X_OFFSET = 133.5      # buildings captured from -267 to 0 in X; +133.5 centers them
Z_OFFSET = -101.5    # buildings captured from +1 to +202 in Z; -101.5 centers them
Y_OFFSET = -15.72   # iterate: lower further until buildings sit on the satellite plane in browser

with open(META_JSON) as f:
    _meta = json.load(f)
TERRAIN_W_M = _meta["ground_w_m"]
TERRAIN_H_M = _meta["ground_h_m"]


def gltf_to_blender(x, y, z):
    # glTF (Y up) -> Blender (Z up): B_x = G_x, B_y = -G_z, B_z = G_y
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
    faces = [(0, 2, 3, 1)]
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


def import_buildings():
    """Import roundabout.glb, offset all geometry to sit on the satellite
    plane, then create per-building box colliders (one per primitive, since
    the glb exports each building as a separate material on a single mesh).
    Box colliders are cheap in cannon.js; a single merged trimesh of 944
    buildings would be laggy.
    """
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=BUILDINGS_GLB)
    imported = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    # glTF offset (X_OFFSET, Y_OFFSET, Z_OFFSET) -> Blender offset (X, -Z, Y).
    bx, by, bz = gltf_to_blender(X_OFFSET, Y_OFFSET, Z_OFFSET)
    building_objs = []
    for obj in imported:
        if obj.type != 'MESH':
            continue
        mesh = obj.data
        for v in mesh.vertices:
            v.co.x += bx
            v.co.y += by
            v.co.z += bz
        mesh.update()
        building_objs.append(obj)
    print(f"imported {len(imported)} objects from buildings.glb; offset applied")

    # The captured glb has all 944 buildings as primitives on ONE mesh (one
    # material per building). Separate by material so each building becomes
    # its own object — we need per-building bounds for the box colliders.
    if len(building_objs) == 1 and len(building_objs[0].data.materials) > 1:
        obj = building_objs[0]
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='MATERIAL')
        bpy.ops.object.mode_set(mode='OBJECT')

    # Refresh building list after separate().
    base_name = "2161535352615260662247"
    building_objs = [o for o in bpy.data.objects
                     if o.type == 'MESH' and o.name.startswith(base_name)]
    print(f"separated into {len(building_objs)} building objects")

    # Mark each building primitive as a convex polyhedron collider. The
    # patched Sketchbook's World.ts converts the mesh vertices to a
    # CANNON.ConvexPolyhedron. Convex hulls are tighter than AABB boxes
    # (follow the actual geometry outline) and much faster than trimesh.
    # keepVisible="true" makes the visible mesh ALSO be the collider — no
    # separate box meshes. All primitives (including road tiles) get a
    # hull, so the car drives on the road's actual flat surface (no steps).
    collider_count = 0
    for obj in building_objs:
        mesh = obj.data
        if not mesh.vertices:
            continue
        set_custom_props(obj, data="physics", type="convex", keepVisible="true")
        collider_count += 1
    print(f"marked {collider_count} primitives as convex colliders")


def main():
    reset_scene()
    # The captured 3D model from GE Pro contains the road + buildings + ground.
    # No flat satellite plane, no flat collider — the captured model is the
    # entire scene. Box colliders from import_buildings() cover everything
    # (road, ground, buildings) for the car to drive on.

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

    player = add_empty("PlayerCarSpawn", (20, 1, 0), parent=scenario)
    set_custom_props(player, data="spawn", type="car", driver="player")

    import_buildings()

    bpy.ops.export_scene.gltf(
        filepath=WORLD_GLB,
        export_format='GLB',
        export_apply=True,
        export_extras=True,
        export_yup=True,
    )
    print(f"exported {WORLD_GLB}")
    print(f"terrain: {TERRAIN_W_M:.0f}m x {TERRAIN_H_M:.0f}m; building offset = "
          f"glTF ({X_OFFSET}, {Y_OFFSET}, {Z_OFFSET})")


if __name__ == "__main__":
    main()