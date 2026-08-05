"""Visible-only 3D model + heightmap trimesh floor.

Imports roundabout.glb (captured GE Pro model) as render-only geometry —
no per-primitive colliders. Builds a heightmap trimesh collider by sampling
the model's lowest Y on a grid, so the car drives on terrain that follows
the actual road elevation instead of a flat plane.
"""
import bpy
import json
import os
from collections import defaultdict

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
META_JSON = os.path.join(OUT_DIR, "satellite_meta.json")
BUILDINGS_GLB = "/home/eeg/tmp/roundabout.glb"
WORLD_GLB = "/home/eeg/Sketchbook/build/assets/world.glb"

# Iterative alignment for the visible model. Units are meters in glTF space.
X_OFFSET = 133.5
Y_OFFSET = -15.72
Z_OFFSET = -101.5

# Heightmap grid spacing (meters). Smaller = follows terrain more closely
# but more trimesh triangles. 10m is a good balance for a 530x276m scene.
GRID_SPACING = 10.0

# Spawn high in the air so the car drops onto whatever's below.
SPAWN_Y = 50.0

with open(META_JSON) as f:
    _meta = json.load(f)
FLOOR_W = _meta["ground_w_m"]
FLOOR_H = _meta["ground_h_m"]


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
    """Import roundabout.glb and offset all geometry. No physics marking."""
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=BUILDINGS_GLB)
    imported = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    bx, by, bz = gltf_to_blender(X_OFFSET, Y_OFFSET, Z_OFFSET)
    # Collect (glTF X, glTF Z, glTF Y) per vertex — X and Z are the ground
    # plane, Y is the height. all_y is just the height column for skirt cutoff.
    all_y = []
    vertex_samples = []  # (gltf_x, gltf_z, gltf_y)
    for obj in imported:
        if obj.type != 'MESH':
            continue
        for v in obj.data.vertices:
            # Blender (x, y, z) -> glTF (x, z, -y) — but we already added the
            # offset in Blender space, so convert back to glTF for sampling.
            gltf_x = v.co.x + bx
            gltf_z = -(v.co.y + by)  # glTF Z = -Blender Y
            gltf_y = v.co.z + bz    # glTF Y = Blender Z
            all_y.append(gltf_y)
            vertex_samples.append((gltf_x, gltf_z, gltf_y))
        for v in obj.data.vertices:
            v.co.x += bx
            v.co.y += by
            v.co.z += bz
        obj.data.update()
    print(f"imported {len(imported)} objects; {len(vertex_samples)} vertices sampled")
    return vertex_samples, all_y


def build_heightmap(vertex_samples, all_y):
    """Build a heightmap mesh from vertex samples.

    For each grid cell (in the X/Z ground plane), take the lowest vertex Y
    in that cell (skipping the bottom 5% to ignore underground skirt).
    Grid extent matches the visible model's XZ bounds plus a 1-cell margin.
    """
    sorted_y = sorted(all_y)
    skirt_cutoff = sorted_y[int(len(sorted_y) * 0.05)]
    print(f"skirt cutoff Y (5th percentile): {skirt_cutoff:.3f}")

    # Compute model's XZ bounds from the sampled vertices (above skirt).
    xs = [s[0] for s in vertex_samples if s[2] >= skirt_cutoff]
    zs = [s[1] for s in vertex_samples if s[2] >= skirt_cutoff]
    if not xs or not zs:
        print("no vertices above skirt cutoff; falling back to satellite extent")
        half_w = FLOOR_W / 2
        half_h = FLOOR_H / 2
    else:
        half_w = (max(xs) - min(xs)) / 2 + GRID_SPACING
        half_h = (max(zs) - min(zs)) / 2 + GRID_SPACING
    nx = int(2 * half_w / GRID_SPACING) + 1
    nz = int(2 * half_h / GRID_SPACING) + 1

    # Bucket vertices by grid cell (X, Z), track Y values per cell.
    # We want the road SURFACE — the top of the lowest cluster of geometry,
    # not the bottom of the road tile (which would sink the car into the
    # visible road) and not the building roof (which would put the car on
    # the roof). For each cell, take min Y, then the max Y within 1m of
    # that min — the top of the road tile / building base.
    cell_ys = defaultdict(list)
    for gltf_x, gltf_z, gltf_y in vertex_samples:
        if gltf_y < skirt_cutoff:
            continue
        gx = int((gltf_x + half_w) / GRID_SPACING)
        gz = int((gltf_z + half_h) / GRID_SPACING)
        if 0 <= gx < nx and 0 <= gz < nz:
            cell_ys[(gx, gz)].append(gltf_y)

    min_y_per_cell = {}
    for key, ys in cell_ys.items():
        cell_min = min(ys)
        # Top of the lowest 1m of geometry — the drivable surface.
        lowest_band_top = max(y for y in ys if y < cell_min + 1.0)
        min_y_per_cell[key] = lowest_band_top

    default_y = skirt_cutoff - 1
    verts = []
    heights = []
    for iz in range(nz):
        for ix in range(nx):
            gltf_x = -half_w + ix * GRID_SPACING
            gltf_z = -half_h + iz * GRID_SPACING
            gltf_y = min_y_per_cell.get((ix, iz), default_y)
            # Convert glTF (x, y, z) to Blender (x, -z, y) for the mesh.
            verts.append((gltf_x, -gltf_z, gltf_y))
            heights.append(gltf_y)

    # Faces: CCW from +Z so normal points up (glTF +Y after export).
    faces = []
    for iz in range(nz - 1):
        for ix in range(nx - 1):
            i00 = iz * nx + ix
            i10 = iz * nx + (ix + 1)
            i01 = (iz + 1) * nx + ix
            i11 = (iz + 1) * nx + (ix + 1)
            faces.append((i00, i01, i11, i10))

    mesh = bpy.data.meshes.new("FloorCollider_mesh")
    obj = bpy.data.objects.new("FloorCollider", mesh)
    bpy.context.collection.objects.link(obj)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    populated = sum(1 for v in heights if v != default_y)
    print(f"heightmap: {nx}x{nz} vertices, {len(faces)} quads, "
          f"{populated}/{len(heights)} cells populated; Y range "
          f"[{min(heights):.2f}, {max(heights):.2f}]")
    return obj


def main():
    reset_scene()

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

    player = add_empty("PlayerCarSpawn", (20, SPAWN_Y, 0), parent=scenario)
    set_custom_props(player, data="spawn", type="car", driver="player")

    vertex_samples, all_y = import_buildings()

    floor = build_heightmap(vertex_samples, all_y)
    set_custom_props(floor, data="physics", type="trimesh")

    bpy.ops.export_scene.gltf(
        filepath=WORLD_GLB,
        export_format='GLB',
        export_apply=True,
        export_extras=True,
        export_yup=True,
    )
    print(f"exported {WORLD_GLB}")
    print(f"player spawn: glTF (20, {SPAWN_Y}, 0)")
    print(f"grid spacing: {GRID_SPACING}m")


if __name__ == "__main__":
    main()