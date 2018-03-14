# You are at the top. If you attempt to go any higher
#   you will go beyond the known limits of the code
#   universe where there are most certainly monsters

# might be able to get a speedup where I'm appending move and -move

# to do:
#  use point raycaster to make a cloth_wrap option
#  fix multiple sew spring error
#  set up better indexing so that edges only get calculated once
#  self colisions
#  object collisions
#  add bending springs
#  add curl by shortening bending springs on one axis or diagonal
#  independantly scale bending springs and structural to create buckling
#  run on frame update as an option?
#  option to cache animation?
#  collisions need to properly exclude pinned and vertex pinned
#  virtual springs do something wierd to the velocity
#  multiple converging springs go to far. Need to divide by number of springs at a vert or move them all towards a mean

# now!!!!
#  refresh self collisions.

# collisions:
# Onlny need to check on of the edges for groups connected to a vertex    
# for edge to face intersections...
# figure out where the edge hit the face
# figure out which end of the edge is inside the face
# move along the face normal to the surface for the point inside.
# if I reflect by flipping the vel around the face normal
#   if it collides on the bounce it will get caught on the next iteration


'''??? Would it make sense to do self collisions with virtual edges ???'''

bl_info = {
    "name": "Modeling Cloth",
    "author": "Rich Colburn, email: the3dadvantage@gmail.com",
    "version": (1, 0),
    "blender": (2, 78, 0),
    "location": "View3D > Extended Tools > Modeling Cloth",
    "description": "Maintains the surface area of an object so it behaves like cloth",
    "warning": "There might be an angry rhinoceros behind you",
    "wiki_url": "",
    "category": '3D View'}


import bpy
import bmesh
import numpy as np
from numpy import newaxis as nax
from bpy_extras import view3d_utils
import time


you_have_a_sense_of_humor = False
#you_have_a_sense_of_humor = True
if you_have_a_sense_of_humor:
    import antigravity


def get_co(ob, arr=None, key=None): # key
    """Returns vertex coords as N x 3"""
    c = len(ob.data.vertices)
    if arr is None:    
        arr = np.zeros(c * 3, dtype=np.float32)
    if key is not None:
        ob.data.shape_keys.key_blocks[key].data.foreach_get('co', arr.ravel())        
        arr.shape = (c, 3)
        return arr
    ob.data.vertices.foreach_get('co', arr.ravel())
    arr.shape = (c, 3)
    return arr


def get_proxy_co(ob, arr):
    """Returns vertex coords with modifier effects as N x 3"""
    me = ob.to_mesh(bpy.context.scene, True, 'PREVIEW')
    if arr is None:
        arr = np.zeros(len(me.vertices) * 3, dtype=np.float32)
        arr.shape = (arr.shape[0] //3, 3)    
    c = arr.shape[0]
    me.vertices.foreach_get('co', arr.ravel())
    bpy.data.meshes.remove(me)
    arr.shape = (c, 3)
    return arr


def triangulate(ob):
    """Requires a mesh. Returns an index array for viewing co as triangles"""
    me = ob.to_mesh(bpy.context.scene, True, 'PREVIEW')
    obm = bmesh.new()
    obm.from_mesh(me)        
    bmesh.ops.triangulate(obm, faces=obm.faces)
    obm.to_mesh(me)        
    count = len(me.polygons)    
    tri_idx = np.zeros(count * 3, dtype=np.int64)        
    me.polygons.foreach_get('vertices', tri_idx)        
    bpy.data.meshes.remove(me)
    obm.free()
    return tri_idx.reshape(count, 3)


def tri_normals_in_place(object, tri_co):    
    """Takes N x 3 x 3 set of 3d triangles and 
    returns non-unit normals and origins"""
    object.origins = tri_co[:,0]
    object.cross_vecs = tri_co[:,1:] - object.origins[:, nax]
    object.normals = np.cross(object.cross_vecs[:,0], object.cross_vecs[:,1])


def get_tri_normals(tr_co):
    """Takes N x 3 x 3 set of 3d triangles and 
    returns non-unit normals and origins"""
    origins = tr_co[:,0]
    cross_vecs = tr_co[:,1:] - origins[:, nax]
    return cross_vecs, np.cross(cross_vecs[:,0], cross_vecs[:,1]), origins


def closest_points_edge(vec, origin, p):
    '''Returns the location of the point on the edge'''
    vec2 = p - origin
    d = (vec2 @ vec) / (vec @ vec)
    cp = vec * d[:, nax]
    return cp, d


def proxy_in_place(object):
    """Overwrite vert coords with modifiers in world space"""
    me = object.ob.to_mesh(bpy.context.scene, True, 'PREVIEW')
    me.vertices.foreach_get('co', object.co.ravel())
    bpy.data.meshes.remove(me)
    object.co = apply_transforms(object.ob, object.co)


def apply_rotation(object):
    """When applying vectors such as normals we only need
    to rotate"""
    m = np.array(object.ob.matrix_world)
    mat = m[:3, :3].T
    object.v_normals = object.v_normals @ mat
    

def proxy_v_normals_in_place(object, world=True):
    """Overwrite vert coords with modifiers in world space"""
    me = object.ob.to_mesh(bpy.context.scene, True, 'PREVIEW')
    me.vertices.foreach_get('normal', object.v_normals.ravel())
    bpy.data.meshes.remove(me)
    if world:    
        apply_rotation(object)


def proxy_v_normals(ob):
    """Overwrite vert coords with modifiers in world space"""
    me = ob.to_mesh(bpy.context.scene, True, 'PREVIEW')
    arr = np.zeros(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get('normal', arr)
    arr.shape = (arr.shape[0] //3, 3)
    bpy.data.meshes.remove(me)
    m = np.array(ob.matrix_world, dtype=np.float32)    
    mat = m[:3, :3].T # rotates backwards without T
    return arr @ mat


def apply_transforms(ob, co):
    """Get vert coords in world space"""
    m = np.array(ob.matrix_world, dtype=np.float32)    
    mat = m[:3, :3].T # rotates backwards without T
    loc = m[:3, 3]
    return co @ mat + loc


def apply_in_place(ob, arr, cloth):
    """Overwrite vert coords in world space"""
    m = np.array(ob.matrix_world, dtype=np.float32)    
    mat = m[:3, :3].T # rotates backwards without T
    loc = m[:3, 3]
    arr[:] = arr @ mat + loc
    #cloth.co = cloth.co @ mat + loc


def applied_key_co(ob, arr=None, key=None):
    """Get vert coords in world space"""
    c = len(ob.data.vertices)
    if arr is None:
        arr = np.zeros(c * 3, dtype=np.float32)
    ob.data.shape_keys.key_blocks[key].data.foreach_get('co', arr)
    arr.shape = (c, 3)
    m = np.array(ob.matrix_world)    
    mat = m[:3, :3].T # rotates backwards without T
    loc = m[:3, 3]
    return co @ mat + loc


def revert_transforms(ob, co):
    """Set world coords on object. 
    Run before setting coords to deal with object transforms
    if using apply_transforms()"""
    m = np.linalg.inv(ob.matrix_world)    
    mat = m[:3, :3].T # rotates backwards without T
    loc = m[:3, 3]
    return co @ mat + loc  


def revert_in_place(ob, co):
    """Revert world coords to object coords in place."""
    m = np.linalg.inv(ob.matrix_world)    
    mat = m[:3, :3].T # rotates backwards without T
    loc = m[:3, 3]
    co[:] = co @ mat + loc


def revert_rotation(ob, co):
    """When reverting vectors such as normals we only need
    to rotate"""
    #m = np.linalg.inv(ob.matrix_world)    
    m = np.array(ob.matrix_world)
    mat = m[:3, :3] # rotates backwards without T
    return co @ mat


def get_last_object():
    """Finds cloth objects for keeping settings active
    while selecting other objects like pins"""
    cloths = [i for i in bpy.data.objects if i.modeling_cloth] # so we can select an empty and keep the settings menu up
    if bpy.context.object.modeling_cloth:
        return cloths, bpy.context.object
    
    if len(cloths) > 0:
        ob = extra_data['last_object']
        return cloths, ob
    return None, None


def get_poly_centers(ob, type=np.float32):
    mod = False
    m_count = len(ob.modifiers)
    if m_count > 0:
        show = np.zeros(m_count, dtype=np.bool)
        ren_set = np.copy(show)
        ob.modifiers.foreach_get('show_render', show)
        ob.modifiers.foreach_set('show_render', ren_set)
        mod = True
    mesh = ob.to_mesh(bpy.context.scene, True, 'RENDER')
    p_count = len(mesh.polygons)
    center = np.zeros(p_count * 3)#, dtype=type)
    mesh.polygons.foreach_get('center', center)
    center.shape = (p_count, 3)
    bpy.data.meshes.remove(mesh)
    if mod:
        ob.modifiers.foreach_set('show_render', show)

    return center


def simple_poly_centers(ob, key=None):
    if key is not None:
        s_key = ob.data.shape_keys.key_blocks[key].data
        return np.squeeze([[np.mean([ob.data.vertices[i].co for i in p.vertices], axis=0)] for p in ob.data.polygons])


def get_poly_normals(ob, type=np.float32):
    mod = False
    m_count = len(ob.modifiers)
    if m_count > 0:
        show = np.zeros(m_count, dtype=np.bool)
        ren_set = np.copy(show)
        ob.modifiers.foreach_get('show_render', show)
        ob.modifiers.foreach_set('show_render', ren_set)
        mod = True
    mesh = ob.to_mesh(bpy.context.scene, True, 'RENDER')
    p_count = len(mesh.polygons)
    normal = np.zeros(p_count * 3)#, dtype=type)
    mesh.polygons.foreach_get('normal', normal)
    normal.shape = (p_count, 3)
    bpy.data.meshes.remove(mesh)
    if mod:
        ob.modifiers.foreach_set('show_render', show)

    return normal


def get_v_normals(ob, arr):
    """Since we're reading from a shape key we have to use
    a proxy mesh."""
    mod = False
    m_count = len(ob.modifiers)
    if m_count > 0:
        show = np.zeros(m_count, dtype=np.bool)
        ren_set = np.copy(show)
        ob.modifiers.foreach_get('show_render', show)
        ob.modifiers.foreach_set('show_render', ren_set)
        mod = True
    mesh = ob.to_mesh(bpy.context.scene, True, 'RENDER')
    #v_count = len(mesh.vertices)
    #normal = np.zeros(v_count * 3)#, dtype=type)
    mesh.vertices.foreach_get('normal', arr.ravel())
    #normal.shape = (v_count, 3)
    bpy.data.meshes.remove(mesh)
    if mod:
        ob.modifiers.foreach_set('show_render', show)

    #return normal


def get_v_nor(ob, nor_arr):
    ob.data.vertices.foreach_get('normal', nor_arr.ravel())
    return nor_arr


def closest_point_edge(e1, e2, p):
    '''Returns the location of the point on the edge'''
    vec1 = e2 - e1
    vec2 = p - e1
    d = np.dot(vec2, vec1) / np.dot(vec1, vec1)
    cp = e1 + vec1 * d 
    return cp


def generate_collision_data(ob, pins, means):
    """The mean of each face is treated as a point then
    checked against the cpoe of the normals of every face.
    If the distance between the cpoe and the center of the face
    it's checking is in the margin, do a second check to see
    if it's also in the virtual cylinder around the normal.
    If it's in the cylinder, back up along the normal until the
    point is on the surface of the cylinder.
    instead of backing up along the normal, could do a line-plane intersect
    on the path of the point against the normal. 
    
    Since I know the direction the points are moving... it might be possible
    to identify the back sides of the cylinders so the margin on the back
    side is infinite. This way I could never miss the collision.
    !!! infinite backsides !!! Instead... since that would work because
    there is no way to tell the difference between a point that's moving
    away from the surface and a point that's already crossed the surface...
    I could do a raycast onto the infinte plane of the normal still treating
    it like a cylinder so instead of all the inside triangle stuff, just check
    the distance from the intersection to the cpoe of the normal
    
    Get cylinder sizes by taking the center of each face,
    and measuring the distance to it's closest neighbor, then back up a bit
    
    !!!could save the squared distance around the cylinders and along the normal 
    to save a step while checking... !!!
    """
    
    # one issue: oddly shaped triangles can cause gaps where face centers could pass through
    # since both sids are being checked it's less likely that both sides line up and pass through the gap
    obm = bmesh.new()
    obm.from_mesh(ob.data)

    obm.faces.ensure_lookup_table()
    obm.verts.ensure_lookup_table()
    p_count = len(obm.faces)
    
    per_face_v =  [[v.co for v in f.verts] for f in obm.faces]
    
    # $$$$$ calculate means with add.at like it's set up already$$$$$
    #means = np.array([np.mean([v.co for v in f.verts], axis=0) for f in obm.faces], dtype=np.float32)
    ### !!! calculating means from below wich is dynamic. Might be better since faces change size anyway. Could get better collisions

    # get sqared distance to closest vert in each face. (this will still work if the mesh isn't flat)
    sq_dist = []
    for i in range(p_count):
        dif = np.array(per_face_v[i]) - means[i]
        sq_dist.append(np.min(np.einsum('ij,ij->i', dif, dif)))
    
    # neighbors for excluding point face collisions.
    neighbors = np.tile(np.ones(p_count, dtype=np.bool), (pins.shape[0], 1))
    #neighbors = np.tile(pins, (pins.shape[0], 1))
    p_neighbors = [[f.index for f in obm.verts[p].link_faces] for p in pins]
    for x in range(neighbors.shape[0]):
        neighbors[x][p_neighbors[x]] = False

    # returns the radius distance from the mean to the closest vert in the polygon
    return np.array(np.sqrt(sq_dist), dtype=np.float32), neighbors
        

def create_vertex_groups(groups=['common', 'not_used'], weights=[0.0, 0.0], ob=None):
    '''Creates vertex groups and sets weights. "groups" is a list of strings
    for the names of the groups. "weights" is a list of weights corresponding 
    to the strings. Each vertex is assigned a weight for each vertex group to
    avoid calling vertex weights that are not assigned. If the groups are
    already present, the previous weights will be preserved. To reset weights
    delete the created groups'''
    if ob is None:
        ob = bpy.context.object
    vg = ob.vertex_groups
    for g in range(0, len(groups)):
        if groups[g] not in vg.keys(): # Don't create groups if there are already there
            vg.new(groups[g])
            vg[groups[g]].add(range(0,len(ob.data.vertices)), weights[g], 'REPLACE')
        else:
            vg[groups[g]].add(range(0,len(ob.data.vertices)), 0, 'ADD') # This way we avoid resetting the weights for existing groups.


def get_bmesh(obj=None):
    ob = get_last_object()[1]
    if ob is None:
        ob = obj
    obm = bmesh.new()
    if ob.mode == 'OBJECT':
        obm.from_mesh(ob.data)
    elif ob.mode == 'EDIT':
        obm = bmesh.from_edit_mesh(ob.data)
    return obm


def get_minimal_edges(ob):
    obm = get_bmesh(ob)
    obm.edges.ensure_lookup_table()
    obm.verts.ensure_lookup_table()
    obm.faces.ensure_lookup_table()
    
    # get sew edges:
    sew = [i.index for i in obm.edges if len(i.link_faces)==0]
    
    # get linear edges
    e_count = len(obm.edges)
    eidx = np.zeros(e_count * 2, dtype=np.int32)
    e_bool = np.zeros(e_count, dtype=np.bool)
    e_bool[sew] = True
    ob.data.edges.foreach_get('vertices', eidx)
    eidx.shape = (e_count, 2)

    # get diagonal edges:
    diag_eidx = []
    print('new============')
    start = 0
    stop = 0
    step_size = [len(i.verts) for i in obm.faces]
    p_v_count = np.sum(step_size)
    p_verts = np.ones(p_v_count, dtype=np.int32)
    ob.data.polygons.foreach_get('vertices', p_verts)
    # can only be understood on a good day when the coffee flows (uses rolling and slicing)
    # creates uniqe diagonal edge sets
    for f in obm.faces:
        fv_count = len(f.verts)
        stop += fv_count
        if fv_count > 3: # triangles are already connected by linear springs
            skip = 2
            f_verts = p_verts[start:stop]
            for fv in range(len(f_verts)):
                if fv > 1:        # as we go around the loop of verts in face we start overlapping
                    skip = fv + 1 # this lets us skip the overlap so we don't have mirror duplicates
                roller = np.roll(f_verts, fv)
                for r in roller[skip:-1]:
                    diag_eidx.append([roller[0], r])

        start += fv_count    
    
    # eidx groups
    sew_eidx = eidx[e_bool]
    lin_eidx = eidx[-e_bool]
    diag_eidx = np.array(diag_eidx)
        
    return lin_eidx, diag_eidx, sew_eidx


def add_virtual_springs(remove=False):
    cloth = data[get_last_object()[1].name]
    obm = get_bmesh()
    obm.verts.ensure_lookup_table()
    count = len(obm.verts)
    idxer = np.arange(count, dtype=np.int32)
    sel = np.array([v.select for v in obm.verts])    
    selected = idxer[sel]

    if remove:
        ls = cloth.virtual_springs[:, 0]
        
        in_sel = np.in1d(ls, idxer[sel])

        deleter = np.arange(ls.shape[0], dtype=np.int32)[in_sel]
        reduce = np.delete(cloth.virtual_springs, deleter, axis=0)
        cloth.virtual_springs = reduce
        
        if cloth.virtual_springs.shape[0] == 0:
            cloth.virtual_springs.shape = (0, 2)
        return

    existing = np.append(cloth.eidx, cloth.virtual_springs, axis=0)
    flip = existing[:, ::-1]
    existing = np.append(existing, flip, axis=0)
    ls = existing[:,0]
        
    springs = []
    for i in idxer[sel]:

        # to avoid duplicates:
        # where this vert occurs on the left side of the existing spring list
        v_in = existing[i == ls]
        v_in_r = v_in[:,1]
        not_in = selected[~np.in1d(selected, v_in_r)]
        idx_set = not_in[not_in != i]
        for sv in idx_set:
            springs.append([i, sv])
    virtual_springs = np.array(springs, dtype=np.int32)
    
    if virtual_springs.shape[0] == 0:
        virtual_springs.shape = (0, 2)
    
    cloth.virtual_springs = np.append(cloth.virtual_springs, virtual_springs, axis=0)
    # gets appended to eidx in the cloth_init function after calling get connected polys in case geometry changes


def generate_guide_mesh():
    """Makes the arrow that appears when creating pins"""
    verts = [[0.0, 0.0, 0.0], [-0.01, -0.01, 0.1], [-0.01, 0.01, 0.1], [0.01, -0.01, 0.1], [0.01, 0.01, 0.1], [-0.03, -0.03, 0.1], [-0.03, 0.03, 0.1], [0.03, 0.03, 0.1], [0.03, -0.03, 0.1], [-0.01, -0.01, 0.2], [-0.01, 0.01, 0.2], [0.01, -0.01, 0.2], [0.01, 0.01, 0.2]]
    edges = [[0, 5], [5, 6], [6, 7], [7, 8], [8, 5], [1, 2], [2, 4], [4, 3], [3, 1], [5, 1], [2, 6], [4, 7], [3, 8], [9, 10], [10, 12], [12, 11], [11, 9], [3, 11], [9, 1], [2, 10], [12, 4], [6, 0], [7, 0], [8, 0]]
    faces = [[0, 5, 6], [0, 6, 7], [0, 7, 8], [0, 8, 5], [1, 3, 11, 9], [1, 2, 6, 5], [2, 4, 7, 6], [4, 3, 8, 7], [3, 1, 5, 8], [12, 10, 9, 11], [4, 2, 10, 12], [3, 4, 12, 11], [2, 1, 9, 10]]
    name = 'ModelingClothPinGuide'
    if 'ModelingClothPinGuide' in bpy.data.objects:
        mesh_ob = bpy.data.objects['ModelingClothPinGuide']
    else:   
        mesh = bpy.data.meshes.new('ModelingClothPinGuide')
        mesh.from_pydata(verts, edges, faces)  
        mesh.update()
        mesh_ob = bpy.data.objects.new(name, mesh)
        bpy.context.scene.objects.link(mesh_ob)
        mesh_ob.show_x_ray = True
    return mesh_ob


def create_giude():
    """Spawns the guide"""
    if 'ModelingClothPinGuide' in bpy.data.objects:
        mesh_ob = bpy.data.objects['ModelingClothPinGuide']
        return mesh_ob
    mesh_ob = generate_guide_mesh()
    bpy.context.scene.objects.active = mesh_ob
    bpy.ops.object.material_slot_add()
    if 'ModelingClothPinGuide' in bpy.data.materials:
        mat = bpy.data.materials['ModelingClothPinGuide']
    else:    
        mat = bpy.data.materials.new(name='ModelingClothPinGuide')
    mat.use_transparency = True
    mat.alpha = 0.35            
    mat.emit = 2     
    mat.game_settings.alpha_blend = 'ALPHA_ANTIALIASING'
    mat.diffuse_color = (1, 1, 0)
    mesh_ob.material_slots[0].material = mat
    return mesh_ob


def delete_giude():
    """Deletes the arrow"""
    if 'ModelingClothPinGuide' in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects['ModelingClothPinGuide'])
    if 'ModelingClothPinGuide' in bpy.data.meshes:        
        guide_mesh = bpy.data.meshes['ModelingClothPinGuide']
        guide_mesh.user_clear()
        bpy.data.meshes.remove(guide_mesh)
    

def scale_source(multiplier):
    """grow or shrink the source shape"""
    ob = get_last_object()[1]
    if ob is not None:
        if ob.modeling_cloth:
            count = len(ob.data.vertices)
            co = np.zeros(count*3, dtype=np.float32)
            ob.data.shape_keys.key_blocks['modeling cloth source key'].data.foreach_get('co', co)
            co.shape = (count, 3)
            mean = np.mean(co, axis=0)
            co -= mean
            co *= multiplier
            co += mean
            ob.data.shape_keys.key_blocks['modeling cloth source key'].data.foreach_set('co', co.ravel())                
            if hasattr(data[ob.name], 'cy_dists'):
                data[ob.name].cy_dists *= multiplier
            

def reset_shapes(ob=None):
    """Sets the modeling cloth key to match the source key.
    Will regenerate shape keys if they are missing"""
    if ob is None:    
        if bpy.context.object.modeling_cloth:
            ob = bpy.context.object
        else:    
            ob = extra_data['last_object']

    if ob.data.shape_keys == None:
        ob.shape_key_add('Basis')    
    if 'modeling cloth source key' not in ob.data.shape_keys.key_blocks:
        ob.shape_key_add('modeling cloth source key')        
    if 'modeling cloth key' not in ob.data.shape_keys.key_blocks:
        ob.shape_key_add('modeling cloth key')        
        ob.data.shape_keys.key_blocks['modeling cloth key'].value=1
    
    keys = ob.data.shape_keys.key_blocks
    count = len(ob.data.vertices)
    co = np.zeros(count * 3, dtype=np.float32)
    keys['modeling cloth source key'].data.foreach_get('co', co)
    #co = applied_key_co(ob, None, 'modeling cloth source key')
    keys['modeling cloth key'].data.foreach_set('co', co)
    
    # reset the data stored in the class
    data[ob.name].vel[:] = 0
    co.shape = (co.shape[0]//3, 3)
    data[ob.name].co = co
    
    keys['modeling cloth key'].mute = True
    keys['modeling cloth key'].mute = False


def get_spring_mix(ob, eidx):
    rs = []
    ls = []
    minrl = []
    for i in eidx:
        r = eidx[eidx == i[1]].shape[0]
        l = eidx[eidx == i[0]].shape[0]
        rs.append (min(r,l))
        ls.append (min(r,l))
    mix = 1 / np.array(rs + ls) ** 1.2
    #mix2 = 1 / np.array(rs + ls)
    #print(mix.shape, "mix shape")
    
    return mix
        

def update_pin_group():
    """Updates the cloth data after changing mesh or vertex weight pins"""
    create_instance(new=False)


def collision_data_update(self, context):
    if self.modeling_cloth_self_collision:    
        create_instance(new=False)    


def refresh_noise(self, context):
    if self.name in data:
        zeros = np.zeros(data[self.name].count, dtype=np.float32)
        random = np.random.random(data[self.name].count)
        zeros[:] = random
        data[self.name].noise = ((zeros + -0.5) * self.modeling_cloth_noise * 0.1)[:, nax]


def generate_wind(wind_vec, ob, nor_arr, wind, vel):
    """Maintains a wind array and adds it to the cloth vel"""    
    wind *= 0.9
    if np.any(wind_vec):
        turb = ob.modeling_cloth_turbulence
        w_vec = revert_rotation(ob, wind_vec)
        wind += w_vec * (1 - np.random.random(nor_arr.shape) * -turb) 
        
        # only blow on verts facing the wind
        perp = nor_arr @ w_vec 
        wind *= np.abs(perp[:, nax])
        vel += wind    
        
    
class Cloth(object):
    pass


def create_instance(new=True):
    """Creates instance of cloth object with attributes needed for engine"""
    if new:
        cloth = Cloth()
        cloth.ob = bpy.context.object # based on what the user has as the active object
        cloth.pin_list = [] # these will not be moved by the engine
        cloth.hook_list = [] # these will be moved by hooks and updated to the engine
        cloth.virtual_springs = np.empty((0,2), dtype=np.int32) # so we can attach points to each other without regard to topology
        cloth.sew_springs = [] # edges with no faces attached can be set to shrink
        
        ###cloth.col_idx = np.empty(0, dtype=np.int32)
        ###cloth.collide_list = np.empty(0, dtype=np.int32)
    
    else: # if we set a modeling cloth object and have something else selected, the most recent object will still have it's settings expose in the ui
        ob = get_last_object()[1]
        cloth = data[ob.name]
        cloth.ob = ob 
    bpy.context.scene.objects.active = cloth.ob
    
    cloth.idxer = np.arange(len(cloth.ob.data.vertices), dtype=np.int32)
    # data only accesible through object mode
    mode = cloth.ob.mode
    if mode == 'EDIT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    # data is read from a source shape and written to the display shape so we can change the target springs by changing the source shape
    cloth.name = cloth.ob.name
    if cloth.ob.data.shape_keys == None:
        cloth.ob.shape_key_add('Basis')    
    if 'modeling cloth source key' not in cloth.ob.data.shape_keys.key_blocks:
        cloth.ob.shape_key_add('modeling cloth source key')        
    if 'modeling cloth key' not in cloth.ob.data.shape_keys.key_blocks:
        cloth.ob.shape_key_add('modeling cloth key')        
        cloth.ob.data.shape_keys.key_blocks['modeling cloth key'].value=1
    cloth.count = len(cloth.ob.data.vertices)
    
    # we can set a large group's pin state using the vertex group. No hooks are used here
    if 'modeling_cloth_pin' not in cloth.ob.vertex_groups:
        cloth.pin_group = create_vertex_groups(groups=['modeling_cloth_pin'], weights=[0.0], ob=None)
    for i in range(cloth.count):
        try:
            cloth.ob.vertex_groups['modeling_cloth_pin'].weight(i)
        except RuntimeError:
            # assign a weight of zero
            cloth.ob.vertex_groups['modeling_cloth_pin'].add(range(0,len(cloth.ob.data.vertices)), 0.0, 'REPLACE')
    cloth.pin_bool = -np.array([cloth.ob.vertex_groups['modeling_cloth_pin'].weight(i) for i in range(cloth.count)], dtype=np.bool)

    # unique edges------------>>>
    uni_edges = get_minimal_edges(cloth.ob)
    if len(uni_edges[1]) > 0:   
        cloth.eidx = np.append(uni_edges[0], uni_edges[1], axis=0)
    else:
        cloth.eidx = uni_edges[0]
    #cloth.eidx = uni_edges[0][0]

    if cloth.virtual_springs.shape[0] > 0:
        cloth.eidx = np.append(cloth.eidx, cloth.virtual_springs, axis=0)
    cloth.eidx_tiler = cloth.eidx.T.ravel()    

    mixology = get_spring_mix(cloth.ob, cloth.eidx)
    

    eidx1 = np.copy(cloth.eidx)
    pindexer = np.arange(cloth.count, dtype=np.int32)[cloth.pin_bool]
    unpinned = np.in1d(cloth.eidx_tiler, pindexer)
    cloth.eidx_tiler = cloth.eidx_tiler[unpinned]    
    cloth.unpinned = unpinned

    cloth.sew_edges = uni_edges[2]
    
    # unique edges------------>>>
    
    cloth.pcount = pindexer.shape[0]
    cloth.pindexer = pindexer
    
    cloth.sco = np.zeros(cloth.count * 3, dtype=np.float32)
    cloth.ob.data.shape_keys.key_blocks['modeling cloth source key'].data.foreach_get('co', cloth.sco)
    cloth.sco.shape = (cloth.count, 3)
    cloth.co = np.zeros(cloth.count * 3, dtype=np.float32)
    cloth.ob.data.shape_keys.key_blocks['modeling cloth key'].data.foreach_get('co', cloth.co)
    cloth.co.shape = (cloth.count, 3)    
    co = cloth.co
    cloth.vel = np.zeros(cloth.count * 3, dtype=np.float32)
    cloth.vel_start = np.zeros(cloth.count * 3, dtype=np.float32)
    cloth.vel_start.shape = (cloth.count, 3)
    cloth.vel.shape = (cloth.count, 3)
    
    cloth.v_normals = np.zeros(co.shape)
    get_v_normals(cloth.ob, cloth.v_normals)
    cloth.wind = np.zeros(co.shape)
    
    #noise---
    noise_zeros = np.zeros(cloth.count, dtype=np.float32)
    random = np.random.random(cloth.count)
    noise_zeros[:] = random
    cloth.noise = ((noise_zeros + -0.5) * cloth.ob.modeling_cloth_noise * 0.1)[:, nax]
    
    cloth.waiting = False
    cloth.clicked = False # for the grab tool
    
    uni = np.unique(cloth.eidx_tiler, return_inverse=True, return_counts=True)

    #cloth.mix = (1/uni[2][uni[1]])[:, nax].astype(np.float32) # force gets divided by number of springs

    # this helps with extra springs behaving as if they had more mass---->>>
    cloth.mix = mixology[unpinned][:, nax]
    #cloth.mix = (cloth.mix ** .87) * 0.35
    # -------------->>>

    # new self collisions:

    cloth.tridex = triangulate(cloth.ob)
    cloth.tridexer = np.arange(cloth.tridex.shape[0], dtype=np.int32)

    c_peat = np.repeat(np.arange(cloth.idxer.shape[0], dtype=np.int16), cloth.tridexer.shape[0])
    t_peat = np.tile(np.arange(cloth.tridexer.shape[0], dtype=np.int16), co.shape[0])

    # eliminate tris that contain the point:
    co_tidex = c_peat.reshape(cloth.idxer.shape[0], cloth.tridexer.shape[0])
    tri_tidex = cloth.tridex[t_peat.reshape(cloth.idxer.shape[0], cloth.tridexer.shape[0])]
    check = tri_tidex == co_tidex[:,:,nax]
    cull = ~np.any(check, axis=2)
    
    # duplicate of each tri for each vert and each vert for each tri
    cloth.c_peat = c_peat[cull.ravel()]
    cloth.t_peat = t_peat[cull.ravel()]

    
    self_col = cloth.ob.modeling_cloth_self_collision
    if self_col:
        # collision======:
        # collision======:
        cloth.p_count = len(cloth.ob.data.polygons)
        #cloth.p_means = get_poly_centers(cloth.ob)
        cloth.p_means = simple_poly_centers(cloth.ob, key="modeling cloth source key")

        
        # could put in a check in case int 32 isn't big enough...
        cloth.cy_dists, cloth.point_mean_neighbors = generate_collision_data(cloth.ob, pindexer, cloth.p_means)
        cloth.cy_dists *= cloth.ob.modeling_cloth_self_collision_cy_size
        
        nei = cloth.point_mean_neighbors.ravel() # eliminate neighbors for point in face check
        cloth.v_repeater = np.repeat(pindexer, cloth.p_count)[nei]
        cloth.p_repeater = np.tile(np.arange(cloth.p_count, dtype=np.int32),(cloth.count,))[nei]
        cloth.bool_repeater = np.ones(cloth.p_repeater.shape[0], dtype=np.bool)
        
        cloth.mean_idxer = np.arange(cloth.p_count, dtype=np.int32)
        cloth.mean_tidxer = np.tile(cloth.mean_idxer, (cloth.count, 1))
        
        # collision======:
        # collision======:

    
    bpy.ops.object.mode_set(mode=mode)
    return cloth


def run_handler(cloth):
    #if not cloth.ob.modeling_cloth_pause:
    if cloth.ob.modeling_cloth_handler_frame | cloth.ob.modeling_cloth_handler_scene:
        if cloth.ob.mode == 'EDIT':
            cloth.waiting = True
        if cloth.waiting:    
            if cloth.ob.mode == 'OBJECT':
                update_pin_group()

        if not cloth.waiting:
    
            eidx = cloth.eidx # world's most important variable

            cloth.ob.data.shape_keys.key_blocks['modeling cloth source key'].data.foreach_get('co', cloth.sco.ravel())
            sco = cloth.sco
            #sco.shape = (cloth.count, 3)
            #cloth.ob.data.shape_keys.key_blocks['modeling cloth key'].data.foreach_get('co', cloth.co.ravel())
            co = cloth.co
            #co.shape = (cloth.count, 3)
            svecs = sco[eidx[:, 1]] - sco[eidx[:, 0]]
            sdots = np.einsum('ij,ij->i', svecs, svecs)

            co[cloth.pindexer] += cloth.noise[cloth.pindexer]
            cloth.noise *= cloth.ob.modeling_cloth_noise_decay

            # mix in vel before collisions and sewing
            co[cloth.pindexer] += cloth.vel[cloth.pindexer]

            cloth.vel_start[:] = co
            force = cloth.ob.modeling_cloth_spring_force
            mix = cloth.mix * force

            #if cloth.clicked: # for the grab tool
                #grab = np.array([extra_data['stored_vidx'][v] + extra_data['move'] for v in range(len(extra_data['vidx']))])
                #grab_idx = extra_data['vidx']    
                    #loc = extra_data['stored_vidx'][v] + extra_data['move']

            for x in range(cloth.ob.modeling_cloth_iterations):    
                
                # add pull
                vecs = co[eidx[:, 1]] - co[eidx[:, 0]]
                dots = np.einsum('ij,ij->i', vecs, vecs)
                div = np.nan_to_num(sdots / dots)
                swap = vecs * np.sqrt(div)[:, nax]
                move = vecs - swap
                # pull only test--->>>
                #move[div > 1] = 0
                push = cloth.ob.modeling_cloth_push_springs
                if push == 0:
                    move[div > 1] = 0
                else:
                    move[div > 1] *= push
                # pull only test--->>>
                
                tiled_move = np.append(move, -move, axis=0)[cloth.unpinned] * mix # * mix for stability: force multiplied by 1/number of springs
                
                #print(np.unique(cloth.eidx_tiler))
                
                #tiled_move = np.append(move, -move, axis=0)[cloth.unpinned] * new_mix # * mix for stability: force multiplied by 1/number of springs
                np.add.at(cloth.co, cloth.eidx_tiler, tiled_move)
                
                ###if cloth.ob.modeling_cloth_object_detect:
                    ###if cloth.collide_list.shape[0] > 0:
                        ###cloth.co[cloth.col_idx] = cloth.collide_list
                
                if len(cloth.pin_list) > 0:
                    hook_co = np.array([cloth.ob.matrix_world.inverted() * i.matrix_world.to_translation() for i in cloth.hook_list])
                    cloth.co[cloth.pin_list] = hook_co
                
                # grab inside spring iterations
                if cloth.clicked: # for the grab tool
                    cloth.co[extra_data['vidx']] = np.array(extra_data['stored_vidx']) + np.array(+ extra_data['move'])   
            
            spring_dif = cloth.co - cloth.vel_start
            grav = cloth.ob.modeling_cloth_gravity * (.01 / cloth.ob.modeling_cloth_iterations)
            cloth.vel += revert_rotation(cloth.ob, np.array([0, 0, grav]))

            # refresh normals for inflate and wind
            get_v_normals(cloth.ob, cloth.v_normals)

            # wind:
            x = cloth.ob.modeling_cloth_wind_x
            y = cloth.ob.modeling_cloth_wind_y
            z = cloth.ob.modeling_cloth_wind_z
            wind_vec = np.array([x,y,z])
            generate_wind(wind_vec, cloth.ob, cloth.v_normals, cloth.wind, cloth.vel)            

            # inflate
            inflate = cloth.ob.modeling_cloth_inflate * .1
            if inflate != 0:
                cloth.v_normals *= inflate
                cloth.vel += cloth.v_normals

            #cloth.vel += spring_dif * 4                    
            # inextensible calc:
            ab_dot = np.einsum('ij, ij->i', cloth.vel, spring_dif)
            aa_dot = np.einsum('ij, ij->i', spring_dif, spring_dif)
            div = np.nan_to_num(ab_dot / aa_dot)
            cp = spring_dif * div[:, nax]
            cloth.vel -= np.nan_to_num(cp)
            cloth.vel += (spring_dif + cp)
            
            cloth.vel += spring_dif        

            # The amount of drag increases with speed. 
            # have to converto to a range between 0 and 1
            squared_move_dist = np.einsum("ij, ij->i", cloth.vel, cloth.vel)
            squared_move_dist += 1
            cloth.vel *= (1 / (squared_move_dist / cloth.ob.modeling_cloth_velocity))[:, nax]
            
            # old self collisions
            self_col = cloth.ob.modeling_cloth_self_collision

            if self_col:
                V3 = [] # because I'm multiplying the vel by this value and it doesn't exist unless there are collisions
                col_margin = cloth.ob.modeling_cloth_self_collision_margin
                sq_margin = col_margin ** 2
                
                cloth.p_means = get_poly_centers(cloth.ob)
                
                #======== collision tree---
                # start with the greatest dimension(if it's flat on the z axis, it will return everything so start with an axis with the greatest dimensions)
                order = np.argsort(cloth.ob.dimensions) # last on first since it goes from smallest to largest
                axis_1 = cloth.co[:, order[2]]
                axis_2 = cloth.co[:, order[1]]
                axis_3 = cloth.co[:, order[0]]
                center_1 = cloth.p_means[:, order[2]]
                center_2 = cloth.p_means[:, order[1]]
                center_3 = cloth.p_means[:, order[0]]
                
                V = cloth.v_repeater # one set of verts for each face
                P = cloth.p_repeater # faces repeated in order to aling to v_repearter
                
                check_1 = np.abs(axis_1[V] - center_1[P]) < cloth.cy_dists[P]
                V1 = V[check_1]
                P1 = P[check_1]
                C1 = cloth.cy_dists[P1]
                
                check_2 = np.abs(axis_2[V1] - center_2[P1]) < C1
                
                V2 = V1[check_2]
                P2 = P1[check_2]
                C2 = C1[P2]            

                check_3 = np.abs(axis_3[V2] - center_3[P2]) < C2

                v_hits = V2[check_3]
                p_hits = P2[check_3]
                #======== collision tree end ---
                if p_hits.shape[0] > 0:        
                    # now do closest point edge with points on normals
                    normals = get_poly_normals(cloth.ob)[p_hits]
                    
                    base_vecs = cloth.co[v_hits] - cloth.p_means[p_hits]
                    d = np.einsum('ij,ij->i', base_vecs, normals) / np.einsum('ij,ij->i', normals, normals)        
                    cp = normals * d[:, nax]
                    
                    # now measure the distance along the normal to see if it's in the cylinder
                    
                    cp_dot = np.einsum('ij,ij->i', cp, cp)
                    in_margin = cp_dot < sq_margin
                    
                    if in_margin.shape[0] > 0:
                        V3 = v_hits[in_margin]
                        #P3 = p_hits[in_margin]
                        cp3 = cp[in_margin]
                        cpd3 = cp_dot[in_margin]
                        
                        d1 = sq_margin
                        d2 = cpd3
                        div = d1/d2
                        surface = cp3 * np.sqrt(div)[:, nax]

                        force = np.nan_to_num(surface - cp3)
                        force *= cloth.ob.modeling_cloth_self_collision_force
                        
                        cloth.co[V3] += force

                        cloth.vel[V3] *= .2                   
                        #np.add.at(cloth.co, V3, force * .5)
                        #np.multiply.at(cloth.vel, V3, 0.2)
                        
                        # could get some speed help by iterating over a dict maybe
                        #if False:    
                        #if True:    
                            #for i in range(len(P3)):
                                #cloth.co[cloth.v_per_p[P3[i]]] -= force[i]
                                #cloth.vel[cloth.v_per_p[P3[i]]] -= force[i]
                                #cloth.vel[cloth.v_per_p[P3[i]]] *= 0.2
                                #cloth.vel[cloth.v_per_p[P3[i]]] += cloth.vel[V3[i]]
                                #need to transfer the velocity back and forth between hit faces.

            #collision=====================================


            if cloth.ob.modeling_cloth_sew != 0:
                if len(cloth.sew_edges) > 0:
                    sew_edges = cloth.sew_edges
                    rs = co[sew_edges[:,1]]
                    ls = co[sew_edges[:,0]]
                    sew_vecs = (rs - ls) * 0.5 * cloth.ob.modeling_cloth_sew
                    co[sew_edges[:,1]] -= sew_vecs
                    co[sew_edges[:,0]] += sew_vecs

            
            # floor ---
            if cloth.ob.modeling_cloth_floor:    
                floored = cloth.co[:,2] < 0        
                cloth.vel[:,2][floored] *= -1
                cloth.vel[floored] *= .1
                cloth.co[:, 2][floored] = 0
            # floor ---            
            

            #co[cloth.pindexer] += cloth.vel[cloth.pindexer]
            #cloth.co = co
            
            # objects ---
            T = time.time()
            if cloth.ob.modeling_cloth_object_detect:
                if extra_data['colliders'] is not None:
                    for i, val in extra_data['colliders'].items():
                        if val.ob == cloth.ob:    
                            self_collide(cloth, val)
                        else:    
                            object_collide(cloth, val)
            print(time.time()-T, "the whole enchalada")
            #print(x)
            # objects ---

            if len(cloth.pin_list) > 0:
                cloth.co[cloth.pin_list] = hook_co
                cloth.vel[cloth.pin_list] = 0

            if cloth.clicked: # for the grab tool
                cloth.co[extra_data['vidx']] = np.array(extra_data['stored_vidx']) + np.array(+ extra_data['move'])
            
            cloth.ob.data.shape_keys.key_blocks['modeling cloth key'].data.foreach_set('co', cloth.co.ravel())
            cloth.ob.data.shape_keys.key_blocks['modeling cloth key'].mute = True
            cloth.ob.data.shape_keys.key_blocks['modeling cloth key'].mute = False


# +++++++++++++ object collisions ++++++++++++++
def bounds_check(co1, co2, fudge):
    """Returns True if object bounding boxes intersect.
    Have to add the fudge factor for collision margins"""
    check = False
    co1_max = None # will never return None if check is true
    co1_min = np.min(co1, axis=0)
    co2_max = np.max(co2, axis=0)

    if np.all(co2_max + fudge > co1_min):
        co1_max = np.max(co1, axis=0)
        co2_min = np.min(co2, axis=0)        
        
        if np.all(co1_max > co2_min - fudge):
            check = True

    return check, co1_min, co1_max # might as well reuse the checks


def triangle_bounds_check(co, tri_co, co_min, co_max, idxer, fudge):
    """Returns a bool aray indexing the triangles that
    intersect the bounds of the object"""

    # min check cull step 1
    tri_min = np.min(tri_co, axis=1) - fudge
    check_min = co_max > tri_min
    in_min = np.all(check_min, axis=1)
    
    # max check cull step 2
    idx = idxer[in_min]
    tri_max = np.max(tri_co[in_min], axis=1) + fudge
    check_max = tri_max > co_min
    in_max = np.all(check_max, axis=1)
    in_min[idx[~in_max]] = False
    
    return in_min, tri_min[in_min], tri_max[in_max] # can reuse the min and max


def tri_back_check(co, tri_min, tri_max, idxer, fudge):
    """Returns a bool aray indexing the vertices that
    intersect the bounds of the culled triangles"""

    # min check cull step 1
    tb_min = np.min(tri_min, axis=0) - fudge
    check_min = co > tb_min
    in_min = np.all(check_min, axis=1)
    idx = idxer[in_min]
    
    # max check cull step 2
    tb_max = np.max(tri_max, axis=0) + fudge
    check_max = co[in_min] < tb_max
    in_max = np.all(check_max, axis=1)        
    in_min[idx[~in_max]] = False    
    
    return in_min 
    

def v_per_tri(co, tri_min, tri_max, idxer, tridexer, c_peat=None, t_peat=None):
    """Checks each point against the bounding box of each triangle"""
    
    if c_peat is None:
        c_peat = np.repeat(np.arange(idxer.shape[0], dtype=np.int16), tridexer.shape[0])
        t_peat = np.tile(np.arange(tridexer.shape[0], dtype=np.int16), co.shape[0])
    
    # X
    # Step 1 check x_min (because we're N squared here we break it into steps)
    co_x = co[:, 0]
    check_x_min = co_x[c_peat] > tri_min[:, 0][t_peat]
    c_peat = c_peat[check_x_min]
    if c_peat.shape[0] == 0:
        return
    t_peat = t_peat[check_x_min]

    # Step 2 check x max
    check_x_max = co_x[c_peat] < tri_max[:, 0][t_peat]
    c_peat = c_peat[check_x_max]
    if c_peat.shape[0] == 0:
        return
    t_peat = t_peat[check_x_max]
    
    # Y
    # Step 3 check y min    
    co_y = co[:, 1]
    check_y_min = co_y[c_peat] > tri_min[:, 1][t_peat]
    c_peat = c_peat[check_y_min]
    if c_peat.shape[0] == 0:
        return
    t_peat = t_peat[check_y_min]

    # Step 4 check y max
    check_y_max = co_y[c_peat] < tri_max[:, 1][t_peat]
    c_peat = c_peat[check_y_max]
    if c_peat.shape[0] == 0:
        return
    t_peat = t_peat[check_y_max]
        
    # Z
    # Step 5 check z min    
    co_z = co[:, 2]
    check_z_min = co_z[c_peat] > tri_min[:, 2][t_peat]
    c_peat = c_peat[check_z_min]
    if c_peat.shape[0] == 0:
        return
    t_peat = t_peat[check_z_min]

    # Step 6 check y max
    check_z_max = co_z[c_peat] < tri_max[:, 2][t_peat]
    c_peat = c_peat[check_z_max]
    if c_peat.shape[0] == 0:
        return
    t_peat = t_peat[check_z_max]    

    return idxer[c_peat], t_peat


def inside_triangles(tri_vecs, v2, co, tri_co_2, cidx, tidx, nor, ori, in_margin):
    idxer = np.arange(in_margin.shape[0], dtype=np.int32)[in_margin]
    
    r_co = co[cidx[in_margin]]    
    r_tri = tri_co_2[tidx[in_margin]]
    
    v0 = tri_vecs[:,0]
    v1 = tri_vecs[:,1]
    
    d00_d11 = np.einsum('ijk,ijk->ij', tri_vecs, tri_vecs)
    d00 = d00_d11[:,0]
    d11 = d00_d11[:,1]
    d01 = np.einsum('ij,ij->i', v0, v1)
    d02 = np.einsum('ij,ij->i', v0, v2)
    d12 = np.einsum('ij,ij->i', v1, v2)

    div = 1 / (d00 * d11 - d01 * d01)
    u = (d11 * d02 - d01 * d12) * div
    v = (d00 * d12 - d01 * d02) * div
    check = (u > 0) & (v > 0) & (u + v < 1)
    in_margin[idxer] = check


def object_collide(cloth, object):
    ###hits = False
    ###cloth.col_idx = np.empty(0, dtype=np.int32)
    ###cloth.collide_list = np.empty(0, dtype=np.int32)
    # get transforms in world space:
    proxy_in_place(object)
    apply_in_place(cloth.ob, cloth.co, cloth)
    
    inner_margin = object.ob.modeling_cloth_inner_margin
    outer_margin = object.ob.modeling_cloth_outer_margin
    fudge = max(inner_margin, outer_margin)
    #fudge = outer_margin# * 2
    
    # check object bounds: (need inner and out margins to adjust box size)
    box_check, co1_min, co1_max = bounds_check(cloth.co, object.co, fudge)

    # check for triangles inside the cloth bounds
    if box_check:
        proxy_v_normals_in_place(object)
        tri_co = object.co[object.tridex]

        # tri vel
        tri_vo = object.vel[object.tridex]
        tris_in, tri_min, tri_max = triangle_bounds_check(cloth.co, tri_co, co1_min, co1_max, object.tridexer, fudge)

        # check for verts in the bounds around the culled triangles
        if np.any(tris_in):    
            tri_co_2 = tri_co[tris_in]
            back_check = tri_back_check(cloth.co, tri_min, tri_max, cloth.idxer, fudge)
    
            # begin every vertex co against every tri
            if np.any(back_check):
                v_tris = v_per_tri(cloth.co[back_check], tri_min, tri_max, cloth.idxer[back_check], object.tridexer[tris_in])
                
                if v_tris is not None:
                    # update the normals. cross_vecs used by barycentric tri check
                    # move the surface along the vertex normals by the outer margin distance
                    marginalized = (object.co + object.v_normals * outer_margin)[object.tridex]
                    tri_normals_in_place(object, marginalized)
                    # add normals to make extruded tris
                    norms_2 = object.normals[tris_in]
                    u_norms = norms_2 / np.sqrt(np.einsum('ij, ij->i', norms_2, norms_2))[:, nax] 
                                        
                    cidx, tidx = v_tris
                    ori = object.origins[tris_in][tidx]
                    nor = u_norms[tidx]
                    vec2 = cloth.co[cidx] - ori
                    
                    d = np.einsum('ij, ij->i', nor, vec2) # nor is unit norms
                    in_margin = (d > -(inner_margin + outer_margin)) & (d < 0)#outer_margin) (we have offset outer margin)
                    
                    # <<<--- Inside triangle check --->>>
                    # will overwrite in_margin:
                    cross_2 = object.cross_vecs[tris_in][tidx][in_margin]
                    inside_triangles(cross_2, vec2[in_margin], cloth.co, marginalized[tris_in], cidx, tidx, nor, ori, in_margin)
                    
                    if np.any(in_margin):
                        # collision response --------------------------->>>
                        # when we only compute the velocity for points that hit,
                        # we get weird velocity vectors when moving in and out
                        # of collision space
                        tri_vo = tri_vo[tris_in]
                        tri_vel1 = np.mean(tri_co_2[tidx[in_margin]], axis=1)
                        tri_vel2 = np.mean(tri_vo[tidx[in_margin]], axis=1)
                        tvel = tri_vel1 - tri_vel2
                        tri_vo[:] = 0
                        
                        
                        
                        col_idx = cidx[in_margin] 
                        #u, ind = np.unique(col_idx, True)
                        cloth.co[col_idx] -= nor[in_margin] * (d[in_margin])[:, nax]
                        #cloth.co[u] -= nor[in_margin][ind] * (d[in_margin][ind])[:, nax]
                        cloth.vel[col_idx] = tvel
                        #cloth.vel[col_idx] = 0
                        #cloth.vel[u] = tvel[ind]
                        # when iterating springs, we keep putting the collided points back
                        ###cloth.col_idx = col_idx
                        ###cloth.collide_list = cloth.co[col_idx]
                        ###hits = True                    
                # could use the mean of the original trianlge to determine which face
                #   to collide with when there are multiples. So closest mean gets used.
    object.vel[:] = object.co    
    revert_in_place(cloth.ob, cloth.co)
    ###if hits:
        ###cloth.collide_list = cloth.co[col_idx]

# update functions --------------------->>>    



def grid_sample(obj, tri_min, tri_max, box_count=10, offset=0.00001):
    """divide mesh into grid and sample from each segment.
    offset prevents boxes from excluding any verts"""

    # I have to eliminate tris containing the vertex
    # I have boxes containing verts
    # I have min and max corners of each tri
    # I have to check every tri whose bounding box intersects the box with the vert
    # If a vert is in a box, all the tris containing it are in that box


    ob = obj.ob
    co = obj.co
    #co = get_co(ob)
    
    # get bounding box corners
    min = np.min(co, axis=0)
    max = np.max(co, axis=0)
    
    # box count is based on largest dimension
    dimensions = max - min
    largest_dimension = np.max(dimensions)
    box_size = largest_dimension / box_count
    
    # get box count for each axis
    xyz_count = dimensions // box_size + 1 #(have to add one so we don't end up with zero boxes when the mesh is flat)
    
    # dynamic number of boxes on each axis:
    box_dimensions = dimensions / xyz_count # each box is this size
    
    line_end = max - box_dimensions # we back up one from the last value
    
    x_line = np.linspace(min[0], line_end[0], num=xyz_count[0], dtype=np.float32)
    y_line = np.linspace(min[1], line_end[1], num=xyz_count[1], dtype=np.float32)
    z_line = np.linspace(min[2], line_end[2], num=xyz_count[2], dtype=np.float32)
    
    
    idxer = np.arange(co.shape[0])
    
    # get x bools
    x_grid = co[:, 0] - x_line[:,nax]
    x_bools = (x_grid + offset > 0) & (x_grid - offset < box_dimensions[0])
    cull_x_bools = x_bools[np.any(x_bools, axis=1)] # eliminate grid sections with nothing
    xb = cull_x_bools

    x_idx = np.tile(idxer, (xyz_count[0], 1))
    
    samples = []
    
    for boo in xb:
        xidx = idxer[boo]
        y_grid = co[boo][:, 1] - y_line[:,nax]
        y_bools = (y_grid + offset > 0) & (y_grid - offset < box_dimensions[1])
        cull_y_bools = y_bools[np.any(y_bools, axis=1)] # eliminate grid sections with nothing
        yb = cull_y_bools
        print(yb[0].shape, "++++++what's my shape here?")
        print(yb[0][yb[0]].shape, "what's my shape here?")
        for yboo in yb:
            yidx = xidx[yboo]
            z_grid = co[yidx][:, 2] - z_line[:,nax]
            z_bools = (z_grid + offset > 0) & (z_grid - offset < box_dimensions[2])
            cull_z_bools = z_bools[np.any(z_bools, axis=1)] # eliminate grid sections with nothing
            zb = cull_z_bools        
            for zboo in zb:
                #samples.append(yidx[zboo][0])
            
                # !!! to use this for collisions !!!:
                #if False:    
                samples.extend([yidx[zboo].tolist()])
    
    
    #print(samples[:10], "what are these?")
    for i in samples[40]:
        ob.data.vertices[i].select=True
    return np.unique(samples) # if offset is zero we don't need unique... return samples


def self_collide(cloth, object):
    #return
    # get transforms in world space:

    fudge = object.ob.modeling_cloth_outer_margin

    #proxy_v_normals_in_place(object, False)
    tri_co = cloth.co[cloth.tridex]

    # tri vel
    tri_vo = cloth.vel[cloth.tridex]


    tri_min = np.min(tri_co, axis=1) - fudge
    tri_max = np.max(tri_co, axis=1) + fudge

    T = time.time()
    #
    #v_tris = v_per_tri(cloth.co, tri_min, tri_max, cloth.idxer, cloth.tridexer, cloth.c_peat, cloth.t_peat)
    x = grid_sample(cloth, tri_min, tri_max, box_count=10, offset=0.00001)
    print(time.time()-T, "time inside")
    #print(cloth.t_peat)
    #print(cloth.c_peat)
    
    
    return
    if v_tris is not None:
        # update the normals. cross_vecs used by barycentric tri check
        # move the surface along the vertex normals by the outer margin distance
        tri_normals_in_place(object, tri_co)
        # add normals to make extruded tris
        u_norms = norms_2 / np.sqrt(np.einsum('ij, ij->i', norms_2, norms_2))[:, nax] 
                            
        cidx, tidx = v_tris
        ori = object.origins[tris_in][tidx]
        nor = u_norms[tidx]
        vec2 = cloth.co[cidx] - ori
        
        d = np.einsum('ij, ij->i', nor, vec2) # nor is unit norms
        in_margin = (d > -inner_margin) & (d < 0)#< outer_margin)
        
        # <<<--- Inside triangle check --->>>
        # will overwrite in_margin:
        cross_2 = object.cross_vecs[tris_in][tidx][in_margin]
        inside_triangles(cross_2, vec2[in_margin], cloth.co, marginalized[tris_in], cidx, tidx, nor, ori, in_margin)
        
        
        if np.any(in_margin):
            # collision response --------------------------->>>
            tri_vo = tri_vo[tris_in]
            tri_vel1 = np.mean(tri_co_2[tidx[in_margin]], axis=1)
            tri_vel2 = np.mean(tri_vo[tidx[in_margin]], axis=1)
            tvel = tri_vel1 - tri_vel2
            
            
            col_idx = cidx[in_margin] 
            #u, ind = np.unique(col_idx, True)
            cloth.co[col_idx] -= nor[in_margin] * (d[in_margin])[:, nax]
            #cloth.co[u] -= nor[in_margin][ind] * (d[in_margin][ind])[:, nax]
            cloth.vel[col_idx] = tvel
            #cloth.vel[col_idx] = 0
            #cloth.vel[u] = tvel[ind]
            object.vel[:] = object.co                    

            # when iterating springs, we keep putting the collided points back
            ###cloth.col_idx = col_idx
            ###cloth.collide_list = cloth.co[col_idx]
            ###hits = True                    
    # could use the mean of the original trianlge to determine which face
    #   to collide with when there are multiples. So closest mean gets used.
    
    revert_in_place(cloth.ob, cloth.co)
    ###if hits:
        ###cloth.collide_list = cloth.co[col_idx]


class Collider(object):
    pass


def create_collider():
    # maybe fixed? !!! bug where first frame of collide uses empty data. Stuff goes flying.
    col = Collider()
    col.ob = bpy.context.object
    col.co = get_proxy_co(col.ob, None)
    proxy_in_place(col)
    col.v_normals = proxy_v_normals(col.ob)
    col.vel = np.copy(col.co)
    col.tridex = triangulate(col.ob)
    col.tridexer = np.arange(col.tridex.shape[0], dtype=np.int32)
    # cross_vecs used later by barycentric tri check
    proxy_v_normals_in_place(col)
    marginalized = col.co + col.v_normals * col.ob.modeling_cloth_outer_margin
    col.cross_vecs, col.origins, col.normals = get_tri_normals(marginalized[col.tridex])    

    return col


# Self collision object
def create_self_collider():
    # maybe fixed? !!! bug where first frame of collide uses empty data. Stuff goes flying.
    col = Collider()
    col.ob = bpy.context.object
    col.co = get_co(col.ob, None)
    proxy_in_place(col)
    col.v_normals = proxy_v_normals(col.ob)
    col.vel = np.copy(col.co)
    col.tridex = triangulate(col.ob)
    col.tridexer = np.arange(col.tridex.shape[0], dtype=np.int32)
    # cross_vecs used later by barycentric tri check
    proxy_v_normals_in_place(col)
    marginalized = col.co + col.v_normals * col.ob.modeling_cloth_outer_margin
    col.cross_vecs, col.origins, col.normals = get_tri_normals(marginalized[col.tridex])    

    return col


# collide object updater
def collision_object_update(self, context):
    """Updates the collider object"""    
    collide = self.modeling_cloth_object_collision
    print(collide, "this is the collide state")
    # remove objects from dict if deleted
    cull_list = []
    if 'colliders' in extra_data:
        if extra_data['colliders'] is not None:   
            if not collide:
                print("not collide")
                if self.name in extra_data['colliders']:
                    print("name was here")
                    del(extra_data['colliders'][self.name])
            for i in extra_data['colliders']:
                remove = True
                if i in bpy.data.objects:
                    if bpy.data.objects[i].type == "MESH":
                        if bpy.data.objects[i].modeling_cloth_object_collision:
                            remove = False
                if remove:
                    cull_list.append(i)
    for i in cull_list:
        del(extra_data['colliders'][i])

    # add class to dict if true.
    if collide:    
        if 'colliders' not in extra_data:    
            extra_data['colliders'] = {}
        if extra_data['colliders'] is None:
            extra_data['colliders'] = {}
        extra_data['colliders'][self.name] = create_collider()

    
# cloth object detect updater:
def cloth_object_update(self, context):
    """Updates the cloth object when detecting."""
    print("ran the detect updater. It did nothing.")


def manage_animation_handler(self, context):
    if self.modeling_cloth_handler_frame:
        self["modeling_cloth_handler_scene"] = False
        update_pin_group()
    
    if handler_frame in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(handler_frame)
    
    if len(data) > 0:
        bpy.app.handlers.frame_change_post.append(handler_frame)
    
    count = len([i for i in bpy.data.objects if i.modeling_cloth_handler_frame])

    #if count == 0:
        #bpy.app.handlers.frame_change_post.remove(handler_frame)
    

        
def manage_continuous_handler(self, context):    
    if self.modeling_cloth_handler_scene:
        self["modeling_cloth_handler_frame"] = False
        update_pin_group()
    
    if handler_scene in bpy.app.handlers.scene_update_post:
        bpy.app.handlers.scene_update_post.remove(handler_scene)
    
    if len(data) > 0:
        bpy.app.handlers.scene_update_post.append(handler_scene)

    count = len([i for i in bpy.data.objects if i.modeling_cloth_handler_scene])

    #if count == 0:
        #bpy.app.handlers.scene_update_post.remove(handler_scene)
    

# =================  Handler  ======================
def handler_frame(scene):
    items = data.items()
    if len(items) == 0:
        for i in bpy.data.objects:
            i.modeling_cloth = False
        
        for i in bpy.app.handlers.frame_change_post:
            if i.__name__ == 'handler_frame':
                bpy.app.handlers.frame_change_post.remove(i)
                
        for i in bpy.app.handlers.scene_update_post:
            if i.__name__ == 'handler_scene':
                bpy.app.handlers.scene_update_post.remove(i)                
    
    for i, cloth in items:    
        if i in bpy.data.objects: # using the name. The name could change
            if cloth.ob.modeling_cloth_handler_frame:    
                run_handler(cloth)
                if cloth.ob.modeling_cloth_auto_reset:
                    if bpy.context.scene.frame_current <= 1:    
                        reset_shapes(cloth.ob)
        else:
            del(data[i])
            break


def handler_scene(scene):
    items = data.items()
    if len(items) == 0:
        for i in bpy.data.objects:
            i.modeling_cloth = False

        for i in bpy.app.handlers.frame_change_post:
            if i.__name__ == 'handler_frame':
                bpy.app.handlers.frame_change_post.remove(i)

        for i in bpy.app.handlers.scene_update_post:
            if i.__name__ == 'handler_scene':
                bpy.app.handlers.scene_update_post.remove(i)                
    
    for i, cloth in items:    
        if i in bpy.data.objects: # using the name. The name could change
            if cloth.ob.modeling_cloth_handler_scene:    
                run_handler(cloth)

        else:
            del(data[i])
            break


def pause_update(self, context):
    if not self.modeling_cloth_pause:
        update_pin_group()


def global_setup():
    global data, extra_data
    data = bpy.context.scene.modeling_cloth_data_set
    extra_data = bpy.context.scene.modeling_cloth_data_set_extra    
    extra_data['alert'] = False
    extra_data['drag_alert'] = False
    extra_data['clicked'] = False


def init_cloth(self, context):
    global data, extra_data
    data = bpy.context.scene.modeling_cloth_data_set
    extra_data = bpy.context.scene.modeling_cloth_data_set_extra
    extra_data['alert'] = False
    extra_data['drag_alert'] = False
    extra_data['last_object'] = self
    extra_data['clicked'] = False
    
    # object collisions
    colliders = [i for i in bpy.data.objects if i.modeling_cloth_object_collision]
    if len(colliders) == 0:    
        extra_data['colliders'] = None    
    
    # iterate through dict: for i, j in d.items()
    if self.modeling_cloth:
        cloth = create_instance() # generate an instance of the class
        data[cloth.name] = cloth  # store class in dictionary using the object name as a key
    
    cull = [] # can't delete dict items while iterating
    for i, value in data.items():
        if not value.ob.modeling_cloth:
            cull.append(i) # store keys to delete

    for i in cull:
        del data[i]
    
#    # could keep the handler unless there are no modeling cloth objects active
#    
#    if handler_frame in bpy.app.handlers.frame_change_post:
#        bpy.app.handlers.frame_change_post.remove(handler_frame)
#    
#    if len(data) > 0:
#        bpy.app.handlers.frame_change_post.append(handler_frame)


def main(context, event):
    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    coord = event.mouse_region_x, event.mouse_region_y

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    ray_target = ray_origin + view_vector
    
    guide = create_giude()

    def visible_objects_and_duplis():
        """Loop over (object, matrix) pairs (mesh only)"""

        for obj in context.visible_objects:
            if obj.type == 'MESH':
                if obj.modeling_cloth:    
                    yield (obj, obj.matrix_world.copy())

    def obj_ray_cast(obj, matrix):
        """Wrapper for ray casting that moves the ray into object space"""

        # get the ray relative to the object
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv * ray_origin
        ray_target_obj = matrix_inv * ray_target
        ray_direction_obj = ray_target_obj - ray_origin_obj

        # cast the ray
        success, location, normal, face_index = obj.ray_cast(ray_origin_obj, ray_direction_obj)

        if success:
            return location, normal, face_index
        else:
            return None, None, None

    # cast rays and find the closest object
    best_length_squared = -1.0
    best_obj = None
    for obj, matrix in visible_objects_and_duplis():
        hit, normal, face_index = obj_ray_cast(obj, matrix)
        if hit is not None:
            hit_world = matrix * hit
            vidx = [v for v in obj.data.polygons[face_index].vertices]
            verts = np.array([matrix * obj.data.shape_keys.key_blocks['modeling cloth key'].data[v].co for v in obj.data.polygons[face_index].vertices])
            vecs = verts - np.array(hit_world)
            closest = vidx[np.argmin(np.einsum('ij,ij->i', vecs, vecs))]
            length_squared = (hit_world - ray_origin).length_squared
            if best_obj is None or length_squared < best_length_squared:
                best_length_squared = length_squared
                best_obj = obj
                guide.location = matrix * obj.data.shape_keys.key_blocks['modeling cloth key'].data[closest].co
                extra_data['latest_hit'] = matrix * obj.data.shape_keys.key_blocks['modeling cloth key'].data[closest].co
                extra_data['name'] = obj.name
                extra_data['obj'] = obj
                extra_data['closest'] = closest
                
                if extra_data['just_clicked']:
                    extra_data['just_clicked'] = False
                    best_length_squared = length_squared
                    best_obj = obj
                   

class ModelingClothPin(bpy.types.Operator):
    """Modal ray cast for placing pins"""
    bl_idname = "view3d.modeling_cloth_pin"
    bl_label = "Modeling Cloth Pin"
    bl_options = {'REGISTER', 'UNDO'}
    def __init__(self):
        bpy.ops.object.select_all(action='DESELECT')    
        extra_data['just_clicked'] = False
        
    def modal(self, context, event):
        bpy.context.window.cursor_set("CROSSHAIR")
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'NUMPAD_0',
        'NUMPAD_PERIOD','NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4',
         'NUMPAD_5', 'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'MOUSEMOVE':
            main(context, event)
            return {'RUNNING_MODAL'}
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if extra_data['latest_hit'] is not None:
                if extra_data['name'] is not None:
                    closest = extra_data['closest']
                    name = extra_data['name']
                    e = bpy.data.objects.new('modeling_cloth_pin', None)
                    bpy.context.scene.objects.link(e)
                    e.location = extra_data['latest_hit']
                    e.show_x_ray = True
                    e.select = True
                    e.empty_draw_size = .1
                    data[name].pin_list.append(closest)
                    data[name].hook_list.append(e)
                    extra_data['latest_hit'] = None
                    extra_data['name'] = None        
        
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            delete_giude()
            cloths = [i for i in bpy.data.objects if i.modeling_cloth] # so we can select an empty and keep the settings menu up
            extra_data['alert'] = False
            if len(cloths) > 0:                                        #
                ob = extra_data['last_object']                         #
                bpy.context.scene.objects.active = ob
            bpy.context.window.cursor_set("DEFAULT")
            return {'CANCELLED'}

            
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        cloth_objects = False
        cloths = [i for i in bpy.data.objects if i.modeling_cloth] # so we can select an empty and keep the settings menu up
        if len(cloths) > 0:
            cloth_objects = True        
            extra_data['alert'] = True
            
        if context.space_data.type == 'VIEW_3D' and cloth_objects:
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            extra_data['alert'] = False
            bpy.context.window.cursor_set("DEFAULT")
            return {'CANCELLED'}


# drag===================================
# drag===================================
#[‘DEFAULT’, ‘NONE’, ‘WAIT’, ‘CROSSHAIR’, ‘MOVE_X’, ‘MOVE_Y’, ‘KNIFE’, ‘TEXT’, ‘PAINT_BRUSH’, ‘HAND’, ‘SCROLL_X’, ‘SCROLL_Y’, ‘SCROLL_XY’, ‘EYEDROPPER’]

def main_drag(context, event):
    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    coord = event.mouse_region_x, event.mouse_region_y

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    ray_target = ray_origin + view_vector

    def visible_objects_and_duplis():
        """Loop over (object, matrix) pairs (mesh only)"""

        for obj in context.visible_objects:
            if obj.type == 'MESH':
                if obj.modeling_cloth:    
                    yield (obj, obj.matrix_world.copy())

    def obj_ray_cast(obj, matrix):
        """Wrapper for ray casting that moves the ray into object space"""

        # get the ray relative to the object
        matrix_inv = matrix.inverted()
        ray_origin_obj = matrix_inv * ray_origin
        ray_target_obj = matrix_inv * ray_target
        ray_direction_obj = ray_target_obj - ray_origin_obj
        
        # cast the ray
        success, location, normal, face_index = obj.ray_cast(ray_origin_obj, ray_direction_obj)

        if success:
            return location, normal, face_index, ray_target
        else:
            return None, None, None, ray_target

    # cast rays and find the closest object
    best_length_squared = -1.0
    best_obj = None

    for obj, matrix in visible_objects_and_duplis():
        hit, normal, face_index, target = obj_ray_cast(obj, matrix)
        extra_data['target'] = target
        if hit is not None:
            
            hit_world = matrix * hit
            length_squared = (hit_world - ray_origin).length_squared

            if best_obj is None or length_squared < best_length_squared:
                best_length_squared = length_squared
                best_obj = obj
                vidx = [v for v in obj.data.polygons[face_index].vertices]
                vert = obj.data.shape_keys.key_blocks['modeling cloth key'].data
            if best_obj is not None:    

                if extra_data['clicked']:    
                    extra_data['matrix'] = matrix.inverted()
                    data[best_obj.name].clicked = True
                    extra_data['stored_mouse'] = np.copy(target)
                    extra_data['vidx'] = vidx
                    extra_data['stored_vidx'] = np.array([vert[v].co for v in extra_data['vidx']])
                    extra_data['clicked'] = False
                    
    if extra_data['stored_mouse'] is not None:
        move = np.array(extra_data['target']) - extra_data['stored_mouse']
        extra_data['move'] = (move @ np.array(extra_data['matrix'])[:3, :3].T)
                   
                   
# dragger===
class ModelingClothDrag(bpy.types.Operator):
    """Modal ray cast for dragging"""
    bl_idname = "view3d.modeling_cloth_drag"
    bl_label = "Modeling Cloth Drag"
    bl_options = {'REGISTER', 'UNDO'}
    def __init__(self):
        bpy.ops.object.select_all(action='DESELECT')    
        extra_data['hit'] = None
        extra_data['clicked'] = False
        extra_data['stored_mouse'] = None
        extra_data['vidx'] = None
        extra_data['new_click'] = True
        extra_data['target'] = None
        for i in data:
            data[i].clicked = False
        
    def modal(self, context, event):
        bpy.context.window.cursor_set("HAND")
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'MOUSEMOVE':
            #pos = queryMousePosition()            
            main_drag(context, event)
            return {'RUNNING_MODAL'}
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # when I click, If I have a hit, store the hit on press
            extra_data['clicked'] = True
            extra_data['vidx'] = []
            
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            extra_data['clicked'] = False
            extra_data['stored_mouse'] = None
            extra_data['vidx'] = None
            extra_data['new_click'] = True
            extra_data['target'] = None
            for i in data:
                data[i].clicked = False

            
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            extra_data['drag_alert'] = False
            extra_data['clicked'] = False
            extra_data['hit'] = None
            bpy.context.window.cursor_set("DEFAULT")
            extra_data['stored_mouse'] = None
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        cloth_objects = False
        cloths = [i for i in bpy.data.objects if i.modeling_cloth] # so we can select an empty and keep the settings menu up
        if len(cloths) > 0:
            cloth_objects = True        
            extra_data['drag_alert'] = True
            
        if context.space_data.type == 'VIEW_3D' and cloth_objects:
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            extra_data['drag_alert'] = False
            extra_data['stored_mouse'] = None
            bpy.context.window.cursor_set("DEFAULT")
            return {'CANCELLED'}


# drag===================================End
# drag===================================End



class DeletePins(bpy.types.Operator):
    """Delete modeling cloth pins and clear pin list for current object"""
    bl_idname = "object.delete_modeling_cloth_pins"
    bl_label = "Delete Modeling Cloth Pins"
    bl_options = {'REGISTER', 'UNDO'}    
    def execute(self, context):

        ob = get_last_object() # returns tuple with list and last cloth objects or None
        if ob is not None:
            print(data[ob[1].name].pin_list, 'at start')            
            l_copy = data[ob[1].name].pin_list[:]
            h_copy = data[ob[1].name].hook_list[:]
            for i in range(len(data[ob[1].name].hook_list)):
                if data[ob[1].name].hook_list[i].select:
                    bpy.data.objects.remove(data[ob[1].name].hook_list[i])
                    l_copy.remove(data[ob[1].name].pin_list[i]) 
                    h_copy.remove(data[ob[1].name].hook_list[i]) 
            
            data[ob[1].name].pin_list = l_copy
            data[ob[1].name].hook_list = h_copy
            print(data[ob[1].name].pin_list, 'after')        

        bpy.context.scene.objects.active = ob[1]
        return {'FINISHED'}


class SelectPins(bpy.types.Operator):
    """Select modeling cloth pins for current object"""
    bl_idname = "object.select_modeling_cloth_pins"
    bl_label = "Select Modeling Cloth Pins"
    bl_options = {'REGISTER', 'UNDO'}    
    def execute(self, context):
        ob = get_last_object() # returns list and last cloth objects or None
        if ob is not None:
            bpy.ops.object.select_all(action='DESELECT')
            for i in data[ob[1].name].hook_list:
                i.select = True

        return {'FINISHED'}


class PinSelected(bpy.types.Operator):
    """Add pins to verts selected in edit mode"""
    bl_idname = "object.modeling_cloth_pin_selected"
    bl_label = "Modeling Cloth Pin Selected"
    bl_options = {'REGISTER', 'UNDO'}    
    def execute(self, context):
        ob = bpy.context.object
        bpy.ops.object.mode_set(mode='OBJECT')
        sel = [i.index for i in ob.data.vertices if i.select]
                
        name = ob.name
        matrix = ob.matrix_world.copy()
        for v in sel:    
            e = bpy.data.objects.new('modeling_cloth_pin', None)
            bpy.context.scene.objects.link(e)
            if ob.active_shape_key is None:    
                closest = matrix * ob.data.vertices[v].co# * matrix
            else:
                closest = matrix * ob.active_shape_key.data[v].co# * matrix
            e.location = closest #* matrix
            e.show_x_ray = True
            e.select = True
            e.empty_draw_size = .1
            data[name].pin_list.append(v)
            data[name].hook_list.append(e)            
            ob.select = False
        bpy.ops.object.mode_set(mode='EDIT')       
        
        return {'FINISHED'}


class UpdataPinWeights(bpy.types.Operator):
    """Update Pin Weights"""
    bl_idname = "object.modeling_cloth_update_pin_group"
    bl_label = "Modeling Cloth Update Pin Weights"
    bl_options = {'REGISTER', 'UNDO'}        
    def execute(self, context):
        update_pin_group()
        return {'FINISHED'}


class GrowSource(bpy.types.Operator):
    """Grow Source Shape"""
    bl_idname = "object.modeling_cloth_grow"
    bl_label = "Modeling Cloth Grow"
    bl_options = {'REGISTER', 'UNDO'}        
    def execute(self, context):
        scale_source(1.02)
        return {'FINISHED'}


class ShrinkSource(bpy.types.Operator):
    """Shrink Source Shape"""
    bl_idname = "object.modeling_cloth_shrink"
    bl_label = "Modeling Cloth Shrink"
    bl_options = {'REGISTER', 'UNDO'}        
    def execute(self, context):
        scale_source(0.98)
        return {'FINISHED'}


class ResetShapes(bpy.types.Operator):
    """Reset Shapes"""
    bl_idname = "object.modeling_cloth_reset"
    bl_label = "Modeling Cloth Reset"
    bl_options = {'REGISTER', 'UNDO'}        
    def execute(self, context):
        reset_shapes()
        return {'FINISHED'}


class AddVirtualSprings(bpy.types.Operator):
    """Add Virtual Springs Between All Selected Vertices"""
    bl_idname = "object.modeling_cloth_add_virtual_spring"
    bl_label = "Modeling Cloth Add Virtual Spring"
    bl_options = {'REGISTER', 'UNDO'}        
    def execute(self, context):
        add_virtual_springs()
        return {'FINISHED'}


class RemoveVirtualSprings(bpy.types.Operator):
    """Remove Virtual Springs Between All Selected Vertices"""
    bl_idname = "object.modeling_cloth_remove_virtual_spring"
    bl_label = "Modeling Cloth Remove Virtual Spring"
    bl_options = {'REGISTER', 'UNDO'}        
    def execute(self, context):
        add_virtual_springs(remove=True)
        return {'FINISHED'}


def create_properties():            

    bpy.types.Object.modeling_cloth = bpy.props.BoolProperty(name="Modeling Cloth", 
        description="For toggling modeling cloth", 
        default=False, update=init_cloth)

    bpy.types.Object.modeling_cloth_floor = bpy.props.BoolProperty(name="Modeling Cloth Floor", 
        description="Stop at floor", 
        default=False)

    bpy.types.Object.modeling_cloth_pause = bpy.props.BoolProperty(name="Modeling Cloth Pause", 
        description="Stop without removing data",
        default=True, update=pause_update)
    
    # handler type ----->>>        
    bpy.types.Object.modeling_cloth_handler_scene = bpy.props.BoolProperty(name="Modeling Cloth Continuous Update", 
        description="Choose continuous update", 
        default=False, update=manage_continuous_handler)        

    bpy.types.Object.modeling_cloth_handler_frame = bpy.props.BoolProperty(name="Modeling Cloth Handler Animation Update", 
        description="Choose animation update", 
        default=False, update=manage_animation_handler)
        
    bpy.types.Object.modeling_cloth_auto_reset = bpy.props.BoolProperty(name="Modeling Cloth Reset at Frame 1", 
        description="Automatically reset if the current frame number is 1 or less", 
        default=False)#, update=manage_handlers)        
    # ------------------>>>

    bpy.types.Object.modeling_cloth_noise = bpy.props.FloatProperty(name="Modeling Cloth Noise", 
        description="Set the noise strength", 
        default=0.001, precision=4, min=0, max=1, update=refresh_noise)

    bpy.types.Object.modeling_cloth_noise_decay = bpy.props.FloatProperty(name="Modeling Cloth Noise Decay", 
        description="Multiply the noise by this value each iteration", 
        default=0.99, precision=4, min=0, max=1)#, update=refresh_noise_decay)

    # spring forces ------------>>>
    bpy.types.Object.modeling_cloth_spring_force = bpy.props.FloatProperty(name="Modeling Cloth Spring Force", 
        description="Set the spring force", 
        default=1, precision=4, min=0, max=1.5)#, update=refresh_noise)

    bpy.types.Object.modeling_cloth_push_springs = bpy.props.FloatProperty(name="Modeling Cloth Spring Force", 
        description="Set the spring force", 
        default=0.2, precision=4, min=0, max=1.5)#, update=refresh_noise)
    # -------------------------->>>

    bpy.types.Object.modeling_cloth_gravity = bpy.props.FloatProperty(name="Modeling Cloth Gravity", 
        description="Modeling cloth gravity", 
        default=0.0, precision=4, min= -10, max=10)#, update=refresh_noise_decay)

    bpy.types.Object.modeling_cloth_iterations = bpy.props.IntProperty(name="Stiffness", 
        description="How stiff the cloth is", 
        default=2, min=1, max=500)#, update=refresh_noise_decay)

    bpy.types.Object.modeling_cloth_velocity = bpy.props.FloatProperty(name="Velocity", 
        description="Cloth keeps moving", 
        default=.9, min= -1.1, max=1.1, soft_min= -1, soft_max=1)#, update=refresh_noise_decay)

    # Wind. Note, wind should be measured agains normal and be at zero when normals are at zero. Squared should work
    bpy.types.Object.modeling_cloth_wind_x = bpy.props.FloatProperty(name="Wind X", 
        description="Not the window cleaner", 
        default=0, min= -1, max=1, soft_min= -10, soft_max=10)#, update=refresh_noise_decay)

    bpy.types.Object.modeling_cloth_wind_y = bpy.props.FloatProperty(name="Wind Y", 
        description="Because wind is cool", 
        default=0, min= -1, max=1, soft_min= -10, soft_max=10)#, update=refresh_noise_decay)

    bpy.types.Object.modeling_cloth_wind_z = bpy.props.FloatProperty(name="Wind Z", 
        description="It's windzee outzide", 
        default=0, min= -1, max=1, soft_min= -10, soft_max=10)#, update=refresh_noise_decay)

    bpy.types.Object.modeling_cloth_turbulence = bpy.props.FloatProperty(name="Wind Turbulence", 
        description="Add Randomness to wind", 
        default=0, min=0, max=1, soft_min= -10, soft_max=10)#, update=refresh_noise_decay)

    # self collision ----->>>
    bpy.types.Object.modeling_cloth_self_collision = bpy.props.BoolProperty(name="Modeling Cloth Self Collsion", 
        description="Toggle self collision", 
        default=False, update=collision_data_update)

    bpy.types.Object.modeling_cloth_self_collision_force = bpy.props.FloatProperty(name="recovery force", 
        description="Self colide faces repel", 
        default=.17, precision=4, min= -1.1, max=1.1, soft_min= 0, soft_max=1)

    bpy.types.Object.modeling_cloth_self_collision_margin = bpy.props.FloatProperty(name="Margin", 
        description="Self colide faces margin", 
        default=.08, precision=4, min= -1, max=1, soft_min= 0, soft_max=1)

    bpy.types.Object.modeling_cloth_self_collision_cy_size = bpy.props.FloatProperty(name="Cylinder size", 
        description="Self colide faces cylinder size", 
        default=1, precision=4, min= 0, max=4, soft_min= 0, soft_max=1.5)
    # ---------------------->>>

    # extras ------->>>
    bpy.types.Object.modeling_cloth_inflate = bpy.props.FloatProperty(name="inflate", 
        description="add force to vertex normals", 
        default=0, precision=4, min= -10, max=10, soft_min= -1, soft_max=1)

    bpy.types.Object.modeling_cloth_sew = bpy.props.FloatProperty(name="sew", 
        description="add force to vertex normals", 
        default=0, precision=4, min= -10, max=10, soft_min= -1, soft_max=1)
    # -------------->>>

    # external collisions ------->>>
    bpy.types.Object.modeling_cloth_object_collision = bpy.props.BoolProperty(name="Modeling Cloth Self Collsion", 
        description="Detect and collide with this object", 
        default=False, update=collision_object_update)
    
    bpy.types.Object.modeling_cloth_object_detect = bpy.props.BoolProperty(name="Modeling Cloth Self Collsion", 
        description="Detect collision objects", 
        default=False, update=cloth_object_update)    

    bpy.types.Object.modeling_cloth_outer_margin = bpy.props.FloatProperty(name="Modeling Cloth Outer Margin", 
        description="Collision margin on positive normal side of face", 
        default=0.04, precision=4, min=0, max=100, soft_min=0, soft_max=1000)
        
    bpy.types.Object.modeling_cloth_inner_margin = bpy.props.FloatProperty(name="Modeling Cloth Inner Margin", 
        description="Collision margin on negative normal side of face", 
        default=0.1, precision=4, min=0, max=100, soft_min=0, soft_max=1000)        
    # ---------------------------->>>
    
    # property dictionaries
    if "modeling_cloth_data_set" not in dir(bpy.types.Scene):
        bpy.types.Scene.modeling_cloth_data_set = {} 
        bpy.types.Scene.modeling_cloth_data_set_extra = {} 
    
        
def remove_properties():            
    '''Drives to the grocery store and buys a sandwich'''
    del(bpy.types.Object.modeling_cloth)
    del(bpy.types.Object.modeling_cloth_floor)
    del(bpy.types.Object.modeling_cloth_pause)
    del(bpy.types.Object.modeling_cloth_noise)    
    del(bpy.types.Object.modeling_cloth_noise_decay)
    del(bpy.types.Object.modeling_cloth_spring_force)
    del(bpy.types.Object.modeling_cloth_gravity)        
    del(bpy.types.Object.modeling_cloth_iterations)
    del(bpy.types.Object.modeling_cloth_velocity)
    del(bpy.types.Object.modeling_cloth_inflate)
    del(bpy.types.Object.modeling_cloth_sew)

    # self collision
    del(bpy.types.Object.modeling_cloth_self_collision)    
    del(bpy.types.Object.modeling_cloth_self_collision_cy_size)    
    del(bpy.types.Object.modeling_cloth_self_collision_force)    
    del(bpy.types.Object.modeling_cloth_self_collision_margin)    

    # data storage
    del(bpy.types.Scene.modeling_cloth_data_set)
    del(bpy.types.Scene.modeling_cloth_data_set_extra)


class ModelingClothPanel(bpy.types.Panel):
    """Modeling Cloth Panel"""
    bl_label = "Modeling Cloth Panel"
    bl_idname = "Modeling Cloth"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = "Extended Tools"
    #gt_show = True
    
    def draw(self, context):
        status = False
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Modeling Cloth")
        ob = bpy.context.object
        cloths = [i for i in bpy.data.objects if i.modeling_cloth] # so we can select an empty and keep the settings menu up
        if len(cloths) > 0:
            extra_data = bpy.context.scene.modeling_cloth_data_set_extra
            if 'alert' not in extra_data:
                global_setup()    
            status = extra_data['alert']
            if ob is not None:
                if ob.type != 'MESH' or status:
                    ob = extra_data['last_object']

        if ob is not None:
            if ob.type == 'MESH':
                col.prop(ob ,"modeling_cloth", text="Modeling Cloth", icon='SURFACE_DATA')               
                
                pause = 'PAUSE'
                if ob.modeling_cloth_pause:
                    pause = 'PLAY'
                
                if ob.modeling_cloth:
                    col = layout.column(align=True)
                    col.scale_y = 2.0
                    #col.prop(ob ,"modeling_cloth_pause", text=pause, icon=pause)               

                    col = layout.column(align=True)
                    col.scale_y = 1.4
                    col.prop(ob, "modeling_cloth_handler_frame", text="Animation Update", icon="TRIA_RIGHT")
                    if ob.modeling_cloth_handler_frame:    
                        col.prop(ob, "modeling_cloth_auto_reset", text="Frame 1 Reset")
                    col.prop(ob, "modeling_cloth_handler_scene", text="Continuous Update", icon="TIME")
                    col = layout.column(align=True)
                    col.scale_y = 2.0
                    col.operator("object.modeling_cloth_reset", text="Reset")
                    col.alert = extra_data['drag_alert']
                    col.operator("view3d.modeling_cloth_drag", text="Grab")
                    col = layout.column(align=True)
                        
                    col.prop(ob ,"modeling_cloth_iterations", text="Iterations")#, icon='OUTLINER_OB_LATTICE')               
                    col.prop(ob ,"modeling_cloth_spring_force", text="Stiffness")#, icon='OUTLINER_OB_LATTICE')               
                    col.prop(ob ,"modeling_cloth_push_springs", text="Push Springs")#, icon='OUTLINER_OB_LATTICE')               
                    col.prop(ob ,"modeling_cloth_noise", text="Noise")#, icon='PLAY')               
                    col.prop(ob ,"modeling_cloth_noise_decay", text="Decay Noise")#, icon='PLAY')               
                    col.prop(ob ,"modeling_cloth_gravity", text="Gravity")#, icon='PLAY')        
                    col.prop(ob ,"modeling_cloth_inflate", text="Inflate")#, icon='PLAY')        
                    col.prop(ob ,"modeling_cloth_sew", text="Sew Force")#, icon='PLAY')        
                    col.prop(ob ,"modeling_cloth_velocity", text="Velocity")#, icon='PLAY')        
                    col = layout.column(align=True)
                    col.label("Wind")                
                    col.prop(ob ,"modeling_cloth_wind_x", text="Wind X")#, icon='PLAY')        
                    col.prop(ob ,"modeling_cloth_wind_y", text="Wind Y")#, icon='PLAY')        
                    col.prop(ob ,"modeling_cloth_wind_z", text="Wind Z")#, icon='PLAY')        
                    col.prop(ob ,"modeling_cloth_turbulence", text="Turbulence")#, icon='PLAY')        
                    col.prop(ob ,"modeling_cloth_floor", text="Floor")#, icon='PLAY')        
                    col = layout.column(align=True)
                    col.scale_y = 1.5
                    col.alert = status
                    if ob.modeling_cloth:    
                        if ob.mode == 'EDIT':
                            col.operator("object.modeling_cloth_pin_selected", text="Pin Selected")
                            col = layout.column(align=True)
                            col.operator("object.modeling_cloth_add_virtual_spring", text="Add Virtual Springs")
                            col.operator("object.modeling_cloth_remove_virtual_spring", text="Remove Selected")
                        else:
                            col.operator("view3d.modeling_cloth_pin", text="Create Pins")
                        col = layout.column(align=True)
                        col.operator("object.select_modeling_cloth_pins", text="Select Pins")
                        col.operator("object.delete_modeling_cloth_pins", text="Delete Pins")
                        col.operator("object.modeling_cloth_grow", text="Grow Source")
                        col.operator("object.modeling_cloth_shrink", text="Shrink Source")
                        col = layout.column(align=True)
                        col.prop(ob ,"modeling_cloth_self_collision", text="Self Collision")#, icon='PLAY')        
                        col.prop(ob ,"modeling_cloth_self_collision_force", text="Repel")#, icon='PLAY')        
                        col.prop(ob ,"modeling_cloth_self_collision_margin", text="Margin")#, icon='PLAY')        
                        col.prop(ob ,"modeling_cloth_self_collision_cy_size", text="Cylinder Size")#, icon='PLAY')        

                # object collisions
                col = layout.column(align=True)
                col.label("Collisions")
                if ob.modeling_cloth:    
                    col.prop(ob ,"modeling_cloth_object_detect", text="Object Collisions", icon="PHYSICS")

                col.prop(ob ,"modeling_cloth_object_collision", text="Collider", icon="STYLUS_PRESSURE")
                if ob.modeling_cloth_object_collision:    
                    col.prop(ob ,"modeling_cloth_outer_margin", text="Outer Margin", icon="FORCE_FORCE")
                    col.prop(ob ,"modeling_cloth_inner_margin", text="Inner Margin", icon="STICKY_UVS_LOC")
                
                col.label("Collide List:")
                colliders = [i.name for i in bpy.data.objects if i.modeling_cloth_object_collision]
                for i in colliders:
                    col.label(i)
                    
                # =============================
                col = layout.column(align=True)
                col.label('Collision Series')
                col.operator("object.modeling_cloth_collision_series", text="Paperback")
                col.operator("object.modeling_cloth_collision_series_kindle", text="Kindle")
                col.operator("object.modeling_cloth_donate", text="Donate")


class CollisionSeries(bpy.types.Operator):
    """Support my addons by checking out my awesome sci fi books"""
    bl_idname = "object.modeling_cloth_collision_series"
    bl_label = "Modeling Cloth Collision Series"
        
    def execute(self, context):
        collision_series()
        return {'FINISHED'}


class CollisionSeriesKindle(bpy.types.Operator):
    """Support my addons by checking out my awesome sci fi books"""
    bl_idname = "object.modeling_cloth_collision_series_kindle"
    bl_label = "Modeling Cloth Collision Series Kindle"
        
    def execute(self, context):
        collision_series(False)
        return {'FINISHED'}


class Donate(bpy.types.Operator):
    """Support my addons by donating"""
    bl_idname = "object.modeling_cloth_donate"
    bl_label = "Modeling Cloth Donate"

        
    def execute(self, context):
        collision_series(False, False)
        self.report({'INFO'}, 'Paypal, The3dAdvantage@gmail.com')
        return {'FINISHED'}


def collision_series(paperback=True, kindle=True):
    import webbrowser
    import imp
    if paperback:    
        webbrowser.open("https://www.createspace.com/6043857")
        imp.reload(webbrowser)
        webbrowser.open("https://www.createspace.com/7164863")
        return
    if kindle:
        webbrowser.open("https://www.amazon.com/Resolve-Immortal-Flesh-Collision-Book-ebook/dp/B01CO3MBVQ")
        imp.reload(webbrowser)
        webbrowser.open("https://www.amazon.com/Formulacrum-Collision-Book-Rich-Colburn-ebook/dp/B0711P744G")
        return
    webbrowser.open("https://www.paypal.com/donate/?token=G1UymFn4CP8lSFn1r63jf_XOHAuSBfQJWFj9xjW9kWCScqkfYUCdTzP-ywiHIxHxYe7uJW&country.x=US&locale.x=US")

# ============================================================================================    
    


def register():
    create_properties()
    bpy.utils.register_class(ModelingClothPanel)
    bpy.utils.register_class(ModelingClothPin)
    bpy.utils.register_class(ModelingClothDrag)
    bpy.utils.register_class(DeletePins)
    bpy.utils.register_class(SelectPins)
    bpy.utils.register_class(PinSelected)
    bpy.utils.register_class(GrowSource)
    bpy.utils.register_class(ShrinkSource)
    bpy.utils.register_class(ResetShapes)
    bpy.utils.register_class(UpdataPinWeights)
    bpy.utils.register_class(AddVirtualSprings)
    bpy.utils.register_class(RemoveVirtualSprings)
    
    
    bpy.utils.register_class(CollisionSeries)
    bpy.utils.register_class(CollisionSeriesKindle)
    bpy.utils.register_class(Donate)


def unregister():
    remove_properties()
    bpy.utils.unregister_class(ModelingClothPanel)
    bpy.utils.unregister_class(ModelingClothPin)
    bpy.utils.unregister_class(ModelingClothDrag)
    bpy.utils.unregister_class(DeletePins)
    bpy.utils.unregister_class(SelectPins)
    bpy.utils.unregister_class(PinSelected)
    bpy.utils.unregister_class(GrowSource)
    bpy.utils.unregister_class(ShrinkSource)
    bpy.utils.unregister_class(ResetShapes)
    bpy.utils.unregister_class(UpdataPinWeights)
    bpy.utils.unregister_class(AddVirtualSprings)
    bpy.utils.unregister_class(RemoveVirtualSprings)
    
    
    bpy.utils.unregister_class(CollisionSeries)
    bpy.utils.unregister_class(CollisionSeriesKindle)
    bpy.utils.unregister_class(Donate)
    
    
if __name__ == "__main__":
    register()

    # testing!!!!!!!!!!!!!!!!
    #generate_collision_data(bpy.context.object)
    # testing!!!!!!!!!!!!!!!!


    
    for i in bpy.data.objects:
        i.modeling_cloth = False
        i.modeling_cloth_object_collision = False
        
    for i in bpy.app.handlers.frame_change_post:
        if i.__name__ == 'handler_frame':
            bpy.app.handlers.frame_change_post.remove(i)
            
    for i in bpy.app.handlers.scene_update_post:
        if i.__name__ == 'handler_scene':
            bpy.app.handlers.scene_update_post.remove(i)            
