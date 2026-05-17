import sys
import os
import tkinter as tk
from tkinter import messagebox

from install_support import collect_environment_report


class StartupDependencyPrompt(tk.Toplevel):
    def __init__(self, parent, detail_lines):
        super().__init__(parent)
        self.title("TSTP AutoClicker v2 - Setup Required")
        self.configure(bg="#e2e8f0")
        self.resizable(False, False)
        self.choice_install = False

        header = tk.Frame(self, bg="#0f172a")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="⚙ Environment Check Detected Missing Requirements",
            bg="#0f172a",
            fg="white",
            font=("Segoe UI", 13, "bold"),
            padx=14,
            pady=10,
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            header,
            text="AutoClicker cannot start until required files and Python packages are installed.",
            bg="#0f172a",
            fg="#cbd5e1",
            font=("Segoe UI", 10),
            padx=14,
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 10))

        body = tk.Frame(self, bg="#e2e8f0")
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        tk.Label(
            body,
            text="\n\n".join(detail_lines),
            bg="#e2e8f0",
            fg="#1e293b",
            justify=tk.LEFT,
            anchor="w",
            font=("Consolas", 10),
        ).pack(fill=tk.X)

        footer = tk.Frame(self, bg="#e2e8f0")
        footer.pack(fill=tk.X, padx=12, pady=(0, 12))
        tk.Button(
            footer,
            text="Open Visual Installer",
            bg="#1d4ed8",
            fg="white",
            activebackground="#1e40af",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=6,
            command=self._choose_install,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            footer,
            text="Exit App",
            font=("Segoe UI", 10),
            padx=12,
            pady=6,
            command=self._choose_exit,
        ).pack(side=tk.LEFT)

        self.protocol("WM_DELETE_WINDOW", self._choose_exit)
        self.grab_set()
        self.transient(parent)

    def _choose_install(self):
        self.choice_install = True
        self.destroy()

    def _choose_exit(self):
        self.choice_install = False
        self.destroy()


def ensure_runtime_ready(v2_dir: str) -> bool:
    report = collect_environment_report(v2_dir=v2_dir, include_dev=False)
    if report.ready:
        return True

    detail_lines = []
    if report.missing_files:
        detail_lines.append("Missing files:\n- " + "\n- ".join(report.missing_files))
    if report.missing_packages:
        detail_lines.append("Missing packages:\n- " + "\n- ".join(report.missing_packages))

    root = tk.Tk()
    root.withdraw()

    prompt = StartupDependencyPrompt(root, detail_lines)
    root.wait_window(prompt)
    should_install = prompt.choice_install

    if not should_install:
        messagebox.showwarning(
            "Startup Cancelled",
            "The app will now exit because required components are still missing.",
        )
        root.destroy()
        return False
    root.destroy()

    from installer_window import run_installer

    ok = run_installer(v2_dir=v2_dir, full_install=False, install_dev=False)
    if not ok:
        return False
    return collect_environment_report(v2_dir=v2_dir, include_dev=False).ready


def main() -> int:
    v2_dir = os.path.abspath(os.path.dirname(__file__))
    if not ensure_runtime_ready(v2_dir=v2_dir):
        return 1

    from PyQt5.QtWidgets import QApplication
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())

