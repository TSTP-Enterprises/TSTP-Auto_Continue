import os
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass


TESSERACT_DOWNLOAD_URL = "https://github.com/UB-Mannheim/tesseract/wiki"

COMMON_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


@dataclass
class CommandResult:
    ok: bool
    output: str


class OCRService:
    def detect_tesseract_path(self, configured_path: str = "") -> str:
        if configured_path and os.path.exists(configured_path):
            return configured_path

        from_path = shutil.which("tesseract")
        if from_path:
            return from_path

        for path in COMMON_TESSERACT_PATHS:
            if os.path.exists(path):
                return path

        return ""

    def verify_tesseract_path(self, path: str) -> CommandResult:
        if not path:
            return CommandResult(False, "No path selected.")
        if not os.path.exists(path):
            return CommandResult(False, f"Path does not exist: {path}")
        try:
            completed = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=25,
            )
            if completed.returncode != 0:
                return CommandResult(False, completed.stderr.strip() or "Tesseract version check failed.")
            first_line = (completed.stdout or "").splitlines()[0] if completed.stdout else "Version returned."
            return CommandResult(True, f"Verified: {first_line}")
        except Exception as exc:
            return CommandResult(False, str(exc))

    def is_tool_available(self, tool_name: str) -> bool:
        return shutil.which(tool_name) is not None

    def install_with_winget(self) -> CommandResult:
        if not self.is_tool_available("winget"):
            return CommandResult(False, "winget is not installed.")
        try:
            completed = subprocess.run(
                ["winget", "install", "-e", "--id", "UB-Mannheim.TesseractOCR", "--accept-source-agreements", "--accept-package-agreements"],
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            return CommandResult(completed.returncode == 0, output.strip())
        except Exception as exc:
            return CommandResult(False, str(exc))

    def install_with_choco(self) -> CommandResult:
        if not self.is_tool_available("choco"):
            return CommandResult(False, "Chocolatey is not installed.")
        try:
            completed = subprocess.run(
                ["choco", "install", "tesseract", "-y"],
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            return CommandResult(completed.returncode == 0, output.strip())
        except Exception as exc:
            return CommandResult(False, str(exc))

    def open_download_page(self) -> None:
        webbrowser.open(TESSERACT_DOWNLOAD_URL)

