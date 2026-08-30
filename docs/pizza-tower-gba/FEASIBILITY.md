# Pizza Tower on the Game Boy Advance — feasibility investigation

Status: investigation / no engine code written yet
Scope: can it be done, by what route, and what breaks first

---

## 1. The short answer

A **1:1 port is impossible**, and not for the reason people assume. It is not
that the GBA lacks storage or sprite memory — the measurements in §4 show art
budgets land at roughly a third of OBJ VRAM and under 6% of a max-size cart.
It is impossible because Pizza Tower is a 60 fps game built on hand-drawn
frames authored for a 960×540 canvas, running on an engine (GameMaker Studio
2) that has no GBA backend and never will. Nothing is transferable except the
design.

A **demake is very feasible**, and unusually so — more feasible than most
"X on GBA" pitches, because the GBA already ran this game's direct ancestor.
Pizza Tower's core loop (explore inward, hit the switch, escape under a timer)
is Wario Land 4's core loop. The hardware has shipped a commercial game of
this exact shape.

Two routes get there. They are not equally good, and the tradeoff is not the
one you would guess:

| | Route A — Wario Land 4 ROM hack | Route B — homebrew from scratch |
|---|---|---|
| Engine | already exists, hardware-proven | you write it |
| Tooling | **this repo** | Butano + devkitARM |
| Time to playable | weeks | months |
| Ceiling | "Pizza Tower–flavoured WL4" | actual PT feel |
| Distribution | patch only; users need their own ROM | free-standing `.gba` |
| Movement fidelity | fights Wario's state machine | whatever you build |

**Recommendation: build Route B, but use Route A first as a two-week
prototype and permanent reference.** Reasoning in §7.

### The legal line

Pizza Tower is a commercial, copyrighted game (Tour de Pizza, 2023). Ripped
sprites, music, or level data cannot be redistributed in any build, on either
route. What is normal and defensible in this space: original art in the game's
style, original music, and — for a ROM hack — distributing an IPS/UPS/BPS
patch rather than a built ROM. That constraint costs nothing technically,
because §4 shows the art has to be redrawn from scratch anyway --
including if you rip every frame first.

---

## 2. What the target actually is

Pizza Tower's identity is four mechanics, in rough order of how much they
matter to whether a build "feels right":

1. **Mach momentum.** Hold run, accumulate speed through three mach tiers,
   and the character stops obeying normal platformer rules — running up walls,
   through enemies, across gaps. Everything else is downstream of this.
2. **Pizza Time.** Hit the pillar at the level's end, a timer starts, the
   level is now a reverse sprint back to the entrance.
3. **Combo scoring.** Chained kills and pickups build a combo that gates rank.
4. **Transformations.** Temporary state swaps with their own movesets.

(1) and (2) are the ones worth building first. (2) is *already implemented in
Wario Land 4*, which is the single most important fact in this document.

---

## 3. What the GBA gives you

ARM7TDMI at 16.78 MHz, no FPU, no cache. 240×160 at 15-bit colour.

| Resource | Budget | Note |
|---|---|---|
| OBJ VRAM | 32 KB | 1024 4bpp 8×8 tiles, tile modes 0–2 |
| BG VRAM | 64 KB | four layers in mode 0 |
| OAM | 128 sprites | max 64×64 each |
| Palettes | 256 BG + 256 OBJ | 4bpp = 16 palettes × 15 usable colours |
| IWRAM | 32 KB | 32-bit bus, zero wait — hot code and state go here |
| EWRAM | 256 KB | 16-bit bus, 2 wait states |
| ROM | 32 MB max | 16-bit bus; also the cap this repo enforces (`ROMUtils.cpp:963`) |
| OBJ render | 1210 cycles/scanline | 954 with H-Blank interval free |
| Audio | 2 DMA PCM + 4 PSG | software mixing, ~10–20% CPU at 16–18 kHz |

The per-scanline OBJ budget is the one that bites. A non-affine sprite costs
one cycle per pixel of its *width* on every scanline it covers; an affine
sprite costs 10 + 2×width. That is a horizontal-density limit, not a sprite
count limit, and it is where a screen full of Pizza Time chaos runs out.

---

## 4. Where the walls actually are

Numbers below are produced by [`budget.py`](./budget.py) in this directory —
re-run it, argue with the assumptions, change the cel sizes.

### Art budgets: comfortable

Peppino at PT's on-screen proportion (~¼ of view height → ~48–64px on a
160px screen), 900 authored frames, streamed cel-by-cel from ROM:

```
OBJ VRAM      19.5 KB / 32.0 KB  (61%)  OK
OAM           18 / 128 entries  OK
ROM (art)     1.8 MB / 32.0 MB cart max  (5.7%)
Worst scanline   512 / 1210 cycles  (42%)  OK
Cel streaming 1.6 KB/frame -> 2,000 cycles (0.71% of a 60 Hz frame)
```

Streaming animation cels from ROM to VRAM by DMA costs **under 1% of a frame**.
This is the finding that makes the project viable: you do not need to fit the
animation set in VRAM, you need to fit *two cels* per animating actor, and the
cart is nowhere near full. Frame count is an art-labour problem, not a
hardware problem.

### Can we skip the redraw and just rip the assets?

No, and the reason is worth being precise about, because the appeal of ripping
is that it saves the art labour — and it doesn't.

Pizza Tower renders at 960x540. Its cels are drawn for that canvas, and a GBA
Peppino is a 48-64px cel: roughly a **3.5-4x linear downscale**. Cartoon art of
this kind carries its readability in a line-weight hierarchy — a heavy outline
holding the silhouette, lighter interior lines, fine detail on top. Divide all
of it by 3.75 and most of that hierarchy lands below one pixel.

[`spritecheck.py`](./spritecheck.py) measures this on any frame you point it at.
On a synthetic cel built at realistic source scale with deliberate 4px/2px/1px
weights:

```
target cel        48 x 48 px   (downscale 3.75x linear, 14.1x area)
    stroke width   source px   at target   survives
            1 px       1,401      0.27px       LOST
            3 px       1,144      0.80px       LOST
            5 px         302      1.33px        yes

  88% of the drawing's ink is drawn at a weight that falls below 1px
  at this scale and cannot survive the downscale.

colour            116 unique opaque colours -> 15 palette entries (8x reduction)
                  mean error 2.9/255 after median-cut
```

Two things worth noting in that output. The **palette reduction is survivable** —
median-cut handles a shading ramp better than intuition suggests, and 15 colours
is less brutal than it sounds. It is the **line weight collapse** that is fatal,
and no filter fixes it: what a human pixel artist does at 48px is re-draw the
silhouette with new, deliberate weights, not shrink the old ones. That is a
redraw by definition.

Run it against real ripped frames before taking this on faith — that is what the
tool is for, and if it reports something different on actual art, this section
is wrong and should be rewritten.

**What ripped assets are genuinely worth having**, and where the time saving
actually is:

- **Reference underlay.** Redrawing at 48px with the original at hand is much
  faster than redrawing from imagination. This is the real win.
- **Animation timing.** Frame counts and per-frame hold durations are directly
  reusable and are a large fraction of what makes the movement read correctly.
- **Palette study.** Which 15 colours a character actually needs, sampled from
  the source rather than guessed.
- **Level metrics.** Room dimensions, platform spacing, and enemy placement in
  world units, which inform the geometry rebuild in the screen-size problem
  above.

On distribution: ripping for reference and private use is ordinary practice.
Shipping a build containing those assets is copyright infringement, and it is
the specific thing that gets fan projects taken down. Tour de Pizza has no
published policy either way that I could find, and a large mod scene exists on
GameBanana and itch.io — but those are mods that require you to already own the
game, which is a materially different legal position from a standalone `.gba`
that does not. Given the above, this costs the project close to nothing: the
cels have to be redrawn regardless, so the redrawn art is original by
construction.

### Prior art: the redraw has partly been done already

Worth correcting an impression the section above could leave. The redraw is not
hypothetical work that nobody has attempted — there is an active community
doing exactly this, and their output is measurable.

The Spriters Resource's [Pizza Tower Customs][ptc] section carries a cluster of
handheld and 8/16-bit demake sheets. In the Wario lineage specifically:
*Peppino (Wario Land 1-Style)*, *Peppino (Wario Land 3-style)*, *Peppino (Game
Boy-Style)*, and *Pizza Box Goblin (Wario Blast-Style)*. Alongside them sit
NES-era Kirby's Adventure-style sheets for Peppino, Fake Peppino, Pepperman,
The Noise, The Vigilante and Pizzaface/Pizzahead, plus SMB1/2/3, Super Mario
World and Super Mario Maker takes.

Measured with `spritecheck.py --sheet`:

| Sheet | Cels | Median cel | Colours | One 4bpp palette? |
|---|---|---|---|---|
| Peppino (Wario Land 1-Style) | 49 | 31 px | 7 | yes, 8 spare |
| Peppino (Wario Land 3-style) | 48 | 26 px | 10 | yes, 5 spare |
| Peppino (Game Boy-Style) | 48 | 16 px | 7 | yes, 8 spare |
| Pizza Box Goblin (Wario Blast-Style) | 4 | 25 px | 4 | yes, 11 spare |

Four things follow, and they cut in different directions.

**The redraw is proven tractable, in this exact aesthetic lineage.** Peppino has
been successfully reduced to a 26-31px Wario-styled cel by people who chose to
do it for fun. That is the strongest available evidence that the art problem is
work rather than risk.

**But these are Game Boy scale, not GBA scale.** They are drawn for 160x144 with
a 4-shade palette. On a 240x160 screen a 31px Peppino reads small — around 19%
of screen height against Pizza Tower's ~25%. Usable, and arguably a *help* given
the sightline problem above, but not the 48-64px cel the budgets in this
document assume.

**They under-use the hardware.** Seven to ten colours where GBA 4bpp allows 15.
Moving GB art to GBA means adding depth rather than removing it, which is the
easy direction — additive work on top of a finished silhouette.

**Frame count is the real gap.** These sheets carry roughly 48 cels: a basic
moveset. A full Peppino needs mach tiers, wall running, grab-and-throw, taunts,
Pizza Time panic and transformations — the several-hundred-frame figure the
budgets model. What exists is on the order of 5-10% of a shipping moveset.

Two practical notes. These sheets are fan works by individual named artists, so
using any of them needs that artist's permission — which is a conversation, not
a blocker, and the same conversation that might recruit them. And the itch.io
project *Pizza Tower On The GBA* (MineKen713, reuploaded by Zee_Scoot) is a
GBA-*styled* GameMaker game for PC, not a GBA build — per its own comments
thread it does not run on the hardware. Useful as a visual target; not a port to
build on.

**This changes the resourcing question from "can it be drawn?" to "who will draw
the other 90%?"** — which is a better question to be stuck on, and points at a
community that has already self-selected for wanting to do it.

[ptc]: https://www.spriters-resource.com/custom_edited/pizzatowercustoms/

### The escape sequence: this is the wall

Pizza Time with eight chasers, sixteen debris pieces, dust, HUD, and four
rotating pickups:

```
Worst scanline  1080 / 1210 cycles  (89%)  OK
                1080 /  954 cycles (113%)  SPRITES WILL DROP  [H-Blank interval free]
```

89% on the worst scanline, with nothing left over, and it **fails outright** if
you enable H-Blank interval free DMA. Two consequences, both design-level:

- The escape sequence needs a hard on-screen actor budget enforced by the
  engine — a spawn cap with priority eviction, not a level-designer promise.
- You likely cannot have both screen-filling chaos *and* HBlank DMA effects.
  Pick one per scene. Decide this before art is authored, not after.

### The screen: the underrated problem

PT shows roughly 320×180 logical pixels. The GBA shows 240×160. You see about
**40% less world**, while the defining mechanic is moving very fast through it.
At mach 3 the player outruns their own sightline and the game becomes unfair.

This is not fixable in code. Mitigations, all of them design work:
- Draw Peppino smaller relative to the screen than PT does (breaks the
  silhouette that makes the art read — a real cost).
- Camera lookahead that leads hard in the direction of travel and zooms out
  its dead zone with speed.
- Rebuild level geometry with longer sightlines and fewer blind commitments.

Budget real time for this. It is the difference between a demake that plays
and one that only looks right in screenshots.

### CPU: tight but tractable

Physics and collision for one fast actor plus a few dozen entities fits in
16.78 MHz if the hot paths are ARM-mode code in IWRAM and all maths is fixed
point. The mach state's swept collision against a large tilemap is the part to
prototype early — a fast actor needs continuous collision, not per-frame point
tests, or it tunnels through walls.

### Audio: expect to lose the most here

PT's soundtrack is dense, layered, live-feeling instrumentation. The GBA gives
you two DMA PCM channels mixed in software. Tracker modules (`.xm`/`.mod`) via
Maxmod are the realistic target. The music will be recognisably arranged, not
reproduced. Plan for an original chiptune arrangement, not a conversion.

---

## 5. Route A — Wario Land 4 ROM hack, using this repo

**This repository is a far more capable base than "a level editor."**

What WL4Editor already provides:

- **Level authoring**: tilemap layers 0–3, tilesets (`Tile8x8DefaultNum 0x600`,
  `Tile16DefaultNum 0x300` — `LevelComponents/Tileset.h:4`), entity placement,
  doors, camera limiters, animated tile groups, palettes.
- **Sprite/OAM editing**: `Dialog/SpritesEditorDialog.*` edits entity OAM
  layouts directly; `LevelComponents/Entity.h` carries per-entity OAM tables.
- **A full custom-code patch system** — the important one. `PatchUtils.cpp`
  compiles C with `arm-none-eabi-gcc -mcpu=arm7tdmi -mthumb -mthumb-interwork
  -O2 -mlong-calls` (`PatchUtils.cpp:256`), links it to a chosen ROM address,
  writes it into free space as a tracked chunk, and hooks it in by overwriting
  bytes at a hook address with a `BL` into Thumb mode.
- **A symbol map into the existing engine.** The generated linker script
  exports known ROM functions to your C — e.g. `memcpy = 0x80950D9;`
  (`PatchUtils.cpp:320`) — plus user-registered `gConsts`/`gFunctions`. You can
  call the shipped WL4 engine from new C code.
- **ROM expansion to 32 MB** with a free-space chunk allocator; the base ROM's
  free region starts at `0x78F970` (`WL4Constants.h:46`).
- **A 106-method scripting interface** (`ScriptInterface.h`) for automating
  bulk level/asset import — essential if you are converting many rooms.

So Route A is not "re-skin Wario." It is "write new gameplay code in C against
a shipping GBA platformer engine, with an editor for all the content."

**What you get for free:** collision, camera, entity system, level streaming,
sound driver, save system, and — critically — the escape sequence. WL4's frog
switch starts a countdown and turns the level into a sprint back to the
entrance. That *is* Pizza Time. It is already written, already tuned, already
runs at speed on hardware.

**What fights you:**
- Wario's moveset overlaps Peppino's but is not it. Dash attack, ground pound,
  and wall jump exist; mach tiers, wall running, grab-and-throw, and
  taunt-cancelling do not. Retrofitting these means reverse-engineering
  Wario's state machine and hooking it — the hardest, least predictable work
  in the whole project, against partially documented code.
- The shared sprite tile budget is tight (`SpritesBasicElementTiles`, 0x3000 =
  12 KB — `WL4Constants.h:28`); a bigger, more animated protagonist needs a new
  streaming path bolted on.
- Every structural change is a negotiation with someone else's engine. The
  ceiling is real, and you find it late.

**Prerequisite:** a specific WL4 ROM (the editor loads `.gba` via
`WL4EditorWindow::OpenROM`, `WL4EditorWindow.cpp:206`) and a devkitARM/EABI
toolchain for the patch system (`PatchUtils::VerifyEABI`).

---

## 6. Route B — homebrew from scratch

Butano (modern C++ GBA engine, actively maintained) on devkitARM. It handles
sprite/BG/palette allocation, asset import, and Maxmod audio, and leaves the
game to you.

**You get:** total control of the movement model — which is the entire point,
since mach momentum *is* the game. A clean `.gba` you can distribute. No
reverse engineering. No base ROM. Open source if you want it.

**You pay for:** the whole engine. Fixed-point physics, swept tilemap
collision, camera, entity pooling, animation streaming, level format and
loader, save, escape-timer state, scoring. All of it is known, solved work with
good references (Tonc, Butano's samples) — it is just work, several months of
it before anything is fun.

Butano's own documented limits are consistent with §4: sprite tiles allocate
from the end of VRAM, hidden sprites cost nothing, and the scanline pixel limit
is the thing that bites — same conclusion, reached independently.

---

## 7. Recommendation

**Build Route B. Spend two weeks on Route A first.**

The reasoning is that the two routes fail in opposite places. Route A's risk
is concentrated in one unpredictable task (bending Wario's state machine into
Peppino's) that you cannot estimate until you are deep in it, and if it goes
badly you have burned months and still have Wario's ceiling. Route B's risk is
spread across many predictable tasks that are individually boring and
collectively months long — but none of them can surprise you.

Route A is nonetheless worth two weeks up front, for three concrete returns:

1. **A feel target you can measure, not guess.** WL4's physics constants are
   sitting in a ROM you can read. Wario's acceleration, friction, jump arc,
   and dash thresholds are the closest shipping reference to what Peppino
   should feel like on this hardware. Extract them and seed Route B's physics
   with real numbers.
2. **A playable escape sequence in days.** Re-skin one WL4 level, run its frog
   switch escape, and you have Pizza Time running on hardware before you have
   written a line of engine code. That answers "is this fun at 240×160" — the
   question that actually decides the project — for two weeks of work instead
   of three months.
3. **This repo's tooling stays useful either way.** The scripting interface
   and tileset/OAM editors are a working asset pipeline you can point at your
   own format later.

If the two-week prototype shows the escape sequence is *more* fun than
expected on a small screen, Route A becomes a legitimate shipping target and
the recommendation flips. That is exactly the kind of thing a prototype should
be allowed to decide.

---

## 8. Roadmap

**Phase 0 — decide the thing that decides everything (2 weeks, Route A).**
Re-skin one WL4 level in this editor. Run its escape sequence. Play it on real
hardware or a cycle-accurate emulator (mGBA). Answer: does a Pizza Time sprint
survive a 240×160 window? Extract WL4's physics constants while you are in
there.

**Phase 1 — vertical slice (Route B, ~6 weeks).** Butano project. Peppino runs,
jumps, and reaches mach 3 across one hand-built test room at a locked 60 fps.
No enemies, no art beyond placeholder cels, no audio. Success condition: mach
movement feels right, and swept collision never tunnels. This is the whole
project's technical risk, isolated.

**Phase 2 — the loop.** Escape timer, one enemy type, combo counter, level
exit and rank screen. One complete level, start to finish. Now it is a game.

**Phase 3 — content and art scale-up.** Real art at the cel sizes §4 validated.
Enforce the escape-sequence actor cap in the engine, with the spawn priority
eviction — build it now, before designers rely on its absence.

**Phase 4 — audio.** Original tracker arrangements via Maxmod. Budget CPU for
it from Phase 1 onward rather than discovering the cost at the end.

**Phase 5 — polish.** Transformations, remaining enemy roster, additional
levels, save/rank persistence.

---

## 9. Open questions

- Which levels? A five-level demake is achievable; the full game is not, at
  any realistic scale of effort.
- Who draws it? Art is the dominant cost on both routes and the one thing no
  amount of engineering removes. This is the resourcing question to answer
  before Phase 1, not after.
- Original characters, or Peppino? Affects distribution more than code.
- Real hardware target — flashcart, or emulator-only? Decide early; it
  constrains ROM size and audio sample rates.
