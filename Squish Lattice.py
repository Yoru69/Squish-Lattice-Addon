bl_info = {
    "name": "Squish Lattice",
    "author": "Claude",
    "version": (2, 3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar (N) > Squash Lattice",
    "description": "One click squish setup: glass cube (parent) + hidden lattice U8 V4 W8 (child) with a Squish Y slider, lattice modifier placed right after the Armature modifier",
    "category": "Object",
}

import bpy
import bmesh
from mathutils import Matrix
from bpy.props import (
    IntProperty, BoolProperty, FloatProperty, FloatVectorProperty,
)

TAG = "squish_setup"          # custom property used to find objects made by this addon
LATTICE_NAME = "Squish Lattice"
CUBE_NAME = "Squish Glass"
MOD_NAME = "Squish Lattice"
MAT_NAME = "Squish Glass"
SQUISH_PROP = "squish_amount"  # custom property on the lattice that drives its Y scale


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def find_squish_lattice():
    for o in bpy.data.objects:
        if o.type == "LATTICE" and o.get(TAG):
            return o
    return None


def remove_existing():
    """Delete everything this addon made before (lattice, cube, material, modifiers)."""
    tagged = [o for o in bpy.data.objects if o.get(TAG)]
    lat_objs = [o for o in tagged if o.type == "LATTICE"]

    # modifiers that point to our lattice (on the character)
    for ob in bpy.data.objects:
        for m in list(ob.modifiers):
            if m.type == "LATTICE" and (m.object in lat_objs or (m.object is None and m.name == MOD_NAME)):
                ob.modifiers.remove(m)

    datas = []
    for o in tagged:
        datas.append(o.data)
        bpy.data.objects.remove(o, do_unlink=True)

    for d in datas:
        if d is None or d.users != 0:
            continue
        if isinstance(d, bpy.types.Lattice):
            bpy.data.lattices.remove(d)
        elif isinstance(d, bpy.types.Mesh):
            bpy.data.meshes.remove(d)

    for mat in list(bpy.data.materials):
        if mat.name.startswith(MAT_NAME) and mat.users == 0:
            bpy.data.materials.remove(mat)

    return len(tagged)


def collect_meshes(objs):
    """Selected meshes, plus the mesh children of any selected armature (the character rig)."""
    found = []
    for o in objs:
        if o.get(TAG):
            continue
        if o.type == "MESH":
            found.append(o)
        elif o.type == "ARMATURE":
            for c in o.children_recursive:
                if c.type == "MESH" and not c.get(TAG):
                    found.append(c)
    unique = []
    for o in found:
        if o not in unique:
            unique.append(o)
    return unique


def move_after_armature(obj, mod):
    """Put the modifier right after the Armature modifier (2nd in the stack).
    If there is no Armature modifier it goes to the top. Never left at the bottom."""
    mods = obj.modifiers
    idx_arm = -1
    for i, m in enumerate(mods):
        if m.type == "ARMATURE":
            idx_arm = i                      # last armature modifier
    cur = list(mods).index(mod)
    if idx_arm < 0:
        target = 0
    elif cur > idx_arm:
        target = idx_arm + 1
    else:
        target = idx_arm                     # armature shifts up by one after the move
    if cur != target:
        try:
            mods.move(cur, target)
        except Exception:
            pass


def add_lattice_modifier(obj, lat_obj):
    mod = None
    for m in obj.modifiers:
        if m.type == "LATTICE" and m.name == MOD_NAME:
            mod = m
            break
    if mod is None:
        mod = obj.modifiers.new(MOD_NAME, "LATTICE")
    mod.object = lat_obj
    move_after_armature(obj, mod)
    return mod


def setup_squish_driver(lat_obj, base_y):
    """Custom property 'squish_amount' (1.0 = normal) drives the lattice's Y scale."""
    lat_obj[SQUISH_PROP] = 1.0
    try:
        ui = lat_obj.id_properties_ui(SQUISH_PROP)
        ui.update(min=0.01, max=3.0, soft_min=0.01, soft_max=2.0,
                  description="Scale of the lattice on Y (1 = normal, lower = more squish)")
    except Exception:
        pass
    fc = lat_obj.driver_add("scale", 1)
    drv = fc.driver
    drv.type = "SCRIPTED"
    var = drv.variables.new()
    var.name = "s"
    var.type = "SINGLE_PROP"
    tgt = var.targets[0]
    tgt.id = lat_obj
    tgt.data_path = f'["{SQUISH_PROP}"]'
    drv.expression = f"s*{base_y:.8f}"


def make_glass_material(mix_factor):
    """Transparent BSDF + Diffuse BSDF (E7E7E7, roughness 0) -> Mix Shader -> Output.
    Render method = Blended (not Dithered)."""
    mat = bpy.data.materials.new(MAT_NAME)
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (200, 0)
    mix.inputs[0].default_value = mix_factor
    transp = nt.nodes.new("ShaderNodeBsdfTransparent")
    transp.location = (-100, 120)
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (-100, -80)
    diff.inputs["Color"].default_value = (0.799, 0.799, 0.799, 1.0)   # sRGB #E7E7E7
    diff.inputs["Roughness"].default_value = 0.0

    nt.links.new(transp.outputs["BSDF"], mix.inputs[1])
    nt.links.new(diff.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])

    # Blended instead of Dithered (name differs between Blender versions)
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    elif hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"

    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False
    if hasattr(mat, "use_transparent_shadow"):
        mat.use_transparent_shadow = True
    if hasattr(mat, "use_transparency_overlap"):
        mat.use_transparency_overlap = True
    if hasattr(mat, "show_transparent_back"):
        mat.show_transparent_back = True

    # viewport colour with alpha (used by Solid view / viewport display)
    mat.diffuse_color = (0.906, 0.906, 0.906, max(mix_factor, 0.05))
    return mat


def make_cube_mesh(cuts):
    """Exactly 1 m cube (-0.5 .. 0.5) so object scale == dimensions."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    m = max(abs(c) for v in bm.verts for c in v.co)
    if m > 0:
        k = 0.5 / m
        for v in bm.verts:
            v.co *= k
    if cuts > 0:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    mesh = bpy.data.meshes.new(CUBE_NAME)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


# ---------------------------------------------------------------------------
# operators
# ---------------------------------------------------------------------------
class SQUASHLAT_OT_remove(bpy.types.Operator):
    """Remove the glass cube, the Squish Lattice and the modifiers"""
    bl_idname = "object.squash_lattice_remove"
    bl_label = "Remove Squish Setup"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        n = remove_existing()
        self.report({"INFO"}, f"Removed {n} object(s)")
        return {"FINISHED"}


class SQUASHLAT_OT_create(bpy.types.Operator):
    """Create the complete squish setup in one click"""
    bl_idname = "object.squash_lattice_create"
    bl_label = "Create Squish Lattice"
    bl_options = {"REGISTER", "UNDO"}

    # lattice resolution
    res_u: IntProperty(name="U", default=8, min=2, max=64)
    res_v: IntProperty(name="V", default=4, min=2, max=64)
    res_w: IntProperty(name="W", default=8, min=2, max=64)

    # glass cube (the lattice copies its size automatically)
    cube_location: FloatVectorProperty(
        name="Cube Location", subtype="TRANSLATION", size=3,
        default=(-0.009995, -0.5473, 0.89565))
    cube_dimensions: FloatVectorProperty(
        name="Cube Dimensions", subtype="XYZ_LENGTH", size=3,
        default=(0.5, 0.185, 0.506))
    cube_cuts: IntProperty(name="Cube Subdivisions", default=7, min=0, max=30,
                           description="Loop cuts per edge")
    glass_mix: FloatProperty(name="Glass Mix", default=0.35, min=0.0, max=1.0,
                             description="Mix Shader factor (0 = fully transparent, 1 = fully diffuse)")

    # selected points
    layer_v: IntProperty(name="Layer (V)", default=2, min=1, max=62,
                         description="Which inner V layer to use")
    count_u: IntProperty(name="Select U", default=6, min=1, max=62)
    count_w: IntProperty(name="Select W", default=6, min=1, max=62)

    # squish pose
    apply_pose: BoolProperty(
        name="Apply Squish Pose", default=True,
        description="Push the layer to the glass surface and scale it on X and Z to fill the lattice")
    squish_y: FloatProperty(
        name="Layer Y (local)", default=0.47, min=-0.5, max=0.5,
        description="Local Y of the layer (0.5 = the outer face of the lattice)")

    # misc
    use_cursor: BoolProperty(name="Place at 3D Cursor", default=False)
    hide_lattice: BoolProperty(name="Hide Lattice", default=True)
    add_to_selected: BoolProperty(
        name="Lattice Modifier on Selected Character", default=True,
        description="Add a Lattice modifier (right after the Armature modifier) to the selected meshes. "
                    "A selected armature uses its child meshes")

    def execute(self, context):
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # character meshes must be read BEFORE the selection changes
        targets = collect_meshes(context.selected_objects) if self.add_to_selected else []

        # only ONE squish setup at a time
        remove_existing()

        cube_loc = tuple(self.cube_location)
        if self.use_cursor:
            cube_loc = tuple(context.scene.cursor.location)

        # ---- glass cube = PARENT ----
        cube = bpy.data.objects.new(CUBE_NAME, make_cube_mesh(self.cube_cuts))
        cube[TAG] = True
        cube.location = cube_loc
        cube.scale = self.cube_dimensions        # 1 m mesh, so scale == dimensions
        cube.data.materials.append(make_glass_material(self.glass_mix))
        cube.show_transparent = True             # Viewport Display > Transparency
        context.collection.objects.link(cube)
        # NOTE: no lattice modifier on the cube

        # ---- lattice = CHILD, same size as the cube ----
        lat_data = bpy.data.lattices.new(LATTICE_NAME)
        lat_data.points_u = self.res_u
        lat_data.points_v = self.res_v
        lat_data.points_w = self.res_w
        for attr in ("interpolation_type_u", "interpolation_type_v", "interpolation_type_w"):
            setattr(lat_data, attr, "KEY_BSPLINE")
        lat_obj = bpy.data.objects.new(LATTICE_NAME, lat_data)
        lat_obj[TAG] = True
        context.collection.objects.link(lat_obj)
        lat_obj.parent = cube
        lat_obj.matrix_parent_inverse = Matrix.Identity(4)
        lat_obj.location = (0.0, 0.0, 0.0)
        lat_obj.rotation_euler = (0.0, 0.0, 0.0)

        # A lattice made from a script can come out in "grid units" (8x4x8 points = 7x3x7 units).
        # Read the real extents of the points and scale the lattice so its box is exactly the
        # size of the cube.
        co_min = [min(p.co[i] for p in lat_data.points) for i in range(3)]
        co_max = [max(p.co[i] for p in lat_data.points) for i in range(3)]
        ext = [(co_max[i] - co_min[i]) or 1.0 for i in range(3)]
        mid = [(co_max[i] + co_min[i]) / 2.0 for i in range(3)]
        lat_obj.scale = (1.0 / ext[0], 1.0 / ext[1], 1.0 / ext[2])

        # ---- squish pose on ONE layer of middle points (centered) ----
        ru, rv, rw = self.res_u, self.res_v, self.res_w
        for p in lat_data.points:
            p.select = False
        v = min(max(self.layer_v, 1), rv - 2)
        cu = min(self.count_u, ru - 2)
        cw = min(self.count_w, rw - 2)
        u0 = (ru - cu) // 2
        w0 = (rw - cw) // 2
        chosen = []
        for w in range(w0, w0 + cw):
            for u in range(u0, u0 + cu):
                p = lat_data.points[w * (ru * rv) + v * ru + u]
                p.select = True
                chosen.append(p)

        if self.apply_pose:
            fu = (ru - 1) / (cu - 1) if cu > 1 else 1.0
            fw = (rw - 1) / (cw - 1) if cw > 1 else 1.0
            for p in chosen:
                p.co_deform = (
                    mid[0] + (p.co.x - mid[0]) * fu,
                    mid[1] + self.squish_y * ext[1],      # 0.5 = outer face
                    mid[2] + (p.co.z - mid[2]) * fw,
                )

        # ---- Squish Y slider (drives the lattice's Y scale, keyframe-able) ----
        setup_squish_driver(lat_obj, 1.0 / ext[1])

        # ---- character modifier, placed right after the Armature modifier ----
        for t in targets:
            add_lattice_modifier(t, lat_obj)

        # ---- select the cube, hide the lattice ----
        for o in context.selected_objects:
            o.select_set(False)
        cube.select_set(True)
        context.view_layer.objects.active = cube
        if self.hide_lattice:
            try:
                lat_obj.hide_set(True)
            except Exception:
                pass

        msg = "Squish setup ready. Use the Squish Y slider in the panel."
        if targets:
            msg += f" Lattice modifier added to {len(targets)} mesh(es)."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class SQUASHLAT_OT_toggle_lattice(bpy.types.Operator):
    """Show / hide the lattice in the viewport"""
    bl_idname = "object.squash_lattice_toggle"
    bl_label = "Show / Hide Lattice"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        lat = find_squish_lattice()
        if lat is None:
            self.report({"ERROR"}, "Create the Squish Lattice first")
            return {"CANCELLED"}
        try:
            lat.hide_set(not lat.hide_get())
        except Exception:
            lat.hide_viewport = not lat.hide_viewport
        return {"FINISHED"}


class SQUASHLAT_OT_add_modifier(bpy.types.Operator):
    """Add the Squish Lattice modifier (right after the Armature modifier) to the selected meshes. A selected rig uses its child meshes"""
    bl_idname = "object.squash_lattice_add_modifier"
    bl_label = "Add Lattice Modifier to Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        lat = find_squish_lattice()
        if lat is None:
            self.report({"ERROR"}, "Create the Squish Lattice first")
            return {"CANCELLED"}
        targets = collect_meshes(context.selected_objects)
        if not targets:
            self.report({"WARNING"}, "Select the character mesh (or its armature) first")
            return {"CANCELLED"}
        for t in targets:
            add_lattice_modifier(t, lat)
        self.report({"INFO"}, f"Added to {len(targets)} mesh(es)")
        return {"FINISHED"}


class SQUASHLAT_OT_remove_modifier(bpy.types.Operator):
    """Remove the Squish Lattice modifier from the selected meshes"""
    bl_idname = "object.squash_lattice_remove_modifier"
    bl_label = "Remove Modifier from Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = 0
        for t in collect_meshes(context.selected_objects):
            for m in list(t.modifiers):
                if m.type == "LATTICE" and m.name == MOD_NAME:
                    t.modifiers.remove(m)
                    n += 1
        self.report({"INFO"}, f"Removed {n} modifier(s)")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class SQUASHLAT_PT_panel(bpy.types.Panel):
    bl_label = "Squish Lattice"
    bl_idname = "SQUASHLAT_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Squash Lattice"

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.scale_y = 1.5
        col.operator("object.squash_lattice_create", icon="LATTICE_DATA")
        col.label(text="Glass cube (parent) + lattice (child)")
        layout.operator("object.squash_lattice_remove", icon="TRASH")

        lat = find_squish_lattice()
        box = layout.box()
        box.label(text="Squish:")
        if lat is not None and SQUISH_PROP in lat.keys():
            box.prop(lat, f'["{SQUISH_PROP}"]', text="Scale Y", slider=True)
            box.operator("object.squash_lattice_toggle", icon="HIDE_OFF", text="Show / Hide Lattice")
        else:
            box.label(text="Create the setup first")

        box = layout.box()
        box.label(text="Character:")
        box.operator("object.squash_lattice_add_modifier", icon="MOD_LATTICE")
        box.operator("object.squash_lattice_remove_modifier", icon="X")


classes = (
    SQUASHLAT_OT_remove,
    SQUASHLAT_OT_create,
    SQUASHLAT_OT_toggle_lattice,
    SQUASHLAT_OT_add_modifier,
    SQUASHLAT_OT_remove_modifier,
    SQUASHLAT_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
