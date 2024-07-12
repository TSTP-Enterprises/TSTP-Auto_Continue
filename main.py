import sys
import os
import cv2
import mss
from PIL import Image
import time
import logging
import pyautogui
import webbrowser
import numpy as np
from PyQt5 import QtGui
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, pyqtSlot
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QInputDialog, QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel, QCheckBox, QHBoxLayout, QProgressBar, QShortcut
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from screeninfo import get_monitors
import json
import traceback

# Ensure the directory exists
base_dir = r'C:\TSTP\AutoContinue'
os.makedirs(base_dir, exist_ok=True)


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)
    except Exception as e:
        logging.error(f"Error in resource_path: {e}")
        return relative_path

class AutoContinueLogWindow(QDialog):
    def __init__(self):
        try:
            super().__init__()
            self.setWindowTitle("Log Window")
            self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))
            self.setGeometry(300, 300, 600, 400)
            self.layout = QVBoxLayout()

            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
            self.layout.addWidget(self.log_text)

            self.refresh_button = QPushButton("Refresh Log")
            self.refresh_button.clicked.connect(self.load_log)
            self.layout.addWidget(self.refresh_button)

            self.setLayout(self.layout)
            self.load_log()
        except Exception as e:
            logging.error(f"Error in AutoContinueLogWindow.__init__: {e}")

    def load_log(self):
        try:
            with open(os.path.join(base_dir, 'autocontinue.log'), 'r') as file:
                self.log_text.setPlainText(file.read())
        except Exception as e:
            self.log_text.setPlainText(f"Error loading log file: {e}")
            logging.error(f"Error in load_log: {e}")

class AutoContinueMonitorSelectionWindow(QDialog):
    def __init__(self, selected_monitors):
        try:
            super().__init__()
            self.setWindowTitle("Select Monitors")
            self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))
            self.setGeometry(300, 300, 400, 300)
            self.layout = QVBoxLayout()

            self.monitor_checkboxes = []
            self.selected_monitors = selected_monitors

            monitors = get_monitors()
            for i, monitor in enumerate(monitors):
                checkbox = QCheckBox(f"Monitor {i + 1} ({monitor.width}x{monitor.height})")
                checkbox.setChecked(i in self.selected_monitors)
                self.monitor_checkboxes.append(checkbox)
                self.layout.addWidget(checkbox)

            self.all_monitors_checkbox = QCheckBox("All Monitors")
            self.all_monitors_checkbox.setChecked(-1 in self.selected_monitors)
            self.layout.addWidget(self.all_monitors_checkbox)

            self.ok_button = QPushButton("OK")
            self.ok_button.clicked.connect(self.save_selection)
            self.layout.addWidget(self.ok_button)

            self.setLayout(self.layout)
        except Exception as e:
            logging.error(f"Error in AutoContinueMonitorSelectionWindow.__init__: {e}")

    def save_selection(self):
        try:
            self.selected_monitors.clear()
            for i, checkbox in enumerate(self.monitor_checkboxes):
                if checkbox.isChecked():
                    self.selected_monitors.append(i)
            if self.all_monitors_checkbox.isChecked():
                self.selected_monitors.append(-1)
            self.accept()
        except Exception as e:
            logging.error(f"Error in save_selection: {e}")

class AutoContinueInfoWindow(QDialog):
    def __init__(self, title, content):
        try:
            super().__init__()
            self.setWindowTitle(title)
            self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))
            self.setGeometry(300, 300, 400, 300)
            self.layout = QVBoxLayout()

            self.label = QLabel(content)
            self.layout.addWidget(self.label)

            self.ok_button = QPushButton("OK")
            self.ok_button.clicked.connect(self.close)
            self.layout.addWidget(self.ok_button)

            self.setLayout(self.layout)
        except Exception as e:
            logging.error(f"Error in AutoContinueInfoWindow.__init__: {e}")

class AutoContinueDonateWindow(QDialog):
    def __init__(self):
        try:
            super().__init__()
            self.setWindowTitle("Donate")
            self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))
            self.setGeometry(300, 300, 400, 200)
            self.layout = QVBoxLayout()

            self.label = QLabel("Thank you for using Auto Continue!\nWould you like to donate?")
            self.layout.addWidget(self.label)

            self.yes_button = QPushButton("Yes")
            self.yes_button.clicked.connect(self.donate)
            self.layout.addWidget(self.yes_button)

            self.ok_button = QPushButton("OK")
            self.ok_button.clicked.connect(self.close)
            self.layout.addWidget(self.ok_button)

            self.setLayout(self.layout)
        except Exception as e:
            logging.error(f"Error in AutoContinueDonateWindow.__init__: {e}")

    def donate(self):
        try:
            webbrowser.open("https://www.tstp.xyz/donate")
            self.close()
        except Exception as e:
            logging.error(f"Error in donate: {e}")

class AutoContinueBrowserMonitor(QThread):
    log_signal = pyqtSignal(str)
    notification_signal = pyqtSignal(str, str, int)
    error_signal = pyqtSignal(str)

    def __init__(self, interval, button_image_path, notifications_enabled, selected_monitors):
        try:
            super().__init__()
            self.interval = interval
            self.button_image_path = button_image_path
            self.notifications_enabled = notifications_enabled
            self.monitoring = True
            self.selected_monitors = selected_monitors
            self.button_template = cv2.imread(self.button_image_path, 0)
            self.consecutive_errors = 0
            self.max_consecutive_errors = 5
        except Exception as e:
            logging.error(f"Error in AutoContinueBrowserMonitor.__init__: {e}")
            self.error_signal.emit(f"Error initializing AutoContinueBrowserMonitor: {str(e)}")

    def run(self):
        try:
            with mss.mss() as sct:
                while self.monitoring:
                    try:
                        self.process_monitors(sct)
                        self.consecutive_errors = 0  # Reset error count on successful iteration
                    except Exception as e:
                        self.handle_error(e)
                    
                    time.sleep(self.interval)
        except Exception as e:
            logging.error(f"Critical error in AutoContinueBrowserMonitor.run: {e}")
            self.error_signal.emit(f"Critical error in monitoring: {str(e)}")

    def process_monitors(self, sct):
        monitors = get_monitors()
        for i, monitor in enumerate(monitors):
            if -1 in self.selected_monitors or i in self.selected_monitors:
                self.process_single_monitor(sct, monitor, i)

    def process_single_monitor(self, sct, monitor, monitor_index):
        try:
            monitor_dict = {
                "top": monitor.y,
                "left": monitor.x,
                "width": monitor.width,
                "height": monitor.height
            }
            screenshot = np.array(sct.grab(monitor_dict))
            gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

            result = cv2.matchTemplate(gray_screenshot, self.button_template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if max_val > 0.8:  # Adjust this threshold as needed
                button_x = monitor.x + max_loc[0] + self.button_template.shape[1] // 2
                button_y = monitor.y + max_loc[1] + self.button_template.shape[0] // 2

                pyautogui.click(button_x, button_y)

                self.log_signal.emit(f"Clicked 'Continue generation' button on monitor {monitor_index+1}")
                if self.notifications_enabled:
                    self.notification_signal.emit("TSTP:Auto Continue", f"Clicked button on monitor {monitor_index+1}", QSystemTrayIcon.Information)
        except mss.exception.ScreenShotError as e:
            raise Exception(f"ScreenShotError on monitor {monitor_index+1}: {e}")
        except Exception as e:
            raise Exception(f"Unexpected error on monitor {monitor_index+1}: {e}")

    def handle_error(self, error):
        self.consecutive_errors += 1
        error_msg = f"Error in monitoring: {str(error)}"
        logging.error(error_msg)
        self.error_signal.emit(error_msg)
        
        if self.consecutive_errors >= self.max_consecutive_errors:
            self.monitoring = False
            critical_error_msg = f"Stopping monitoring due to {self.consecutive_errors} consecutive errors"
            logging.critical(critical_error_msg)
            self.error_signal.emit(critical_error_msg)

    def stop(self):
        try:
            self.monitoring = False
        except Exception as e:
            logging.error(f"Error in AutoContinueBrowserMonitor.stop: {e}")
            self.error_signal.emit(f"Error stopping AutoContinueBrowserMonitor: {str(e)}")

class AutoContinueApp(QSystemTrayIcon):
    def __init__(self):
        try:
            super().__init__()
            self.setIcon(QIcon(resource_path("app_icon.ico")))
            self.setToolTip("TSTP:Auto Continue")

            # Setup logging
            logging.basicConfig(filename=os.path.join(base_dir, 'autocontinue.log'), level=logging.INFO,
                                format='%(asctime)s - %(levelname)s - %(message)s')

            # Load settings
            self.settings_file = os.path.join(base_dir, 'settings.json')
            self.interval = 1  # Default to 1 second
            self.notifications_enabled = True
            self.selected_monitors = [-1]  # Default to all monitors
            self.load_settings()

            # Button image path
            self.button_image_path = resource_path("button_image.png")

            # Create the menu
            self.create_menu()

            self.monitoring = False
            self.monitor_thread = None
            self.log_window = None

            # Setup watchdog timer
            self.watchdog_timer = QTimer(self)
            self.watchdog_timer.timeout.connect(self.check_monitoring_status)
            self.watchdog_timer.start(60000)  # Check every minute

            # Setup global shortcuts
            self.setup_shortcuts()

        except Exception as e:
            logging.critical(f"Critical error in AutoContinueApp.__init__: {e}")
            self.show_error_message(f"Critical error initializing application: {str(e)}")

    def create_menu(self):
        try:
            self.menu = QMenu()

            self.toggle_action = QAction("Enable", self)
            self.toggle_action.triggered.connect(self.toggle_monitoring)
            self.menu.addAction(self.toggle_action)

            self.notification_action = QAction("Disable Notifications", self)
            self.notification_action.triggered.connect(self.toggle_notifications)
            self.menu.addAction(self.notification_action)

            self.interval_action = QAction("Set Interval", self)
            self.interval_action.triggered.connect(self.set_interval)
            self.menu.addAction(self.interval_action)

            self.monitor_action = QAction("Select Monitors", self)
            self.monitor_action.triggered.connect(self.select_monitors)
            self.menu.addAction(self.monitor_action)

            self.log_action = QAction("Show Log", self)
            self.log_action.triggered.connect(self.show_log_window)
            self.menu.addAction(self.log_action)

            self.about_action = QAction("About", self)
            self.about_action.triggered.connect(lambda: self.show_info_window("About", "TSTP:Auto Continue\nVersion 1.0\nDeveloped by TSTP"))
            self.menu.addAction(self.about_action)

            self.tutorial_action = QAction("Tutorial", self)
            self.tutorial_action.triggered.connect(self.show_tutorial_window)
            self.menu.addAction(self.tutorial_action)

            self.donate_action = QAction("Donate", self)
            self.donate_action.triggered.connect(self.show_donate_window)
            self.menu.addAction(self.donate_action)

            self.tstp_action = QAction("TSTP.xyz", self)
            self.tstp_action.triggered.connect(lambda: webbrowser.open("https://www.TSTP.xyz"))
            self.menu.addAction(self.tstp_action)

            self.exit_action = QAction("Exit", self)
            self.exit_action.triggered.connect(self.exit_app)
            self.menu.addAction(self.exit_action)

            self.setContextMenu(self.menu)
        except Exception as e:
            logging.error(f"Error in create_menu: {e}")
            self.show_error_message(f"Error creating menu: {str(e)}")

    def setup_shortcuts(self):
        try:
            self.enable_shortcut = QShortcut(QKeySequence("Ctrl+Alt+E"), self)
            self.enable_shortcut.activated.connect(self.toggle_monitoring)

            self.notifications_shortcut = QShortcut(QKeySequence("Ctrl+Alt+N"), self)
            self.notifications_shortcut.activated.connect(self.toggle_notifications)
        except Exception as e:
            logging.error(f"Error in setup_shortcuts: {e}")
            self.show_error_message(f"Error setting up shortcuts: {str(e)}")

    def toggle_monitoring(self):
        try:
            if not self.monitoring:
                self.start_monitoring()
            else:
                self.stop_monitoring()
            self.save_settings()
        except Exception as e:
            logging.error(f"Error in toggle_monitoring: {e}")
            self.show_error_message(f"Error toggling monitoring: {str(e)}")

    def start_monitoring(self):
        try:
            self.monitoring = True
            self.toggle_action.setText("Disable")
            if self.notifications_enabled:
                self.showMessage("TSTP:Auto Continue", "Monitoring enabled.", QSystemTrayIcon.Information)
            logging.info("Monitoring enabled")

            self.monitor_thread = AutoContinueBrowserMonitor(self.interval, self.button_image_path, self.notifications_enabled, self.selected_monitors)
            self.monitor_thread.log_signal.connect(self.log_message)
            self.monitor_thread.notification_signal.connect(self.showMessage)
            self.monitor_thread.error_signal.connect(self.handle_monitor_error)
            self.monitor_thread.start()
        except Exception as e:
            logging.error(f"Error in start_monitoring: {e}")
            self.show_error_message(f"Error starting monitoring: {str(e)}")

    def stop_monitoring(self):
        try:
            self.monitoring = False
            self.toggle_action.setText("Enable")
            if self.notifications_enabled:
                self.showMessage("TSTP:Auto Continue", "Monitoring disabled.", QSystemTrayIcon.Information)
            logging.info("Monitoring disabled")
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
        except Exception as e:
            logging.error(f"Error in stop_monitoring: {e}")
            self.show_error_message(f"Error stopping monitoring: {str(e)}")

    def handle_monitor_error(self, error_message):
        logging.error(f"Monitor thread error: {error_message}")
        self.show_error_message(f"Monitoring error: {error_message}")
        self.stop_monitoring()
        self.toggle_action.setText("Enable")

    def check_monitoring_status(self):
        try:
            if self.monitoring and (not self.monitor_thread or not self.monitor_thread.isRunning()):
                logging.warning("Monitoring thread stopped unexpectedly. Restarting...")
                self.stop_monitoring()
                self.start_monitoring()
        except Exception as e:
            logging.error(f"Error in check_monitoring_status: {e}")

    def show_error_message(self, message):
        logging.error(message)
        self.showMessage("TSTP:Auto Continue Error", message, QSystemTrayIcon.Critical)

    def toggle_notifications(self):
        try:
            self.notifications_enabled = not self.notifications_enabled
            self.notification_action.setText("Disable Notifications" if self.notifications_enabled else "Enable Notifications")
            logging.info(f"Notifications {'enabled' if self.notifications_enabled else 'disabled'}")
            self.save_settings()
        except Exception as e:
            logging.error(f"Error in toggle_notifications: {e}")
            self.show_error_message(f"Error toggling notifications: {str(e)}")

    def set_interval(self):
        try:
            interval, ok = QInputDialog.getInt(None, "Set Interval", "Enter interval (seconds):", self.interval, 1, 60, 1)
            if ok:
                self.interval = interval
                self.save_settings()
                if self.notifications_enabled:
                    self.showMessage("TSTP:Auto Continue", f"Interval set to {self.interval} seconds.", QSystemTrayIcon.Information)
                logging.info(f"Interval set to {self.interval} seconds")
        except Exception as e:
            logging.error(f"Error in set_interval: {e}")
            self.show_error_message(f"Error setting interval: {str(e)}")

    def select_monitors(self):
        try:
            dialog = AutoContinueMonitorSelectionWindow(self.selected_monitors)
            if dialog.exec_():
                self.save_settings()
                if self.notifications_enabled:
                    self.showMessage("TSTP:Auto Continue", "Monitor selection updated.", QSystemTrayIcon.Information)
                logging.info("Monitor selection updated")
        except Exception as e:
            logging.error(f"Error in select_monitors: {e}")
            self.show_error_message(f"Error selecting monitors: {str(e)}")

    def log_message(self, message):
        try:
            logging.info(message)
        except Exception as e:
            logging.error(f"Error in log_message: {e}")

    def show_log_window(self):
        try:
            if not self.log_window:
                self.log_window = AutoContinueLogWindow()
            self.log_window.show()
        except Exception as e:
            logging.error(f"Error in show_log_window: {e}")

    def show_info_window(self, title, content):
        try:
            info_window = AutoContinueInfoWindow(title, content)
            info_window.exec_()
        except Exception as e:
            logging.error(f"Error in show_info_window: {e}")

    def show_donate_window(self):
        try:
            donate_window = AutoContinueDonateWindow()
            donate_window.exec_()
        except Exception as e:
            logging.error(f"Error in show_donate_window: {e}")

    def show_tutorial_window(self):
        try:
            tutorial_window = AutoContinueTutorialWindow()
            tutorial_window.exec_()
        except Exception as e:
            logging.error(f"Error in show_tutorial_window: {e}")

    def exit_app(self):
        try:
            self.monitoring = False
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
            logging.info("Application exited")
            self.save_settings()
            QApplication.quit()
        except Exception as e:
            logging.error(f"Error in exit_app: {e}")

    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    self.interval = settings.get('interval', 5)
                    self.notifications_enabled = settings.get('notifications_enabled', True)
                    self.selected_monitors = settings.get('selected_monitors', [-1])
        except Exception as e:
            logging.error(f"Error in load_settings: {e}")

    def save_settings(self):
        try:
            settings = {
                'interval': self.interval,
                'notifications_enabled': self.notifications_enabled,
                'selected_monitors': self.selected_monitors
            }
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            logging.error(f"Error in save_settings: {e}")

class AutoContinueTutorialWindow(QDialog):
    def __init__(self, parent=None):
        super(AutoContinueTutorialWindow, self).__init__(parent)
        self.setWindowTitle("Interactive Tutorial")
        self.setGeometry(100, 100, 800, 600)
        self.setWindowModality(Qt.ApplicationModal)

        self.layout = QVBoxLayout()

        self.webView = QWebEngineView()
        self.layout.addWidget(self.webView)

        self.navigation_layout = QHBoxLayout()

        self.home_button = QPushButton("Home")
        self.home_button.clicked.connect(self.go_to_home_page)
        self.navigation_layout.addWidget(self.home_button)

        self.back_button = QPushButton("Previous")
        self.back_button.clicked.connect(self.go_to_previous_page)
        self.navigation_layout.addWidget(self.back_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.navigation_layout.addWidget(self.progress_bar)

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.go_to_next_page)
        self.navigation_layout.addWidget(self.next_button)

        self.start_button = QPushButton("Start Using App")
        self.start_button.clicked.connect(self.close)
        self.navigation_layout.addWidget(self.start_button)

        self.layout.addLayout(self.navigation_layout)
        self.setLayout(self.layout)

        self.current_page_index = 0
        self.page_history = [self.current_page_index]
        self.tutorial_pages = [
            self.create_index_page(),
            self.create_intro_page(),
            self.create_features_page(),
            self.create_usage_page(),
            self.create_shortcuts_page(),
        ]

        self.load_tutorial_page(self.current_page_index)

        self.channel = QWebChannel()
        self.webView.page().setWebChannel(self.channel)
        self.channel.registerObject("qt", self)

    @pyqtSlot()
    def on_load_finished(self):
        self.webView.page().runJavaScript("""
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.tutorial = channel.objects.qt;
            });
        """)

    @pyqtSlot(int)
    def jupyterloadPage(self, index):
        try:
            self.load_tutorial_page(index)
        except Exception as e:
            self.log_error(f"Error loading tutorial page {index}: " + str(e))

    def load_tutorial_page(self, index):
        try:
            self.log_debug(f"Loading tutorial page {index}")
            self.current_page_index = index
            self.webView.setHtml(self.tutorial_pages[index])
            self.progress_bar.setValue(int((index + 1) / len(self.tutorial_pages) * 100))
        except Exception as e:
            self.log_error(f"Error loading tutorial page {index}: " + str(e))

    def go_to_home_page(self):
        try:
            self.load_tutorial_page(0)
            self.page_history = [0]
        except Exception as e:
            self.log_error("Error navigating to home page: " + str(e))

    def go_to_previous_page(self):
        try:
            if len(self.page_history) > 1:
                self.page_history.pop()  # Remove current page from history
                previous_page = self.page_history.pop()  # Get previous page
                self.load_tutorial_page(previous_page)
                self.page_history.append(previous_page)  # Re-add previous page
        except Exception as e:
            self.log_error("Error navigating to previous page: " + str(e))

    def go_to_next_page(self):
        try:
            if self.current_page_index < len(self.tutorial_pages) - 1:
                next_page = self.current_page_index + 1
                self.load_tutorial_page(next_page)
                self.page_history.append(next_page)
        except Exception as e:
            self.log_error("Error navigating to next page: " + str(e))

    def log_error(self, message):
        print("ERROR: " + message)

    def log_debug(self, message):
        print("DEBUG: " + message)

    def create_index_page(self):
        try:
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body { font-family: Arial, sans-serif; }
                    h1 { color: #333; }
                    p { font-size: 14px; }
                    .button-container {
                        display: flex;
                        flex-direction: column;
                        align-items: flex-start;
                    }
                    .tutorial-button {
                        margin: 5px 0;
                        padding: 10px;
                        background-color: #007BFF;
                        color: white;
                        border: none;
                        cursor: pointer;
                        width: 100%;
                        text-align: left;
                        box-sizing: border-box;
                    }
                    .tutorial-button:hover {
                        background-color: #0056b3;
                    }
                </style>
                <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
                <script>
                    document.addEventListener("DOMContentLoaded", function() {
                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            window.tutorial = {
                                loadPage: function(index) {
                                    channel.objects.qt.jupyterloadPage(index);
                                }
                            };
                        });
                    });
                </script>
            </head>
            <body>
                <h1>Welcome to TSTP:Auto Continue Tutorial</h1>
                <p>This tutorial will guide you through the features and usage of the Auto-Continue program.</p>
                <div class="button-container">
                    <button class="tutorial-button" onclick="window.tutorial.loadPage(1)">Introduction</button>
                    <button class="tutorial-button" onclick="window.tutorial.loadPage(2)">Features</button>
                    <button class="tutorial-button" onclick="window.tutorial.loadPage(3)">How to Use</button>
                    <button class="tutorial-button" onclick="window.tutorial.loadPage(4)">Shortcuts</button>
                </div>
            </body>
            </html>
            """
        except Exception as e:
            self.log_error("Error creating index page: " + str(e))
            return ""

    def create_intro_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h1 { color: #333; }
                p { font-size: 14px; }
            </style>
        </head>
        <body>
            <h1>Introduction</h1>
            <p>The Auto-Continue program is designed to automatically click the "Continue generation" button on ChatGPT.com when the response ends but there is more to display. This helps you avoid interruptions and ensures continuous generation of responses.</p>
        </body>
        </html>
        """

    def create_features_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h1 { color: #333; }
                p { font-size: 14px; }
            </style>
        </head>
        <body>
            <h1>Features</h1>
            <ul>
                <li>Automatic detection and clicking of the "Continue generation" button on ChatGPT.com</li>
                <li>Supports multiple monitors</li>
                <li>Configurable monitoring interval</li>
                <li>Enable/disable notifications</li>
                <li>View logs for monitoring activities</li>
                <li>Global keyboard shortcuts for quick actions</li>
                <li>System tray icon for easy access to features and settings</li>
            </ul>
        </body>
        </html>
        """

    def create_usage_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h1 { color: #333; }
                p { font-size: 14px; }
            </style>
        </head>
        <body>
            <h1>How to Use</h1>
            <ol>
                <li>Launch the Auto-Continue program. It will minimize to the system tray.</li>
                <li>Right-click the system tray icon to access the menu.</li>
                <li>Enable monitoring by selecting "Enable". The program will start detecting and clicking the "Continue generation" button on ChatGPT.com.</li>
                <li>Configure the monitoring interval by selecting "Set Interval". Enter the desired interval in seconds.</li>
                <li>Select specific monitors for monitoring by choosing "Select Monitors".</li>
                <li>View logs for monitoring activities by selecting "Show Log".</li>
                <li>Enable or disable notifications through the "Disable Notifications" option.</li>
            </ol>
        </body>
        </html>
        """

    def create_shortcuts_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h1 { color: #333; }
                p { font-size: 14px; }
            </style>
        </head>
        <body>
            <h1>Shortcuts</h1>
            <p>Use the following keyboard shortcuts for quick actions:</p>
            <ul>
                <li><strong>Ctrl + Alt + E:</strong> Enable/Disable monitoring</li>
                <li><strong>Ctrl + Alt + N:</strong> Enable/Disable notifications</li>
            </ul>
        </body>
        </html>
        """

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        QApplication.setQuitOnLastWindowClosed(False)
        tray_app = AutoContinueApp()
        tray_app.show()
        logging.info("Application started")
        sys.exit(app.exec_())
    except Exception as e:
        logging.critical(f"Critical error on startup: {e}")
        print(f"Critical error on startup: {e}")
        if 'tray_app' in locals():
            tray_app.show_error_message(f"Critical error on startup: {str(e)}")
