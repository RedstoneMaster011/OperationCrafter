"""Shared application and plugin-theme styling.

Keeping the fallback theme here prevents Qt's platform style from leaking gray
surfaces into dialogs, empty tab pages, menus, and file pickers.
"""

from PyQt6.QtCore import QDir, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (QBoxLayout, QDialog, QFrame, QGridLayout,
                             QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                             QMessageBox, QPushButton)


DEFAULT_THEME = {
    "background": "#06111c",
    "sidebar": "#081724",
    "accent": "#58d2ff",
    "accent_dark": "#14638b",
    "selection": "#185b7e",
    "console_bg": "#030b12",
    "line_numbers_background": "#1c4059",
    "block_editor_background": "#071421",
    "block_editor_sidebar_background": "#061522",
    "block_editor_grid": "#102638",
    "block_editor_major_grid": "#18384f",
    "input_background": "#081724",
    "input_focus_background": "#04101a",
    "input_border": "#28516c",
    "text": "#e6f3fb",
    "editor_text": "#c7ddea",
    "muted_text": "#7195aa",
    "link": "#58d2ff",
    "button_hover": "#15577a",
    "button_active": "#0a354e",
    "danger": "#ff6670",
    "success": "#42d39a",
}


class WindowTitleBar(QFrame):
    """Themeable title bar used where native window chrome cannot be colored."""

    def __init__(self, target, title=None, allow_minimize=False, allow_maximize=False):
        super().__init__(target)
        self.target = target
        self.allow_maximize = allow_maximize
        self._drag_offset = None
        self._restore_ratio = 0.5
        self.setObjectName("window_title_bar")
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 4, 3)
        layout.setSpacing(3)
        self.title_label = QLabel(title or target.windowTitle())
        self.title_label.setObjectName("window_title_text")
        layout.addWidget(self.title_label, 1)

        if allow_minimize:
            self.minimize_button = self._make_button("−", "window_minimize_btn")
            self.minimize_button.setToolTip("Minimize")
            self.minimize_button.clicked.connect(target.showMinimized)
            layout.addWidget(self.minimize_button)

        if allow_maximize:
            self.maximize_button = self._make_button("□", "window_maximize_btn")
            self.maximize_button.setToolTip("Maximize or restore")
            self.maximize_button.clicked.connect(self.toggle_maximized)
            layout.addWidget(self.maximize_button)

        self.close_button = self._make_button("×", "window_close_btn")
        self.close_button.setToolTip("Close")
        self.close_button.clicked.connect(target.close)
        layout.addWidget(self.close_button)
        target.windowTitleChanged.connect(self.title_label.setText)

    def _make_button(self, text, object_name):
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setFixedSize(30, 26)
        return button

    def toggle_maximized(self):
        if self.target.isMaximized():
            self.target.showNormal()
        else:
            self.target.showMaximized()

    def mouseDoubleClickEvent(self, event):
        if self.allow_maximize and event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._restore_ratio = max(0.05, min(0.95, event.position().x() / max(1, self.width())))
            self._drag_offset = (
                event.globalPosition().toPoint() - self.target.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            if self.target.isMaximized() and self.allow_maximize:
                self.target.showNormal()
                new_x = global_pos.x() - round(self.target.width() * self._restore_ratio)
                new_y = global_pos.y() - event.position().toPoint().y()
                self.target.move(new_x, new_y)
                self._drag_offset = global_pos - self.target.frameGeometry().topLeft()
            self.target.move(global_pos - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


def resolved_theme(theme=None):
    """Return a complete theme while preserving plugin-supplied colors."""
    colors = dict(DEFAULT_THEME)
    if theme:
        colors.update({key: value for key, value in theme.items() if value})
        derived = {
            "selection": colors.get("accent_dark", colors["accent"]),
            "input_background": colors["sidebar"],
            "input_focus_background": colors["background"],
            "input_border": colors["line_numbers_background"],
            "muted_text": colors["editor_text"],
            "link": colors["accent"],
            "success": colors["accent"],
            "danger": colors["accent"],
        }
        for key, value in derived.items():
            if key not in theme:
                colors[key] = value
    return colors


def build_app_stylesheet(theme=None):
    """Build the complete stylesheet used by the app and UI-theme plugins."""
    c = resolved_theme(theme)
    bg = c["background"]
    panel = c["sidebar"]
    accent = c["accent"]
    accent_dark = c["accent_dark"]
    selection = c["selection"]
    console = c["console_bg"]
    line = c["line_numbers_background"]
    block_bg = c["block_editor_background"]
    block_panel = c["block_editor_sidebar_background"]
    input_bg = c["input_background"]
    input_focus = c["input_focus_background"]
    input_border = c["input_border"]
    text = c["text"]
    editor_text = c["editor_text"]
    muted = c["muted_text"]
    hover = c["button_hover"]
    active = c["button_active"]
    danger = c["danger"]
    success = c["success"]

    return f"""
        QMainWindow, QDialog, QMessageBox, QInputDialog, QFileDialog,
        QWidget {{
            background-color: {bg};
            color: {text};
            font-family: "Segoe UI", sans-serif;
            selection-background-color: {selection};
            selection-color: {text};
        }}
        QDialog {{ border: 1px solid {accent}; }}
        QMainWindow {{ border: 1px solid {line}; }}
        QLabel {{ background: transparent; color: {text}; }}
        QLabel#app_brand, QLabel#Title {{
            background: transparent;
            color: {accent};
            font-weight: bold;
            letter-spacing: 1px;
        }}
        QLabel#Title {{ font-size: 28px; }}
        QLabel#AppIcon {{ background: transparent; }}

        QFrame#window_title_bar {{
            background: {panel};
            border: none;
            border-bottom: 1px solid {line};
        }}
        QLabel#window_title_text {{
            background: transparent;
            color: {text};
            font-weight: 600;
            padding-left: 4px;
        }}
        QPushButton#window_minimize_btn,
        QPushButton#window_maximize_btn,
        QPushButton#window_close_btn {{
            background: transparent;
            color: {muted};
            border: none;
            border-radius: 4px;
            padding: 0;
            font-weight: bold;
        }}
        QPushButton#window_minimize_btn:hover,
        QPushButton#window_maximize_btn:hover {{
            background: {hover};
            color: {text};
        }}
        QPushButton#window_close_btn:hover {{
            background: {danger};
            color: {bg};
        }}

        QPushButton, QToolButton {{
            background: {panel};
            color: {text};
            border: 1px solid {input_border};
            border-radius: 6px;
            padding: 6px 11px;
            outline: none;
        }}
        QPushButton:hover, QToolButton:hover {{
            background: {hover};
            border-color: {accent};
            color: {text};
        }}
        QPushButton:pressed, QPushButton:checked,
        QToolButton:pressed, QToolButton:checked {{ background: {active}; }}
        QPushButton:disabled, QToolButton:disabled {{
            background: {bg};
            border-color: {line};
            color: {muted};
        }}
        QPushButton[role="primary"] {{
            background: {accent_dark};
            border-color: {accent};
            font-weight: bold;
        }}
        QPushButton[role="success"] {{
            background: {panel};
            border-color: {success};
            color: {success};
        }}
        QPushButton#CloseBtn {{
            background: transparent;
            border: none;
            font-size: 18px;
        }}
        QPushButton#CloseBtn:hover {{ background: transparent; color: {danger}; }}

        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox,
        QDoubleSpinBox, QDateEdit, QTimeEdit {{
            background: {input_bg};
            color: {text};
            border: 1px solid {input_border};
            border-radius: 6px;
            padding: 6px 8px;
            selection-background-color: {selection};
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QDateEdit:focus, QTimeEdit:focus {{
            background: {input_focus};
            border-color: {accent};
        }}
        QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
        QComboBox:disabled, QSpinBox:disabled {{ color: {muted}; }}
        QComboBox::drop-down {{
            background: {panel};
            border: none;
            border-left: 1px solid {input_border};
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background: {panel};
            color: {text};
            border: 1px solid {accent};
            outline: none;
            selection-background-color: {selection};
        }}

        QTreeView, QTreeWidget, QListView, QListWidget,
        QTableView, QTableWidget, QColumnView {{
            background: {panel};
            alternate-background-color: {input_bg};
            color: {text};
            border: 1px solid {line};
            border-radius: 5px;
            outline: none;
        }}
        QTreeView::item, QTreeWidget::item,
        QListView::item, QListWidget::item {{ padding: 3px; }}
        QTreeView::item:hover, QTreeWidget::item:hover,
        QListView::item:hover, QListWidget::item:hover {{ background: {hover}; }}
        QTreeView::item:selected, QTreeWidget::item:selected,
        QListView::item:selected, QListWidget::item:selected,
        QTableView::item:selected, QTableWidget::item:selected {{
            background: {selection};
            color: {text};
        }}
        QHeaderView, QHeaderView::viewport {{ background: {panel}; }}
        QHeaderView::section {{
            background: {panel};
            color: {text};
            border: none;
            border-right: 1px solid {line};
            border-bottom: 1px solid {line};
            padding: 7px;
        }}
        QTableCornerButton::section {{ background: {panel}; border: 1px solid {line}; }}

        QTabWidget, QTabWidget::pane, QTabWidget QStackedWidget,
        QStackedWidget, QAbstractScrollArea, QAbstractScrollArea::viewport {{
            background: {bg};
            color: {text};
        }}
        QTabWidget::pane {{ border: 1px solid {line}; top: -1px; }}
        QTabBar {{ background: {bg}; }}
        QTabBar::tab {{
            background: {panel};
            color: {muted};
            border: 1px solid {line};
            padding: 8px 13px;
        }}
        QTabBar::tab:hover {{ background: {hover}; color: {text}; }}
        QTabBar::tab:selected {{
            background: {bg};
            color: {text};
            border-bottom: 2px solid {accent};
        }}

        QMenu, QMenuBar {{
            background: {panel};
            color: {text};
            border: 1px solid {line};
        }}
        QMenu::item, QMenuBar::item {{ background: transparent; padding: 6px 20px; }}
        QMenu::item:selected, QMenuBar::item:selected {{ background: {selection}; }}
        QMenu::separator {{ height: 1px; background: {line}; margin: 4px 8px; }}

        QCheckBox, QRadioButton {{ background: transparent; color: {text}; spacing: 6px; }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 15px;
            height: 15px;
            background: {input_bg};
            border: 1px solid {input_border};
        }}
        QCheckBox::indicator {{ border-radius: 3px; }}
        QRadioButton::indicator {{ border-radius: 8px; }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent}; }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background: {accent};
            border-color: {accent};
        }}

        QGroupBox {{
            background: {panel};
            border: 1px solid {line};
            border-radius: 7px;
            margin-top: 10px;
            padding-top: 8px;
        }}
        QGroupBox::title {{ color: {accent}; subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        QDialogButtonBox {{ background: transparent; }}
        QSplitter, QSplitter::handle {{ background: {bg}; }}
        QSplitter::handle {{ background: {line}; width: 3px; height: 3px; }}
        QStatusBar, QToolBar {{ background: {panel}; color: {text}; border-color: {line}; }}

        QScrollBar:vertical {{ background: {bg}; width: 12px; margin: 0; }}
        QScrollBar::handle:vertical {{
            background: {selection};
            min-height: 28px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {accent}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: {bg}; height: 12px; margin: 0; }}
        QScrollBar::handle:horizontal {{
            background: {selection};
            min-width: 28px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

        QProgressBar {{
            background: {input_bg};
            color: {text};
            border: 1px solid {line};
            border-radius: 5px;
            text-align: center;
        }}
        QProgressBar::chunk {{ background: {accent_dark}; border-radius: 4px; }}
        QToolTip {{ background: {panel}; color: {text}; border: 1px solid {accent}; padding: 4px; }}

        QWidget#node_library_panel, BlockContainerSidebar {{
            background: {block_panel};
            border-color: {line};
        }}
        QWidget#node_toolbar, QWidget#editor_mode_bar {{
            background: {panel};
            border-bottom: 1px solid {line};
        }}
        QLabel#editor_mode_title, QLabel#node_library_title,
        QLabel#node_graph_title {{ color: {accent}; font-weight: bold; }}
        QLabel#node_library_hint {{ color: {muted}; }}
        BlockView {{ background: {block_bg}; border: none; }}
        QPlainTextEdit {{ color: {editor_text}; }}
        LineNumberArea {{ background: {line}; color: {editor_text}; }}
        QTextEdit#terminal {{
            background: {console};
            color: {editor_text};
            border: 1px solid {line};
        }}
    """


def apply_application_palette(application, theme=None):
    """Color palette roles used by controls that do not honor every QSS rule."""
    c = resolved_theme(theme)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(c["background"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(c["input_background"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["sidebar"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["sidebar"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(c["sidebar"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(c["accent"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(c["link"]))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(c["link"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c["selection"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted_text"]))
    application.setPalette(palette)


def install_window_title_bar(target, allow_minimize=False, allow_maximize=False):
    """Make an existing Qt dialog frameless and prepend a themed title bar."""
    existing = target.findChild(WindowTitleBar, "window_title_bar")
    if existing:
        return existing

    target.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
    title_bar = WindowTitleBar(
        target,
        target.windowTitle(),
        allow_minimize=allow_minimize,
        allow_maximize=allow_maximize,
    )
    layout = target.layout()
    if isinstance(layout, QBoxLayout):
        layout.insertWidget(0, title_bar)
    elif isinstance(layout, QGridLayout):
        items = []
        max_column = 1
        for index in range(layout.count() - 1, -1, -1):
            row, column, row_span, column_span = layout.getItemPosition(index)
            item = layout.takeAt(index)
            items.append((row, column, row_span, column_span, item))
            effective_span = column_span if column_span > 0 else 1
            max_column = max(max_column, column + effective_span)
        layout.addWidget(title_bar, 0, 0, 1, max_column)
        for row, column, row_span, column_span, item in reversed(items):
            layout.addItem(item, row + 1, column, row_span, column_span)
    return title_bar


def _inherit_or_default_stylesheet(dialog, parent):
    stylesheet = parent.styleSheet() if parent is not None else ""
    dialog.setStyleSheet(stylesheet or build_app_stylesheet())


def themed_message(parent, icon, title, text, buttons=QMessageBox.StandardButton.Ok):
    """Show a fully themed message box and return the selected standard button."""
    dialog = QMessageBox(parent)
    dialog.setIcon(icon)
    dialog.setWindowTitle(title)
    dialog.setText(text)
    dialog.setStandardButtons(buttons)
    _inherit_or_default_stylesheet(dialog, parent)
    install_window_title_bar(dialog)
    dialog.exec()
    clicked = dialog.clickedButton()
    return dialog.standardButton(clicked) if clicked is not None else QMessageBox.StandardButton.NoButton


def themed_text_input(parent, title, label, text=""):
    """QInputDialog.getText equivalent with the themed custom window frame."""
    dialog = QInputDialog(parent)
    dialog.setInputMode(QInputDialog.InputMode.TextInput)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextValue(text)
    _inherit_or_default_stylesheet(dialog, parent)
    install_window_title_bar(dialog)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.textValue(), accepted


def themed_file_dialog(parent, title, directory="", name_filter="",
                       file_mode=QFileDialog.FileMode.ExistingFile,
                       accept_mode=QFileDialog.AcceptMode.AcceptOpen,
                       show_hidden=False):
    """Show an open/save/directory picker without desktop-gray window chrome."""
    dialog = QFileDialog(parent, title, directory, name_filter)
    dialog.setFileMode(file_mode)
    dialog.setAcceptMode(accept_mode)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    if file_mode == QFileDialog.FileMode.Directory:
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    # AllDirs is intentionally different from Dirs/AllEntries: it keeps every
    # directory visible even when a filename pattern such as *.projectdata is
    # active, so users can still navigate the whole filesystem.
    filters = (
        QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.Drives
        | QDir.Filter.NoDotAndDotDot
    )
    if show_hidden:
        filters |= QDir.Filter.Hidden
    dialog.setFilter(filters)
    _inherit_or_default_stylesheet(dialog, parent)
    install_window_title_bar(dialog)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return "", ""
    selected = dialog.selectedFiles()
    return (selected[0] if selected else ""), dialog.selectedNameFilter()
