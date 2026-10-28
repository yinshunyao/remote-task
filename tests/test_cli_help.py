from __future__ import annotations

from remote_task.cli import build_parser, main


def test_parser_subcommands():
    parser = build_parser()
    args = parser.parse_args(["version"])
    assert args.command == "version"


def test_main_version(capsys):
    assert main(["version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.count(".") >= 1
