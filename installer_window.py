import argparse
import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, scrolledtext

from install_support import collect_environment_report


class InstallerWindow(tk.Tk):
    def __init__(self, v2_dir: str, full_install: bool, install_dev: bool):
        super().__init__()
        self.title("TSTP AutoClicker v2 Installer")
        self.geometry("900x640")
        self._v2_dir = v2_dir
        self._full_install = full_install
        self._install_dev = install_dev
        self._install_dev_var = tk.BooleanVar(value=bool(install_dev or full_install))
        self._full_stack_var = tk.BooleanVar(value=bool(full_install))
        self._report_queue: queue.Queue[str] = queue.Queue()
        self._install_thread: threading.Thread | None = None
        self.install_ok = False

        self._build_ui()
        self._refresh_report()
        self.after(100, self._drain_queue)

    def _build_ui(self):
        self.configure(bg="#e2e8f0")
        hero = tk.Frame(self, bg="#0f172a")
        hero.pack(fill=tk.X)
        tk.Label(
            hero,
            text="⚙ TSTP AutoClicker v2 Setup Assistant",
            font=("Segoe UI", 14, "bold"),
            anchor="w",
            bg="#0f172a",
            fg="white",
            padx=12,
            pady=10,
        ).pack(fill=tk.X)
        tk.Label(
            hero,
            text="Install/repair runtime dependencies and review detailed diagnostics for failures.",
            anchor="w",
            justify=tk.LEFT,
            bg="#0f172a",
            fg="#cbd5e1",
            padx=12,
        ).pack(fill=tk.X, pady=(0, 10))

        top = tk.Frame(self, bg="#e2e8f0")
        top.pack(fill=tk.X, padx=12, pady=12)

        self.summary_label = tk.Label(
            top,
            text="",
            anchor="w",
            justify=tk.LEFT,
            fg="#1f2937",
            bg="#e2e8f0",
        )
        self.summary_label.pack(fill=tk.X, pady=(8, 0))

        option_frame = tk.Frame(self, bg="#e2e8f0")
        option_frame.pack(fill=tk.X, padx=12, pady=(0, 8))
        tk.Checkbutton(
            option_frame,
            text="Also install developer dependencies (tests/build tools)",
            variable=self._install_dev_var,
            bg="#e2e8f0",
        ).pack(anchor="w")
        tk.Checkbutton(
            option_frame,
            text="Attempt optional full-stack setup",
            variable=self._full_stack_var,
            bg="#e2e8f0",
        ).pack(anchor="w")

        actions = tk.Frame(self, bg="#e2e8f0")
        actions.pack(fill=tk.X, padx=12, pady=(0, 8))

        self.install_button = tk.Button(
            actions,
            text="Install / Repair Now",
            font=("Segoe UI", 10, "bold"),
            command=self._start_install,
        )
        self.install_button.pack(side=tk.LEFT, padx=(0, 8))

        self.verify_button = tk.Button(actions, text="Re-check", command=self._refresh_report)
        self.verify_button.pack(side=tk.LEFT, padx=(0, 8))

        self.close_button = tk.Button(actions, text="Close", command=self.destroy)
        self.close_button.pack(side=tk.LEFT)

        self.log_text = scrolledtext.ScrolledText(self, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

    def _append_log(self, text: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text.rstrip() + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_report(self):
        report = collect_environment_report(self._v2_dir, include_dev=False)
        if report.ready:
            self.summary_label.config(text="Everything required for runtime is currently installed.", fg="#166534")
        else:
            lines = []
            if report.missing_files:
                lines.append("Missing files:\n  - " + "\n  - ".join(report.missing_files))
            if report.missing_packages:
                lines.append("Missing packages:\n  - " + "\n  - ".join(report.missing_packages))
            self.summary_label.config(text="\n".join(lines), fg="#991b1b")

    def _start_install(self):
        if self._install_thread and self._install_thread.is_alive():
            return
        self.install_button.config(state=tk.DISABLED)
        self.verify_button.config(state=tk.DISABLED)
        self.install_ok = False
        self._append_log("Starting install/repair...")
        self._install_thread = threading.Thread(target=self._run_install, daemon=True)
        self._install_thread.start()

    def _run_install(self):
        try:
            report = collect_environment_report(self._v2_dir, include_dev=False)
            if report.missing_files:
                self._report_queue.put(
                    "ERROR: Required files are missing:\n  - " + "\n  - ".join(report.missing_files)
                )
                self._report_queue.put("__FAILED__")
                return

            commands = [
                [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--upgrade", "pip"],
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "-r",
                    os.path.join(self._v2_dir, "requirements.txt"),
                ],
            ]
            if self._install_dev_var.get():
                commands.append(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--no-cache-dir",
                        "-r",
                        os.path.join(self._v2_dir, "requirements-dev.txt"),
                    ]
                )
            if self._full_stack_var.get():
                self._report_queue.put(
                    "Full-stack mode enabled: optional third-party tools can be installed from the OCR Setup Wizard inside the app."
                )

            for command in commands:
                self._run_command(command)

            post_report = collect_environment_report(self._v2_dir, include_dev=False)
            if post_report.ready:
                self._report_queue.put("Install/repair completed successfully.")
                self._report_queue.put("__SUCCESS__")
            else:
                details = []
                if post_report.missing_files:
                    details.append("Missing files: " + ", ".join(post_report.missing_files))
                if post_report.missing_packages:
                    details.append("Missing packages: " + ", ".join(post_report.missing_packages))
                self._report_queue.put("Install finished but requirements are still missing:\n" + "\n".join(details))
                self._report_queue.put("__FAILED__")
        except Exception:
            self._report_queue.put("Installer crashed:\n" + traceback.format_exc())
            self._report_queue.put("__FAILED__")

    def _run_command(self, command: list[str]):
        self._report_queue.put("$ " + " ".join(command))
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=self._v2_dir,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            self._report_queue.put(line.rstrip())
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"Command failed with exit code {code}: {' '.join(command)}")

    def _drain_queue(self):
        try:
            while True:
                line = self._report_queue.get_nowait()
                if line == "__SUCCESS__":
                    self.install_ok = True
                    self.install_button.config(state=tk.NORMAL)
                    self.verify_button.config(state=tk.NORMAL)
                    self._refresh_report()
                    messagebox.showinfo("Installer", "Installation/repair completed.")
                elif line == "__FAILED__":
                    self.install_ok = False
                    self.install_button.config(state=tk.NORMAL)
                    self.verify_button.config(state=tk.NORMAL)
                    self._refresh_report()
                    messagebox.showerror(
                        "Installer",
                        "Installation/repair failed. Check details in the log window.",
                    )
                else:
                    self._append_log(line)
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)


def run_installer(v2_dir: str, full_install: bool, install_dev: bool) -> bool:
    app = InstallerWindow(v2_dir=v2_dir, full_install=full_install, install_dev=install_dev)
    app.mainloop()
    return app.install_ok


def main():
    parser = argparse.ArgumentParser(description="Visual installer for TSTP AutoClicker v2.")
    parser.add_argument("--full", action="store_true", help="Install runtime + developer requirements.")
    parser.add_argument("--dev", action="store_true", help="Install dev requirements as well.")
    args = parser.parse_args()

    v2_dir = os.path.abspath(os.path.dirname(__file__))
    ok = run_installer(v2_dir=v2_dir, full_install=args.full, install_dev=args.dev)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

