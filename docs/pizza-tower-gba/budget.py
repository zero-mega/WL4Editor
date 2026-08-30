#!/usr/bin/env python3
"""
GBA asset/performance budget calculator.

Written for the "Pizza Tower on GBA" feasibility investigation. Every number
quoted in FEASIBILITY.md comes out of this script, so the numbers can be
re-derived (and argued with) instead of taken on faith.

Hardware figures are from GBATEK. Run with no arguments for the default
scenario, or point it at a JSON scene file with --scene.

    ./budget.py
    ./budget.py --scene myscene.json
"""

import argparse
import json
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Hardware constants (GBATEK)
# ---------------------------------------------------------------------------

CPU_HZ = 16777216           # ARM7TDMI, 16.78 MHz
FRAMES_PER_SEC = 59.7275    # actual GBA refresh
CYCLES_PER_FRAME = 280896   # 228 scanlines * 1232 cycles
VISIBLE_SCANLINES = 160
SCREEN_W, SCREEN_H = 240, 160

OBJ_VRAM_BYTES = 32 * 1024  # 0x6010000..0x6017FFF in tile modes (modes 0-2)
BG_VRAM_BYTES = 64 * 1024
IWRAM_BYTES = 32 * 1024
EWRAM_BYTES = 256 * 1024
MAX_ROM_BYTES = 32 * 1024 * 1024

OAM_ENTRIES = 128
MAX_SPRITE_DIM = 64

# OBJ rendering cycle budget per scanline. The lower figure applies when
# DISPCNT's "H-Blank interval free" bit is set (which buys you HBlank DMA time
# at the cost of sprite throughput).
OBJ_CYCLES_PER_SCANLINE = 1210
OBJ_CYCLES_PER_SCANLINE_HBLANK_FREE = 954

# Per-sprite cost on a scanline it covers.
def obj_scanline_cost(width_px: int, affine: bool) -> int:
    return 10 + 2 * width_px if affine else width_px


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class Actor:
    """One character/effect: its cel size, how many animation frames exist,
    and how many instances are on screen in the worst case."""
    name: str
    w: int
    h: int
    frames: int              # total animation frames authored (ROM cost)
    onscreen: int = 1        # worst-case simultaneous instances
    bpp: int = 4
    affine: bool = False
    resident: bool = True    # frames live in VRAM vs streamed per animation frame

    @property
    def tiles_per_cel(self) -> int:
        # Sprites are built from 8x8 tiles; partial tiles still cost a full tile.
        return ((self.w + 7) // 8) * ((self.h + 7) // 8)

    @property
    def bytes_per_cel(self) -> int:
        return self.tiles_per_cel * 8 * 8 * self.bpp // 8

    @property
    def rom_bytes(self) -> int:
        return self.bytes_per_cel * self.frames

    @property
    def vram_bytes(self) -> int:
        """VRAM held at once. Streamed actors need a double buffer (one cel
        being displayed, one being DMA'd in) per on-screen instance that can
        animate independently."""
        if self.resident:
            return self.bytes_per_cel * self.frames
        return self.bytes_per_cel * 2 * self.onscreen

    def oam_entries(self) -> int:
        """A sprite larger than 64x64 must be split across several OBJs."""
        return self.onscreen * (((self.w + MAX_SPRITE_DIM - 1) // MAX_SPRITE_DIM) *
                                ((self.h + MAX_SPRITE_DIM - 1) // MAX_SPRITE_DIM))


@dataclass
class Scene:
    name: str
    actors: list = field(default_factory=list)
    # How many of the actors' rows realistically overlap the single worst
    # scanline. Defaults to "all of them", which is pessimistic but safe.
    worst_scanline_overlap: float = 1.0


def analyse(scene: Scene, hblank_free: bool = False) -> dict:
    budget = (OBJ_CYCLES_PER_SCANLINE_HBLANK_FREE if hblank_free
              else OBJ_CYCLES_PER_SCANLINE)

    rom = sum(a.rom_bytes for a in scene.actors)
    vram = sum(a.vram_bytes for a in scene.actors)
    oam = sum(a.oam_entries() for a in scene.actors)

    # Worst-case scanline: every on-screen instance covering the same row.
    scan = sum(a.onscreen * obj_scanline_cost(a.w, a.affine) for a in scene.actors)
    scan = int(scan * scene.worst_scanline_overlap)

    # Streaming cost: each streamed actor pushes one cel per animation frame.
    # Assume animations step at 15 Hz (every 4th display frame), so per display
    # frame we move roughly 1/4 of a cel per instance. DMA3 on ROM->VRAM moves
    # 2 bytes per ~2.5 cycles (16-bit bus, 3/1 waitstates).
    stream_bytes = sum(a.bytes_per_cel * a.onscreen / 4
                       for a in scene.actors if not a.resident)
    stream_cycles = stream_bytes * 1.25

    return {
        "rom_bytes": rom,
        "vram_bytes": vram,
        "vram_pct": 100.0 * vram / OBJ_VRAM_BYTES,
        "oam": oam,
        "scanline_cycles": scan,
        "scanline_budget": budget,
        "scanline_pct": 100.0 * scan / budget,
        "stream_bytes_per_frame": stream_bytes,
        "stream_cycles": stream_cycles,
        "stream_pct_of_frame": 100.0 * stream_cycles / CYCLES_PER_FRAME,
    }


def fmt_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB"):
        if abs(n) < 1024 or unit == "MB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n:,.0f} B"
        n /= 1024
    return f"{n} B"


def report(scene: Scene, hblank_free: bool = False) -> None:
    r = analyse(scene, hblank_free)
    print(f"\n=== {scene.name} ===\n")
    print(f"{'actor':<22}{'cel':>10}{'tiles':>7}{'cel B':>8}"
          f"{'frames':>8}{'ROM':>11}{'VRAM':>10}{'OBJ':>5}")
    print("-" * 81)
    for a in scene.actors:
        print(f"{a.name:<22}{f'{a.w}x{a.h}':>10}{a.tiles_per_cel:>7}"
              f"{a.bytes_per_cel:>8}{a.frames:>8}"
              f"{fmt_bytes(a.rom_bytes):>11}{fmt_bytes(a.vram_bytes):>10}"
              f"{a.oam_entries():>5}")
    print("-" * 81)
    print(f"{'TOTAL':<22}{'':>10}{'':>7}{'':>8}{'':>8}"
          f"{fmt_bytes(r['rom_bytes']):>11}{fmt_bytes(r['vram_bytes']):>10}"
          f"{r['oam']:>5}")

    print(f"\nOBJ VRAM      {fmt_bytes(r['vram_bytes'])} / "
          f"{fmt_bytes(OBJ_VRAM_BYTES)}  ({r['vram_pct']:.0f}%)  "
          f"{'OK' if r['vram_pct'] <= 100 else 'OVER BUDGET'}")
    print(f"OAM           {r['oam']} / {OAM_ENTRIES} entries  "
          f"{'OK' if r['oam'] <= OAM_ENTRIES else 'OVER BUDGET'}")
    print(f"ROM (art)     {fmt_bytes(r['rom_bytes'])} / "
          f"{fmt_bytes(MAX_ROM_BYTES)} cart max  "
          f"({100.0 * r['rom_bytes'] / MAX_ROM_BYTES:.1f}%)")
    print(f"Worst scanline{r['scanline_cycles']:>6} / {r['scanline_budget']} cycles  "
          f"({r['scanline_pct']:.0f}%)  "
          f"{'OK' if r['scanline_pct'] <= 100 else 'SPRITES WILL DROP'}"
          f"{'  [H-Blank interval free]' if hblank_free else ''}")
    print(f"Cel streaming {fmt_bytes(r['stream_bytes_per_frame'])}/frame -> "
          f"{r['stream_cycles']:,.0f} cycles "
          f"({r['stream_pct_of_frame']:.2f}% of a 60 Hz frame)")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def default_scenes() -> list:
    """Two takes on the same fight: PT-faithful sprite scale, and a scale that
    actually fits a 240x160 screen."""

    # Peppino at PT's on-screen proportion. In PT he occupies roughly a quarter
    # of the view height; on a 160px-tall screen that is ~40px, and his wilder
    # poses (mach, superjump, taunt) need a cel about 64x64.
    faithful = Scene(
        "Faithful scale - mid-level combat, 6 enemies + debris",
        [
            Actor("Peppino", 64, 64, frames=900, onscreen=1, resident=False),
            Actor("enemy (goblin)", 32, 32, frames=40, onscreen=4, resident=False),
            Actor("enemy (big)", 48, 48, frames=30, onscreen=2, resident=False),
            Actor("debris/particles", 16, 16, frames=24, onscreen=8, resident=True),
            Actor("combo/score text", 32, 16, frames=16, onscreen=3, resident=True),
        ],
    )

    # A GBA-native scale: smaller cels, tighter frame counts, fewer bodies.
    native = Scene(
        "GBA-native scale - retimed combat, 4 enemies + debris",
        [
            Actor("Peppino", 48, 48, frames=420, onscreen=1, resident=False),
            Actor("enemy (goblin)", 24, 24, frames=24, onscreen=3, resident=False),
            Actor("enemy (big)", 32, 40, frames=20, onscreen=1, resident=False),
            Actor("debris/particles", 16, 16, frames=16, onscreen=6, resident=True),
            Actor("combo/score text", 32, 16, frames=12, onscreen=2, resident=True),
        ],
    )
    return [faithful, native]


def load_scene(path: str) -> Scene:
    with open(path) as f:
        data = json.load(f)
    return Scene(
        data.get("name", path),
        [Actor(**a) for a in data["actors"]],
        data.get("worst_scanline_overlap", 1.0),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", help="JSON scene file")
    ap.add_argument("--hblank-free", action="store_true",
                    help="assume DISPCNT H-Blank interval free (lower OBJ budget)")
    args = ap.parse_args(argv)

    scenes = [load_scene(args.scene)] if args.scene else default_scenes()
    for s in scenes:
        report(s, args.hblank_free)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
