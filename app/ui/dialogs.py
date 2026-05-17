import os

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QKeySequenceEdit,
)
from PyQt5.QtGui import QKeySequence

from app.build.exe_builder import ExeBuilder
from app.controls.hotkeys import normalize_hotkey
from app.core.models import TargetSpec
from app.ocr.service import OCRService


def show_error(parent, title: str, message: str, details: str = "") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    if details:
        box.setDetailedText(details)
    box.exec_()


class HotkeyCaptureDialog(QDialog):
    def __init__(self, current_hotkey: str, purpose: str = "emergency stop"):
        super().__init__()
        self.setWindowTitle("Capture Hotkey")
        self._selected_hotkey = current_hotkey

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Press key or key combo for {purpose}:"))
        self.editor = QKeySequenceEdit()
        if current_hotkey:
            display = (
                current_hotkey.replace("<ctrl>", "Ctrl")
                .replace("<alt>", "Alt")
                .replace("<shift>", "Shift")
                .replace("<cmd>", "Meta")
                .replace("<esc>", "Esc")
                .replace("<", "")
                .replace(">", "")
            )
            self.editor.setKeySequence(QKeySequence(display))
        layout.addWidget(self.editor)

        button_row = QHBoxLayout()
        ok_button = QPushButton("Save")
        ok_button.clicked.connect(self._save)
        button_row.addWidget(ok_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)
        self.setLayout(layout)

    def _save(self):
        sequence = self.editor.keySequence().toString(QKeySequence.PortableText)
        self._selected_hotkey = normalize_hotkey(sequence)
        self.accept()

    @property
    def selected_hotkey(self) -> str:
        return self._selected_hotkey


class TargetEditorDialog(QDialog):
    def __init__(self, target: TargetSpec | None, allow_text: bool):
        super().__init__()
        self._target = target
        self._allow_text = allow_text
        self._result: TargetSpec | None = None
        self.setWindowTitle("Target Editor")

        layout = QFormLayout()
        self.name_input = QLineEdit(target.name if target else "")
        layout.addRow("Name", self.name_input)

        self.type_combo = QComboBox()
        if allow_text:
            self.type_combo.addItems(["image", "text"])
        else:
            self.type_combo.addItems(["image"])
        self.type_combo.setCurrentText(target.target_type if target else "image")
        self.type_combo.currentTextChanged.connect(self._sync_type_ui)
        layout.addRow("Type", self.type_combo)

        value_row = QHBoxLayout()
        self.value_input = QLineEdit(target.value if target else "")
        value_row.addWidget(self.value_input)
        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self._browse_path)
        value_row.addWidget(self.browse_button)
        layout.addRow("Value", value_row)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.5, 0.99)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(target.threshold if target else 0.88)
        layout.addRow("Threshold", self.threshold_spin)

        self.enabled_checkbox = QCheckBox("Enabled")
        self.enabled_checkbox.setChecked(True if target is None else target.enabled)
        layout.addRow("", self.enabled_checkbox)

        button_row = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self._save)
        button_row.addWidget(save_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addRow(button_row)
        self.setLayout(layout)
        self._sync_type_ui(self.type_combo.currentText())

    def _sync_type_ui(self, target_type: str):
        is_image = target_type == "image"
        self.browse_button.setEnabled(is_image)
        self.threshold_spin.setEnabled(is_image)
        if not is_image:
            self.threshold_spin.setValue(1.0)

    def _browse_path(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select target image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp)",
        )
        if selected:
            self.value_input.setText(selected)

    def _save(self):
        name = self.name_input.text().strip()
        target_type = self.type_combo.currentText()
        value = self.value_input.text().strip()
        if not name:
            show_error(self, "Invalid Target", "Target name is required.")
            return
        if not value:
            show_error(self, "Invalid Target", "Target value is required.")
            return
        if target_type == "image" and not os.path.exists(value):
            show_error(self, "Invalid Target", f"Image file does not exist:\n{value}")
            return
        threshold = self.threshold_spin.value() if target_type == "image" else 1.0
        self._result = TargetSpec(
            id=self._target.id if self._target else TargetSpec().id,
            name=name,
            target_type=target_type,
            value=value,
            threshold=threshold,
            enabled=self.enabled_checkbox.isChecked(),
        )
        self.accept()

    @property
    def result_target(self) -> TargetSpec | None:
        return self._result


class OCRSetupDialog(QDialog):
    def __init__(self, service: OCRService, current_path: str):
        super().__init__()
        self.setWindowTitle("OCR Setup Wizard")
        self._service = service
        self._selected_path = current_path

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel(
                "Find or install Tesseract OCR.\n"
                "You can auto-install with winget/choco, browse manually, or open the official download page."
            )
        )

        self.path_label = QLabel(self._selected_path or "(No OCR path selected)")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        detect_button = QPushButton("Detect Existing OCR")
        detect_button.clicked.connect(self._detect_existing)
        layout.addWidget(detect_button)

        browse_button = QPushButton("Select OCR Path Manually")
        browse_button.clicked.connect(self._browse_manual)
        layout.addWidget(browse_button)

        verify_button = QPushButton("Verify Selected OCR Path")
        verify_button.clicked.connect(self._verify_selected)
        layout.addWidget(verify_button)

        winget_button = QPushButton("Install OCR via winget")
        winget_button.clicked.connect(self._install_winget)
        layout.addWidget(winget_button)

        choco_button = QPushButton("Install OCR via choco")
        choco_button.clicked.connect(self._install_choco)
        layout.addWidget(choco_button)

        download_button = QPushButton("Open Official OCR Download Page")
        download_button.clicked.connect(self._open_download)
        layout.addWidget(download_button)

        self.output_box = QPlainTextEdit()
        self.output_box.setReadOnly(True)
        layout.addWidget(self.output_box)

        action_row = QHBoxLayout()
        save_button = QPushButton("Save OCR Path")
        save_button.clicked.connect(self.accept)
        action_row.addWidget(save_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        action_row.addWidget(cancel_button)
        layout.addLayout(action_row)
        self.setLayout(layout)

    @property
    def selected_path(self) -> str:
        return self._selected_path

    def _append_output(self, text: str):
        if not text:
            return
        self.output_box.appendPlainText(text.strip())

    def _set_path(self, path: str):
        self._selected_path = path
        self.path_label.setText(path or "(No OCR path selected)")

    def _detect_existing(self):
        found = self._service.detect_tesseract_path(self._selected_path)
        if not found:
            self._append_output("No existing Tesseract installation found.")
            return
        self._set_path(found)
        self._append_output(f"Detected OCR path: {found}")

    def _browse_manual(self):
        selected, _ = QFileDialog.getOpenFileName(self, "Select tesseract.exe", "", "Executable (*.exe)")
        if selected:
            self._set_path(selected)
            self._append_output(f"Manual path selected: {selected}")

    def _verify_selected(self):
        result = self._service.verify_tesseract_path(self._selected_path)
        self._append_output(result.output)
        if result.ok:
            QMessageBox.information(self, "OCR Verification", "OCR path verified successfully.")
        else:
            show_error(self, "OCR Verification Failed", result.output)

    def _install_winget(self):
        result = self._service.install_with_winget()
        self._append_output(result.output)
        if not result.ok and not self._service.is_tool_available("winget"):
            self._append_output("winget is missing. Install App Installer from Microsoft Store.")

    def _install_choco(self):
        result = self._service.install_with_choco()
        self._append_output(result.output)
        if not result.ok and not self._service.is_tool_available("choco"):
            self._append_output("Chocolatey is missing. Install from https://chocolatey.org/install")

    def _open_download(self):
        self._service.open_download_page()
        self._append_output("Opened official OCR download page in browser.")


class BuildExeDialog(QDialog):
    def __init__(self, builder: ExeBuilder):
        super().__init__()
        self._builder = builder
        self.setWindowTitle("Build EXE")
        self.resize(720, 500)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Build a standalone EXE for v2 source mode."))

        run_button = QPushButton("Build EXE Now")
        run_button.clicked.connect(self._run_build)
        layout.addWidget(run_button)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.setLayout(layout)

    def _run_build(self):
        result = self._builder.build()
        self.output.setPlainText(result.output)
        if result.ok:
            QMessageBox.information(self, "Build Complete", f"Build finished.\nOutput folder:\n{result.dist_path}")
        else:
            show_error(self, "Build Failed", "EXE build failed.", result.output)

