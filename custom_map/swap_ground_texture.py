"""Swap Sketchbook world.blend's grass material to use the satellite PNG as
its base color, then re-export as world.glb.
"""
import bpy
import os

BLEND = "/home/eeg/Sketchbook/src/blend/world.blend"
SATELLITE_PNG = "/home/eeg/Sketchbook/custom_map/satellite_raw.png"
WORLD_GLB = "/home/eeg/Sketchbook/build/assets/world.glb"


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sat_img = bpy.data.images.load(SATELLITE_PNG)

    grass = bpy.data.materials["grass"]
    print("grass nodes:")
    for n in grass.node_tree.nodes:
        print(" ", n.type, n.name, getattr(n, "image", None))
    print("grass links:")
    for l in grass.node_tree.links:
        print(f"  {l.from_node.name}.{l.from_socket.name} -> {l.to_node.name}.{l.to_socket.name}")

    # Find any Image Texture node whose image name contains "Moss" (the grass
    # texture) and swap it to the satellite image. If we can't find it, find
    # the BSDF and inject a new Image Texture node.
    swapped = False
    for n in grass.node_tree.nodes:
        if n.type == 'TEX_IMAGE' and n.image is not None:
            # The first image-texture node we find is the albedo
            print(f"swapping texture {n.image.name} -> {sat_img.name}")
            n.image = sat_img
            swapped = True
            break

    if not swapped:
        # Inject an Image Texture node into the BSDF's Base Color input
        nodes = grass.node_tree.nodes
        links = grass.node_tree.links
        bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
        # Disconnect whatever is connected to Base Color
        for l in list(links):
            if l.to_node == bsdf and l.to_socket.name == 'Base Color':
                links.remove(l)
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = sat_img
        tex.location = (bsdf.location.x - 400, bsdf.location.y)
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    # Export
    bpy.ops.export_scene.gltf(
        filepath=WORLD_GLB,
        export_format='GLB',
        export_apply=True,
        export_extras=True,
        export_yup=True,
    )
    print(f"exported {WORLD_GLB}")


if __name__ == "__main__":
    main()