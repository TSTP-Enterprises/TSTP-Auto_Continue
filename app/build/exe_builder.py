import os
import subprocess
import sys
from dataclasses import dataclass


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


@dataclass
class BuildResult:
    ok: bool
    output: str
    dist_path: str


class ExeBuilder:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.entry_script = os.path.join(project_root, "v2", "main.py")
        self.dist_path = os.path.join(project_root, "v2", "dist")

    def build(self) -> BuildResult:
        if is_frozen():
            return BuildResult(False, "Build is disabled inside packaged EXE.", self.dist_path)

        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "TSTP-AutoClicker-v2",
            self.entry_script,
        ]
        completed = subprocess.run(
            cmd,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        return BuildResult(completed.returncode == 0, output.strip(), self.dist_path)

