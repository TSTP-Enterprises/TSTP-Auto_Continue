import copy
import logging
import os
import time

import cv2
import mss
import numpy as np
import pyautogui
from PyQt5.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QFileDialog,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
    QInputDialog,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from app.automation.engine import AutomationEngine
from app.build.exe_builder import ExeBuilder, is_frozen
from app.controls.hotkeys import GlobalHotkeyService, HotkeyError, normalize_hotkey
from app.controls.watchdog import EngineWatchdog
from app.core.logger import configure_logging
from app.core.models import AppConfig, TargetSpec
from app.core.settings_store import SettingsStore
from app.core.time_units import to_seconds
from app.ocr.service import OCRService
from app.ui.dialogs import (
    BuildExeDialog,
    HotkeyCaptureDialog,
    OCRSetupDialog,
    TargetEditorDialog,
    show_error,
)


class _FixedWidthScrollArea(QScrollArea):
    def __init__(self, parent: QWidget | None = None, minimum_content_height: int = 340):
        super().__init__(parent)
        self._minimum_content_height = max(120, int(minimum_content_height))
        self._content: QWidget | None = None
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.viewport().installEventFilter(self)

    def setWidget(self, widget: QWidget):  # noqa: N802 - Qt API
        super().setWidget(widget)
        self._content = widget
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        QTimer.singleShot(1, self.sync_content_geometry)

    def eventFilter(self, obj: QObject, event: QEvent):  # noqa: N802 - Qt API
        if obj is self.viewport() and event.type() == QEvent.Resize:
            self.sync_content_geometry()
        return super().eventFilter(obj, event)

    def sync_content_geometry(self):
        if self._content is None:
            return
        viewport_width = max(1, self.viewport().width())
        self._content.setFixedWidth(viewport_width)
        layout = self._content.layout()
        if layout is not None:
            self._content.setMinimumHeight(max(self._minimum_content_height, layout.sizeHint().height()))


class _MousePathPreview(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._points: list[tuple[float, float]] = []
        self._scene_size = (1.0, 1.0)
        self.setMinimumHeight(180)
        self.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; border-radius: 6px;")

    def set_scene_size(self, width: int, height: int):
        self._scene_size = (max(1.0, float(width)), max(1.0, float(height)))
        self.update()

    def clear_path(self):
        self._points.clear()
        self.update()

    def add_point(self, x: float, y: float):
        self._points.append((x, y))
        if len(self._points) > 300:
            self._points = self._points[-300:]
        self.update()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self._points:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Movement path will appear here")
            return

        scene_width, scene_height = self._scene_size
        x_scale = max(1.0, self.width() - 12) / scene_width
        y_scale = max(1.0, self.height() - 12) / scene_height

        pen = QPen(QColor("#38bdf8"))
        pen.setWidth(2)
        painter.setPen(pen)

        previous = None
        for x, y in self._points:
            mapped = QPoint(int(6 + x * x_scale), int(6 + y * y_scale))
            if previous is not None:
                painter.drawLine(previous, mapped)
            previous = mapped

        painter.setPen(QPen(QColor("#22c55e"), 3))
        for x, y in self._points[-40:]:
            mapped = QPoint(int(6 + x * x_scale), int(6 + y * y_scale))
            painter.drawPoint(mapped)


class MainWindow(QMainWindow):
    emergency_signal = pyqtSignal(str)
    start_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        configure_logging()

        self._store = SettingsStore()
        self._config: AppConfig = self._store.load()
        self._engine: AutomationEngine | None = None
        self._monitoring_expected = False
        self._allow_quit = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._test_timer = QTimer(self)
        self._test_timer.timeout.connect(self._run_test_cycle)
        self._test_active = False
        self._test_total_clicks = 0
        self._test_sequence_index = 0
        self._test_started_at = 0.0
        self._test_buttons: dict[str, QPushButton] = {}
        self._test_click_counts: dict[str, int] = {}
        self._test_templates: dict[str, np.ndarray] = {}
        self._test_surface_paused = False
        self._target_monitor_click_counts: dict[str, int] = {}
        self._monitor_started_at = 0.0

        self._ocr_service = OCRService()
        self._hotkey_service = GlobalHotkeyService(self._on_hotkey_pressed)
        self._start_hotkey_service = GlobalHotkeyService(self._on_start_hotkey_pressed)
        self.emergency_signal.connect(self._panic_stop)
        self.start_signal.connect(self._handle_start_hotkey)

        self._project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        icon_path = os.path.join(self._project_root, "app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setWindowTitle("TSTP AutoClicker v2")
        self.resize(1220, 780)
        self._build_ui()
        self._load_config_to_form()
        self._refresh_target_lists()
        self._setup_tray_icon()

        self._apply_hotkey(self._config.emergency_hotkey, show_success=False)
        self._apply_start_hotkey(self._config.start_hotkey, show_success=False)
        self._watchdog = EngineWatchdog(
            self,
            should_be_running=self._should_be_running,
            is_alive=self._engine_alive,
            recover=self._recover_engine,
        )

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_kid_tab(), "Kid Mode")
        self.tabs.addTab(self._build_advanced_tab(), "Advanced")
        self.tabs.addTab(self._build_test_tab(), "Test")
        layout.addWidget(self.tabs)

        self.setCentralWidget(root)

    def _setup_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logging.warning("System tray is not available on this system.")
            return

        self._tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        tray_menu = QMenu()

        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show_from_tray)
        tray_menu.addAction(show_action)

        hide_action = QAction("Minimize to Tray", self)
        hide_action.triggered.connect(self.minimize_to_tray)
        tray_menu.addAction(hide_action)

        tray_menu.addSeparator()

        kid_mode_action = QAction("Open Kid Mode", self)
        kid_mode_action.triggered.connect(lambda: self.open_mode_tab(0))
        tray_menu.addAction(kid_mode_action)

        advanced_mode_action = QAction("Open Advanced Mode", self)
        advanced_mode_action.triggered.connect(lambda: self.open_mode_tab(1))
        tray_menu.addAction(advanced_mode_action)

        tray_menu.addSeparator()

        start_action = QAction("Start Monitoring", self)
        start_action.triggered.connect(self.start_monitoring)
        tray_menu.addAction(start_action)

        stop_action = QAction("Stop Monitoring", self)
        stop_action.triggered.connect(self.stop_monitoring)
        tray_menu.addAction(stop_action)

        emergency_action = QAction("Emergency Stop", self)
        emergency_action.triggered.connect(lambda: self._panic_stop("Emergency stop from tray menu"))
        tray_menu.addAction(emergency_action)

        tray_menu.addSeparator()

        self.tray_minimize_on_close_action = QAction("Minimize on Close", self)
        self.tray_minimize_on_close_action.setCheckable(True)
        self.tray_minimize_on_close_action.setChecked(self._config.minimize_to_tray_on_close)
        self.tray_minimize_on_close_action.triggered.connect(self._toggle_minimize_on_close_from_tray)
        tray_menu.addAction(self.tray_minimize_on_close_action)

        self.tray_minimize_on_start_action = QAction("Minimize on Start", self)
        self.tray_minimize_on_start_action.setCheckable(True)
        self.tray_minimize_on_start_action.setChecked(self._config.minimize_on_start)
        self.tray_minimize_on_start_action.triggered.connect(self._toggle_minimize_on_start_from_tray)
        tray_menu.addAction(self.tray_minimize_on_start_action)

        tray_menu.addSeparator()

        exit_action = QAction("Exit App", self)
        exit_action.triggered.connect(self.exit_from_tray)
        tray_menu.addAction(exit_action)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_from_tray()

    def _toggle_minimize_on_close_from_tray(self):
        self._config.minimize_to_tray_on_close = self.tray_minimize_on_close_action.isChecked()
        self.minimize_to_tray_checkbox.setChecked(self._config.minimize_to_tray_on_close)
        self._store.save(self._config)

    def _toggle_minimize_on_start_from_tray(self):
        self._config.minimize_on_start = self.tray_minimize_on_start_action.isChecked()
        self._sync_minimize_on_start_controls()
        self._store.save(self._config)

    def _toggle_minimize_on_start_from_kid(self, checked: bool):
        self._config.minimize_on_start = checked
        self._sync_minimize_on_start_controls()
        self._store.save(self._config)

    def _toggle_kid_instructions(self, expanded: bool):
        if hasattr(self, "kid_instruction_body"):
            self.kid_instruction_body.setVisible(expanded)
        if hasattr(self, "kid_instruction_toggle"):
            self.kid_instruction_toggle.setText("Hide Instructions" if expanded else "Show Instructions")

    def _sync_minimize_on_start_controls(self):
        if hasattr(self, "minimize_on_start_checkbox"):
            self.minimize_on_start_checkbox.blockSignals(True)
            self.minimize_on_start_checkbox.setChecked(self._config.minimize_on_start)
            self.minimize_on_start_checkbox.blockSignals(False)
        if hasattr(self, "kid_minimize_on_start_toggle"):
            self.kid_minimize_on_start_toggle.blockSignals(True)
            self.kid_minimize_on_start_toggle.setChecked(self._config.minimize_on_start)
            self.kid_minimize_on_start_toggle.blockSignals(False)
        if hasattr(self, "tray_minimize_on_start_action"):
            self.tray_minimize_on_start_action.blockSignals(True)
            self.tray_minimize_on_start_action.setChecked(self._config.minimize_on_start)
            self.tray_minimize_on_start_action.blockSignals(False)

    def open_mode_tab(self, index: int):
        self.tabs.setCurrentIndex(index)
        self.show_from_tray()

    def minimize_to_tray(self):
        if self._tray_icon is None:
            return
        self.hide()
        self._tray_icon.showMessage(
            "TSTP AutoClicker v2",
            "Running in system tray. Right-click tray icon for controls.",
            QSystemTrayIcon.Information,
            2500,
        )

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def exit_from_tray(self):
        self._allow_quit = True
        self.close()

    def _build_kid_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.kid_status_label = QLabel("Status: Stopped")
        self.kid_status_label.setFont(QFont("Arial", 24, QFont.Bold))
        self.kid_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.kid_status_label)

        self.kid_click_count_label = QLabel("Clicks this cycle: 0")
        self.kid_click_count_label.setFont(QFont("Arial", 16))
        self.kid_click_count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.kid_click_count_label)

        self.kid_instruction_toggle = QPushButton("Show Instructions")
        self.kid_instruction_toggle.setCheckable(True)
        self.kid_instruction_toggle.toggled.connect(
            lambda expanded: self._toggle_kid_instructions(expanded)
        )
        layout.addWidget(self.kid_instruction_toggle)

        self.kid_instruction_body = QLabel(
            "Step 1: Pick one or more pictures so the app knows what to click.\n"
            "Step 2: (Optional) Edit names to something easy to read.\n"
            "Step 3: Turn on Minimize on Start if you want it to hide to tray when running.\n"
            "Step 4: Press START to begin.\n"
            "Step 5: Press EMERGENCY any time to stop instantly.\n"
            "Step 6: Watch the Target Dashboard to confirm each image is being clicked."
        )
        self.kid_instruction_body.setWordWrap(True)
        self.kid_instruction_body.setStyleSheet("font-size: 14px; color: #334155;")
        self.kid_instruction_body.setVisible(False)
        layout.addWidget(self.kid_instruction_body)

        target_group = QGroupBox("Click Pictures (Kid Friendly)")
        target_layout = QVBoxLayout(target_group)
        self.kid_click_target_list = QListWidget()
        target_layout.addWidget(self.kid_click_target_list)

        target_buttons = QHBoxLayout()
        self.kid_add_target_button = QPushButton("Pick Picture")
        self.kid_add_target_button.clicked.connect(self.kid_add_click_target)
        target_buttons.addWidget(self.kid_add_target_button)

        self.kid_edit_target_button = QPushButton("Edit Selected")
        self.kid_edit_target_button.clicked.connect(self.kid_edit_click_target)
        target_buttons.addWidget(self.kid_edit_target_button)

        self.kid_remove_target_button = QPushButton("Remove Selected")
        self.kid_remove_target_button.clicked.connect(self.kid_remove_click_target)
        target_buttons.addWidget(self.kid_remove_target_button)
        target_layout.addLayout(target_buttons)
        layout.addWidget(target_group)

        self.kid_minimize_on_start_toggle = QCheckBox("Minimize on Start")
        self.kid_minimize_on_start_toggle.toggled.connect(self._toggle_minimize_on_start_from_kid)
        layout.addWidget(self.kid_minimize_on_start_toggle)

        controls_row = QHBoxLayout()
        self.kid_start_button = QPushButton("START")
        self.kid_start_button.setMinimumHeight(70)
        self.kid_start_button.setStyleSheet("font-size: 26px; background-color: #2e7d32; color: white;")
        self.kid_start_button.clicked.connect(self.start_monitoring)
        controls_row.addWidget(self.kid_start_button)

        self.kid_stop_button = QPushButton("STOP")
        self.kid_stop_button.setMinimumHeight(70)
        self.kid_stop_button.setStyleSheet("font-size: 26px; background-color: #1565c0; color: white;")
        self.kid_stop_button.clicked.connect(self.stop_monitoring)
        controls_row.addWidget(self.kid_stop_button)

        self.kid_panic_button = QPushButton("EMERGENCY")
        self.kid_panic_button.setMinimumHeight(70)
        self.kid_panic_button.setStyleSheet("font-size: 28px; background-color: #b71c1c; color: white;")
        self.kid_panic_button.clicked.connect(lambda: self._panic_stop("Emergency stop button pressed"))
        controls_row.addWidget(self.kid_panic_button)

        self.kid_minimize_button = QPushButton("MINIMIZE TO TRAY")
        self.kid_minimize_button.setMinimumHeight(70)
        self.kid_minimize_button.setStyleSheet("font-size: 20px; background-color: #475569; color: white;")
        self.kid_minimize_button.clicked.connect(self.minimize_to_tray)
        controls_row.addWidget(self.kid_minimize_button)
        layout.addLayout(controls_row)

        dashboard_group = QGroupBox("Target Dashboard")
        dashboard_layout = QVBoxLayout(dashboard_group)
        self.kid_dashboard_list = QListWidget()
        dashboard_layout.addWidget(self.kid_dashboard_list)
        layout.addWidget(dashboard_group)

        return tab

    def _build_advanced_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        scroll = _FixedWidthScrollArea(tab, minimum_content_height=680)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)

        settings_group = QGroupBox("Runtime Settings")
        settings_layout = QGridLayout(settings_group)

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.001, 600000.0)
        self.interval_spin.setDecimals(3)
        settings_layout.addWidget(QLabel("Scan Interval"), 0, 0)
        settings_layout.addWidget(self.interval_spin, 0, 1)
        self.interval_unit_combo = QComboBox()
        self.interval_unit_combo.addItems(["ms", "s", "min"])
        settings_layout.addWidget(self.interval_unit_combo, 0, 2)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["parallel", "sequence"])
        settings_layout.addWidget(QLabel("Click Mode"), 1, 0)
        settings_layout.addWidget(self.mode_combo, 1, 1, 1, 2)

        self.reset_spin = QDoubleSpinBox()
        self.reset_spin.setRange(0.001, 600000.0)
        self.reset_spin.setDecimals(3)
        settings_layout.addWidget(QLabel("Sequence Reset Time"), 2, 0)
        settings_layout.addWidget(self.reset_spin, 2, 1)
        self.reset_unit_combo = QComboBox()
        self.reset_unit_combo.addItems(["ms", "s", "min"])
        settings_layout.addWidget(self.reset_unit_combo, 2, 2)

        self.max_clicks_spin = QSpinBox()
        self.max_clicks_spin.setRange(1, 1000)
        settings_layout.addWidget(QLabel("Max Clicks/Cycle"), 3, 0)
        settings_layout.addWidget(self.max_clicks_spin, 3, 1, 1, 2)

        self.show_mouse_movement_checkbox = QCheckBox("Show mouse movement before clicking")
        self.show_mouse_movement_checkbox.toggled.connect(self._sync_mouse_movement_controls)
        settings_layout.addWidget(self.show_mouse_movement_checkbox, 4, 0, 1, 3)

        self.mouse_move_duration_spin = QDoubleSpinBox()
        self.mouse_move_duration_spin.setRange(1.0, 10000.0)
        self.mouse_move_duration_spin.setDecimals(2)
        settings_layout.addWidget(QLabel("Mouse Move Duration"), 5, 0)
        settings_layout.addWidget(self.mouse_move_duration_spin, 5, 1)
        self.mouse_move_duration_unit_combo = QComboBox()
        self.mouse_move_duration_unit_combo.addItems(["ms", "s", "min"])
        settings_layout.addWidget(self.mouse_move_duration_unit_combo, 5, 2)

        self.notifications_checkbox = QCheckBox("Enable notifications")
        settings_layout.addWidget(self.notifications_checkbox, 6, 0, 1, 3)

        self.restart_prompt_checkbox = QCheckBox("Prompt restart after emergency stop")
        settings_layout.addWidget(self.restart_prompt_checkbox, 7, 0, 1, 3)

        self.minimize_to_tray_checkbox = QCheckBox("Minimize to tray when closing window")
        settings_layout.addWidget(self.minimize_to_tray_checkbox, 8, 0, 1, 3)

        self.minimize_on_start_checkbox = QCheckBox("Minimize to tray when monitoring starts")
        self.minimize_on_start_checkbox.toggled.connect(
            lambda checked: self._toggle_minimize_on_start_from_kid(checked)
        )
        settings_layout.addWidget(self.minimize_on_start_checkbox, 9, 0, 1, 3)

        self.hotkey_input = QLineEdit()
        settings_layout.addWidget(QLabel("Emergency Hotkey"), 10, 0)
        settings_layout.addWidget(self.hotkey_input, 10, 1)
        capture_hotkey_button = QPushButton("Capture")
        capture_hotkey_button.clicked.connect(self.capture_hotkey)
        settings_layout.addWidget(capture_hotkey_button, 10, 2)

        self.start_hotkey_input = QLineEdit()
        settings_layout.addWidget(QLabel("Start Hotkey"), 11, 0)
        settings_layout.addWidget(self.start_hotkey_input, 11, 1)
        capture_start_hotkey_button = QPushButton("Capture")
        capture_start_hotkey_button.clicked.connect(self.capture_start_hotkey)
        settings_layout.addWidget(capture_start_hotkey_button, 11, 2)

        apply_hotkey_button = QPushButton("Apply Emergency Hotkey")
        apply_hotkey_button.clicked.connect(self.apply_hotkey)
        settings_layout.addWidget(apply_hotkey_button, 12, 0, 1, 3)

        apply_start_hotkey_button = QPushButton("Apply Start Hotkey")
        apply_start_hotkey_button.clicked.connect(self.apply_start_hotkey)
        settings_layout.addWidget(apply_start_hotkey_button, 13, 0, 1, 3)

        ocr_button = QPushButton("Open OCR Setup Wizard")
        ocr_button.clicked.connect(self.open_ocr_setup)
        settings_layout.addWidget(ocr_button, 14, 0, 1, 2)
        self.ocr_label = QLabel("(No OCR path)")
        self.ocr_label.setWordWrap(True)
        settings_layout.addWidget(self.ocr_label, 14, 2)

        control_row = QHBoxLayout()
        start_button = QPushButton("Start")
        start_button.clicked.connect(self.start_monitoring)
        control_row.addWidget(start_button)
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self.stop_monitoring)
        control_row.addWidget(stop_button)
        panic_button = QPushButton("Emergency")
        panic_button.clicked.connect(lambda: self._panic_stop("Manual emergency stop from Advanced tab"))
        control_row.addWidget(panic_button)
        tray_button = QPushButton("Minimize to Tray")
        tray_button.clicked.connect(self.minimize_to_tray)
        control_row.addWidget(tray_button)
        save_button = QPushButton("Save Settings")
        save_button.clicked.connect(self.save_settings)
        control_row.addWidget(save_button)
        settings_layout.addLayout(control_row, 15, 0, 1, 3)
        content_layout.addWidget(settings_group)

        build_console_group = QGroupBox("Build and Console")
        build_console_layout = QVBoxLayout(build_console_group)
        if not is_frozen():
            build_button = QPushButton("Build EXE")
            build_button.clicked.connect(self.open_build_dialog)
            build_console_layout.addWidget(build_button)
        else:
            disabled_label = QLabel("Build EXE is disabled inside packaged executable.")
            build_console_layout.addWidget(disabled_label)
        self.advanced_console = QPlainTextEdit()
        self.advanced_console.setReadOnly(True)
        self.advanced_console.setMinimumHeight(180)
        build_console_layout.addWidget(self.advanced_console)
        content_layout.addWidget(build_console_group)

        targets_row = QHBoxLayout()

        click_group = QGroupBox("Click Targets (ordered top -> bottom)")
        click_layout = QVBoxLayout(click_group)
        self.click_target_list = QListWidget()
        click_layout.addWidget(self.click_target_list)
        click_button_row = QHBoxLayout()
        add_click_button = QPushButton("Add")
        add_click_button.clicked.connect(self.add_click_target)
        click_button_row.addWidget(add_click_button)
        edit_click_button = QPushButton("Edit")
        edit_click_button.clicked.connect(self.edit_click_target)
        click_button_row.addWidget(edit_click_button)
        remove_click_button = QPushButton("Remove")
        remove_click_button.clicked.connect(self.remove_click_target)
        click_button_row.addWidget(remove_click_button)
        up_click_button = QPushButton("Up")
        up_click_button.clicked.connect(self.move_click_target_up)
        click_button_row.addWidget(up_click_button)
        down_click_button = QPushButton("Down")
        down_click_button.clicked.connect(self.move_click_target_down)
        click_button_row.addWidget(down_click_button)
        click_layout.addLayout(click_button_row)
        targets_row.addWidget(click_group, 1)

        stop_group = QGroupBox("Emergency Stop Targets")
        stop_layout = QVBoxLayout(stop_group)
        self.stop_target_list = QListWidget()
        stop_layout.addWidget(self.stop_target_list)
        stop_button_row = QHBoxLayout()
        add_stop_button = QPushButton("Add")
        add_stop_button.clicked.connect(self.add_stop_target)
        stop_button_row.addWidget(add_stop_button)
        edit_stop_button = QPushButton("Edit")
        edit_stop_button.clicked.connect(self.edit_stop_target)
        stop_button_row.addWidget(edit_stop_button)
        remove_stop_button = QPushButton("Remove")
        remove_stop_button.clicked.connect(self.remove_stop_target)
        stop_button_row.addWidget(remove_stop_button)
        toggle_stop_button = QPushButton("Toggle ON/OFF")
        toggle_stop_button.clicked.connect(self.toggle_stop_target)
        stop_button_row.addWidget(toggle_stop_button)
        stop_layout.addLayout(stop_button_row)
        targets_row.addWidget(stop_group, 1)

        content_layout.addLayout(targets_row)

        status_group = QGroupBox("Advanced Status")
        status_layout = QVBoxLayout(status_group)
        self.advanced_status_label = QLabel("Status: Stopped")
        status_layout.addWidget(self.advanced_status_label)
        self.advanced_status_detail_label = QLabel("Details: Waiting for activity.")
        status_layout.addWidget(self.advanced_status_detail_label)
        content_layout.addWidget(status_group)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        tab_layout.addWidget(scroll)
        return tab

    def _build_test_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        title = QLabel("Live Test Harness")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Each test click is vision-verified from the live test surface before click execution."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #334155;")
        layout.addWidget(subtitle)

        metrics_row = QHBoxLayout()
        self.test_status_label = QLabel("Test: Stopped")
        self.test_status_label.setStyleSheet("font-weight: 600;")
        metrics_row.addWidget(self.test_status_label)
        self.test_total_clicks_label = QLabel("Total Clicks: 0")
        metrics_row.addWidget(self.test_total_clicks_label)
        self.test_speed_label = QLabel("Speed: 0.00 clicks/sec")
        metrics_row.addWidget(self.test_speed_label)
        metrics_row.addStretch(1)
        layout.addLayout(metrics_row)

        controls = QHBoxLayout()
        start_test = QPushButton("Start Test")
        start_test.clicked.connect(self.start_test_run)
        controls.addWidget(start_test)
        stop_test = QPushButton("Stop Test")
        stop_test.clicked.connect(self.stop_test_run)
        controls.addWidget(stop_test)
        reset_test = QPushButton("Reset Counters")
        reset_test.clicked.connect(self.reset_test_counters)
        controls.addWidget(reset_test)
        clear_path = QPushButton("Clear Path")
        clear_path.clicked.connect(self.clear_test_path)
        controls.addWidget(clear_path)
        refresh_buttons = QPushButton("Refresh Buttons")
        refresh_buttons.clicked.connect(self._refresh_test_buttons)
        controls.addWidget(refresh_buttons)
        controls.addStretch(1)
        layout.addLayout(controls)

        path_group = QGroupBox("Mouse Movement Path")
        path_layout = QVBoxLayout(path_group)
        self.test_path_preview = _MousePathPreview()
        path_layout.addWidget(self.test_path_preview)
        layout.addWidget(path_group)

        self.test_buttons_scroll = QScrollArea()
        self.test_buttons_scroll.setWidgetResizable(True)
        self.test_buttons_container = QWidget()
        self.test_buttons_layout = QGridLayout(self.test_buttons_container)
        self.test_buttons_layout.setSpacing(10)
        self.test_buttons_scroll.setWidget(self.test_buttons_container)
        layout.addWidget(self.test_buttons_scroll, stretch=1)

        return tab

    def _load_config_to_form(self):
        self.interval_spin.setValue(self._config.scan_interval_value)
        self.interval_unit_combo.setCurrentText(self._config.scan_interval_unit)
        self.mode_combo.setCurrentText(self._config.mode)
        self.reset_spin.setValue(self._config.sequence_reset_value)
        self.reset_unit_combo.setCurrentText(self._config.sequence_reset_unit)
        self.max_clicks_spin.setValue(self._config.max_clicks_per_cycle)
        self.show_mouse_movement_checkbox.setChecked(self._config.show_mouse_movement)
        self.mouse_move_duration_spin.setValue(self._config.mouse_move_duration_value)
        self.mouse_move_duration_unit_combo.setCurrentText(self._config.mouse_move_duration_unit)
        self.notifications_checkbox.setChecked(self._config.notifications_enabled)
        self.restart_prompt_checkbox.setChecked(self._config.prompt_restart_after_emergency_stop)
        self.minimize_to_tray_checkbox.setChecked(self._config.minimize_to_tray_on_close)
        self.hotkey_input.setText(self._config.emergency_hotkey)
        if hasattr(self, "start_hotkey_input"):
            self.start_hotkey_input.setText(self._config.start_hotkey)
        self.ocr_label.setText(self._config.ocr_path or "(No OCR path)")
        self._sync_mouse_movement_controls()
        self._sync_minimize_on_start_controls()

    def _sync_mouse_movement_controls(self):
        enabled = self.show_mouse_movement_checkbox.isChecked()
        self.mouse_move_duration_spin.setEnabled(enabled)
        self.mouse_move_duration_unit_combo.setEnabled(enabled)

    def _pull_form_to_config(self):
        self._config.scan_interval_value = self.interval_spin.value()
        self._config.scan_interval_unit = self.interval_unit_combo.currentText()
        self._config.mode = self.mode_combo.currentText()
        self._config.sequence_reset_value = self.reset_spin.value()
        self._config.sequence_reset_unit = self.reset_unit_combo.currentText()
        self._config.max_clicks_per_cycle = self.max_clicks_spin.value()
        self._config.show_mouse_movement = self.show_mouse_movement_checkbox.isChecked()
        self._config.mouse_move_duration_value = self.mouse_move_duration_spin.value()
        self._config.mouse_move_duration_unit = self.mouse_move_duration_unit_combo.currentText()
        self._config.notifications_enabled = self.notifications_checkbox.isChecked()
        self._config.prompt_restart_after_emergency_stop = self.restart_prompt_checkbox.isChecked()
        self._config.minimize_to_tray_on_close = self.minimize_to_tray_checkbox.isChecked()
        self._config.minimize_on_start = self.minimize_on_start_checkbox.isChecked()
        if hasattr(self, "start_hotkey_input"):
            self._config.start_hotkey = self.start_hotkey_input.text().strip() or self._config.start_hotkey
        if hasattr(self, "tray_minimize_on_close_action"):
            self.tray_minimize_on_close_action.setChecked(self._config.minimize_to_tray_on_close)
        self._sync_minimize_on_start_controls()
        self._sync_sequence_order()

    def _refresh_target_lists(self):
        self.click_target_list.clear()
        click_lookup = {target.id: target for target in self._config.click_targets}
        ordered_ids = [target_id for target_id in self._config.sequence_order if target_id in click_lookup]
        for target in self._config.click_targets:
            if target.id not in ordered_ids:
                ordered_ids.append(target.id)

        for target_id in ordered_ids:
            target = click_lookup[target_id]
            item = QListWidgetItem(target.label())
            item.setData(Qt.UserRole, target.id)
            self.click_target_list.addItem(item)

        if hasattr(self, "kid_click_target_list"):
            self.kid_click_target_list.clear()
            for target_id in ordered_ids:
                target = click_lookup[target_id]
                kid_item = QListWidgetItem(target.label())
                kid_item.setData(Qt.UserRole, target.id)
                self.kid_click_target_list.addItem(kid_item)

        self.stop_target_list.clear()
        for target in self._config.stop_targets:
            item = QListWidgetItem(target.label())
            item.setData(Qt.UserRole, target.id)
            self.stop_target_list.addItem(item)
        self._refresh_test_buttons()
        self._refresh_kid_dashboard()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    def _refresh_test_buttons(self):
        if not hasattr(self, "test_buttons_layout"):
            return

        self._clear_layout(self.test_buttons_layout)
        self._test_buttons = {}
        self._test_templates = {}
        existing_counts = dict(self._test_click_counts)
        self._test_click_counts = {}

        image_targets = [target for target in self._config.click_targets if target.target_type == "image"]
        if not image_targets:
            empty = QLabel("No click targets yet. Add targets in Kid Mode or Advanced tab.")
            empty.setStyleSheet("color: #64748b; font-size: 14px;")
            self.test_buttons_layout.addWidget(empty, 0, 0)
            return

        columns = 4
        for index, target in enumerate(image_targets):
            button = QPushButton()
            button.setMinimumSize(180, 150)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            button.clicked.connect(lambda _checked=False, target_id=target.id: self._record_test_click(target_id))

            if os.path.exists(target.value):
                pixmap = QPixmap(target.value)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(QSize(120, 90), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    button.setIcon(QIcon(scaled))
                    button.setIconSize(scaled.size())
                    template = self._pixmap_to_gray_array(scaled)
                    if template is not None:
                        self._test_templates[target.id] = template
            button.setStyleSheet("text-align: center; padding: 8px;")
            self._test_buttons[target.id] = button
            self._test_click_counts[target.id] = existing_counts.get(target.id, 0)
            self._update_test_button_caption(target.id)

            row = index // columns
            col = index % columns
            self.test_buttons_layout.addWidget(button, row, col)
        if hasattr(self, "test_path_preview"):
            self.test_path_preview.set_scene_size(self.test_buttons_container.width(), self.test_buttons_container.height())
        self._refresh_kid_dashboard()

    def _pixmap_to_gray_array(self, pixmap: QPixmap):
        image = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        width = image.width()
        height = image.height()
        if width <= 0 or height <= 0:
            return None
        ptr = image.bits()
        ptr.setsize(image.byteCount())
        array = np.frombuffer(ptr, dtype=np.uint8).reshape((height, image.bytesPerLine()))
        rgb = array[:, : width * 3].reshape((height, width, 3))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return gray

    def clear_test_path(self):
        if hasattr(self, "test_path_preview"):
            self.test_path_preview.clear_path()

    def _capture_test_surface_gray(self):
        if not hasattr(self, "test_buttons_container"):
            return None
        if not self.isVisible() or self.isMinimized() or not self.test_buttons_container.isVisible():
            if not self._test_surface_paused:
                self._test_surface_paused = True
                if hasattr(self, "test_status_label"):
                    self.test_status_label.setText("Test: Waiting (targets not visible on screen)")
                self._log_console("Test paused: target surface is hidden or minimized.")
            return None

        top_left = self.test_buttons_container.mapToGlobal(self.test_buttons_container.rect().topLeft())
        bottom_right = self.test_buttons_container.mapToGlobal(self.test_buttons_container.rect().bottomRight())
        left = int(min(top_left.x(), bottom_right.x()))
        top = int(min(top_left.y(), bottom_right.y()))
        width = int(abs(bottom_right.x() - top_left.x()) + 1)
        height = int(abs(bottom_right.y() - top_left.y()) + 1)
        if width <= 2 or height <= 2:
            return None

        try:
            with mss.mss() as capture:
                shot = np.array(
                    capture.grab(
                        {
                            "left": left,
                            "top": top,
                            "width": width,
                            "height": height,
                        }
                    )
                )
            gray = cv2.cvtColor(shot, cv2.COLOR_BGRA2GRAY)
            if hasattr(self, "test_path_preview"):
                self.test_path_preview.set_scene_size(gray.shape[1], gray.shape[0])
            if self._test_surface_paused:
                self._test_surface_paused = False
                if self._test_active and hasattr(self, "test_status_label"):
                    self.test_status_label.setText("Test: Running")
                self._log_console("Test resumed: target surface visible again.")
            return gray
        except Exception as exc:
            self._log_console(f"Test capture error: {exc}")
            return None

    def _find_target_in_test_surface(self, target_id: str, surface_gray):
        template = self._test_templates.get(target_id)
        if template is None or surface_gray is None:
            return None
        if surface_gray.shape[0] < template.shape[0] or surface_gray.shape[1] < template.shape[1]:
            return None

        result = cv2.matchTemplate(surface_gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_score, _, max_loc = cv2.minMaxLoc(result)
        target = self._find_click_target(target_id)
        threshold = max(0.70, (target.threshold - 0.10) if target else 0.75)
        if max_score < threshold:
            return None

        local_x = int(max_loc[0] + template.shape[1] // 2)
        local_y = int(max_loc[1] + template.shape[0] // 2)
        global_point = self.test_buttons_container.mapToGlobal(QPoint(local_x, local_y))
        return {
            "local_x": local_x,
            "local_y": local_y,
            "global_x": int(global_point.x()),
            "global_y": int(global_point.y()),
            "score": float(max_score),
        }

    def _perform_visible_move(self, target_x: int, target_y: int, duration: float):
        if duration <= 0:
            pyautogui.moveTo(target_x, target_y, duration=0)
            return

        start_x, start_y = pyautogui.position()
        steps = max(2, int(duration * 120))
        step_sleep = duration / steps
        for step in range(1, steps + 1):
            progress = step / steps
            next_x = int(start_x + (target_x - start_x) * progress)
            next_y = int(start_y + (target_y - start_y) * progress)
            pyautogui.moveTo(next_x, next_y, duration=0)
            time.sleep(step_sleep)

    def _update_test_button_caption(self, target_id: str):
        button = self._test_buttons.get(target_id)
        target = self._find_click_target(target_id)
        if button is None or target is None:
            return
        count = self._test_click_counts.get(target_id, 0)
        button.setText(f"{target.name}\nClicks: {count}")

    def _record_test_click(self, target_id: str):
        if target_id not in self._test_click_counts:
            self._test_click_counts[target_id] = 0
        self._test_click_counts[target_id] += 1
        self._test_total_clicks += 1
        self._update_test_button_caption(target_id)
        self._update_test_metrics()
        self._refresh_kid_dashboard()

    def _update_test_metrics(self):
        elapsed = max(0.001, time.monotonic() - self._test_started_at) if self._test_started_at else 0.0
        cps = (self._test_total_clicks / elapsed) if elapsed > 0 else 0.0
        if hasattr(self, "test_total_clicks_label"):
            self.test_total_clicks_label.setText(f"Total Clicks: {self._test_total_clicks}")
        if hasattr(self, "test_speed_label"):
            self.test_speed_label.setText(f"Speed: {cps:.2f} clicks/sec")

    def _refresh_kid_dashboard(self):
        if not hasattr(self, "kid_dashboard_list"):
            return

        self.kid_dashboard_list.clear()
        monitor_elapsed = (
            max(0.001, time.monotonic() - self._monitor_started_at)
            if self._monitoring_expected and self._monitor_started_at
            else 0.0
        )
        test_elapsed = (
            max(0.001, time.monotonic() - self._test_started_at)
            if self._test_active and self._test_started_at
            else 0.0
        )

        image_targets = [target for target in self._config.click_targets if target.target_type == "image"]
        if not image_targets:
            self.kid_dashboard_list.addItem("No image targets configured yet.")
            return

        for target in image_targets:
            monitor_count = self._target_monitor_click_counts.get(target.id, 0)
            test_count = self._test_click_counts.get(target.id, 0)
            monitor_rate = (monitor_count / monitor_elapsed) if monitor_elapsed > 0 else 0.0
            test_rate = (test_count / test_elapsed) if test_elapsed > 0 else 0.0
            total = monitor_count + test_count
            self.kid_dashboard_list.addItem(
                f"{target.name} | monitor={monitor_count} ({monitor_rate:.2f}/s) | "
                f"test={test_count} ({test_rate:.2f}/s) | total={total}"
            )

    def start_test_run(self):
        self._pull_form_to_config()
        self._refresh_test_buttons()
        if not self._test_buttons:
            QMessageBox.information(self, "No Targets", "Add at least one click image target before running test.")
            return
        self._test_started_at = time.monotonic()
        self._test_active = True
        self._test_surface_paused = False
        self.test_status_label.setText("Test: Running")
        if self._config.scan_interval_unit == "s":
            interval_ms = max(1, int(self._config.scan_interval_value * 1000))
        elif self._config.scan_interval_unit == "min":
            interval_ms = max(1, int(self._config.scan_interval_value * 60000))
        else:
            interval_ms = max(1, int(self._config.scan_interval_value))
        self._test_timer.start(interval_ms)

    def stop_test_run(self):
        self._test_active = False
        self._test_surface_paused = False
        self._test_timer.stop()
        if hasattr(self, "test_status_label"):
            self.test_status_label.setText("Test: Stopped")

    def reset_test_counters(self):
        self._test_total_clicks = 0
        self._test_sequence_index = 0
        self._test_started_at = time.monotonic() if self._test_active else 0.0
        for target_id in list(self._test_click_counts.keys()):
            self._test_click_counts[target_id] = 0
            self._update_test_button_caption(target_id)
        self._update_test_metrics()
        self._refresh_kid_dashboard()

    def _run_test_cycle(self):
        if not self._test_active:
            return
        enabled_ids = [target.id for target in self._config.click_targets if target.enabled and target.target_type == "image"]
        if not enabled_ids:
            self.stop_test_run()
            return
        surface_gray = self._capture_test_surface_gray()
        if surface_gray is None:
            return
        if self._config.mode == "sequence":
            ordered = [target_id for target_id in self._config.sequence_order if target_id in enabled_ids]
            if not ordered:
                ordered = enabled_ids
            target_id = ordered[self._test_sequence_index % len(ordered)]
            if self._trigger_test_button(target_id, surface_gray):
                self._test_sequence_index += 1
            return
        # parallel test mode
        for target_id in enabled_ids:
            self._trigger_test_button(target_id, surface_gray)

    def _trigger_test_button(self, target_id: str, surface_gray):
        button = self._test_buttons.get(target_id)
        if button is None:
            return False
        detection = self._find_target_in_test_surface(target_id, surface_gray)
        if detection is None:
            target = self._find_click_target(target_id)
            target_name = target.name if target else target_id
            self._log_console(f"Test verify failed for target '{target_name}' (not found on current frame).")
            return False

        if hasattr(self, "test_path_preview"):
            self.test_path_preview.add_point(detection["local_x"], detection["local_y"])

        if self._config.show_mouse_movement:
            try:
                duration = max(
                    0.0,
                    to_seconds(self._config.mouse_move_duration_value, self._config.mouse_move_duration_unit),
                )
                self._perform_visible_move(detection["global_x"], detection["global_y"], duration)
            except pyautogui.FailSafeException:
                self.stop_test_run()
                self._panic_stop("Test stopped by PyAutoGUI fail-safe (mouse reached a corner).")
                return False
            except Exception as exc:
                self.stop_test_run()
                show_error(self, "Test Movement Error", str(exc))
                return False
        try:
            pyautogui.click(detection["global_x"], detection["global_y"])
            self._record_test_click(target_id)
            target = self._find_click_target(target_id)
            target_name = target.name if target else target_id
            self._log_console(
                f"Test click verified for '{target_name}' score={detection['score']:.2f} "
                f"at ({detection['global_x']}, {detection['global_y']})"
            )
        except pyautogui.FailSafeException:
            self.stop_test_run()
            self._panic_stop("Test stopped by PyAutoGUI fail-safe (mouse reached a corner).")
            return False
        except Exception as exc:
            self.stop_test_run()
            show_error(self, "Test Click Error", str(exc))
            return False
        return True

    def _sync_sequence_order(self):
        ordered_ids = []
        for index in range(self.click_target_list.count()):
            item = self.click_target_list.item(index)
            target_id = item.data(Qt.UserRole)
            if target_id:
                ordered_ids.append(target_id)
        self._config.sequence_order = ordered_ids

    def _find_click_target(self, target_id: str) -> TargetSpec | None:
        for target in self._config.click_targets:
            if target.id == target_id:
                return target
        return None

    def _find_stop_target(self, target_id: str) -> TargetSpec | None:
        for target in self._config.stop_targets:
            if target.id == target_id:
                return target
        return None

    def _remove_click_target_by_id(self, target_id: str):
        self._config.click_targets = [target for target in self._config.click_targets if target.id != target_id]
        self._config.sequence_order = [id_ for id_ in self._config.sequence_order if id_ != target_id]

    def kid_add_click_target(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Pick a picture to click",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp)",
        )
        if not file_path:
            return

        default_name = os.path.splitext(os.path.basename(file_path))[0]
        name, ok = QInputDialog.getText(
            self,
            "Target Name",
            "Name for this picture target:",
            text=default_name,
        )
        if not ok:
            return
        name = name.strip() or default_name
        self._config.click_targets.append(
            TargetSpec(
                name=name,
                target_type="image",
                value=file_path,
                threshold=0.88,
                enabled=True,
            )
        )
        self._config.sequence_order = [target.id for target in self._config.click_targets]
        self._refresh_target_lists()

    def kid_edit_click_target(self):
        item = self.kid_click_target_list.currentItem() if hasattr(self, "kid_click_target_list") else None
        if item is None:
            return
        target = self._find_click_target(item.data(Qt.UserRole))
        if target is None:
            return
        dialog = TargetEditorDialog(target=copy.deepcopy(target), allow_text=False)
        if dialog.exec_() and dialog.result_target:
            replacement = dialog.result_target
            for index, existing in enumerate(self._config.click_targets):
                if existing.id == replacement.id:
                    self._config.click_targets[index] = replacement
                    break
            self._refresh_target_lists()

    def kid_remove_click_target(self):
        item = self.kid_click_target_list.currentItem() if hasattr(self, "kid_click_target_list") else None
        if item is None:
            return
        self._remove_click_target_by_id(item.data(Qt.UserRole))
        self._refresh_target_lists()

    def add_click_target(self):
        dialog = TargetEditorDialog(target=None, allow_text=False)
        if dialog.exec_() and dialog.result_target:
            self._config.click_targets.append(dialog.result_target)
            self._config.sequence_order.append(dialog.result_target.id)
            self._refresh_target_lists()

    def edit_click_target(self):
        item = self.click_target_list.currentItem()
        if item is None:
            return
        target = self._find_click_target(item.data(Qt.UserRole))
        if target is None:
            return
        dialog = TargetEditorDialog(target=copy.deepcopy(target), allow_text=False)
        if dialog.exec_() and dialog.result_target:
            replacement = dialog.result_target
            for index, existing in enumerate(self._config.click_targets):
                if existing.id == replacement.id:
                    self._config.click_targets[index] = replacement
                    break
            self._refresh_target_lists()

    def remove_click_target(self):
        item = self.click_target_list.currentItem()
        if item is None:
            return
        target_id = item.data(Qt.UserRole)
        self._remove_click_target_by_id(target_id)
        self._refresh_target_lists()

    def move_click_target_up(self):
        row = self.click_target_list.currentRow()
        if row <= 0:
            return
        item = self.click_target_list.takeItem(row)
        self.click_target_list.insertItem(row - 1, item)
        self.click_target_list.setCurrentRow(row - 1)
        self._sync_sequence_order()

    def move_click_target_down(self):
        row = self.click_target_list.currentRow()
        if row < 0 or row >= self.click_target_list.count() - 1:
            return
        item = self.click_target_list.takeItem(row)
        self.click_target_list.insertItem(row + 1, item)
        self.click_target_list.setCurrentRow(row + 1)
        self._sync_sequence_order()

    def add_stop_target(self):
        dialog = TargetEditorDialog(target=None, allow_text=True)
        if dialog.exec_() and dialog.result_target:
            self._config.stop_targets.append(dialog.result_target)
            self._refresh_target_lists()

    def edit_stop_target(self):
        item = self.stop_target_list.currentItem()
        if item is None:
            return
        target = self._find_stop_target(item.data(Qt.UserRole))
        if target is None:
            return
        dialog = TargetEditorDialog(target=copy.deepcopy(target), allow_text=True)
        if dialog.exec_() and dialog.result_target:
            replacement = dialog.result_target
            for index, existing in enumerate(self._config.stop_targets):
                if existing.id == replacement.id:
                    self._config.stop_targets[index] = replacement
                    break
            self._refresh_target_lists()

    def remove_stop_target(self):
        item = self.stop_target_list.currentItem()
        if item is None:
            return
        target_id = item.data(Qt.UserRole)
        self._config.stop_targets = [target for target in self._config.stop_targets if target.id != target_id]
        self._refresh_target_lists()

    def toggle_stop_target(self):
        item = self.stop_target_list.currentItem()
        if item is None:
            return
        target = self._find_stop_target(item.data(Qt.UserRole))
        if target is None:
            return
        target.enabled = not target.enabled
        self._refresh_target_lists()

    def capture_hotkey(self):
        try:
            dialog = HotkeyCaptureDialog(self._config.emergency_hotkey, purpose="emergency stop")
            if dialog.exec_():
                self.hotkey_input.setText(dialog.selected_hotkey)
        except Exception as exc:
            show_error(self, "Hotkey Capture Failed", str(exc))

    def capture_start_hotkey(self):
        try:
            dialog = HotkeyCaptureDialog(self._config.start_hotkey, purpose="start monitoring/tests")
            if dialog.exec_():
                self.start_hotkey_input.setText(dialog.selected_hotkey)
        except Exception as exc:
            show_error(self, "Start Hotkey Capture Failed", str(exc))

    def apply_hotkey(self):
        try:
            hotkey = self.hotkey_input.text().strip()
            self._apply_hotkey(hotkey, show_success=True)
        except Exception as exc:
            show_error(self, "Hotkey Error", str(exc))

    def apply_start_hotkey(self):
        try:
            hotkey = self.start_hotkey_input.text().strip()
            self._apply_start_hotkey(hotkey, show_success=True)
        except Exception as exc:
            show_error(self, "Start Hotkey Error", str(exc))

    def _apply_hotkey(self, hotkey: str, show_success: bool):
        try:
            normalized = normalize_hotkey(hotkey)
            normalized = self._hotkey_service.register(normalized)
            self._config.emergency_hotkey = normalized
            self.hotkey_input.setText(normalized)
            if show_success:
                QMessageBox.information(self, "Hotkey Updated", f"Emergency hotkey set to {normalized}")
        except HotkeyError as exc:
            show_error(self, "Hotkey Setup Failed", str(exc))

    def _apply_start_hotkey(self, hotkey: str, show_success: bool):
        try:
            normalized = normalize_hotkey(hotkey)
            normalized = self._start_hotkey_service.register(normalized)
            self._config.start_hotkey = normalized
            self.start_hotkey_input.setText(normalized)
            if show_success:
                QMessageBox.information(self, "Start Hotkey Updated", f"Start hotkey set to {normalized}")
        except HotkeyError as exc:
            show_error(self, "Start Hotkey Setup Failed", str(exc))

    def open_ocr_setup(self):
        dialog = OCRSetupDialog(self._ocr_service, self._config.ocr_path)
        if dialog.exec_():
            self._config.ocr_path = dialog.selected_path
            self.ocr_label.setText(self._config.ocr_path or "(No OCR path)")

    def open_build_dialog(self):
        builder = ExeBuilder(self._project_root)
        BuildExeDialog(builder).exec_()

    def save_settings(self):
        try:
            self._pull_form_to_config()
            self._store.save(self._config)
            QMessageBox.information(self, "Settings Saved", "Settings were saved successfully.")
        except Exception as exc:
            show_error(self, "Save Failed", str(exc))

    def start_monitoring(self):
        try:
            self._pull_form_to_config()
            self._store.save(self._config)
            if self._engine and self._engine.isRunning():
                self._engine.update_config(self._config)
                return

            self._engine = AutomationEngine(self._config)
            self._engine.status_signal.connect(self._set_status)
            self._engine.error_signal.connect(self._handle_engine_error)
            self._engine.emergency_signal.connect(self._panic_stop)
            self._engine.cycle_click_count_signal.connect(self._set_cycle_click_count)
            self._engine.click_executed_signal.connect(self._on_engine_click_executed)
            self._monitoring_expected = True
            if self._monitor_started_at == 0.0:
                self._monitor_started_at = time.monotonic()
            self._engine.start()
            self._set_status("Monitoring started")
            self._log_console("Monitoring started.")
            if self._config.minimize_on_start:
                self.minimize_to_tray()
        except Exception as exc:
            logging.exception("Failed to start monitoring.")
            show_error(self, "Start Failed", str(exc))

    def stop_monitoring(self):
        self._monitoring_expected = False
        if self._engine is not None:
            self._engine.stop()
            self._engine.wait(5000)
            self._engine = None
        self._set_status("Monitoring stopped")
        self._log_console("Monitoring stopped.")

    def _set_status(self, text: str):
        self.kid_status_label.setText(f"Status: {text}")
        self.advanced_status_label.setText(f"Status: {text}")
        if hasattr(self, "advanced_status_detail_label"):
            self.advanced_status_detail_label.setText(
                f"Details: mode={self._config.mode}, targets={len(self._config.click_targets)}, stop-targets={len(self._config.stop_targets)}"
            )
        self._log_console(f"STATUS: {text}")

    def _set_cycle_click_count(self, value: int):
        self.kid_click_count_label.setText(f"Clicks this cycle: {value}")
        self._log_console(f"Cycle queued clicks: {value}")

    def _on_engine_click_executed(self, target_id: str, x: int, y: int):
        self._target_monitor_click_counts[target_id] = self._target_monitor_click_counts.get(target_id, 0) + 1
        self._refresh_kid_dashboard()
        target = self._find_click_target(target_id)
        target_name = target.name if target else target_id
        self._log_console(f"Clicked target '{target_name}' at ({x}, {y})")

    def _log_console(self, message: str):
        if not hasattr(self, "advanced_console"):
            return
        timestamp = time.strftime("%H:%M:%S")
        self.advanced_console.appendPlainText(f"[{timestamp}] {message}")

    def _handle_engine_error(self, message: str):
        self.stop_monitoring()
        self._log_console(f"ERROR: {message}")
        show_error(self, "Automation Error", message)

    def _on_hotkey_pressed(self):
        self.emergency_signal.emit(f"Emergency hotkey pressed ({self._config.emergency_hotkey})")

    def _on_start_hotkey_pressed(self):
        self.start_signal.emit()

    def _handle_start_hotkey(self):
        if self._test_active or self._monitoring_expected:
            return
        if self.tabs.currentIndex() == 2:
            self.start_test_run()
            self._log_console(f"Start hotkey triggered test run ({self._config.start_hotkey})")
        else:
            self.start_monitoring()
            self._log_console(f"Start hotkey triggered monitoring ({self._config.start_hotkey})")

    def _panic_stop(self, reason: str):
        if self._monitoring_expected:
            self.stop_monitoring()
        if self._test_active:
            self.stop_test_run()
        self._log_console(f"EMERGENCY: {reason}")
        QMessageBox.warning(self, "Emergency Stop", reason)
        if self._config.prompt_restart_after_emergency_stop:
            choice = QMessageBox.question(
                self,
                "Restart Monitoring",
                "Do you want to start monitoring again?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if choice == QMessageBox.Yes:
                self.start_monitoring()

    def _should_be_running(self) -> bool:
        return self._monitoring_expected

    def _engine_alive(self) -> bool:
        return self._engine is not None and self._engine.isRunning()

    def _recover_engine(self):
        if not self._monitoring_expected:
            return
        self.stop_monitoring()
        self.start_monitoring()

    def closeEvent(self, event):
        self._pull_form_to_config()
        if self._config.minimize_to_tray_on_close and not self._allow_quit and self._tray_icon is not None:
            event.ignore()
            self.minimize_to_tray()
            return

        self.stop_monitoring()
        self.stop_test_run()
        self._hotkey_service.stop()
        self._start_hotkey_service.stop()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        event.accept()

