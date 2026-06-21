High-level goals for the Ambition music generator:

We are building a **build-time / authoring-time music generation system**, not a runtime AI system. The shipped game should not run deep models or expensive inference. It should ship compact declarative music specs and/or generated OGG assets, then use those through a unified runtime music abstraction.

I want Ambition to support AI-authored music in a compact, game-native way, where the music could be generated from text/specs instead of shipping large hand-authored binary audio assets for everything.

I like the idea that an LLM could generate or edit a small textual music representation. The spec itself should be small relative to MP3/OGG/WAV assets, easy to version, easy to regenerate, and editable by language models.

The main goal is: **small text specs should be able to generate expressive, adaptive game music assets**.

More specifically:

1. **The YAML/spec should be the source of truth.**
   New music should be authored by changing data, not Python code. The renderer should not contain one-off goblin-composition logic. If we need more expressive capability, add generic renderer/schema features.

2. **The renderer must faithfully obey the YAML.**
   No silent dead config. If `postprocess`, `stem_postprocess`, `group_postprocess`, automation, instruments, gain, EQ, reverb, section structure, or state maps exist in the YAML, either honor them or fail/warn clearly. A big problem right now is that some branches ignored parts of the config.

3. **Preview and runtime assets should match conceptually.**
   The full soundtrack preview is for human listening. The game uses adaptive stems/sections. Those two outputs should be close enough that listening to the preview tells us something true about the in-game mix. If the preview has a master chain but runtime stems do not, that mismatch needs to be deliberate and documented.

4. **Simple music and adaptive music are the same abstraction.**
   “Enter room, play loop” should just be a one-section, one-layer cue. “Goblin battle with intro, wave loops, stems, and outro” is the same cue abstraction with more layers/states. Runtime game code should not care whether the cue came from a single OGG, generated stems, procedural rendering, or future AI-authored assets.

5. **Generated assets should be deterministic and reproducible.**
   Given the same YAML, renderer version, backend, soundfont, and seed, we should get the same assets. Hashes/manifests are good. Runtime-facing installed filenames should be stable so Rust code does not churn when the generated hash changes.

6. **No binary audio assets should be committed.**
   We commit the renderer, YAML specs, manifests/scripts/config, and installer/generation scripts. Generated `.ogg`, `.wav`, `.mid`, etc. stay ignored and are regenerated locally.

7. **The renderer should produce correctly leveled audio directly.**
   We do not want blind post-hoc loudness normalization as a band-aid. If audio is too quiet, buried, underwater, or imbalanced, fix the synth path, mix settings, postprocess chain, or stem rendering so the assets are generated properly the first time.

8. **Fast backend should be useful, but honest.**
   The built-in fallback renderer is important for iteration and CI-ish workflows, but it must either support the same meaningful musical features as the spec or warn/document when it does not. If CC automation, expression ramps, pan automation, or instrument classification are ignored, that is a correctness bug or needs to be explicit.

9. **Audio quality matters.**
   We want something suitable for a professional-ish game prototype: expressive, varied, adaptive, not shrill, not underwater, not clicky, not full of pops, not wildly different in-game versus preview. The goblin tune is a proof of concept, but the renderer should generalize to other moods.

10. **The near-term goal is robust architecture over cleverness.**
    Please favor simple, reliable, testable renderer code over clever special cases. The best next steps are things like:

    * make all render paths share the same postprocess semantics,
    * remove config-ignoring shortcuts,
    * add audits/tests for stem loudness and config usage,
    * fix fallback renderer instrument-family detection,
    * fix drum tails/clicks,
    * make runtime eventually consume cue manifests instead of hardcoded Rust cue gains.

The goblin encounter music is just the current demo asset. Do not optimize the whole system around goblins. Use it as a regression test for the broader goal: declarative, compact, reproducible, adaptive music generation for Ambition.
