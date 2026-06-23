# SFZ instrument notes (provisional — NOT authoritative)

Working notes on which SFZ libraries (by `library_ref` alias) render audibly
through `sfizz_render` vs. come out **silent**, gathered while reworking
`solo_soar`. This is a *memory aid to avoid the broken ones until we dig in* —
**not** a verdict that a library is bad. In several cases the samples are
present and the failure is almost certainly our setup (path resolution,
keyswitch/CC, or a missing sub-pack), so treat "doesn't work" as "doesn't work
*the way we currently call it*."

Probed on this machine against `/data/audio-tools/sfz` with a plain
`sfizz_render --sfz X --midi Y --wav Z` over a small note/velocity sweep. RMS is
of that test render; below ~ -55 dB = effectively silent.

## Render audibly (safe to use)

| alias | library | notes |
|---|---|---|
| `guitar.clean` / `guitar.hollowbody` / `guitar.electric_lead` | Karoryfer Black & Green Guitars | all resolve to the green keyswitch program; clean. |
| `bass.growly` | Karoryfer Growlybass | loud, present. |
| `freepats.salamander_grand` | FreePats Salamander Grand Piano | clean. |
| `freepats.upright_piano_kw` | FreePats Upright Piano KW | clean. |
| `drums.gogodze` | Karoryfer Gogodze Phu Vol II | kit renders. |
| `strings.cello` | Karoryfer BigcatCello | bowed velocity-layer program renders. |
| `strings.cyborg` | Karoryfer String Cyborgs | warm string-synth pad; loud (-23 dB). |
| `folk.harp` | Etherealwinds Harp | clean. |
| `folk.banjo` | Ganjo | renders in isolation BUT was silent in the `solo_soar` context — suspect a played-range / keyswitch issue, not a dead library. |

## Render silent the way we call them (avoid for now)

| alias | library | what we saw | likely cause (unconfirmed) |
|---|---|---|---|
| `guitar.acoustic` | Karoryfer Shinyguitar | 272 samples "could not resolve" → all regions dropped → silence | Samples ARE on disk (846 files under `Samples/`), but the `.sfz` references them with `acoustic\…` and **no `default_path`**, and the regions look CC100-gated. Almost certainly fixable by injecting a default path + sending CC, not a missing install. |
| `brass.tuba` | Karoryfer WarTuba | 52 samples missing → silence | same family of path/sample issue as Shinyguitar; not dug in. |
| `vpo.violin` / `vpo.strings` / `vpo.brass` / `vpo.choir` | Virtual Playing Orchestra | 18–64 samples "could not resolve" → silence | the SFZ points at `..\libs\NoBudgetOrch\…` samples that are **not installed** — a genuine missing sub-pack, fixable by downloading it. |

## How the renderer copes (so a bad pick is loud-fails, not silent)

`render_group_audio` now treats a silent SFZ render of a noted instrument as a
failure: it **warns** (with the instrument + SFZ path) and falls back to
`fallback_backend` (FluidR3 GM via pretty-midi), so a broken library degrades to
audible-GM instead of dropping the whole stem. `render.strict_backends: true`
turns those into hard errors instead. So when picking instruments: if a stem
sounds like plain GM and the render log warns "rendered SILENCE … using
'pretty-midi' fallback", that alias is in the avoid list above.

## To revisit when we dig in

- Inject `default_path` for the Karoryfer Programs/+Samples/ split libraries
  (Shinyguitar, WarTuba) and check whether they then trigger.
- Handle keyswitch/CC-gated programs (send the selecting keyswitch / CC100).
- Install the VPO `NoBudgetOrch` sample sub-pack.
- Figure out the `folk.banjo` (Ganjo) range/keyswitch so it isn't silent in context.
