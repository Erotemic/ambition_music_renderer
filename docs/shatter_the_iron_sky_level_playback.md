# Shatter the Iron Sky: loopable level cue

MusicIR score: `scores/active/shatter_the_iron_sky.music.yaml`.

The source of truth is the score. No new sampled instruments are introduced.
The 168 BPM lower-octave FSBS motif, existing rhythm tones, dual guitar support,
Growlybass, choir, and unchanged high-register shred solo are preserved. Five
new eight-bar developments extend the musical form without changing its tempo.

## Runtime musical shape

| Playback section | Score bars (1-based, end exclusive) | Bars | Time | Loop? |
| --- | --- | ---: | ---: | --- |
| `intro` | 1–9 | 8 | 0:11.429 | No |
| `combat` | 9–113 | 104 | **2:28.571** | Yes |
| `outro` | 113–121 | 8 | 0:11.429 | No |

The entire rendered score, including the one-shot intro and outro, is about
**2:51.429**. The requested **2:20–2:40** target refers to `combat`, not the
full audition preview.

Order for ordinary gameplay: **intro → combat → combat → ... → outro**.
All transitions are quantized to a musical boundary. `combat` is designed to
resolve its final B7(♭9) into the downbeat E5 power chord at its start, while
`outro` replaces that repeat with a final E5 statement and ringing decay.

The final **two** bars of `intro` are byte-for-byte identical in source events
to the final two bars of `combat` on **all twelve instruments**. Thus intro →
combat and combat → combat approach the downbeat via the same turnaround.
Every eight-bar combat subsection also ends on B7(♭9), permitting phrase-
quantized handoffs when the game's adaptive-section player uses the
`adaptive/<form_section>/<form_section>.full.ogg` assets.

## Form / orchestration

1. `intro`: sparse, ominous choir and E-pedal; builds to the exact loop turnaround.
2. `iron_gate`: original power-chord announcement.
3. `shattered_orders`: original synchronized guitar gallop.
4. `war_machine`: original cathedral proclamation.
5. `black_iron_procession` **new**: staggered chugs, choir downbeats, and accented bass root answers.
6. `counterattack`: original brutal thrash.
7. `serpent_circuit` **new**: chromatic sixteenth-note chugs, strategic stops, and double-kick drive.
8. `the_false_triumph`: original half-time contrast.
9. `cathedral_of_ash` **new**: ominous choir and sustained half-time chords building to marching kicks.
10. `breaking_the_columns`: original eight-bar high-register shred solo.
11. `iron_crown_ascent` **new**: return to low melody, answering the solo without extending it.
12. `no_throne`: original evil proclamation/reprise.
13. `final_decree` **new**: riff-driven final escalation with choir punctuation.
14. `iron_sky_falls`: original B7(♭9) turnaround leading into the loop's E5 downbeat.
15. `outro`: distinct exit cadence; final low E5 with approximately one second of decay after its sustained notes.

## Exports, publishing and game wiring

Run the normal cue renderer with `--render_audio_mode=full`. It writes both
`adaptive/` form-section audio and `playback/` runtime-layer files. The
`playback` mapping names four independent layers: `bed`, `hook`, `war_machine`,
`dread`. Each has an `intro`, `combat`, and `outro` playback OGG. The full
`cue bundle --zip` now includes those playback OGGs as well as the standard
preview and adaptive OGGs.

Use `--publish` once the sound is approved to put these at stable paths under:

```
${AMBITION_MUSIC_PUBLISH_ROOT}/shatter_the_iron_sky/
  playback/intro/intro.{bed,hook,war_machine,dread}.ogg
  playback/combat/combat.{bed,hook,war_machine,dread}.ogg
  playback/outro/outro.{bed,hook,war_machine,dread}.ogg
  adaptive/iron_gate/iron_gate.full.ogg
  ...
```

The renderer/publisher can generate and install these files. **Game-state
logic must still select sections and trigger exits**; rendering doesn't by
itself wire transitions to level events. Using the monolithic `combat` playback
file means an exit transition can happen at its end (up to 2:28.6 away). For
more responsive exits, the existing adaptive form-section exports provide
**eight-bar handoff opportunities (at most 11.43 seconds apart)**. Their
seams should be auditioned before using arbitrary handoffs; the harmonic
B7(♭9) → Em connection is deliberately provided, but it does not guarantee
sample-exact reverb-tail continuity.

The renderer currently applies a 1 ms fade-in and 4 ms fade-out to each
playback-layer section. Validate the rendered OGG seam by listening to
`combat` tail → `combat` head, intro → combat, and combat → outro in the
runtime mixer. For full-section mastered `adaptive/` files, use a short
bar-aligned de-click/crossfade (avoid washing out the first kick). Do not
assume the symbolic score alone proves a transparent audio seam.

## Render

```bash
cd ~/code/ambition
source scripts/lib/asset_roots.sh
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle \
  shatter_the_iron_sky --backend=pretty-midi --force \
  --render_audio_mode=full --audition_stems --jobs=2 --zip
```

Optional `--publish` copies the generated full mix and runtime files into the
game's generated music-asset tree.
