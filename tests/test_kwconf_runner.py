from pathlib import Path

import kwconf

from ambition_music_renderer.kwconf_runner import config_to_argv
from ambition_music_renderer.kwconf_runner import KwconfCommand


class OptionalPositionalConfig(kwconf.Config):
    root: Path = kwconf.Value(Path("default"), position=1, parser=Path, nargs="?")
    window: list[float] = kwconf.Value(default_factory=lambda: [0.0, 1.0], nargs=2)
    verbose: bool = kwconf.Flag(False)

    @classmethod
    def main(cls, argv=True, **kwargs):
        return 0


class VariadicPositionalConfig(kwconf.Config):
    cues: list[str] = kwconf.Value(default_factory=list, position=1, nargs="*")
    force: bool = kwconf.Flag(False)

    @classmethod
    def main(cls, argv=True, **kwargs):
        return 0


def test_config_to_argv_preserves_optional_positionals():
    argv = config_to_argv(
        OptionalPositionalConfig,
        {"root": Path("/tmp/example"), "window": [2.0, 3.0], "verbose": True},
    )
    assert argv == ["/tmp/example", "--window", "2.0", "3.0", "--verbose"]
    parsed = OptionalPositionalConfig.cli(argv=argv)
    assert parsed.root == Path("/tmp/example")
    assert parsed.window == [2.0, 3.0]
    assert parsed.verbose is True


def test_config_to_argv_preserves_variadic_positionals():
    argv = config_to_argv(VariadicPositionalConfig, {"cues": ["a", "b"], "force": True})
    assert argv == ["a", "b", "--force"]
    parsed = VariadicPositionalConfig.cli(argv=argv)
    assert parsed.cues == ["a", "b"]
    assert parsed.force is True


def test_kwconf_command_uses_positional_argv_for_python_command():
    cmd = KwconfCommand(OptionalPositionalConfig, module="example.module")
    argv = cmd.python_command({"root": Path("/tmp/example")})
    assert argv[-1] == "/tmp/example"
    assert "--root=/tmp/example" not in argv
