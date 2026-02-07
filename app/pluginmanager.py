import glob
import json
import os
import shutil
import tempfile
import zipfile

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget,
                             QTreeWidgetItem, QPushButton, QFileDialog,
                             QMessageBox, QHeaderView)


class PluginManager:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.plugins_dir = os.path.join(self.root_dir, "plugins")
        self.temp_dir = tempfile.mkdtemp()
        self.loaded_blocks = []
        self.plugin_statuses = []
        self.ui_themes = []
        self.failed_to_load = ""

        if not os.path.exists(self.plugins_dir):
            os.makedirs(self.plugins_dir)

    def load_plugins(self):
        self.loaded_blocks = []
        self.plugin_statuses = []
        self.ui_themes = []
        plugin_zips = glob.glob(os.path.join(self.plugins_dir, "*.zip"))

        for zip_path in plugin_zips:
            zip_name = os.path.basename(zip_path)
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    file_list = zip_ref.namelist()

                    if "ui/colors.json" in file_list:
                        try:
                            with zip_ref.open("ui/colors.json") as f:
                                self.ui_themes.append(json.load(f))
                        except Exception as te:
                            self.failed_to_load = f"Theme Error in {zip_name}: {te}"

                    if "plugin.json" in file_list:
                        with zip_ref.open("plugin.json") as f:
                            info = json.load(f)

                        for file in file_list:
                            if file.startswith("blocks/") and file.endswith(".json"):
                                target_path = os.path.join(self.temp_dir, os.path.basename(file))
                                with open(target_path, "wb") as f_out:
                                    f_out.write(zip_ref.read(file))
                                self.loaded_blocks.append(target_path)

                        self.plugin_statuses.append({
                            "name": info.get("name", zip_name),
                            "version": info.get("version", "?"),
                            "author": info.get("author", "Unknown"),
                            "description": info.get("description", "No description provided."),
                            "status": "Loaded",
                            "path": zip_path
                        })
                    else:
                        self.plugin_statuses.append({
                            "name": zip_name,
                            "version": "-",
                            "author": "-",
                            "description": "Missing plugin.json inside ZIP.",
                            "status": "Broken",
                            "path": zip_path
                        })
                        self.failed_to_load = f"Plugin Error in {zip_name}"
            except Exception as e:
                self.plugin_statuses.append({
                    "name": zip_name,
                    "version": "-",
                    "author": "-",
                    "description": str(e),
                    "status": "Error",
                    "path": zip_path
                })
                self.failed_to_load = f"Plugin Error in {zip_name}: {e}"
        return self.loaded_blocks

    def apply_plugin_theme(self, window):
        if not self.ui_themes:
            return

        theme = self.ui_themes[0]

        bg = theme.get("background", "#1a1b26")
        sidebar_bg = theme.get("sidebar", "#16161e")
        accent = theme.get("accent", "#bb9af7")
        console_bg = theme.get("console_bg", "#121214")
        line_bg = theme.get("line_numbers_background", "#2f334d")
        block_bg = theme.get("block_editor_background", "#1a1b26")
        block_sidebar_bg = theme.get("block_editor_sidebar_background", "#16161e")
        ui_text = theme.get("text", "#c0caf5")
        editor_text = theme.get("editor_text", "#a9b1d6")

        btn_hover = theme.get("button_hover", "#2f334d")

        if hasattr(window, 'terminal'):
            window.terminal.setStyleSheet("")
            window.terminal.append(self.failed_to_load)
        if hasattr(window, 'tabs'):
            window.tabs.setStyleSheet("")

        full_style = f"""
            QMainWindow, QDialog, QWidget {{ 
                background-color: {bg}; 
                color: {ui_text}; 
            }}

            /* Top Row Buttons (Build, Run, etc) */
            QPushButton[class="top_btn"] {{
                background-color: {sidebar_bg};
                border: 1px solid {line_bg};
                color: {ui_text};
            }}

            QPushButton[class="top_btn"]:hover {{
                background-color: {btn_hover};
                border: 1px solid {accent};
            }}

            /* Visual Editor Toggle Button */
            QPushButton#visual_toggle_btn {{
                background-color: {sidebar_bg};
                color: {accent};
                border: 1px solid {accent};
                font-weight: bold;
            }}

            QPushButton#visual_toggle_btn:checked {{
                background-color: {accent};
                color: {bg};
            }}

            QTreeWidget, QTreeView {{ 
                background-color: {sidebar_bg}; 
                color: {ui_text}; 
                border: none;
            }}
            BlockContainerSidebar {{
                background-color: {block_sidebar_bg};
                border: none;
            }}
            QPlainTextEdit {{
                background-color: {bg};
                color: {editor_text};
                border: none;
            }}
            LineNumberArea {{
                background-color: {line_bg};
            }}
            BlockView {{
                background-color: {block_bg};
                border: none;
            }}
            QTextEdit#terminal {{
                background-color: {console_bg};
                color: {editor_text};
            }}
            QTabBar::tab {{ 
                background: {sidebar_bg}; 
                color: {ui_text}; 
                padding: 8px 12px; 
            }}
            QTabBar::tab:selected {{ 
                background: {bg}; 
                border-bottom: 2px solid {accent}; 
            }}
        """
        window.setStyleSheet(full_style)


class PluginDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Plugin Manager")
        self.resize(700, 480)
        self.setStyleSheet("background: #1e1e1e; color: white;")

        layout = QVBoxLayout(self)

        self.list_widget = QTreeWidget()
        self.list_widget.setColumnCount(4)
        self.list_widget.setHeaderLabels(["Plugin Name", "Version", "Author", "Status"])

        header = self.list_widget.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.list_widget.setStyleSheet("""
            QTreeWidget { background: #2d2d2d; color: white; border: 1px solid #444; outline: none; }
            QHeaderView::section { background: #333; color: white; padding: 8px; border: 1px solid #444; }
        """)

        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()

        self.toggle_btn = QPushButton("Enable/Disable Selected")
        self.toggle_btn.setStyleSheet("""
            QPushButton { background: #444; color: white; padding: 10px; border-radius: 4px; }
            QPushButton:hover { background: #5a5a5a; }
        """)
        self.toggle_btn.clicked.connect(self.toggle_plugin_status)

        self.install_btn = QPushButton("Install Plugin")
        self.install_btn.setStyleSheet("""
                    QPushButton { 
                        background: #007acc; 
                        color: white; 
                        padding: 10px; 
                        font-weight: bold; 
                        border-radius: 4px; 
                    }
                    QPushButton:hover { 
                        background: #0098ff; 
                    }
                """)
        self.install_btn.clicked.connect(self.install_plugin)

        btn_layout.addWidget(self.toggle_btn)
        btn_layout.addWidget(self.install_btn)
        layout.addLayout(btn_layout)

        self.load_plugin_list()

    def load_plugin_list(self):
        self.list_widget.clear()

        all_files = glob.glob(os.path.join(self.manager.plugins_dir, "*"))
        plugin_files = [f for f in all_files if f.endswith(".zip") or f.endswith(".disabled")]

        for f_path in plugin_files:
            is_disabled = f_path.endswith(".disabled")
            filename = os.path.basename(f_path)

            name, version, author, desc = filename, "-", "-", "No metadata found."

            try:
                with zipfile.ZipFile(f_path, 'r') as z:
                    if "plugin.json" in z.namelist():
                        with z.open("plugin.json") as f:
                            data = json.load(f)
                            name = data.get("name", name)
                            version = data.get("version", "-")
                            author = data.get("author", "-")
                            desc = data.get("description", "No description.")
            except:
                pass

            status_text = "Disabled" if is_disabled else "Loaded"
            item = QTreeWidgetItem([name, version, author, status_text])
            item.setData(0, Qt.ItemDataRole.UserRole, f_path)
            item.setData(1, Qt.ItemDataRole.UserRole, desc)

            for i in range(4):
                item.setToolTip(i, desc)

            if is_disabled:
                item.setForeground(3, QColor("#888888"))
            else:
                item.setForeground(3, QColor("#007acc"))

            self.list_widget.addTopLevelItem(item)

    def toggle_plugin_status(self):
        selected = self.list_widget.currentItem()
        if not selected:
            return

        old_path = selected.data(0, Qt.ItemDataRole.UserRole)

        if old_path.endswith(".zip"):
            new_path = old_path.replace(".zip", ".zip.disabled")
            action = "Disabled"
        elif old_path.endswith(".zip.disabled"):
            new_path = old_path.replace(".zip.disabled", ".zip")
            action = "Enabled"
        else:
            return

        try:
            os.rename(old_path, new_path)
            QMessageBox.information(self, "Restart Required",
                                    f"Plugin {action}. Please restart the IDE to apply changes.")
            self.load_plugin_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not change status: {e}")

    def install_plugin(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Plugin ZIP", "", "ZIP Files (*.zip)")
        if file_path:
            try:
                shutil.copy(file_path, self.manager.plugins_dir)
                self.load_plugin_list()
                QMessageBox.information(self, "Success", "Plugin installed. Restart to load.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Installation failed: {e}")