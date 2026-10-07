# V5: 11.6 mm low-profile electronics housing

Housing: **70 × 32 × 11.6 mm**, down from 13.4 mm in v4.
Complete assembly with the unchanged glue-on dock: approximately
**72 × 36 × 17.0 mm**, down from 18.8 mm.

## Height budget

| Item | Height |
|---|---:|
| Floor | 1.20 mm |
| Thin battery mounting tape | 0.20 mm |
| Measured battery | 8.66 mm |
| Gap above the battery | 0.34 mm |
| Cover | 1.00 mm |
| Small outer rim allowance | 0.20 mm |
| Total housing | **11.60 mm** |

The flush dovetail lid rails fit within this height; v4's raised rail roofs are
removed. The side walls remain sturdy, while the floor and cover are thinner.
This is close to the practical lower limit for this battery. A substantially
lower housing would need a thinner battery, reduced clearance, or weaker skins.

## Parts retained

The existing fitted board tray, glue-on adapter and shoe base STLs are
byte-for-byte unchanged. All battery/PCB X–Y fit dimensions and the open wire
routes are retained. The battery and board/tray sit 0.4 mm lower because the
floor is thinner. Only the housing and sliding-cover designs change.

Keep the existing 0.2 mm tape allowance under the battery; do not add a thick
foam pad. The battery clearance above is only 0.34 mm, so check the printed
roof fit before closing and do not use the cover to compress the pouch cell.

## Printing

The same files are designed for PLA and PETG, with the flat print orientations
already saved. Start with a calibrated profile, 0.2 mm layers, a 0.4 mm nozzle,
and four walls. The floor is six 0.2 mm layers, and the cover is five layers.
The thinner cover is less stiff than v4, but still restrained along both rails.

- Housing: full flat bottom on the bed, electronics bays up.
- Cover: broad outer face on the bed; its tapered flanges grow at about
  42 degrees from vertical, and its pads/skirt grow upward.
- Glue adapter: flat glue face on the bed.
- Shoe base: bottom on the bed, sloped female dock channels upward.
- Tray: reuse your existing fitted part, or print the unchanged file flat.

Designed for supports off, with self-supporting rail slopes and no large bridge
across the outer USB boot window. Inspect the slicer layer preview; printer
settings may still need tuning for short local bridges and thin features.
Do not fuse the five separate parts in `low-profile-v5-print-plate.stl`.

## Assembly and use

Dry-fit the adapter and shoe base first. CA-glue the adapter's broad flat face
to the housing underside, aligning it with the four registration ticks. Its
catch faces the USB end and the side carrying the shoe base's release button.
Keep glue out of the moving rails/catch, and follow the adhesive's surface
preparation and cure instructions. Test the cured joint before installing
the electronics. Do not glue the shoe base to the adapter.

Place the permanently connected battery and board/tray in their separate bays,
with the battery's taped/wire end facing the board. Lay the leads in the
5.4 mm top-open gate and existing tray notch. Keep slack out of the lid rails
and hold-down pads; no connector needs to be disconnected or threaded through
a closed hole.

Slide the cover in from the USB end toward the battery end until it clicks.
Lift the small front tab about 0.7 mm to release and slide the cover out. If
the PCB has vertical play, use thin soft nonconductive tape only at the PCB-edge
hold-down pads. The cover should close without squeezing the battery.

Install the shoe base on the laces once. For charging, press its side tab inward
about 1.1 mm, slide the whole pod toward the USB end about 30 mm, and lift it
away. The shoe base stays attached. Charge with the cover closed and slide the
pod back until it clicks. No screws or hinge pins are required.

## Verification and limits

All five files have valid connected/watertight geometry and quantified flat bed
faces. CAD checks pass for the measured battery, official Sense board,
top-loading assembly, cover motion, released docking motion, and both catches
blocking withdrawal when latched. The nominal cover-arm beam strain estimate
is approximately 0.13%; the unchanged dock-arm estimate is 0.24%.

These are model checks, not physical PLA/PETG fatigue, printer or CA-bond tests.
Test fit, repeated release and attachment retention before running. The USB
opening is not waterproof. Editable CAD and the actual-height validation report
are included in the package.
