"""V5: lower 11.6mm housing with flush dovetail cover rails.

PLA/PETG geometry, five printed parts, zero metal fasteners. Millimetres.
Carrier STL is the exact tested v2 part. Each export has a substantial bed face.
"""
from pathlib import Path
import hashlib,json,math,shutil
import cadquery as cq
import trimesh

OUT=Path(__file__).resolve().parent
BATTERY=(26.31,25.07,8.66)
BAT_X,BAY_X=-16.0,18.0
MODULE_L,MODULE_W,FLOOR=36.0,32.0,1.2
H=11.6
CASE_L,CASE_X=70.0,1.0
CELL_Z=1.4
PCB_X,PCB_Z=22.5,3.4
LID_Z,LID_T=10.4,1.0
LID_Y,LID_ARM_W=11.2,3.2
LID_CLEAR=.20
DOCK_CLEAR=.20
BASE_Z,BASE_T=-5.4,1.4
SPRING_L,SPRING_T,RELEASE_TRAVEL=31.0,1.4,1.1
ADAPTER_Z,ADAPTER_T=-1.3,1.2
GLUE_GAP=.10
LID_ARM_L=28.0
SCREWS=[(x,y) for x in (-15.7,15.7) for y in (-13.7,13.7)]

def box(x,y,z,dx,dy,dz):
    return cq.Workplane('XY').box(dx,dy,dz).translate((x,y,z))
def rounded(dx,dy,dz,r,z=0,x=0,y=0):
    return (cq.Workplane('XY').sketch().rect(dx,dy).vertices().fillet(r)
            .finalize().extrude(dz).translate((x,y,z)))
def cyl(x,y,z,r,h):
    return cq.Workplane('XY').circle(r).extrude(h).translate((x,y,z))
def profile_cut(x,y,z,w,h,r,depth):
    return (cq.Workplane('YZ',origin=(x,y,z)).sketch().rect(w,h).vertices()
            .fillet(r).finalize().extrude(depth))
def yz_poly(points,x,length):
    return cq.Workplane('YZ',origin=(x,0,0)).polyline(points).close().extrude(length)
def common_volume(a,b):
    a=a.val() if isinstance(a,cq.Workplane) else a
    b=b.val() if isinstance(b,cq.Workplane) else b
    aa,bb=a.BoundingBox(),b.BoundingBox()
    if aa.xmax<=bb.xmin or bb.xmax<=aa.xmin or aa.ymax<=bb.ymin or bb.ymax<=aa.ymin or aa.zmax<=bb.zmin or bb.zmax<=aa.zmin:return 0.0
    return a.intersect(b).Volume()

# Exact v2 carrier CAD construction; only its location in the case changes.
carrier=rounded(31.3,27.2,1.2,2,11.0)
for x,y in SCREWS:carrier=carrier.cut(cyl(x,y,10.0,2.60,4.2))
wire_notch=box(-9.7,-4.7,13.0,15.0,5.4,7.0)
carrier=carrier.cut(wire_notch)
for y in (-8.55,8.55):carrier=carrier.union(box(4.5,y,12.7,18,.65,1.0))
for y in (-9.85,9.85):carrier=carrier.union(box(4.5,y,13.4,19.8,1.4,2.4))
for x in (4.5-21.35/2-.5,4.5+21.35/2+.5):
    for y in (-7.45,7.45):carrier=carrier.union(box(x,y,13.4,1,2.6,2.4))
carrier=carrier.cut(wire_notch).translate((BAY_X,0,-9.8))

# Official board geometry is used for clearance checks and previews.
raw=cq.importers.importStep(str(next((OUT/'references').glob('sense-official-*.step'))))
raw_pcb=max(raw.solids().vals(),key=lambda s:s.Volume());bb=raw_pcb.BoundingBox()
def place(s):
    return s.rotate((0,0,0),(1,0,0),90).translate(
        (PCB_X-(bb.xmin+bb.xmax)/2,(bb.zmin+bb.zmax)/2,PCB_Z-bb.ymin))
board_shape=cq.Compound.makeCompound([place(s) for s in raw.solids().vals()])
board=cq.Workplane('XY').newObject([board_shape])
pcb=place(raw_pcb);PCB_TOP=pcb.BoundingBox().zmax
usb=place(next(s for s in raw.solids().vals() if 41<s.Volume()<42));ub=usb.BoundingBox()
USB_Y,USB_Z=(ub.ymin+ub.ymax)/2,(ub.zmin+ub.zmax)/2
USB_W,USB_H=ub.ymax-ub.ymin+.60,ub.zmax-ub.zmin+.60
battery=box(BAT_X,0,CELL_Z+BATTERY[2]/2,*BATTERY)

body=rounded(CASE_L,MODULE_W,H,2,x=CASE_X)
for module_x in (BAT_X,BAY_X):
    body=body.cut(rounded(32.8,28.8,H+1,1.4,FLOOR,module_x))
    # Preserve the tested bay's floor, wall/corner profile and clearances.
    for x,y in SCREWS:body=body.union(cyl(module_x+x,y,0,2.3,10.3 if module_x==BAT_X else 3.9))
# Keep the ledges' top/inner boundary, add 45-degree support underneath.
for sign in (-1,1):
    p=[(sign*14.6,8.2),(sign*14.6,10.2),(sign*12.8,10.2),(sign*12.8,10.0)]
    body=body.union(yz_poly(p,BAT_X-10,20))
for x in (-16.05,16.05):
    for y in (-10.8,10.8):body=body.union(box(BAY_X+x,y,1.5,.5,2,2.6))
# Both wire gates are top-open. The soldered pair is never threaded through a hole.
body=body.cut(box(1,-4.7,8.2,4.0,5.4,14))
# Sloping female rails capture the tapered cover within the cover's height.
# This removes the raised roof above the v4 rectangular lid slot.
rail_profile=[(-15.4,10.3),(15.4,10.3),(14.4,11.4),(14.4,H+1),(-14.4,H+1),(-14.4,11.4)]
body=body.cut(yz_poly(rail_profile,-32.4,69.0))
# Entry slots for the deep PCB hold-down pads, hidden by the cover's front cap.
for y in (-8.55,8.55):body=body.cut(box(35.8,y,9.0,3.2,1.15,8.4))
# Close USB guide and outer boot relief; removable cover closes the upper part.
body=body.cut(profile_cut(33.8,USB_Y,USB_Z,USB_W,USB_H,.55,4))
body=body.cut(box(36,USB_Y,(USB_Z+USB_H/2+H+1)/2,4,USB_W,H+1-(USB_Z+USB_H/2)))
body=body.cut(profile_cut(35,USB_Y,USB_Z,12,7,1,2))
# Lift-to-release cover latch catches inside the front wall, away from the USB port.
body=body.cut(box(34.5,LID_Y,9.80,1.20,LID_ARM_W+.4,1.10))
body=body.cut(box(35.7,LID_Y,11.8,3.8,LID_ARM_W+.4,2.0))
# The cover front provides the upper end wall and the latch entry.
body=body.cut(box(35.4,0,11.8,2.2,27.6,1.2))

# Tiny engraved registration ticks preserve a large, coplanar housing bed face.
for x in (-20,20):
    for y in (-15,15):
        body=body.cut(box(x,y,.10,3.0,.6,.20))
        body=body.cut(box(x,y,.10,.6,3.0,.20))

# Separate adapter: print its broad glue face DOWN, then flip/glue below housing.
adapter=rounded(40,30,ADAPTER_T,2,ADAPTER_Z)
for y in (-10,10):
    p=[(y-1.1,-1.2),(y+1.1,-1.2),(y+2.2,-3.6),(y-2.2,-3.6)]
    adapter=adapter.union(yz_poly(p,-13.25,26.5))
# Rigid catch is a fork when printed glue-face-down, so its window has no roof bridge.
receiver=box(12.2,-16.55,-2.25,6.4,.9,4.3)
receiver=receiver.union(box(12.2,-14.85,-.7,6.4,4.3,1.2))
receiver=receiver.cut(box(12.4,-16.55,-3.75,3.2,1.5,2.1))
adapter=adapter.union(receiver)

# Sliding panel enters from +X (board end). Low board pads never cross the cell.
lid_rigid=yz_poly([(-15.1,LID_Z),(15.1,LID_Z),(14.2,LID_Z+LID_T),(-14.2,LID_Z+LID_T)],-32.2,69.2)
for x in (BAY_X+1,BAY_X+10):
    for y in (-8.55,8.55):
        low=PCB_TOP+.35
        lid_rigid=lid_rigid.union(box(x,y,(low+LID_Z)/2,4,.65,LID_Z-low))
# USB cap is carried by the panel and clears the board during sliding.
lip_z=USB_Z+USB_H/2
cap=box(35.0,USB_Y,(lip_z+LID_Z)/2,2,USB_W,LID_Z-lip_z)
cap=cap.cut(profile_cut(35.0,USB_Y,USB_Z,12,7,1,2))
lid_rigid=lid_rigid.union(cap)
endcap=box(36.65,0,6.3,1.0,32.0,10.2)
endcap=endcap.cut(profile_cut(35.9,USB_Y,USB_Z,12.5,8.0,1,2))
# Open the lower boot edge: when printed upside down this avoids a 12.5mm bridge.
endcap=endcap.cut(box(36.65,USB_Y,1.5,1.4,12.5,1.0))
endcap=endcap.cut(box(36.8,LID_Y,11.3,3.0,LID_ARM_W+1.2,4.6))
lid_rigid=lid_rigid.union(endcap)
# Longer, low-deflection leaf is less demanding of PLA than the v3 arm.
for y in (9.3,13.1):lid_rigid=lid_rigid.cut(box(21.9,y,10.9,28.1,.60,4))
lid_rigid=lid_rigid.cut(box(35.8,LID_Y,10.9,.60,LID_ARM_W+1.2,4))
lid_leaf=box(21.9,LID_Y,10.9,LID_ARM_L,LID_ARM_W,LID_T)
lid_leaf=lid_leaf.union(box(36.4,LID_Y,10.9,3.0,LID_ARM_W,LID_T))
lid_tooth=(cq.Workplane('XZ',origin=(0,LID_Y+LID_ARM_W/2,0))
           .polyline([(34.1,LID_Z),(34.9,LID_Z),(34.9,LID_Z-.65)]).close().extrude(LID_ARM_W))
lid_leaf=lid_leaf.union(lid_tooth)
lid=lid_rigid.union(lid_leaf)

# Lace base is flat on the bed. Female dovetails have sloped, open-top channels.
base_fixed=rounded(48,28,BASE_T,3,BASE_Z)
for x in (-18,18):base_fixed=base_fixed.cut(rounded(5,21,BASE_T+2,1.3,BASE_Z-1,x))
base_fixed=base_fixed.cut(rounded(34,4.2,4,1.2,BASE_Z-1,-1.5,-14.0))
for y in (-10,10):
    channel=box(0,y,-2.8,30,6.0,2.6)
    points=[(y-2.45,-3.85),(y+2.45,-3.85),(y+1.3,-1.2),(y-1.3,-1.2)]
    channel=channel.cut(yz_poly(points,-13.6,29.0))
    base_fixed=base_fixed.union(channel)
# A 45-degree underside gusset supports the rail beside the latch clearance pocket.
base_fixed=base_fixed.union(yz_poly([(-11.7,-5.4),(-11.7,-4.0),(-13,-4.0),(-13,-4.1)],-15,30))
# Large rounded root, thin long planar beam; ~0.24% nominal strain at release.
base_fixed=base_fixed.union(rounded(6,4.6,2.4,1.0,BASE_Z,-20,-13.1))
spring=box(-2.0,-15.1,-4.2,32.0,SPRING_T,2.4)
spring=spring.union(cq.Workplane('XY').polyline([(11.0,-15.8),(11.0,-16.8),(13.8,-15.8)])
                    .close().extrude(2.4).translate((0,0,BASE_Z)))
spring=spring.union(box(12.0,-17.6,-5.0,2.4,3.8,.8))
spring=spring.union(rounded(4.8,1.8,2.4,.6,BASE_Z,12.0,-19.4))
base=base_fixed.union(spring)

parts={'body':body,'sliding-cover':lid,'board-carrier':carrier,'glue-on-adapter':adapter,'lace-base':base}
report={'units':'mm','battery_mm':BATTERY,'enclosure_mm':[CASE_L,MODULE_W,H],
        'floor_thickness_mm':FLOOR,'cover_thickness_mm':LID_T,'battery_headroom_mm':round(LID_Z-(CELL_Z+BATTERY[2]),2),
        'hardware_count':0,'assembly':'CA-glue the separate adapter to the flat housing base.',
        'glue_gap_mm':GLUE_GAP,'board_carrier':'Exact tested v2 STL, unchanged.',
        'lid_rail_clearance_per_side_mm':LID_CLEAR,'dock_clearance_per_side_mm':DOCK_CLEAR,
        'pcb_pocket_mm':[21.35,18.20],'wire_gate_width_mm':5.4,'parts':{}}
for name,p in parts.items():
    assert p.val().isValid() and len(p.solids().vals())==1,(name,'invalid or disconnected CAD')
    for other,q in parts.items():
        if name<other:
            overlap=common_volume(p,q)
            assert overlap<.001,(name,other,overlap)
    assert common_volume(p,battery)<.001,(name,'cell overlap')
    for i,s in enumerate(board_shape.Solids()):
        overlap=common_volume(p,s)
        assert overlap<.001,(name,'board',i,overlap)
# Rigid cover features slide clear; the leaf is held up while its tooth crosses the catch.
for dx in (.5,1,3,8,16,32,70):
    moving=lid_rigid.union(lid_leaf.translate((0,0,.70))).translate((dx,0,0))
    assert common_volume(moving,body)<.001,('cover sliding',dx,common_volume(moving,body))
    assert common_volume(moving,battery)<.001,('cover over cell',dx)
    for i,s in enumerate(board_shape.Solids()):
        assert common_volume(moving,s)<.001,('cover over board',dx,i)
# Approximate full released position; actual leaf bends, it does not translate rigidly.
released_base=base_fixed.union(spring.translate((0,RELEASE_TRAVEL,0)))
for dx in (.5,2,6,12,24,36,76):
    for name,obj in [('body',body),('adapter',adapter)]:
        assert common_volume(obj.translate((dx,0,0)),released_base)<.001,('quick-release dock',name,dx)
# Both catches must physically block withdrawal until their release tabs are used.
assert common_volume(adapter.translate((.5,0,0)),base)>.01,'dock catch does not retain'
assert common_volume(lid.translate((.5,0,0)),body)>.01,'cover catch does not retain'
for dz in (.5,2,6,12):
    for name,obj in [('battery',battery),('carrier',carrier),('board',board)]:
        assert common_volume(obj.translate((0,0,dz)),body)<.001,('top loading',name,dz)
report['estimated_latch_strain_percent']={'dock':round(100*3*SPRING_T*RELEASE_TRAVEL/(2*SPRING_L**2),2),
        'cover':round(100*3*LID_T*.70/(2*LID_ARM_L**2),2)}

plate_meshes=[];assembly=cq.Assembly(name='low-profile-foot-pod-v5')
offsets=[(0,0,0),(0,44,0),(82,0,0),(82,40,0),(0,88,0)]
for name,p in parts.items():
    cq.exporters.export(p,str(OUT/f'{name}-assembly.stl'),tolerance=.035,angularTolerance=.12)
    path=OUT/f'{name}.stl'
    if name in ('board-carrier','glue-on-adapter','lace-base'):
        ref=OUT/'references'/('proven-'+name+'.stl')
        shutil.copy2(ref,path)
        assert path.read_bytes()==ref.read_bytes()
    else:
        printable=p.rotate((0,0,0),(1,0,0),180) if name in ('sliding-cover','glue-on-adapter') else p
        pb=printable.val().BoundingBox()
        printable=printable.translate((-pb.xmin,-pb.ymin,-pb.zmin))
        cq.exporters.export(printable,str(path),tolerance=.035,angularTolerance=.12)
    mesh=trimesh.load_mesh(path)
    if name not in ('board-carrier','glue-on-adapter','lace-base'):
        # OCCT bounding boxes can include tolerance; put the actual mesh on z=0.
        mesh.apply_translation(-mesh.bounds[0])
        mesh.export(path)
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0,name
    assert len(mesh.split())==1,name
    # Quantify the actual coplanar contact face in the saved printing orientation.
    on_bed=(abs(mesh.triangles[:,:,2]-mesh.bounds[0,2]).max(axis=1)<.0001)&(mesh.face_normals[:,2]<-.99)
    area=float(mesh.area_faces[on_bed].sum())
    assert area>25,(name,'insufficient flat bed face',area)
    report['parts'][name]={'size_mm':mesh.extents.round(2).tolist(),'volume_cm3':round(mesh.volume/1000,3),
        'watertight':True,'flat_bed_contact_mm2':round(area,1)}
    # The unchanged tray file retains v2's tiny origin tolerance; the plate drops it to bed.
    mesh.apply_translation(-mesh.bounds[0])
    mesh.apply_translation(offsets[len(plate_meshes)]);plate_meshes.append(mesh)
    assembly.add(p,name=name)
plate=trimesh.util.concatenate(plate_meshes)
assert plate.is_watertight and len(plate.split())==5
plate.export(OUT/'low-profile-v5-print-plate.stl')
cq.exporters.export(assembly.toCompound(),str(OUT/'low-profile-v5.step'))
for n,p in [('sense-board-reference',board),('battery-reference',battery),('usb-reference',usb),
            ('shield-reference',place(raw.solids().vals()[24]))]:
    cq.exporters.export(p,str(OUT/f'{n}.stl'),tolerance=.06)
overall=assembly.toCompound().BoundingBox()
report['complete_mount_mm']=[round(overall.xlen,2),round(overall.ylen,2),round(overall.zlen,2)]
report['checks']=['Five valid, connected, watertight print parts; zero metal hardware.',
        'Each exported print has a quantified flat bed-contact face.',
        'Housing bottom is flat; adapter glue face prints flat after flipping.',
        'No assembled overlaps with the measured cell or official board model.',
        'Board carrier STL is byte-identical to the tested v2 part.',
        'V4 glue-on adapter and shoe base STLs are unchanged.',
        'Battery contact dimensions retained; ledge undersides have 45-degree print ramps.',
        'Sliding cover checked over the electronics at seven offsets with latch lifted.',
        'Quick-release docking path checked at seven offsets with lateral latch released.',
        'Both catches block withdrawal when their tabs are not released.',
        'Top-loading battery and connected board/carrier clearance checked.']
report['print_design']={'material_targets':['PLA','PETG'],'supports':'Designed without generated supports; short bridges may still need printer tuning.',
        'rail_wall_inward_slope_degrees':round(math.degrees(math.atan(1.15/2.65)),1),
        'case_upper_rail_roof_slope_degrees':round(math.degrees(math.atan(1.0/1.1)),1)}
(OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
