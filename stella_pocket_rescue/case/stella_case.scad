// Stella Pocket — корпус для Orange Pi 4 LTS
// Откройте в OpenSCAD, выберите part, нажмите F6 и File → Export → STL.
// part: "base" основание, "lid" крышка, "dome" колпачок лампочки,
//       "test" тестовая рамка (печать ~15 мин), "all" сборка, "exploded" разнесённый вид

part = "all";
$fn = 64;

board_l = 91;
board_w = 56;
pcb_t = 1.6;

clr = 0.5;
wall = 2.2;
floor_t = 2;
r_out = 6;
standoff = 4;
base_h = 22;
lid_skirt = 6;
lid_t = 2;
lip_h = 5;
lip_t = 1.6;
lip_clr = 0.3;

fan = 30;
fan_holes = 24;
fan_pos = [40, 28];

led_pos = [80, 44];
led_d = 5.2;

pins = [[3.5, 3.5], [3.5, 52.5], [87.5, 3.5], [87.5, 52.5]];
pins_on = [true, true, true, true];

in_l = board_l + 2 * clr;
in_w = board_w + 2 * clr;
out_l = in_l + 2 * wall;
out_w = in_w + 2 * wall;
r_in = r_out - wall;
o = wall + clr;
pcb_z = floor_t + standoff;
top_z = pcb_z + pcb_t;
lid_z = base_h;
lid_top = lid_z + lid_skirt + lid_t;

// окна под разъёмы: [сторона, от, до, низ, верх], от/до — вдоль края платы
// x1 — короткий край с Ethernet и USB, y0 — длинный край с USB-C, HDMI и аудио,
// x0 — короткий край с microSD. Если на вашей плате иначе, поменяйте здесь.
windows = [
  ["x1", 2, 54, top_z - 1, top_z + 17.5],
  ["y0", 6, 85, top_z - 0.8, top_z + 8.5],
  ["x0", 14, 42, pcb_z - 2.5, top_z + 0.6]
];

snaps_x = [25, 66];
snap_z = base_h - 2.6;

module rrect(l, w, r) {
  translate([r, r]) offset(r = r) square([l - 2 * r, w - 2 * r]);
}

module window(wd) {
  s = wd[0]; a = wd[1]; b = wd[2]; z0 = wd[3]; z1 = wd[4];
  d = wall + lip_clr + lip_t + 1.5;
  if (s == "x0") translate([-1, o + a, z0]) cube([d + 1, b - a, z1 - z0]);
  if (s == "x1") translate([out_l - d, o + a, z0]) cube([d + 1, b - a, z1 - z0]);
  if (s == "y0") translate([o + a, -1, z0]) cube([b - a, d + 1, z1 - z0]);
  if (s == "y1") translate([o + a, out_w - d, z0]) cube([b - a, d + 1, z1 - z0]);
}

module windows_cut() { for (wd = windows) window(wd); }

module base() {
  difference() {
    union() {
      difference() {
        linear_extrude(base_h) rrect(out_l, out_w, r_out);
        translate([wall, wall, floor_t]) linear_extrude(base_h) rrect(in_l, in_w, r_in);
      }
      for (p = pins) translate([o + p[0] - 3.5, o + p[1] - 3.5, 0]) cube([7, 7, pcb_z]);
    }
    windows_cut();
    for (x = [22 : 4.5 : 72]) translate([o + x, out_w - wall - 1, 8]) cube([2, wall + 2, 8]);
    for (x = [28 : 4 : 64]) translate([o + x, o + 12, -1]) cube([2, 32, floor_t + 2]);
    for (x = snaps_x, y = [-1, out_w - wall - 1])
      translate([o + x - 4.5, y, snap_z - 0.9]) cube([9, wall + 2, 1.8]);
    for (p = [[10, 10], [out_l - 10, 10], [10, out_w - 10], [out_l - 10, out_w - 10]])
      translate([p[0], p[1], -0.01]) cylinder(d = 10.5, h = 1);
  }
}

module lip() {
  a = wall + lip_clr;
  difference() {
    translate([a, a, 0]) linear_extrude(lip_h) rrect(in_l - 2 * lip_clr, in_w - 2 * lip_clr, r_in - lip_clr);
    translate([a + lip_t, a + lip_t, -1]) linear_extrude(lip_h + 2)
      rrect(in_l - 2 * lip_clr - 2 * lip_t, in_w - 2 * lip_clr - 2 * lip_t, r_in - lip_clr - lip_t);
  }
  for (x = snaps_x) {
    translate([o + x, wall + lip_clr, snap_z - (lid_z - lip_h)]) rotate([0, 90, 0]) cylinder(r = 0.8, h = 8, center = true);
    translate([o + x, out_w - wall - lip_clr, snap_z - (lid_z - lip_h)]) rotate([0, 90, 0]) cylinder(r = 0.8, h = 8, center = true);
  }
}

module grille() {
  intersection() {
    cylinder(d = fan - 2, h = 20, center = true);
    for (i = [-14 : 3.2 : 14]) translate([i - 0.9, -20, -10]) cube([1.8, 40, 20]);
  }
}

module lid() {
  difference() {
    union() {
      translate([0, 0, lid_z]) difference() {
        linear_extrude(lid_skirt + lid_t) rrect(out_l, out_w, r_out);
        translate([wall, wall, -1]) linear_extrude(lid_skirt + 1) rrect(in_l, in_w, r_in);
      }
      translate([0, 0, lid_z - lip_h]) lip();
      for (i = [0 : len(pins) - 1]) if (pins_on[i])
        translate([o + pins[i][0], o + pins[i][1], top_z + 0.4]) cylinder(d = 3, h = lid_z + lid_skirt - top_z - 0.3);
      translate([o + led_pos[0], o + led_pos[1], lid_z + lid_skirt - 5]) cylinder(d = 8, h = 5.1);
    }
    windows_cut();
    translate([o + fan_pos[0], o + fan_pos[1], lid_top - 1]) grille();
    for (dx = [-1, 1], dy = [-1, 1])
      translate([o + fan_pos[0] + dx * fan_holes / 2, o + fan_pos[1] + dy * fan_holes / 2, lid_z]) cylinder(d = 3.2, h = 20);
    translate([o + led_pos[0], o + led_pos[1], lid_z]) cylinder(d = led_d, h = 20);
    translate([o + led_pos[0], o + led_pos[1], lid_top - 1.4]) cylinder(d = 10.6, h = 2);
    translate([o + 6, o + 4, lid_top - 0.8])
      linear_extrude(1) text("STELLA", size = 6, font = "Liberation Sans:style=Bold", spacing = 1.15);
  }
}

module dome() {
  difference() {
    union() {
      cylinder(d = 10.2, h = 1.2);
      translate([0, 0, 1.2]) sphere(r = 4.6);
      translate([0, 0, -2]) cylinder(d = 7.6, h = 2);
    }
    translate([0, 0, -2.1]) cylinder(d = 5.3, h = 6.5);
    translate([0, 0, -10]) cube([30, 30, 16.2], center = true);
  }
}

module test_frame() {
  intersection() {
    base();
    translate([-1, -1, -1]) cube([out_l + 2, out_w + 2, top_z + 3]);
  }
}

if (part == "base") base();
if (part == "lid") translate([0, out_w, lid_top]) rotate([180, 0, 0]) lid();
if (part == "dome") translate([0, 0, 2]) dome();
if (part == "test") test_frame();
if (part == "all" || part == "exploded") {
  e = part == "exploded" ? 30 : 0;
  color("#3b3e45") base();
  color("#16171a") translate([0, 0, e]) lid();
  color("#ff3b30") translate([o + led_pos[0], o + led_pos[1], lid_top - 1.4 + 2 * e]) dome();
  color("#1f6f4a") translate([o, o, pcb_z + e / 2]) cube([board_l, board_w, pcb_t]);
}
