# You Are Too Slow — matched call/response cadence

This overlay is relative to `tools/ambition_music_renderer`.

Changes only `scores/active/you_are_too_slow.music.yaml`:

- slows the cue from 170 BPM to 160 BPM;
- lengthens `dash_hook` from 3.5 to exactly 4.5 beats;
- ends the call with F#5 -> B5, with B5 landing on the following B chord;
- trims the reply's final duration from 0.75 to 0.50 beats so both call and
  response are exactly 4.5 beats;
- preserves all other notes, orchestration, register cleanup, and loudness trim.
