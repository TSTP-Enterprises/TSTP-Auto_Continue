import os

from install_support import read_requirements


def test_read_requirements_with_nested_include(tmp_path):
    base = tmp_path / "requirements.txt"
    nested = tmp_path / "requirements-extra.txt"
    nested.write_text("numpy>=1.0\n# comment\n", encoding="utf-8")
    base.write_text("-r requirements-extra.txt\nPyQt5>=5.15.0\n", encoding="utf-8")

    packages = read_requirements(str(base))
    assert "numpy" in packages
    assert "PyQt5" in packages


def test_read_requirements_missing_file_returns_empty(tmp_path):
    missing = os.path.join(str(tmp_path), "does-not-exist.txt")
    assert read_requirements(missing) == []

