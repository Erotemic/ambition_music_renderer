
Instructions for: Ubuntu 24.04 and Ardour 9.7-312-g97a96e7c24

sudo apt update

sudo apt install -y \
    build-essential \
    pkg-config \
    python3 \
    gettext \
    intltool \
    itstool \
    ladspa-sdk \
    libarchive-dev \
    libasound2-dev \
    libaubio-dev \
    libboost-dev \
    libcairomm-1.0-dev \
    libcurl4-openssl-dev \
    libcwiid-dev \
    libdbus-1-dev \
    libfftw3-dev \
    libfluidsynth-dev \
    libglibmm-2.4-dev \
    libgtkmm-2.4-dev \
    libhidapi-dev \
    libjack-jackd2-dev \
    liblilv-dev \
    liblo-dev \
    liblrdf0-dev \
    libltc-dev \
    libpangomm-1.4-dev \
    libpulse-dev \
    libqm-dsp-dev \
    libreadline-dev \
    librubberband-dev \
    libsamplerate0-dev \
    libsigc++-2.0-dev \
    libsndfile1-dev \
    libsuil-dev \
    libtag1-dev \
    libusb-1.0-0-dev \
    libwebsockets-dev \
    libxinerama-dev \
    libxrandr-dev \
    lv2-dev \
    vamp-plugin-sdk


cd ~/code/ardour

/usr/bin/python3 ./waf configure \
    --optimize \
    --cxx17 \
    --ptformat \
    --with-backends=jack,alsa,pulseaudio,dummy \
    --libjack=weak

/usr/bin/python3 ./waf -j"$(nproc)"


cd ~/code/ardour/gtk2_ardour
./ardev



sudo dpkg-reconfigure -p high jackd2

## Ambition MusicIR editing workflow

Ardour is the primary DAW target. Keep `.ardour` session state outside the
MusicIR authority boundary: the neutral MIDI + sidecar in the generated session
remains the eventual reconciliation baseline.

### Forward export: preferred path

From the renderer repo, create an editable Ardour session directly:

```bash
python -m ambition_music_renderer cue ardour_export \
    scores/experiments/standing_on_shoulders_extended_boss.music.yaml \
    --destination /tmp/standing-on-shoulders-extended-ardour
```

Then open:

```bash
cd ~/code/ardour/gtk2_ardour
./ardev /tmp/standing-on-shoulders-extended-ardour/standing_on_shoulders_extended_boss.ardour
```

Expected session shape:

- one MIDI track per `CompiledScore` instrument, using its semantic name;
- Python writes exactly one ACE Reasonable Synth per MIDI track as the validated audible scaffold;
- unless `--audition-only` is used, `ardour_export` auto-detects Ardour's `arlua` frontend and asks libardour to replace that one synth with sfizz or ACE Fluid Synth on resolvable tracks;
- unsupported/unresolved tracks stay on the known-good ACE Reasonable Synth rather than entering a broken plugin chain;
- normal exports route tracks through semantic `AMB Group <group>` buses, then `AMB Composition`, then Master;
- the track fader carries instrument `mix_gain_db`; group/composition fader automation carries section `stem_mix_db` / `mix_gain_db` transitions;
- supported canonical group/master `ProcessingPlan` operations appear as editable processors on group buses / Master, in renderer order;
- **no instrument plugin on Master**;
- section markers from compiled form;
- current Ardour audio backend/device left to Ardour rather than serialized from another machine;
- neutral MIDI + `.musicir-interchange.json` under `ambition/`; and
- `.ambition-ardour-export.json` containing resolved renderer instrument plans plus processing fidelity/omission diagnostics.

The current adapter supports fixed tempo/meter sessions. It does **not** hand-write
SFZ/SoundFont LV2 state. Instead `ambition/apply_real_instruments.lua` is run by
Ardour's command-line Lua/libardour frontend, which creates the plugin, sets its
path-valued asset property, and serializes the resulting session itself. Pass
`--ardour-lua <path>` if auto-detection does not find `~/code/ardour/gtk2_ardour/arlua`.

Mix/processing transport is a second libardour transaction. The static routing
and gain riders are written into the timing-preserving scaffold from compiled
metadata; `ambition/apply_processing.lua` then instantiates the editable DSP
processors selected from canonical `ProcessingPlan` objects. Python verifies and
grafts only those processors back onto the pre-processing session so an Ardour
save cannot mutate MIDI timing. If processing realization fails, the session
retains its verified real instruments and mix-routing scaffold. Use
`--no-processing` to skip this pass. Current explicit gaps are transient-tame,
stereo-width, time-varying canonical section-bus DSP, soft
limiter/normalization/loudness, and exact outer wet/dry wrappers around
otherwise-supported plugins.

Do not overwrite a session after making DAW edits.

For note-composition review, export a separate `--audition-only` session. That
keeps every track on the validated Reasonable Synth and is currently the safest
neutral pitch/rhythm audit surface. Instrument A/B should be implemented as a
parallel/replace workflow, not by chaining two instrument plugins in series.

If playback is silent, first verify that MIDI-track meters and Master move. The
audio backend can be ALSA or PulseAudio; on the maintainer setup PulseAudio maps
cleanly to the default speaker output. A synth belongs on MIDI tracks, not Master.

### Neutral/manual path and later round trip

```bash
python -m ambition_music_renderer cue daw_export <cue> --destination /tmp/<cue>-daw
# Manual Ardour import, then edit/export MIDI.
python -m ambition_music_renderer cue daw_reconcile <cue> \
    --midi /tmp/<cue>-edited.mid \
    --manifest /tmp/<cue>-daw/<cue>.musicir-interchange.json \
    --output /tmp/<cue>-reconciliation.json
python -m ambition_music_renderer cue daw_apply <cue> \
    --midi /tmp/<cue>-edited.mid \
    --manifest /tmp/<cue>-daw/<cue>.musicir-interchange.json \
    --output /tmp/<cue>.daw.music.yaml \
    --report /tmp/<cue>-apply.json
```

Round-trip work is intentionally secondary to exercising the forward Ardour
editing workflow.
