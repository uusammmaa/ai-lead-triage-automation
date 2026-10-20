"""Deploy config stays consistent: Docker reads requirements.txt, Vercel reads pyproject.toml and vercel.json."""

import json
import tomllib

from conftest import CORE


def test_pyproject_dependencies_match_requirements():
    pyproject = tomllib.loads((CORE / "pyproject.toml").read_text())
    requirements = [
        line.strip()
        for line in (CORE / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert sorted(pyproject["project"]["dependencies"]) == sorted(requirements)


def test_vercel_function_points_at_the_entrypoint():
    pyproject = tomllib.loads((CORE / "pyproject.toml").read_text())
    module, attr = pyproject["tool"]["vercel"]["entrypoint"].split(":")
    entry_file = module.replace(".", "/") + ".py"
    assert (CORE / entry_file).is_file() and attr == "app"
    functions = json.loads((CORE / "vercel.json").read_text())["functions"]
    assert list(functions) == [entry_file]
    # Hobby caps maxDuration at 300s.
    assert 0 < functions[entry_file]["maxDuration"] <= 300
    # The rules file is read at startup, so it must stay in the bundle.
    assert "config" not in functions[entry_file].get("excludeFiles", "")
