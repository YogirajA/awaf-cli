"""`awaf --version` should report the installed package version."""

from __future__ import annotations

from importlib.metadata import version

from click.testing import CliRunner

from awaf.cli import cli


def test_version_flag_reports_package_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert version("awaf") in result.output
