import importlib.util
import os
import re
from dataclasses import dataclass
from typing import Dict, List


REQUIREMENTS_FILE = "requirements.txt"
REQUIREMENTS_DEV_FILE = "requirements-dev.txt"

REQUIRED_RUNTIME_FILES = [
    "main.py",
    os.path.join("app", "ui", "main_window.py"),
    os.path.join("app", "automation", "engine.py"),
    REQUIREMENTS_FILE,
]

IMPORT_OVERRIDES: Dict[str, str] = {
    "opencv-python": "cv2",
    "pillow": "PIL",
    "pyqt5": "PyQt5",
}


@dataclass
class EnvironmentReport:
    missing_files: List[str]
    missing_packages: List[str]

    @property
    def ready(self) -> bool:
        return not self.missing_files and not self.missing_packages


def _parse_requirement_name(line: str) -> str:
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return ""
    if cleaned.startswith("-r "):
        return ""
    # Drop markers and version operators.
    cleaned = cleaned.split(";")[0].strip()
    name = re.split(r"[<>=!~\[]", cleaned)[0].strip()
    return name


def read_requirements(requirements_path: str, _seen: set | None = None) -> List[str]:
    _seen = _seen or set()
    abs_path = os.path.abspath(requirements_path)
    if abs_path in _seen or not os.path.exists(abs_path):
        return []

    _seen.add(abs_path)
    packages: List[str] = []
    base_dir = os.path.dirname(abs_path)

    with open(abs_path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                include = line[3:].strip()
                nested = os.path.join(base_dir, include)
                packages.extend(read_requirements(nested, _seen=_seen))
                continue
            name = _parse_requirement_name(line)
            if name:
                packages.append(name)
    return packages


def collect_environment_report(v2_dir: str, include_dev: bool = False) -> EnvironmentReport:
    missing_files: List[str] = []
    for relative_path in REQUIRED_RUNTIME_FILES:
        full_path = os.path.join(v2_dir, relative_path)
        if not os.path.exists(full_path):
            missing_files.append(relative_path)

    requirement_paths = [os.path.join(v2_dir, REQUIREMENTS_FILE)]
    if include_dev:
        requirement_paths.append(os.path.join(v2_dir, REQUIREMENTS_DEV_FILE))

    all_packages: List[str] = []
    for requirement_path in requirement_paths:
        all_packages.extend(read_requirements(requirement_path))

    deduplicated = []
    for package in all_packages:
        if package.lower() not in [p.lower() for p in deduplicated]:
            deduplicated.append(package)

    missing_packages: List[str] = []
    for package in deduplicated:
        module_name = IMPORT_OVERRIDES.get(package.lower(), package)
        if importlib.util.find_spec(module_name) is None:
            missing_packages.append(package)

    return EnvironmentReport(missing_files=missing_files, missing_packages=missing_packages)

