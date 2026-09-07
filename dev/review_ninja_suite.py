#!/usr/bin/env python3
"""Render the ninja suite and package reproducible source/loop/listening evidence.

Run from the renderer checkout with its normal uv environment. --score-only
needs the compiler dependencies but no sample libraries or synthesis tools.
This script never publishes, modifies scores, or substitutes instruments.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CUES = ("nine_lives_at_midnight", "the_last_lantern")
AUDIO_SUFFIXES = {".ogg", ".wav", ".flac", ".mp3", ".mid", ".midi", ".npy"}


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf8")


def run_logged(command: list[str], path: Path) -> None:
    print("[ninja review] " + " ".join(command), flush=True)
    with path.open("w", encoding="utf8") as log:
        with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors="replace") as process:
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            code = process.wait()
    if code:
        raise RuntimeError(f"render/bundle exited {code}; see {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cue", choices=CUES, action="append", help="review only this cue; repeat for both")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = (args.output or ROOT / "generated" / "ninja_suite_reviews" / stamp).resolve()
    # A new directory prevents a failed run from packaging an older good render.
    output.mkdir(parents=True, exist_ok=False)
    from ambition_music_renderer.audit.composition_quality import composition_quality_report
    from ambition_music_renderer.audit.determinism import compilation_determinism_report
    from ambition_music_renderer.audit.loop_review import audio_loop_report, score_loop_report
    from ambition_music_renderer.musicir.compile import compile_score
    from ambition_music_renderer.musicir.model import compiled_score_fingerprint
    from ambition_music_renderer.render.generated_layout import latest_manifest_in_roots
    from ambition_music_renderer.validation.v3 import diagnose_v3_spec
    import yaml

    results, package_roots = [], []
    for cue in dict.fromkeys(args.cue or CUES):
        work = output / cue
        evidence = work / "evidence"
        evidence.mkdir(parents=True)
        package_roots.append((evidence, cue + "/evidence"))
        bundle_root = work / "bundles"
        source = ROOT / "scores" / "active" / f"{cue}.music.yaml"
        result = {"cue": cue, "status": "failed", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        results.append(result)
        try:
            shutil.copy2(source, evidence / source.name)
            spec = yaml.safe_load(source.read_text(encoding="utf8"))
            diagnostics = diagnose_v3_spec(spec)
            save_json(evidence / "validation.json", [d.as_dict() for d in diagnostics])
            if any(d.severity == "error" for d in diagnostics):
                raise RuntimeError("score schema validation failed; inspect validation.json")
            compiled = compile_score(spec)
            fingerprint = compiled_score_fingerprint(compiled)
            result["compiled_fingerprint"] = fingerprint
            loop_report = score_loop_report(compiled)
            determinism = compilation_determinism_report(spec, rounds=3)
            quality = composition_quality_report(compiled)
            pacing = {
                "notes_per_second": quality["notes_per_second"],
                "groups": {
                    row["group"]: {
                        "note_count": row["note_count"],
                        "mean_note_duration_s": row["mean_note_duration_s"],
                        "notes_per_active_second": row["notes_per_active_second"],
                    }
                    for row in quality["groups"]
                },
            }
            result["composition_pacing"] = pacing
            save_json(evidence / "loop_source.json", loop_report)
            save_json(evidence / "composition_quality.json", quality)
            save_json(evidence / "composition_pacing.json", pacing)
            save_json(evidence / "determinism.json", determinism)
            melody = pacing["groups"].get("melody", {})
            bass = pacing["groups"].get("bass", {})
            print(
                f"[ninja review] {cue}: pacing {pacing['notes_per_second']:.2f} notes/s; "
                f"melody mean {melody.get('mean_note_duration_s', 0):.2f}s; "
                f"bass mean {bass.get('mean_note_duration_s', 0):.2f}s",
                flush=True,
            )
            compiled.pm.write(str(evidence / f"{cue}.mid"))
            if not determinism["deterministic"]:
                raise RuntimeError("independent score compilations differ")
            if any(loop_report[k] for k in ["duplicate_notes", "same_pitch_overlaps", "out_of_form_notes"]):
                raise RuntimeError("score has overlapping, duplicate, or out-of-form notes; inspect loop_source.json")
            if not loop_report["loops"] or not all(r["pre_roll_matches_ending"] and r["boundary_controller_state_equal"] and not r["notes_crossing_end"] for r in loop_report["loops"]):
                raise RuntimeError("the suite's intended pre-roll/loop contract is not satisfied")
            if args.score_only:
                result["status"] = "score_only_passed"
                print(f"[ninja review] {cue}: score checks passed; audio not rendered", flush=True)
                continue
            render_dir, bundle_root = work / "render", work / "bundles"
            command = [sys.executable, "-m", "ambition_music_renderer", "cue", "bundle", cue,
                       "--backend", "pretty-midi", "--outdir", str(render_dir),
                       "--bundle_root", str(bundle_root), "--render_audio_mode", "full-mix-only",
                       "--audition_stems", "--all_audits", "--jobs", str(args.jobs)]
            result["command"] = command
            run_logged(command, evidence / "render.log")
            manifest_path = latest_manifest_in_roots([render_dir], cue)
            if manifest_path is None:
                raise RuntimeError("render returned no manifest")
            manifest = json.loads(manifest_path.read_text(encoding="utf8"))
            if manifest.get("compiled_score", {}).get("fingerprint") != fingerprint:
                raise RuntimeError("manifest does not describe the score just compiled")
            result["render_manifest"] = str(manifest_path)
            shutil.copy2(manifest_path, evidence / manifest_path.name)
            import soundfile as sf
            for row in loop_report["loops"]:
                relative = manifest["files"]["adaptive"][row["section"]]["full"]
                audio_path = (manifest_path.parent / relative).resolve()
                if not audio_path.is_relative_to(manifest_path.parent.resolve()):
                    raise RuntimeError("manifest audio escapes its render directory")
                audio, sample_rate = sf.read(audio_path, always_2d=True, dtype="float32")
                measured, seam = audio_loop_report(audio, sample_rate, period_seconds=row["period_seconds"])
                measured["source_audio"] = str(audio_path)
                save_json(evidence / f"{row['section']}_audio.json", measured)
                # FLOAT preserves the decoded export without clipping or normalization.
                sf.write(evidence / f"{row['section']}_seam.wav", seam, sample_rate, subtype="FLOAT")
                if not measured["duration_matches_score"]:
                    raise RuntimeError("exported loop duration differs from the score")
                if measured["samples_at_or_above_full_scale"]:
                    raise RuntimeError("exported loop reaches digital full scale; inspect the mix")
            bundles = [p.parent for p in bundle_root.glob("*/bundle_manifest.json")]
            if len(bundles) != 1:
                raise RuntimeError(f"expected one new bundle, found {len(bundles)}")
            bundle_manifest = json.loads((bundles[0] / "bundle_manifest.json").read_text(encoding="utf8"))
            result["audit_warnings"] = bundle_manifest.get("warnings", [])
            result["failed_commands"] = [command for command in bundle_manifest.get("commands", [])
                                         if command.get("returncode", 0) != 0]
            if result["failed_commands"]:
                raise RuntimeError("one or more native audit commands failed; reports and audio are retained")
            result["status"] = "rendered_and_measured"
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
            print(f"[ninja review] {cue}: {result['error']}", file=sys.stderr, flush=True)
            save_json(evidence / "failure.json", result)
        finally:
            # Preserve a completed native bundle even when its audio/audits fail
            # a check. This fresh directory cannot contain another run's output.
            for manifest in sorted(bundle_root.glob("*/bundle_manifest.json")):
                package_roots.append((manifest.parent, cue + "/bundle/" + manifest.parent.name))
    run = {"schema": "ambition.ninja_suite_review.v1", "created_utc": stamp,
           "python": sys.version, "argv": sys.argv, "score_only": args.score_only,
           "results": results,
           "listening": "Start with each full soundtrack, then the unmodified zone_loop_seam.wav (wrap at 8 seconds). Use review_stem_* for balance; audition_stem_* are independently normalized."}
    save_json(output / "RUN.json", run)
    for report_only in (False, True):
        name = "ninja_suite_report.zip" if report_only else "ninja_suite_review.zip"
        with zipfile.ZipFile(output / name, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(output / "RUN.json", "RUN.json")
            for folder, prefix in package_roots:
                for path in sorted(folder.rglob("*")):
                    if not path.is_file() or path.suffix == ".npy":
                        continue
                    if report_only and path.suffix.lower() in AUDIO_SUFFIXES:
                        continue
                    archive.write(path, str(Path(prefix) / path.relative_to(folder)))
        print(f"[ninja review] {output / name}", flush=True)
    return int(any(r["status"] == "failed" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
