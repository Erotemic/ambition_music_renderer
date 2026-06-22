"""Small helpers for invoking kwconf Config commands.

The renderer has a few orchestration boundaries where a command can either run
inside the current interpreter for profiling/debugging, or in a fresh Python
process for production isolation.  kwconf makes those two paths share the same
configuration class: direct calls pass keyword data to ``Config.main``; process
calls render those same key/value pairs as CLI arguments.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import kwconf


def _field_names(config_cls: type[kwconf.Config]) -> set[str]:
    return set(getattr(config_cls, "__default__", {}) or {})


def _coerce_command_data(
    config_cls: type[kwconf.Config],
    data: Mapping[str, Any] | kwconf.Config | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return plain keyword data filtered to fields on ``config_cls``."""
    if data is None:
        raw: dict[str, Any] = {}
    elif isinstance(data, kwconf.Config):
        raw = data.asdict()
    else:
        raw = dict(data)
    raw.update(kwargs)
    fields = _field_names(config_cls)
    if fields:
        raw = {key: value for key, value in raw.items() if key in fields}
    return raw


def _cli_scalar(value: Any) -> str:
    """Stringify one scalar CLI value without changing its semantic type."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value)
    return str(value)


def _is_flat_cli_sequence(value: Any) -> bool:
    """Return true when a sequence should be emitted as nargs tokens.

    kwconf fields such as ``window = kwconf.Value(..., nargs=2)`` expect
    ``--window 0 53.333``.  Emitting ``--window=[0, 53.333]`` only works when
    the receiving field opts into a structured parser such as ``parser='yaml'``.
    Keep nested lists/dicts as one JSON/YAML-ish scalar, but treat flat
    scalar sequences as normal argparse/kwconf nargs values.
    """
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        return False
    if not isinstance(value, (list, tuple)):
        return False
    return all(not isinstance(item, (list, tuple, dict, set)) for item in value)


def config_to_argv(
    config_cls: type[kwconf.Config],
    data: Mapping[str, Any] | kwconf.Config | None = None,
    **kwargs: Any,
) -> list[str]:
    """Render kwconf config data as explicit CLI key/value arguments.

    Non-boolean values become ``--key=value``.  Boolean True values become a
    bare ``--key`` and Boolean False values become ``--no-key`` because kwconf's
    flag action is intentionally flag-oriented and supports the negated form.
    """
    raw = _coerce_command_data(config_cls, data, **kwargs)
    argv: list[str] = []
    for key, value in raw.items():
        if value is None:
            continue
        cli_key = key.replace("-", "_")
        if isinstance(value, bool):
            argv.append(f"--{cli_key}" if value else f"--no-{cli_key}")
        elif _is_flat_cli_sequence(value):
            argv.append(f"--{cli_key}")
            argv.extend(_cli_scalar(item) for item in value)
        else:
            argv.append(f"--{cli_key}={_cli_scalar(value)}")
    return argv


@dataclass(frozen=True)
class KwconfCommand:
    """Invoke one ``kwconf.Config`` command directly or via ``python -m``."""

    config_cls: type[kwconf.Config]
    module: str | None = None
    cwd: Path | None = None

    def cli_argv(
        self,
        data: Mapping[str, Any] | kwconf.Config | None = None,
        **kwargs: Any,
    ) -> list[str]:
        return config_to_argv(self.config_cls, data, **kwargs)

    def python_command(
        self,
        data: Mapping[str, Any] | kwconf.Config | None = None,
        **kwargs: Any,
    ) -> list[str]:
        module = self.module or self.config_cls.__module__
        return [sys.executable, "-m", module, *self.cli_argv(data, **kwargs)]

    def run_direct(
        self,
        argv: Sequence[str] | str | bool | None = False,
        data: Mapping[str, Any] | kwconf.Config | None = None,
        **kwargs: Any,
    ) -> int:
        raw = _coerce_command_data(self.config_cls, data, **kwargs)
        return int(self.config_cls.main(argv=argv, **raw))

    def run_subprocess(
        self,
        data: Mapping[str, Any] | kwconf.Config | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        popen_kwargs = {key: kwargs.pop(key) for key in list(kwargs) if key in {"stdout", "stderr", "env"}}
        cwd = kwargs.pop("cwd", self.cwd)
        cmd = self.python_command(data, **kwargs)
        return subprocess.run(cmd, cwd=cwd, **popen_kwargs)

    def popen(
        self,
        data: Mapping[str, Any] | kwconf.Config | None = None,
        **kwargs: Any,
    ) -> subprocess.Popen[Any]:
        popen_kwargs = {key: kwargs.pop(key) for key in list(kwargs) if key in {"stdout", "stderr", "env"}}
        cwd = kwargs.pop("cwd", self.cwd)
        cmd = self.python_command(data, **kwargs)
        return subprocess.Popen(cmd, cwd=cwd, **popen_kwargs)

    def run(
        self,
        mode: str,
        argv: Sequence[str] | str | bool | None = False,
        data: Mapping[str, Any] | kwconf.Config | None = None,
        **kwargs: Any,
    ) -> int | subprocess.CompletedProcess[Any]:
        if mode == "direct":
            return self.run_direct(argv=argv, data=data, **kwargs)
        if mode == "subprocess":
            return self.run_subprocess(data=data, **kwargs)
        raise KeyError(f"unknown kwconf command mode: {mode!r}")
