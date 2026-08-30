#!/usr/bin/env python3
"""
Check whether a source sprite frame survives conversion to GBA scale.

Point this at a ripped/high-res animation cel and it reports what actually
happens to that frame on the way to a 4bpp GBA sprite: how much the linework
has to shrink, which strokes fall below one pixel, how many colours are lost
to a 15-entry palette, and whether the result lands on the 8px tile grid.

    ./spritecheck.py peppino_idle_00.png            # target 48px tall cel
    ./spritecheck.py frame.png --target-h 64
    ./spritecheck.py --demo                         # synthetic frame, no assets needed

The verdict is deliberately mechanical: it measures the source and does the
arithmetic. It does not know whether the result looks good -- but if the
linework collapses and the palette error is large, no amount of tooling
rescues it and the frame has to be redrawn by hand.
"""

import argparse
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("needs Pillow:  pip install Pillow")


def pixels(img):
    """Flat pixel list, across Pillow versions."""
    getter = getattr(img, "get_flattened_data", None) or img.getdata
    return list(getter())

# GBA 4bpp sprites: 16 palette entries, one spent on transparency.
GBA_PALETTE_COLOURS = 15
TILE = 8
# 5-bit-per-channel display: the 32 values a GBA channel can actually take.
GBA_CHANNEL_LEVELS = [round(n * 255 / 31) for n in range(32)]


def stroke_widths(mask, w, h, max_w=12):
    """Histogram of ink stroke widths, by repeated erosion.

    A pixel surviving k erosions sits at the core of a stroke at least
    2k+1 wide, so the count that dies at round k tells us how much of the
    drawing is drawn at that weight.
    """
    cur = mask
    hist = {}
    prev_count = sum(cur)
    for k in range(1, max_w + 1):
        nxt = bytearray(w * h)
        for y in range(1, h - 1):
            row = y * w
            for x in range(1, w - 1):
                i = row + x
                if cur[i] and cur[i - 1] and cur[i + 1] and cur[i - w] and cur[i + w]:
                    nxt[i] = 1
        count = sum(nxt)
        hist[2 * k - 1] = prev_count - count      # strokes of width 2k-1
        prev_count = count
        cur = nxt
        if count == 0:
            break
    if prev_count:
        hist[f">{2 * max_w}"] = prev_count
    return hist


def ink_mask(img, threshold=70):
    """Dark pixels over an opaque background -- the drawing's linework.

    The threshold matters: set it too high and the dark side of a shaded fill
    is counted as ink, which inflates the apparent stroke widths. If the ink
    total looks implausibly large for the drawing, lower --ink-threshold.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    m = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 128 and (r * 299 + g * 587 + b * 114) // 1000 < threshold:
                m[y * w + x] = 1
    return m, w, h


def opaque_colours(img):
    rgba = img.convert("RGBA")
    counts = {}
    for r, g, b, a in pixels(rgba):
        if a > 128:
            counts[(r, g, b)] = counts.get((r, g, b), 0) + 1
    return counts


def snap_gba(c):
    return min(GBA_CHANNEL_LEVELS, key=lambda v: abs(v - c))


def palette_loss(img, colours=GBA_PALETTE_COLOURS):
    """Mean per-pixel colour error after median-cut to `colours`, then after
    snapping those to the GBA's 5-bit channel grid."""
    rgb = img.convert("RGBA")
    bg = Image.new("RGB", rgb.size, (255, 0, 255))
    bg.paste(rgb, mask=rgb.split()[3])
    q = bg.quantize(colors=colours, method=Image.MEDIANCUT).convert("RGB")

    src, dst = pixels(bg), pixels(q)
    alpha = pixels(rgb.split()[3])

    err_q = err_g = n = 0
    for (s, d, a) in zip(src, dst, alpha):
        if a <= 128:
            continue
        n += 1
        err_q += sum(abs(s[i] - d[i]) for i in range(3)) / 3
        err_g += sum(abs(s[i] - snap_gba(d[i])) for i in range(3)) / 3
    return (err_q / n if n else 0, err_g / n if n else 0, n)


def make_demo(path):
    """A synthetic cartoon cel at realistic source scale.

    Pizza Tower renders at 960x540 and its protagonist stands roughly a
    quarter of that height, so a source cel is on the order of 180px -- not
    the 400px+ a naive test would use. Line weights here are the ones
    hand-drawn cartoon art actually relies on: a 4px outline carrying the
    silhouette, 2px interior lines, 1px detail. Soft shading is included so
    the palette measurement has something to lose.
    """
    W = H = 180
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = img.load()
    ink = (20, 18, 26, 255)

    def disc(cx, cy, r, col):
        for y in range(max(0, cy - r), min(H, cy + r + 1)):
            for x in range(max(0, cx - r), min(W, cx + r + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    px[x, y] = col

    def shaded_disc(cx, cy, r, base, lift=58):
        """Body fill with a soft light-to-dark ramp -- the kind of shading
        that turns into dozens of distinct colours in a real cel."""
        for y in range(max(0, cy - r), min(H, cy + r + 1)):
            for x in range(max(0, cx - r), min(W, cx + r + 1)):
                dx, dy = x - cx, y - cy
                if dx * dx + dy * dy <= r * r:
                    t = max(0.0, min(1.0, (1 - (dx / r) * .55 - (dy / r) * .8) / 2))
                    px[x, y] = tuple(
                        min(255, int(base[i] + lift * t)) for i in range(3)) + (255,)

    disc(90, 95, 68, ink)                     # 4px outline
    shaded_disc(90, 95, 64, (198, 62, 44))    # shaded body
    disc(90, 68, 42, ink)
    shaded_disc(90, 68, 38, (196, 158, 112))  # shaded head
    for cx in (76, 104):                      # 2px interior lines
        disc(cx, 63, 9, ink)
        disc(cx, 63, 7, (250, 250, 250, 255))
        disc(cx, 65, 4, ink)
    for i in range(-20, 21):                  # 1px detail strokes
        px[90 + i, 84 + int(6 * (1 - (i / 20.0) ** 2))] = ink
    for i in range(34):
        px[68 + i, 116] = ink
        px[68 + i, 128] = ink
    img.save(path)
    return path


def report(path, target_h, ink_threshold=70):
    img = Image.open(path)
    sw, sh = img.size
    scale = sh / target_h
    target_w = round(sw / scale)

    print(f"\nsource            {path}")
    print(f"                  {sw} x {sh} px")
    print(f"target cel        {target_w} x {target_h} px   "
          f"(downscale {scale:.2f}x linear, {scale*scale:.1f}x area)")

    tw = -(-target_w // TILE) * TILE
    th = -(-target_h // TILE) * TILE
    waste = (tw * th - target_w * target_h) / (tw * th) * 100
    print(f"8px tile grid     {tw} x {th} = {(tw//TILE)*(th//TILE)} tiles, "
          f"{waste:.0f}% of the allocation is padding")

    mask, w, h = ink_mask(img, ink_threshold)
    ink_px = sum(mask)
    if ink_px:
        hist = stroke_widths(mask, w, h)
        print(f"\nlinework          {ink_px:,} ink px")
        print(f"{'stroke width':>16}{'source px':>12}{'at target':>12}{'survives':>11}")
        lost = kept = 0
        for k, v in sorted(hist.items(), key=lambda kv: (isinstance(kv[0], str), kv[0])):
            if not v:
                continue
            src_w = int(str(k).lstrip(">"))
            out_w = src_w / scale
            ok = out_w >= 1.0
            lost += 0 if ok else v
            approx = ">" if str(k).startswith(">") else ""
            print(f"{str(k) + ' px':>16}{v:>12,}{approx + f'{out_w:.2f}':>10}px"
                  f"{('yes' if ok else 'LOST'):>11}")
        pct = 100 * lost / ink_px
        print(f"\n  {pct:.0f}% of the drawing's ink is drawn at a weight that "
              f"falls below 1px\n  at this scale and cannot survive the downscale.")
    else:
        print("\nlinework          no dark ink detected (threshold too low?)")
        pct = 0.0

    counts = opaque_colours(img)
    eq, eg, n = palette_loss(img)
    print(f"\ncolour            {len(counts):,} unique opaque colours "
          f"-> {GBA_PALETTE_COLOURS} palette entries "
          f"({len(counts)/GBA_PALETTE_COLOURS:.0f}x reduction)")
    print(f"                  mean error {eq:.1f}/255 after median-cut, "
          f"{eg:.1f}/255 after snapping to the GBA's 5-bit channels")

    print("\nverdict")
    hard = pct > 25 or eq > 18
    if hard:
        print("  Not convertible by downscaling. The frame is a usable reference")
        print("  underlay, but the cel itself has to be redrawn at target size.")
    else:
        print("  Borderline -- worth an eyeball test on a real frame before")
        print("  committing either way.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", help="source sprite frame (PNG)")
    ap.add_argument("--target-h", type=int, default=48,
                    help="target cel height in px (default 48)")
    ap.add_argument("--demo", action="store_true",
                    help="generate and analyse a synthetic cartoon cel")
    ap.add_argument("--ink-threshold", type=int, default=70,
                    help="luminance below which a pixel counts as linework "
                         "rather than shading (default 70)")
    a = ap.parse_args(argv)

    if a.demo:
        path = make_demo("_spritecheck_demo.png")
        print("synthetic cel written to _spritecheck_demo.png "
              "(180px source, 4px outline, 2px interior, 1px detail, soft shading)")
        return report(path, a.target_h, a.ink_threshold)
    if not a.image:
        ap.error("give an image, or use --demo")
    return report(a.image, a.target_h, a.ink_threshold)


if __name__ == "__main__":
    sys.exit(main())
