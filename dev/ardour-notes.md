
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
- resolved SFZ tracks use sfizz and resolved SoundFont/GM tracks use ACE Fluid Synth;
- an inactive ACE Reasonable Synth follows each resolved real instrument as a neutral MIDI-audit fallback;
- stereo audio from each MIDI track into Master;
- **no instrument plugin on Master**;
- section markers from compiled form;
- current Ardour audio backend/device left to Ardour rather than serialized from another machine;
- neutral MIDI + `.musicir-interchange.json` under `ambition/`; and
- `.ambition-ardour-export.json` containing resolved renderer instrument plans.

The current adapter supports fixed tempo/meter sessions. It writes SFZ/SoundFont
plugin state into Ardour's `plugins/<processor-id>/state1/state.ttl` directories,
using the canonical resolved local asset paths. It does not yet recreate renderer
processing/mastering. Do not overwrite a session after making DAW edits.

For note-composition review, either export with `--audition-only`, or bypass the
real sfizz/ACE Fluid Synth processor on one track and activate the Reasonable Synth
behind it. The MIDI stays fixed while the listening timbre changes, which makes
instrument swapping and neutral pitch/rhythm review cheap inside Ardour.

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
