import glob
import json
import os
import re
import shutil
import tempfile
import zipfile
import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget,
                             QTreeWidgetItem, QPushButton, QMessageBox,
                             QHeaderView, QWidget)

from .theme import (WindowTitleBar, build_app_stylesheet, resolved_theme,
                    themed_file_dialog, themed_message)


def uuid_safe_name(value):
    """Create a stable, filesystem-safe extraction directory name."""
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return clean or "plugin"


class PluginManager:
    PLUGIN_API_VERSION = 2

    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.plugins_dir = os.path.join(self.root_dir, "plugins")
        self.temp_dir = tempfile.mkdtemp()
        self.loaded_blocks = []
        self.plugin_statuses = []
        self.ui_themes = []
        self.failed_to_load = ""
        self.load_errors = []

        if not os.path.exists(self.plugins_dir):
            os.makedirs(self.plugins_dir)

    def load_plugins(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir = tempfile.mkdtemp(prefix="operationcrafter_plugins_")
        self.loaded_blocks = []
        self.plugin_statuses = []
        self.ui_themes = []
        self.load_errors = []
        self.failed_to_load = ""

        sources = sorted(glob.glob(os.path.join(self.plugins_dir, "*.zip")))
        sources += sorted(
            path for path in glob.glob(os.path.join(self.plugins_dir, "*"))
            if os.path.isdir(path) and not path.endswith(".disabled")
        )

        for source_path in sources:
            try:
                if os.path.isdir(source_path):
                    self._load_directory_plugin(source_path)
                else:
                    self._load_zip_plugin(source_path)
            except Exception as e:
                source_name = os.path.basename(source_path)
                self.plugin_statuses.append({
                    "name": source_name,
                    "version": "-",
                    "author": "-",
                    "description": str(e),
                    "status": "Broken",
                    "path": source_path,
                })
                self.load_errors.append(f"{source_name}: {e}")

        self.failed_to_load = "\n".join(f"Plugin warning: {error}" for error in self.load_errors)
        return self.loaded_blocks

    def _validate_manifest(self, info, source_name):
        if not isinstance(info, dict):
            raise ValueError("plugin.json must contain a JSON object")
        if not str(info.get("name", "")).strip():
            raise ValueError("plugin.json is missing a plugin name")
        try:
            api_version = int(info.get("api_version", 1))
        except (TypeError, ValueError):
            raise ValueError("api_version must be an integer")
        if api_version > self.PLUGIN_API_VERSION:
            raise ValueError(
                f"requires plugin API {api_version}; this app supports {self.PLUGIN_API_VERSION}"
            )
        info = dict(info)
        info["api_version"] = api_version
        info.setdefault("version", "?")
        info.setdefault("author", "Unknown")
        info.setdefault("description", "No description provided.")
        return info

    def _record_loaded(self, info, path, block_count, has_theme):
        capabilities = []
        if block_count:
            capabilities.append(f"{block_count} block file{'s' if block_count != 1 else ''}")
        if has_theme:
            capabilities.append("theme")
        detail = info.get("description", "No description provided.")
        if capabilities:
            detail += "\nProvides: " + ", ".join(capabilities)
        self.plugin_statuses.append({
            "name": info["name"],
            "version": info["version"],
            "author": info["author"],
            "description": detail,
            "status": f"Loaded (API {info['api_version']})",
            "path": path,
        })

    def _load_zip_plugin(self, zip_path):
        source_name = os.path.basename(zip_path)
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = archive.namelist()
            if "plugin.json" not in names:
                raise ValueError("missing plugin.json")
            with archive.open("plugin.json") as handle:
                info = self._validate_manifest(json.load(handle), source_name)

            theme_loaded = False
            if "ui/colors.json" in names:
                with archive.open("ui/colors.json") as handle:
                    theme = json.load(handle)
                if not isinstance(theme, dict):
                    raise ValueError("ui/colors.json must contain a JSON object")
                theme["_plugin_name"] = info["name"]
                self.ui_themes.append(theme)
                theme_loaded = True

            plugin_temp = os.path.join(
                self.temp_dir,
                uuid_safe_name(f"{os.path.splitext(source_name)[0]}_{info['name']}")
            )
            os.makedirs(plugin_temp, exist_ok=True)
            block_count = 0
            for member in names:
                normalized = member.replace("\\", "/")
                if not normalized.startswith("blocks/") or not normalized.endswith(".json"):
                    continue
                relative = normalized[len("blocks/"):]
                if not relative or ".." in relative.split("/"):
                    continue
                target_path = os.path.join(plugin_temp, *relative.split("/"))
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, "wb") as output:
                    output.write(archive.read(member))
                self.loaded_blocks.append(target_path)
                block_count += 1
            self._record_loaded(info, zip_path, block_count, theme_loaded)

    def _load_directory_plugin(self, directory):
        manifest_path = os.path.join(directory, "plugin.json")
        if not os.path.isfile(manifest_path):
            raise ValueError("directory plugin is missing plugin.json")
        with open(manifest_path, "r", encoding="utf-8") as handle:
            info = self._validate_manifest(json.load(handle), os.path.basename(directory))

        theme_loaded = False
        theme_path = os.path.join(directory, "ui", "colors.json")
        if os.path.isfile(theme_path):
            with open(theme_path, "r", encoding="utf-8") as handle:
                theme = json.load(handle)
            if not isinstance(theme, dict):
                raise ValueError("ui/colors.json must contain a JSON object")
            theme["_plugin_name"] = info["name"]
            self.ui_themes.append(theme)
            theme_loaded = True

        blocks_dir = os.path.join(directory, "blocks")
        block_paths = sorted(glob.glob(os.path.join(blocks_dir, "**", "*.json"), recursive=True))
        self.loaded_blocks.extend(block_paths)
        self._record_loaded(info, directory, len(block_paths), theme_loaded)

    def apply_plugin_theme(self, window):
        if not self.ui_themes:
            return

        theme = self.ui_themes[0]

        colors = resolved_theme(theme)
        bg = colors["background"]
        sidebar_bg = colors["sidebar"]
        accent = colors["accent"]
        console_bg = colors["console_bg"]
        line_bg = colors["line_numbers_background"]
        block_bg = colors["block_editor_background"]
        block_sidebar_bg = colors["block_editor_sidebar_background"]
        ui_text = colors["text"]
        editor_text = colors["editor_text"]

        btn_hover = colors["button_hover"]
        btn_active = colors["button_active"]
        selection = colors["selection"]
        input_bg = colors["input_background"]

        if window.__class__.__name__ in {"SettingsDialog", "HelpDialog", "PluginDialog"}:
            for child in window.findChildren(QWidget):
                child.setStyleSheet("")

        if hasattr(window, 'terminal'):
            window.terminal.setStyleSheet("")
            if self.failed_to_load and getattr(window, "_last_plugin_warning", None) != self.failed_to_load:
                window.terminal.append(self.failed_to_load)
                window._last_plugin_warning = self.failed_to_load
        if hasattr(window, 'tabs'):
            window.tabs.setStyleSheet("")
        if hasattr(window, "findChildren"):
            themed_inline_names = {
                "app_brand", "node_library_title", "node_library_search",
                "node_library_hint", "node_graph_title",
            }
            for child in window.findChildren(QWidget):
                if child.objectName() in themed_inline_names:
                    child.setStyleSheet("")

        full_style = f"""
            also in readme, so images limits i think are like 80x80, can you fix that?QMainWindow, QDialog, QWidget {{ 
                background-color: {bg}; 
                color: {ui_text}; 
            }}

            QLabel#app_brand {{
                background: transparent;
                color: {accent};
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 1px;
                padding-right: 12px;
            }}
            QLabel#Title {{
                background: transparent;
                color: {accent};
                font-size: 28px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QLabel#AppIcon {{ background: transparent; }}
            QStackedWidget {{ border: 1px solid {line_bg}; border-radius: 12px; }}

            QPushButton {{
                background-color: {sidebar_bg};
                border: 1px solid {line_bg};
                border-radius: 6px;
                padding: 6px 11px;
                color: {ui_text};
            }}
            QPushButton:hover {{ background-color: {btn_hover}; border-color: {accent}; }}
            QPushButton:pressed, QPushButton:checked {{ background-color: {selection}; }}
            QPushButton#CloseBtn {{ background: transparent; border: none; font-size: 18px; }}
            QPushButton#CloseBtn:hover {{ background: transparent; color: {accent}; }}

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
            QTreeWidget::item:hover, QTreeView::item:hover {{ background: {btn_hover}; }}
            QTreeWidget::item:selected, QTreeView::item:selected {{
                background: {selection}; color: {ui_text};
            }}
            QHeaderView::section {{
                background: {sidebar_bg}; color: {ui_text}; border: none;
                border-bottom: 1px solid {line_bg}; padding: 6px;
            }}
            QWidget#node_library_panel {{
                background-color: {block_sidebar_bg};
                border-right: 1px solid {line_bg};
            }}
            QWidget#node_toolbar {{
                background-color: {sidebar_bg};
                border-bottom: 1px solid {line_bg};
            }}
            QWidget#editor_mode_bar {{
                background-color: {sidebar_bg};
                border-bottom: 1px solid {line_bg};
            }}
            QLabel#editor_mode_title {{
                color: {accent};
                font-weight: bold;
            }}
            QLabel#node_library_title, QLabel#node_graph_title {{
                background: transparent;
                color: {accent};
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QLabel#node_library_hint {{
                background: transparent;
                color: {editor_text};
                font-size: 10px;
            }}
            QLineEdit#node_library_search, QLineEdit, QComboBox, QSpinBox {{
                background: {input_bg}; color: {ui_text}; border: 1px solid {line_bg};
                border-radius: 6px; padding: 7px 9px;
                selection-background-color: {selection};
            }}
            QLineEdit#node_library_search:focus, QLineEdit:focus,
            QComboBox:focus, QSpinBox:focus {{ border-color: {accent}; }}
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
            QTabBar::tab:hover {{ background: {btn_hover}; color: {ui_text}; }}
            QSplitter::handle {{ background: {line_bg}; width: 3px; height: 3px; }}
            QScrollBar:vertical {{ background: {bg}; width: 12px; margin: 0; }}
            QScrollBar::handle:vertical {{
                background: {selection}; min-height: 28px; border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {accent}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{ background: {bg}; height: 12px; margin: 0; }}
            QScrollBar::handle:horizontal {{
                background: {selection}; min-width: 28px; border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QMenu {{ background: {sidebar_bg}; color: {ui_text}; border: 1px solid {line_bg}; }}
            QMenu::item:selected {{ background: {selection}; }}
            QToolTip {{ background: {sidebar_bg}; color: {ui_text}; border: 1px solid {accent}; }}
        """
        # The shared builder covers every Qt surface, including empty tab pages,
        # native-looking dialogs, combo popups, title bars, and disabled states.
        full_style = build_app_stylesheet(theme)
        window.setStyleSheet(full_style)
        if hasattr(window, "centralWidget") and callable(window.centralWidget):
            central = window.centralWidget()
            if central:
                central.setStyleSheet(full_style)
        if hasattr(window, "findChildren"):
            for child in window.findChildren(QWidget):
                palette = child.palette()
                palette.setColor(QPalette.ColorRole.Link, QColor(colors["link"]))
                palette.setColor(QPalette.ColorRole.LinkVisited, QColor(colors["link"]))
                child.setPalette(palette)
                if hasattr(child, "set_node_theme"):
                    child.set_node_theme(theme)
        if hasattr(window, "set_node_theme"):
            window.set_node_theme(theme)
        # Dialogs and controls created with the fallback theme may already be
        # polished before a plugin is applied. Force Qt to discard that cached
        # blue rendering so the new theme appears immediately on every child.
        themed_widgets = [window]
        if hasattr(window, "findChildren"):
            themed_widgets.extend(window.findChildren(QWidget))
        for widget in themed_widgets:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()


class PluginDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Plugin Manager")
        self.resize(700, 480)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setStyleSheet(build_app_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 10)
        layout.addWidget(WindowTitleBar(self, self.windowTitle()))

        self.list_widget = QTreeWidget()
        self.list_widget.setColumnCount(4)
        self.list_widget.setHeaderLabels(["Plugin Name", "Version", "Author", "Status"])

        header = self.list_widget.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()

        self.toggle_btn = QPushButton("Enable/Disable Selected")
        self.toggle_btn.clicked.connect(self.toggle_plugin_status)

        self.plugins_list = QPushButton("Official Plugin Downloads")
        self.plugins_list.setProperty("role", "success")
        self.plugins_list.clicked.connect(self.open_plugins_list)

        self.install_btn = QPushButton("Install Plugin")
        self.install_btn.setProperty("role", "primary")
        self.install_btn.clicked.connect(self.install_plugin)

        self.reload_btn = QPushButton("Reload Now")
        self.reload_btn.clicked.connect(self.reload_plugins)

        btn_layout.addWidget(self.toggle_btn)
        btn_layout.addWidget(self.plugins_list)
        btn_layout.addWidget(self.reload_btn)
        btn_layout.addWidget(self.install_btn)
        layout.addLayout(btn_layout)

        self.load_plugin_list()

    def load_plugin_list(self):
        self.list_widget.clear()
        theme = self.manager.ui_themes[0] if self.manager.ui_themes else None
        colors = resolved_theme(theme)

        all_files = glob.glob(os.path.join(self.manager.plugins_dir, "*"))
        plugin_files = [
            path for path in all_files
            if path.endswith(".zip") or path.endswith(".disabled") or os.path.isdir(path)
        ]

        for f_path in plugin_files:
            is_disabled = f_path.endswith(".disabled")
            filename = os.path.basename(f_path)

            name, version, author, desc = filename, "-", "-", "No metadata found."
            is_broken = False

            try:
                if os.path.isdir(f_path):
                    manifest = os.path.join(f_path, "plugin.json")
                    with open(manifest, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                else:
                    with zipfile.ZipFile(f_path, 'r') as archive:
                        with archive.open("plugin.json") as handle:
                            data = json.load(handle)
                name = data.get("name", name)
                version = data.get("version", "-")
                author = data.get("author", "-")
                desc = data.get("description", "No description.")
            except (OSError, KeyError, ValueError, zipfile.BadZipFile):
                is_broken = True

            status_text = "Broken" if is_broken else ("Disabled" if is_disabled else "Loaded")
            runtime_status = next(
                (status for status in self.manager.plugin_statuses
                 if os.path.normcase(status.get("path", "")) == os.path.normcase(f_path)),
                None,
            )
            if runtime_status and not is_disabled:
                status_text = runtime_status.get("status", status_text)
                desc = runtime_status.get("description", desc)
            item = QTreeWidgetItem([name, version, author, status_text])
            item.setData(0, Qt.ItemDataRole.UserRole, f_path)
            item.setData(1, Qt.ItemDataRole.UserRole, desc)

            for i in range(4):
                item.setToolTip(i, desc)

            if status_text == "Broken":
                item.setForeground(3, QColor(colors["danger"]))
            elif is_disabled:
                item.setForeground(3, QColor(colors["muted_text"]))
            else:
                item.setForeground(3, QColor(colors["accent"]))

            self.list_widget.addTopLevelItem(item)

    def open_plugins_list(self):
        webbrowser.open(
            "https://github.com/RedstoneMaster011/OperationCrafter/"
            "tree/master/Official-Plugins/Downloads"
        )


    def toggle_plugin_status(self):
        selected = self.list_widget.currentItem()
        if not selected:
            return

        old_path = selected.data(0, Qt.ItemDataRole.UserRole)

        if old_path.endswith(".zip"):
            new_path = old_path + ".disabled"
            action = "Disabled"
        elif old_path.endswith(".zip.disabled"):
            new_path = old_path[:-len(".disabled")]
            action = "Enabled"
        elif old_path.endswith(".disabled"):
            new_path = old_path[:-len(".disabled")]
            action = "Enabled"
        elif os.path.isdir(old_path):
            new_path = old_path + ".disabled"
            action = "Disabled"
        else:
            return

        try:
            os.rename(old_path, new_path)
            self.reload_plugins(show_message=False)
            themed_message(
                self,
                QMessageBox.Icon.Information,
                "Plugin Updated",
                f"Plugin {action}. The plugin library has been reloaded.",
            )
            self.load_plugin_list()
        except Exception as e:
            themed_message(
                self, QMessageBox.Icon.Critical, "Error",
                f"Could not change status: {e}",
            )

    def install_plugin(self):
        file_path, _ = themed_file_dialog(
            self, "Select Plugin ZIP", "", "ZIP Files (*.zip)"
        )
        if file_path:
            try:
                target = os.path.join(self.manager.plugins_dir, os.path.basename(file_path))
                if os.path.exists(target):
                    answer = themed_message(
                        self,
                        QMessageBox.Icon.Question,
                        "Replace Plugin?",
                        f"{os.path.basename(target)} is already installed. Replace it?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return
                shutil.copy2(file_path, target)
                self.reload_plugins(show_message=False)
                self.load_plugin_list()
                themed_message(
                    self, QMessageBox.Icon.Information, "Success",
                    "Plugin installed and loaded.",
                )
            except Exception as e:
                themed_message(
                    self, QMessageBox.Icon.Critical, "Error",
                    f"Installation failed: {e}",
                )

    def reload_plugins(self, show_message=True):
        self.manager.load_plugins()
        parent = self.parent()
        if parent:
            self.manager.apply_plugin_theme(parent)
            for container in getattr(parent, "opened_files", {}).values():
                if hasattr(container, "canvas_view"):
                    container.canvas_view.plugin_manager = self.manager
                if hasattr(container, "refresh_toolbox"):
                    container.refresh_toolbox()
        self.load_plugin_list()
        if show_message:
            loaded = sum(status.get("status", "").startswith("Loaded")
                         for status in self.manager.plugin_statuses)
            message = f"Reloaded {loaded} plugin{'s' if loaded != 1 else ''}."
            if self.manager.load_errors:
                message += f"\n{len(self.manager.load_errors)} plugin warning(s) were reported."
            themed_message(
                self, QMessageBox.Icon.Information, "Plugins Reloaded", message
            )
