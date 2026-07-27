# Code smell backlog

Running log of smells noticed *opportunistically* while doing other work. The
rule: while focused on a big task, don't chase smells — append them here so they
aren't forgotten, and revisit later. Only fix inline when the fix is very clear
AND carries no risk of slowing the main task.

Append-only during runs; triage/prune during cleanup passes (move fixed items to
a Resolved section, condensed to a one-liner with the verdict/commit).

Entry format:

```
## YYYY-MM-DD <short title>
- **Where:** file:line (or module)
- **Smell:** what's wrong, one or two sentences
- **Noticed while:** the task being worked
- **Suggested fix / size:** sketch + rough effort (S/M/L)
```

---

## Open

## 2026-07-26 Group mixdown did its length math in one channel layout and its addition in another
- **Where:** `render/group.py` — `render_group_audio()`, the final mixdown loop (fixed inline).
- **Smell:** `max_len = max(len(x) for x in rendered)` sized the output buffer from the **raw** stems, then added `coerce_stereo(x)`. `coerce_stereo` deliberately accepts channel-first buffers and transposes them, so for a channel-first stem `len(x)` is the CHANNEL count, not the sample count. A single such stem raised `non-broadcastable output operand with shape (1,2) doesn't match the broadcast shape (2,2)` and took down the whole cue (`fast_paced_violin_boss`, 1 of 65). Fixed by coercing once up front and doing all length math on the normalized list. The general shape of the bug: a normalizer that accepts several input layouts creates an obligation to normalize *before* anything reads a shape, and the two call sites here were one line apart.
- **Noticed while:** verifying zero-to-runnable setup from a fresh clone of the ambition superproject (2026-07-26).
- **Suggested fix / size:** DONE (S). Worth a follow-up sweep (S): `rg 'len\(' `over modules that also call `coerce_stereo`, since any other site reading a length off a raw buffer has the same latent bug. A property test over the four layouts `coerce_stereo` documents (1-D, `(N,C)`, `(C,N)`, `C==1`) would pin it cheaply.
- **Fresh-clone relevance:** this fires on the *fallback* path, which is the path any machine without the SFZ corpus always takes — so it is far likelier to bite a new checkout than the authoring machine where the samples resolve.

## 2026-07-26 Active scores hardcode one machine's absolute `/data/audio-tools` paths
- **Where:** `scores/active/*.music.yaml` — 26 references across 10 scores. Two shapes: `render.sfizz.library_roots` listing `/data/audio-tools/sfz` + `/data/audio-tools` (argand_overdrive, argand_waltz, between_objectives, broken_transmitter, fable, flying_spaghetti_monster_roots_{boss,stage}_choir_backing, gradient_ascent, invincible_maryo, something_worth_building), and 8 fully-qualified `sfz:` paths naming exact library layouts, e.g. `broken_transmitter.music.yaml:131` → `/data/audio-tools/sfz/Sonatina/sso-4.0/Sonatina Symphonic Orchestra/Strings - Performance/Violin Solo 1 Sustain (looped).sfz`.
- **Smell:** committed score data encodes one developer's filesystem layout. `configured_sfz_roots()` already supports `AMBITION_AUDIO_TOOLS_ROOT` / `AMBITION_MUSIC_SFZ_ROOTS` and defaults to `/data/audio-tools`, so the roots lists are redundant *and* override the env var (explicit `library_roots` is treated as an override, by design). On any machine without that exact tree these instruments can never resolve — they degrade to fallback silently because all 44 SFZ-referencing instrument backends are `optional: true`. The failure mode is "the song quietly sounds wrong," which is the hardest kind to notice.
- **Noticed while:** verifying zero-to-runnable setup from a fresh clone of the ambition superproject (2026-07-26); confirming whether a missing SFZ corpus blocks asset regen (it does not — it just degrades).
- **Suggested fix / size:** S for the roots lists — delete them from scores and let `AMBITION_AUDIO_TOOLS_ROOT` / the built-in default answer, so one env var relocates the corpus. M for the absolute `sfz:` paths — they should go through `library_ref` like the other instruments do (`strings.violin_solo_marcato`, `freepats.salamander_grand`, …), which is the existing indirection built for exactly this and already resolves against configured roots.

## 2026-07-26 The SFZ corpus is an undeclared prerequisite with no wiring
- **Where:** `download_ambition_audio_tools.sh` (957 lines) vs the superproject's `run_developer_setup.sh` / `regen_music.sh`.
- **Smell:** nothing ever calls this script. Superproject setup apt-installs only the general-MIDI soundfonts, so a fresh clone renders all 10 SFZ-using cues through fallback instruments and no step ever says so. `ROOT` defaults to `/data/audio-tools` and `MODE` to `pro`, matching the hardcoded score paths above — the two halves of the same undocumented convention, neither of which is stated anywhere a newcomer reads. The superproject's `docs/tools/generated-audio-tools.md` doesn't mention the downloader at all.
- **Noticed while:** same fresh-clone verification.
- **Suggested fix / size:** M — derive the instruments the *shipped* scores actually need (every SFZ instrument already names a `library_ref`, so the subset is computable from `scores/active/`) and expose a `--songs-only` mode setup can call, keeping the full `pro`/`all` corpus opt-in for authoring. Pair with a startup notice naming which libraries are missing, so degraded renders announce themselves instead of just sounding thin.
- **The measured subset**, from a full 65-cue render with no corpus present (counts = distinct instruments requesting it): `epiano.rhodes` ×4; `freepats.upright_piano_kw` ×3; `freepats.salamander_grand` ×3; `folk.harp` ×3; `strings.violins_1_marcato` ×2; `strings.violin_solo_marcato` ×2; `strings.celli` ×2; `bass.growly` ×2; then `strings.violins_1`, `strings.violins_2`, `strings.violas`, `strings.violin_solo`, `strings.cello`, `strings.basses`, `viola-SEC-sustain` ×1 each. Roughly a dozen libraries — two pianos, a Rhodes, a harp, and one string section — a far smaller fetch than `MODE=pro`. This list is a measurement, not a design: regenerate it by grepping the render log for `requested SFZ library` rather than trusting it after the scores change.
