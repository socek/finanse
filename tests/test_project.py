import tomllib
from pathlib import Path

from finanse import __version__
from finanse.gui.about_tab import changelog_text

ROOT = Path(__file__).resolve().parent.parent


def pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))


def test_current_version_is_in_changelog():
    assert __version__ == "0.1"
    assert f"\n## {__version__} (" in changelog_text()


def test_pyproject_takes_version_from_package():
    config = pyproject()
    assert "version" in config["project"]["dynamic"]
    assert config["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "finanse.__version__"
    }


def test_pyproject_lists_every_package_and_data_file():
    setuptools = pyproject()["tool"]["setuptools"]
    packages = {
        ".".join(path.parent.relative_to(ROOT).parts)
        for path in (ROOT / "finanse").rglob("__init__.py")
    }
    assert set(setuptools["packages"]) == packages
    data = setuptools["package-data"]["finanse"]
    assert "CHANGELOG.md" in data and "migrations/*.sql" in data
