"""V5 11.6mm enclosure and flat-bed previews, using the exported geometry."""
from pathlib import Path
import bpy,math
from mathutils import Vector

OUT=Path(__file__).resolve().parent
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene;scene.render.engine='CYCLES'
scene.cycles.samples=32;scene.cycles.use_denoising=False
scene.render.resolution_x=1200;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
scene.world.color=(.6,.6,.6);scene.view_settings.view_transform='AgX'
scene.render.image_settings.file_format='PNG'
def mat(name,c,metal=0,rough=.4):
    m=bpy.data.materials.new(name);m.use_nodes=True;m.diffuse_color=(*c,1)
    n=m.node_tree.nodes.get('Principled BSDF');n.inputs['Base Color'].default_value=(*c,1)
    n.inputs['Metallic'].default_value=metal;n.inputs['Roughness'].default_value=rough
    return m
shell=mat('PETG enclosure',(.055,.09,.12));covermat=mat('Sliding cover',(.08,.14,.18))
teal=mat('Quick-release shoe base',(.025,.5,.43));pcbmat=mat('Board reference',(.03,.20,.10))
orange=mat('CA-glue adapter',(.93,.27,.035))
silver=mat('USB / cell / shield reference',(.63,.66,.71),.7,.28)
gold=mat('Cell protection tape',(.79,.45,.015),.1,.4)
red=mat('Positive lead',(.7,.012,.025));black=mat('Negative lead',(.01,.016,.021))
lacemat=mat('Laces',(.72,.77,.8),0,.8)
objects={}
def load(n,f,m):
    bpy.ops.wm.stl_import(filepath=str(OUT/f));o=bpy.context.object;o.name=n;o.data.materials.append(m)
    o.data.use_auto_smooth=True
    for face in o.data.polygons:face.use_smooth=True
    o.modifiers.new('Surface normals','WEIGHTED_NORMAL');objects[n]=o;return o
for n,m in [('body',shell),('sliding-cover',covermat),('board-carrier',teal),('glue-on-adapter',orange),('lace-base',teal)]:load(n,n+'-assembly.stl',m)
for n,m in [('sense-board',pcbmat),('battery',silver),('usb',silver),('shield',silver)]:load(n,n+'-reference.stl',m)
def cube(n,co,scale,m):
    bpy.ops.mesh.primitive_cube_add(size=1,location=co);o=bpy.context.object;o.name=n;o.dimensions=scale
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(m);return o
def curve(n,points,m,r=.5):
    c=bpy.data.curves.new(n,'CURVE');c.dimensions='3D';c.bevel_depth=r;c.bevel_resolution=3
    s=c.splines.new('BEZIER');s.bezier_points.add(len(points)-1)
    for p,co in zip(s.bezier_points,points):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
    o=bpy.data.objects.new(n,c);scene.collection.objects.link(o);o.data.materials.append(m);return o
tape=cube('Battery tape / wires face board',(-4.3,0,5.73),(3.0,25.07,8.66),gold)
wires=[]
for d,n,m in [(.9,'Soldered red lead',red),(-.9,'Soldered black lead',black)]:
    wires.append(curve(n,[(-2.9,-4.7+d,8.9),(-1.7,-4.7+d,7.6),(.6,-4.7+d,3.6),
       (4.5,-4.7+d,2.8),(10,-4.7+d,2.85),(13.29,-4.7+d,3.1)],m))
laces=[]
for x in (-18,18):
    laces.append(curve('Lace through base slot',[(x,-29,-1.8),(x,-12,-2.0),
        (x,-8,-5.5),(x,8,-5.5),(x,12,-2.0),(x,29,-1.8)],lacemat,1.25))
ground=cube('Studio floor',(0,0,-7.5),(400,400,1),mat('Floor',(.9,.915,.93),0,.65))
for loc,power,size in [((-60,-90,110),140000,90),((90,-30,75),75000,75),((20,75,90),120000,70)]:
    bpy.ops.object.light_add(type='AREA',location=loc);o=bpy.context.object;o.data.energy=power;o.data.shape='DISK';o.data.size=size
    o.rotation_euler=(Vector((0,0,5))-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(100,-130,85));camera=bpy.context.object;scene.camera=camera
camera.data.type='ORTHO';camera.data.clip_end=1000
def render(n,target,scale):
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.ortho_scale=scale;scene.render.filepath=str(OUT/(n+'.png'));bpy.ops.render.render(write_still=True)
render('assembled',(0,0,3),91)
# Open view reveals the unchanged carrier and cell fit. Cover is removed for clarity.
objects['sliding-cover'].hide_render=True
cut=cube('Cutaway tool',(0,-60,50),(150,120,97),shell)
mod=objects['body'].modifiers.new('Cutaway preview only','BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=cut
cut.hide_render=True
render('side-by-side',(0,0,3),91)
objects['body'].modifiers.remove(mod);objects['sliding-cover'].hide_render=False
# Daily charging: only the pod moves; the threaded lace base stays on the shoe.
delta=Vector((36,0,8))
for n in ('body','sliding-cover','board-carrier','glue-on-adapter','sense-board','battery','usb','shield'):objects[n].location+=delta
tape.location+=delta
for o in wires:o.location+=delta
render('quick-release',(17,0,5),126)
# All five print files, exactly as supplied, sit on a common z=0 print bed.
for o in list(scene.objects):
    if o.type not in ('CAMERA','LIGHT') and o!=ground:o.hide_render=True
ground.location=(61,60,-.5)
ground.dimensions=(160,160,1)
offsets=[(0,0,0),(0,44,0),(82,0,0),(82,40,0),(0,88,0)]
for (n,m),off in zip([('body',shell),('sliding-cover',covermat),('board-carrier',teal),('glue-on-adapter',orange),('lace-base',teal)],offsets):
    o=load(n+' print',n+'.stl',m);o.location=off
gridmat=mat('Bed grid',(.35,.40,.45),0,.7)
for x in range(-10,151,20):curve('20mm bed grid',[(x,-10,.02),(x,150,.02)],gridmat,.035)
for y in range(-10,151,20):curve('20mm bed grid',[(-10,y,.02),(150,y,.02)],gridmat,.035)
camera.location=(170,-110,165)
render('print-bed',(60,60,4),187)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'v5-preview.blend'))
