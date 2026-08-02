import glob
import json
import os
import re
import shutil
from collections import Counter

from PyQt6.QtCore import Qt, QEvent, QTimer, QRect, QPoint, QPointF, QSize, QMimeData
from PyQt6.QtGui import (QFileSystemModel, QShortcut, QKeySequence, QPainter,
                         QColor, QTextCursor, QDrag, QImage, QPen, QIcon,
                         QPixmap)
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QTreeView, QPushButton, QSplitter,
                             QMessageBox, QMenu, QTabWidget,
                             QTabBar, QRubberBand, QPlainTextEdit, QLineEdit,
                             QFrame, QDialog, QFormLayout, QDialogButtonBox,
                             QStackedWidget, QTreeWidget, QTreeWidgetItem, QGraphicsView, QApplication, QLabel,
                             QFileDialog, QListWidget, QListWidgetItem)

import app.metadata
from .pluginmanager import PluginManager, PluginDialog
from .block import BlockCanvas, VisualBlock, load_block_definitions
from .emulator import OSLauncher
from .highlight import SyntaxHighlighter
from .midi_import import MidiImportError, midi_events_to_asm, read_midi_events
from .theme import (DEFAULT_THEME, WindowTitleBar, build_app_stylesheet,
                    resolved_theme, themed_file_dialog, themed_message,
                    themed_text_input)


MAX_IMPORTED_IMAGE_WIDTH = 80
MAX_IMPORTED_IMAGE_HEIGHT = 80


def image_exceeds_safe_bounds(image):
    return (
        image.width() > MAX_IMPORTED_IMAGE_WIDTH
        or image.height() > MAX_IMPORTED_IMAGE_HEIGHT
    )


def scale_image_to_safe_bounds(image):
    return image.scaled(
        QSize(MAX_IMPORTED_IMAGE_WIDTH, MAX_IMPORTED_IMAGE_HEIGHT),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class SettingsDialog(QDialog):
    def __init__(self, current_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project Settings")
        self.setFixedWidth(350)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setStyleSheet(build_app_stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 10)
        layout.addWidget(WindowTitleBar(self, self.windowTitle()))
        form = QFormLayout()
        form.setContentsMargins(12, 10, 12, 6)
        self.name_input = QLineEdit(current_data.get("name", ""))
        self.version_input = QLineEdit(current_data.get("version", "1.0.0"))
        form.addRow("Project Name:", self.name_input)
        form.addRow("Version:", self.version_input)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.setContentsMargins(12, 0, 12, 0)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_data(self):
        return {
            "name": self.name_input.text(), "version": self.version_input.text()
        }

class ProjectTreeView(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeView.DragDropMode.InternalMove)
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.clipboard_path = None
        self._rubber_band = None
        self._origin = QPoint()

    def show_error(self, title, message):
        themed_message(self, QMessageBox.Icon.Critical, title, message)

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid() and event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.pos()
            if not self._rubber_band:
                self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
            self._rubber_band.setGeometry(QRect(self._origin, self._origin).normalized())
            self._rubber_band.show()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._rubber_band and self._rubber_band.isVisible():
            self._rubber_band.setGeometry(QRect(self._origin, event.pos()).normalized())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._rubber_band and self._rubber_band.isVisible():
            rect = self._rubber_band.geometry()
            self._rubber_band.hide()
            self.selectionModel().clearSelection()
            self.select_items_in_rect(rect)
        super().mouseReleaseEvent(event)

    def select_items_in_rect(self, rect):
        for i in range(self.model().rowCount(self.rootIndex())):
            idx = self.model().index(i, 0, self.rootIndex())
            if rect.intersects(self.visualRect(idx)):
                self.selectionModel().select(idx, self.selectionModel().SelectionFlag.Select)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F2:
            idx = self.currentIndex()
            if idx.isValid():
                self.window().rename_item(idx)
            return

        if event.key() == Qt.Key.Key_Delete:
            if self.selectionModel().hasSelection():
                self.window().delete_item()
            return

        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            index = self.currentIndex()
            if index.isValid():
                self.clipboard_path = self.model().filePath(index)

        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V:
            if self.clipboard_path:
                index = self.currentIndex()
                dest = self.model().filePath(index)
                if not os.path.isdir(dest):
                    dest = os.path.dirname(dest)
                self.perform_paste(self.clipboard_path, dest)

        else:
            super().keyPressEvent(event)

    def perform_paste(self, src, dest):
        try:
            name = os.path.basename(src)
            target = os.path.join(dest, name)
            if os.path.exists(target):
                base, ext = os.path.splitext(name)
                target = os.path.join(dest, f"{base}_copy{ext}")
            if os.path.isdir(src):
                shutil.copytree(src, target)
            else:
                shutil.copy2(src, target)
        except Exception as e:
            self.show_error("Paste Error", str(e))


class FindReplaceBar(QFrame):
    def __init__(self, editor_widget, container, parent=None):
        super().__init__(parent)
        self.editor = editor_widget
        self.container = container
        self.setFixedHeight(45)
        self.set_node_theme(DEFAULT_THEME)
        layout = QHBoxLayout(self)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find...")
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace...")
        self.replace_input.hide()
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self.find_next)
        self.btn_replace = QPushButton("Replace")
        self.btn_replace.clicked.connect(self.replace_current)
        self.btn_replace.hide()
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedWidth(30)
        self.btn_close.clicked.connect(self.hide_bar)
        layout.addWidget(self.find_input)
        layout.addWidget(self.replace_input)
        layout.addWidget(self.btn_next)
        layout.addWidget(self.btn_replace)
        layout.addStretch()
        layout.addWidget(self.btn_close)

    def set_node_theme(self, theme):
        colors = resolved_theme(theme)
        background = colors["sidebar"]
        input_bg = colors["input_background"]
        line = colors["line_numbers_background"]
        text = colors["text"]
        accent = colors["accent"]
        hover = colors["button_hover"]
        self.setStyleSheet(f"""
            QFrame {{ background-color: {background}; border-bottom: 1px solid {line}; }}
            QLineEdit {{ background: {input_bg}; color: {text}; border: 1px solid {line}; padding: 4px; }}
            QPushButton {{ background: {background}; color: {text}; border: 1px solid {line}; padding: 4px 10px; }}
            QPushButton:hover {{ background: {hover}; border-color: {accent}; }}
        """)

    def show_find(self):
        self.container.btn_toggle.hide()
        self.replace_input.hide()
        self.btn_replace.hide()
        self.show()
        self.find_input.setFocus()

    def show_replace(self):
        self.container.btn_toggle.hide()
        self.replace_input.show()
        self.btn_replace.show()
        self.show()
        self.find_input.setFocus()

    def hide_bar(self):
        self.hide()
        self.editor.setFocus()
        if self.container.file_path.lower().endswith('.asm'): self.container.btn_toggle.show()

    def find_next(self):
        txt = self.find_input.text()
        if not txt or not self.editor.find(txt):
            self.editor.moveCursor(QTextCursor.MoveOperation.Start)
            self.editor.find(txt)

    def replace_current(self):
        cursor = self.editor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == self.find_input.text():
            cursor.insertText(self.replace_input.text())
        self.find_next()


class LineNumberArea(QWidget):
    def __init__(self, editor): 
        super().__init__(editor)
        self.editor = editor
        
    def sizeHint(self): 
        return QSize(self.editor.line_number_area_width(), 0)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), self.palette().window().color())
        self.editor.lineNumberAreaPaintEvent(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, file_path, parent_window, plugin_manager, parent=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.file_path = file_path
        self.parent_window = parent_window
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.update_line_number_area_width(0)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.set_node_theme(DEFAULT_THEME)
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.auto_save)
        self.textChanged.connect(lambda: self.save_timer.start(500))

    def auto_save(self):
        if self.file_path:
            with open(self.file_path, 'w', encoding='utf-8', errors='ignore') as f: f.write(self.toPlainText())

    def set_node_theme(self, theme):
        colors = resolved_theme(theme)
        background = colors["background"]
        text = colors["editor_text"]
        self.setStyleSheet(
            f"background: {background}; color: {text}; font-family: 'Consolas'; "
            "font-size: 13px; border: none;"
        )
        line_background = QColor(colors["line_numbers_background"])
        palette = self.line_number_area.palette()
        palette.setColor(self.line_number_area.backgroundRole(), line_background)
        palette.setColor(self.line_number_area.foregroundRole(), QColor(text))
        self.line_number_area.setPalette(palette)
        self.line_number_area.setAutoFillBackground(True)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        theme = self.plugin_manager.ui_themes[0] if self.plugin_manager.ui_themes else DEFAULT_THEME
        colors = resolved_theme(theme)
        background = colors["sidebar"]
        text = colors["text"]
        line = colors["line_numbers_background"]
        hover = colors["button_hover"]
        menu.setStyleSheet(f"""
            QMenu {{ background: {background}; color: {text}; border: 1px solid {line}; }}
            QMenu::item:selected {{ background: {hover}; }}
        """)
        menu.addAction("Undo", self.undo)
        menu.addAction("Redo", self.redo)
        menu.addSeparator()
        menu.addAction("Cut", self.cut)
        menu.addAction("Copy", self.copy)
        menu.addAction("Paste", self.paste)
        menu.addSeparator()
        container = self.parentWidget().parentWidget()
        menu.addAction("Find", container.find_bar.show_find)
        menu.addAction("Replace", container.find_bar.show_replace)
        menu.exec(event.globalPos())

    def line_number_area_width(self):
        return 12 + self.fontMetrics().horizontalAdvance('9') * len(str(max(1, self.blockCount())))

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy: 
            self.line_number_area.scroll(0, dy)
        else: 
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self.line_number_area.palette().window().color())
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            painter.setPen(self.line_number_area.palette().windowText().color())
            painter.drawText(0, top, self.line_number_area_width() - 5, self.fontMetrics().height(),
                             Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            block = block.next()
            top += round(self.blockBoundingRect(block).height())


class BlockView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("border: none; background: #071421")
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._zoom = 1.0
        self._pan_start = None
        self._background_color = QColor("#071421")
        self._minor_grid_color = QColor("#102638")
        self._major_grid_color = QColor("#18384f")

    def set_node_theme(self, theme):
        self._background_color = QColor(theme.get("block_editor_background", "#071421"))
        self._minor_grid_color = QColor(theme.get("block_editor_grid", "#102638"))
        self._major_grid_color = QColor(theme.get("block_editor_major_grid", "#18384f"))
        self.scene().setBackgroundBrush(self._background_color)
        self.setStyleSheet(f"border: none; background: {self._background_color.name()};")
        if hasattr(self.scene(), "set_theme"):
            self.scene().set_theme(theme)
        self.viewport().update()

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self._background_color)
        minor = 24
        major = minor * 5
        left = int(rect.left()) - (int(rect.left()) % minor)
        top = int(rect.top()) - (int(rect.top()) % minor)

        painter.setPen(QPen(self._minor_grid_color, 1))
        x = left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += minor
        y = top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += minor

        major_left = int(rect.left()) - (int(rect.left()) % major)
        major_top = int(rect.top()) - (int(rect.top()) % major)
        painter.setPen(QPen(self._major_grid_color, 1))
        x = major_left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += major
        y = major_top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += major

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Shift+wheel pans vertically without changing zoom. The cursor
            # remains anchored over the same graph location, matching zoom's feel.
            steps = event.angleDelta().y() / 120.0
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(steps * 90)
            )
            event.accept()
            return
        factor = 1.16 if event.angleDelta().y() > 0 else 1 / 1.16
        next_zoom = self._zoom * factor
        if 0.25 <= next_zoom <= 2.5:
            self._zoom = next_zoom
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            current = event.position().toPoint()
            delta = current - self._pan_start
            self._pan_start = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.scene().delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Home:
            self.frame_all()
            event.accept()
            return
        super().keyPressEvent(event)

    def frame_all(self):
        bounds = self.scene().itemsBoundingRect().adjusted(-80, -80, 80, 80)
        if bounds.isValid():
            self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()

    def contextMenuEvent(self, event):
        callback = getattr(self, "open_block_search", None)
        if callable(callback):
            callback(event.globalPos(), self.mapToScene(event.pos()))
            event.accept()
            return
        super().contextMenuEvent(event)

    def dragEnterEvent(self, e): 
        e.accept() if e.mimeData().hasText() else e.ignore()
        
    def dragMoveEvent(self, e): 
        e.accept() if e.mimeData().hasText() else e.ignore()

    def dropEvent(self, e):
        definition = None
        mime = e.mimeData()
        if mime.hasFormat("application/x-operationcrafter-block"):
            try:
                definition = json.loads(bytes(mime.data("application/x-operationcrafter-block")).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                definition = None

        if definition is None and mime.hasText():
            blocks_dir = os.path.join(os.path.dirname(__file__), "blocks")
            paths = glob.glob(os.path.join(blocks_dir, "*.json"))
            manager = getattr(self, "plugin_manager", None)
            if manager:
                paths += manager.loaded_blocks
            definitions, _ = load_block_definitions(paths)
            definition = next((item for item in definitions if item.get("name") == mime.text()), None)

        if definition:
            definition.pop("_source_path", None)
            block = VisualBlock.from_definition(definition)
            drop_pos = self.mapToScene(e.position().toPoint())
            self.scene().add_new_block(block, drop_pos - QPointF(block.node_width / 2, 20))
            e.acceptProposedAction()
            return
        e.ignore()


class HelpDialog(QDialog):
    README_URL = (
        "https://github.com/RedstoneMaster011/OperationCrafter/blob/master/README.md"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Operation Crafter - Help")
        self.setFixedSize(390, 190)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setStyleSheet(build_app_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 12)
        layout.addWidget(WindowTitleBar(self, self.windowTitle()))

        self.msg_label = QLabel("The Help is located in the README.md")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.msg_label)

        self.link_label = QLabel()
        self.link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.link_label.setOpenExternalLinks(True)
        self.set_node_theme(DEFAULT_THEME)
        layout.addWidget(self.link_label)

        btn_layout = QHBoxLayout()
        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedWidth(80)
        self.close_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def set_node_theme(self, theme):
        colors = resolved_theme(theme)
        self.link_label.setText(
            f'README.md: <a href="{self.README_URL}" '
            f'style="color: {colors["link"]};">README.MD</a>'
        )

class BlockContainerSidebar(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setHeaderHidden(True)
        self.setIconSize(QSize(12, 12))
        self.setStyleSheet("""
                    QTreeWidget { 
                        background-color: #081521;
                        border: 1px solid #18334a;
                        border-radius: 6px;
                        color: #c6d8e8;
                        font-family: 'Segoe UI', sans-serif;
                        font-size: 11px;
                        outline: none;
                    }
                    QTreeWidget::item {
                        min-height: 25px;
                        padding: 2px 5px;
                        border-radius: 3px;
                    }
                    QTreeWidget::item:hover {
                        background: #12304a;
                    }
                    QTreeWidget::item:selected {
                        background: #16577b;
                        color: white;
                    }
                """)

    def set_node_theme(self, theme):
        background = theme.get("block_editor_sidebar_background", theme.get("sidebar", "#081521"))
        line = theme.get("line_numbers_background", "#18334a")
        text = theme.get("text", "#c6d8e8")
        hover = theme.get("button_hover", "#12304a")
        selected = theme.get("selection", theme.get("accent_dark", theme.get("accent", "#16577b")))
        self.setStyleSheet(f"""
            QTreeWidget {{ background-color: {background}; border: 1px solid {line};
                border-radius: 6px; color: {text}; font-family: 'Segoe UI', sans-serif;
                font-size: 11px; outline: none; }}
            QTreeWidget::item {{ min-height: 25px; padding: 2px 5px; border-radius: 3px; }}
            QTreeWidget::item:hover {{ background: {hover}; }}
            QTreeWidget::item:selected {{ background: {selected}; color: {text}; }}
        """)

    def startDrag(self, actions):
        item = self.currentItem()
        if item and item.parent():
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(item.text(0))
            definition = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(definition, dict):
                clean_definition = dict(definition)
                clean_definition.pop("_source_path", None)
                mime.setData(
                    "application/x-operationcrafter-block",
                    json.dumps(clean_definition).encode("utf-8"),
                )
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)


class BlockSearchPopup(QDialog):
    """Blender-like searchable Add popup used from the graph's right-click menu."""

    def __init__(self, definitions, parent=None, theme=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.definitions = definitions
        self.selected_definition = None
        self.setFixedSize(430, 500)
        theme = theme or {}
        background = theme.get("background", "#071522")
        panel = theme.get("sidebar", "#081724")
        input_bg = theme.get("input_background", "#0a1d2d")
        line = theme.get("line_numbers_background", "#25506d")
        accent = theme.get("accent", "#58d2ff")
        accent_dark = theme.get("accent_dark", theme.get("selection", "#14638b"))
        hover = theme.get("button_hover", "#123652")
        text = theme.get("text", "#d9e9f5")
        self.setStyleSheet(f"""
            QDialog {{ background: {background}; color: {text}; border: 1px solid {accent};
                      border-radius: 9px; }}
            QLabel {{ color: {accent}; font-weight: bold; letter-spacing: 1px; }}
            QLineEdit {{ background: {input_bg}; color: {text}; border: 1px solid {line};
                        border-radius: 6px; padding: 9px; font-size: 12px; }}
            QLineEdit:focus {{ border-color: {accent}; }}
            QListWidget {{ background: {panel}; color: {text}; border: 1px solid {line};
                          border-radius: 6px; outline: none; padding: 4px; }}
            QListWidget::item {{ min-height: 30px; padding: 3px 7px; border-radius: 4px; }}
            QListWidget::item:hover {{ background: {hover}; }}
            QListWidget::item:selected {{ background: {accent_dark}; color: {text}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(QLabel("ADD NODE"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search all blocks, groups, and tags…")
        self.search.textChanged.connect(self.populate)
        self.search.returnPressed.connect(self.choose_current)
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _: self.choose_current())
        layout.addWidget(self.results, 1)
        self.populate("")
        self.search.setFocus()

    def populate(self, query):
        query = query.strip().casefold()
        self.results.clear()
        for definition in self.definitions:
            searchable = " ".join((
                str(definition.get("name", "")),
                str(definition.get("group", "")),
                str(definition.get("description", "")),
                " ".join(str(tag) for tag in definition.get("tags", [])),
            )).casefold()
            if query and query not in searchable:
                continue
            item = QListWidgetItem(
                f"{definition['name']}    ·    {definition.get('group', 'General')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, definition)
            item.setToolTip(definition.get("description", ""))
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def choose_current(self):
        item = self.results.currentItem()
        if item:
            self.selected_definition = item.data(Qt.ItemDataRole.UserRole)
            self.accept()


class IDEWindow(QMainWindow):
    def __init__(self, compiler, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1280, 820)
        self.compiler = compiler
        self.launcher = OSLauncher(self.compiler.root_dir)
        self.opened_files = {}
        self.plugin_manager = PluginManager(self.compiler.root_dir)
        self.plugin_manager.load_plugins()
        self.terminal = QTextEdit()
        self.terminal.setObjectName("terminal")

        self.plugin_manager.apply_plugin_theme(self)

    def handle_export(self):
        source_path = os.path.join(self.compiler.project_dir, "build", "boot.img")

        if not os.path.exists(source_path):
            self.show_error("Export Error", "Error: boot.img not found. Run Build first.")
            return

        p_file = os.path.join(self.compiler.project_dir, ".projectdata")
        try:
            with open(p_file, "r") as f:
                data = json.load(f)
        except:
            data = {
                "name": "Project",
                "version": "1.0.0"
            }
        dlg = SettingsDialog(data, self)
        self.plugin_manager.apply_plugin_theme(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_data = dlg.get_data()

        project_name = new_data["name"]
        project_version = new_data["version"]

        dest_path, _ = themed_file_dialog(
            self,
            "Export Boot Image",
            os.path.join(os.path.expanduser("~"), f"{project_name}-{project_version}.img"),
            "Image Files (*.img)",
            file_mode=QFileDialog.FileMode.AnyFile,
            accept_mode=QFileDialog.AcceptMode.AcceptSave,
        )

        if dest_path:
            try:
                shutil.copy2(source_path, dest_path)
                self.terminal.append(f"Successfully exported.")
            except Exception as e:
                self.show_error("Export Error", f"Failed to export file: {str(e)}")

    def import_and_convert_png(self):
        src_path, _ = themed_file_dialog(
            self, "Import PNG for Operation Crafter", "", "Images (*.png)"
        )
        if not src_path:
            return

        img = QImage(src_path)
        if img.isNull():
            self.show_error("Import Error", "Could not load the selected image.")
            return

        if image_exceeds_safe_bounds(img):
            original_width = img.width()
            original_height = img.height()
            choice = themed_message(
                self,
                QMessageBox.Icon.Warning,
                "Image Exceeds Safe Size",
                f"This image is {original_width}×{original_height}. The safe maximum "
                f"is {MAX_IMPORTED_IMAGE_WIDTH}×{MAX_IMPORTED_IMAGE_HEIGHT}.\n\n"
                "Select OK to scale it down proportionally, or Cancel to stop importing.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if choice != QMessageBox.StandardButton.Ok:
                return
            img = scale_image_to_safe_bounds(img)
            self.terminal.append(
                f"Scaled imported image from {original_width}×{original_height} to "
                f"{img.width()}×{img.height()} for the 16-bit image resource limit."
            )

        img = img.convertToFormat(QImage.Format.Format_Indexed8)

        base_name = os.path.splitext(os.path.basename(src_path))[0]
        file_name, ok = themed_text_input(
            self, "Image Resource Name", "Assembly resource file:", base_name + ".asm"
        )
        if not ok or not file_name:
            return
        if not file_name.lower().endswith(".asm"):
            file_name += ".asm"
        symbol = re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(file_name)[0])
        if not symbol or symbol[0].isdigit():
            symbol = "image_" + symbol

        hex_values = []
        for i in range(256):
            c = QColor(img.colorTable()[i]) if i < img.colorCount() else QColor(0, 0, 0)
            hex_values.append(f"0x{c.red() // 4:02x}")
            hex_values.append(f"0x{c.green() // 4:02x}")
            hex_values.append(f"0x{c.blue() // 4:02x}")

        for y in range(img.height()):
            for x in range(img.width()):
                hex_values.append(f"0x{img.pixelIndex(x, y):02x}")

        asm_content = f"{symbol}_width dw {img.width()}\n"
        asm_content += f"{symbol}_height dw {img.height()}\n"
        asm_content += f"{symbol}_data: db " + ", ".join(hex_values)

        dest_path = os.path.join(self.compiler.project_dir, file_name)
        try:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(asm_content)

            self.model.setRootPath(self.compiler.project_dir)
            self.terminal.append(
                f"Imported image as {file_name} (resource symbol: {symbol})."
            )
        except Exception as e:
            self.show_error("File Error", f"Failed to save resource: {str(e)}")

    def import_and_convert_midi(self):
        source_path, _ = themed_file_dialog(
            self, "Import MIDI for Operation Crafter", "", "MIDI Files (*.mid *.midi)"
        )
        if not source_path:
            return

        base_name = os.path.splitext(os.path.basename(source_path))[0]
        file_name, ok = themed_text_input(
            self, "MIDI Resource Name", "Assembly resource file:", base_name + ".asm"
        )
        if not ok or not file_name:
            return
        if not file_name.lower().endswith(".asm"):
            file_name += ".asm"
        symbol = re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(file_name)[0])
        if not symbol or symbol[0].isdigit():
            symbol = "music_" + symbol

        try:
            events, metadata = read_midi_events(source_path)
            asm_content = midi_events_to_asm(
                events, symbol, os.path.basename(source_path)
            )
            destination = os.path.join(self.compiler.project_dir, file_name)
            with open(destination, "w", encoding="utf-8") as handle:
                handle.write(asm_content)
            self.model.setRootPath(self.compiler.project_dir)
            self.terminal.append(
                f"Imported MIDI as {file_name}: {len(events)} events from "
                f"{metadata['tracks']} track(s) (resource symbol: {symbol})."
            )
        except (OSError, MidiImportError, ValueError) as error:
            self.show_error("MIDI Import Error", str(error))

    def show_error(self, title, message):
        themed_message(self, QMessageBox.Icon.Critical, title, message)
        self.plugin_manager.apply_plugin_theme(self)

    def launch_ide(self, path):
        self.compiler.project_dir = path
        self.setup_ui()
        self.setup_shortcuts()
        self.plugin_manager.apply_plugin_theme(self)
        self.showMaximized()
        path_str = str(path)
        windows_path = path_str.replace("/", "\\")
        self.setWindowTitle(f"Operation Crafter {app.metadata.version} - {windows_path}")
        self.setWindowIcon(QApplication.windowIcon())

    def setup_ui(self):
        central = QWidget()
        central.setObjectName("main_window_central")
        self.setCentralWidget(central)
        central.setStyleSheet(build_app_stylesheet())
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(7)
        self.window_title_bar = WindowTitleBar(
            self,
            self.windowTitle() or "Operation Crafter",
            allow_minimize=True,
            allow_maximize=True,
        )
        layout.addWidget(self.window_title_bar)
        t_bar = QHBoxLayout()
        brand = QLabel("OPERATION CRAFTER")
        brand.setObjectName("app_brand")
        brand.setStyleSheet("background: transparent; color: #72d5f4; font-size: 13px; font-weight: bold; letter-spacing: 1px; padding-right: 12px;")
        t_bar.addWidget(brand)
        for txt, func in [("Build (F5)", self.handle_build),
                          ("Run (F6)", self.handle_run),
                          ("Settings", self.open_settings_gui),
                          ("Plugins", self.open_plugins_gui),
                          ("Export (F8)", self.handle_export),
                          ("Help", self.open_help_gui)]:
            btn = QPushButton(txt)
            btn.setProperty("class", "top_btn")
            btn.clicked.connect(func)
            t_bar.addWidget(btn)
        t_bar.addStretch()
        layout.addLayout(t_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.model = QFileSystemModel()
        self.model.setRootPath(self.compiler.project_dir)
        self.model.setReadOnly(False)
        self.tree = ProjectTreeView()
        self.tree.setMinimumWidth(190)
        self.tree.setMaximumWidth(320)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(self.compiler.project_dir))
        for i in range(1, 4): self.tree.setColumnHidden(i, True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.doubleClicked.connect(self.open_file)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().installEventFilter(self)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.tabs)
        self.splitter.setSizes([250, 750])
        layout.addWidget(self.splitter)
        self.terminal = QTextEdit()
        self.terminal.setFixedHeight(120)
        self.terminal.setReadOnly(True)
        self.terminal.setPlaceholderText("Build and emulator output will appear here.")
        self.terminal.setStyleSheet(
            "background: #030b12; color: #c7ddea; border: 1px solid #1c4059; "
            "border-radius: 5px; padding: 6px; font-family: Consolas;"
        )
        layout.addWidget(self.terminal)
        self.plugin_manager.apply_plugin_theme(self)

    def open_help_gui(self):
        hpg = HelpDialog(self)
        self.plugin_manager.apply_plugin_theme(hpg)
        hpg.exec()

    def open_plugins_gui(self):
        dlg = PluginDialog(self.plugin_manager, self)
        self.plugin_manager.apply_plugin_theme(dlg)
        dlg.exec()

    def open_file(self, index):
        path = self.model.filePath(index)
        if not os.path.isfile(path) or path in self.opened_files:
            return

        try:
            cont = EditorContainer(path, self, self.plugin_manager)
            cont.highlighter = SyntaxHighlighter(cont.editor.document())

            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                cont.editor.setPlainText(f.read())

            idx = self.tabs.addTab(cont, os.path.basename(path))
            btn = TabButton("×")
            btn.clicked.connect(lambda: self.close_tab(self.tabs.indexOf(cont)))
            self.tabs.tabBar().setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)
            self.opened_files[path] = cont
            self.tabs.setCurrentIndex(idx)
            self.plugin_manager.apply_plugin_theme(self)
        except Exception as e:
            self.show_error("File Load Error", f"Could not open {os.path.basename(path)}\n\nReason: {str(e)}")

    def delete_item(self):
        focused_widget = QApplication.focusWidget()

        if focused_widget and (isinstance(focused_widget, QLineEdit) or
                               "BlockView" in str(type(focused_widget))):
            return

        indices = self.tree.selectionModel().selectedRows()
        if not indices:
            return

        paths = [self.model.filePath(i) for i in indices]

        confirm = themed_message(
            self,
            QMessageBox.Icon.Question,
            "Confirm Delete",
            f"Are you sure you want to delete {len(paths)} item(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            for path in paths:
                try:
                    if path in self.opened_files:
                        tab_idx = self.tabs.indexOf(self.opened_files[path])
                        if tab_idx != -1:
                            self.close_tab(tab_idx)

                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                except Exception as e:
                    self.show_error("Delete Error", f"Could not delete {path}: {e}")

    def rename_item(self, idx):
        old = self.model.filePath(idx)
        name, ok = themed_text_input(self, "Rename", "Name:", os.path.basename(old))
        if ok and name: os.rename(old, os.path.join(os.path.dirname(old), name))

    def show_context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        menu = QMenu(self)

        menu.addAction("New File", lambda: self.add_file(idx))
        menu.addAction("New Folder", lambda: self.add_folder(idx))
        menu.addSeparator()

        menu.addAction("Copy", lambda: setattr(self.tree, 'clipboard_path', self.model.filePath(idx)))
        menu.addAction("Rename", lambda: self.rename_item(idx))
        menu.addAction("Delete", self.delete_item)
        menu.addAction("Import/Convert .PNG (Raw Data)", self.import_and_convert_png)
        menu.addAction("Import/Convert MIDI (PC Speaker)", self.import_and_convert_midi)

        p_act = menu.addAction("Paste")
        p_act.setEnabled(hasattr(self.tree, 'clipboard_path'))
        p_act.triggered.connect(lambda: self.handle_paste(idx))

        menu.exec(self.tree.viewport().mapToGlobal(pos))
        self.plugin_manager.apply_plugin_theme(self)

    def handle_paste(self, idx):
        dest = self.model.filePath(idx) if idx.isValid() else self.compiler.project_dir
        self.tree.perform_paste(self.tree.clipboard_path, dest)

    def open_settings_gui(self):
        p_file = os.path.join(self.compiler.project_dir, ".projectdata")
        try:
            with open(p_file, "r") as f:
                data = json.load(f)
        except:
            data = {
                "name": "Project", 
                "version": "1.0.0"
            }
        dlg = SettingsDialog(data, self)
        self.plugin_manager.apply_plugin_theme(dlg)
        if dlg.exec():
            new_stuff = dlg.get_data()
            data.update(new_stuff)
            with open(p_file, "w") as f:
                json.dump(data, f, indent=4)
        self.plugin_manager.apply_plugin_theme(self)

    def handle_build(self):
        if hasattr(self, 'launcher') and self.launcher.is_running():
            self.show_error("Build Blocked",
                            "The Emulator is still running. Close it before building!")
            return

        try:
            result = self.compiler.compile_to_img(self.terminal)
            if isinstance(result, tuple) and result and result[0] is False:
                message = result[1] if len(result) > 1 else "The image could not be created."
                self.terminal.append(message)
                self.show_error("Build Error", message)
                return
            self.terminal.append("Build finished successfully.")

        except PermissionError:
            self.show_error("Access Denied",
                            "Could not write to the image file. It is locked by another program.")
        except Exception as e:
            self.show_error("Build Error", f"A serious error occurred:\n\n{str(e)}")
            self.terminal.append(f"Error: {str(e)}")
    def handle_run(self): 
        self.launcher.run(self.compiler.project_dir, self.terminal.append)

    def setup_shortcuts(self):
        QShortcut(QKeySequence("F5"), self, self.handle_build)
        QShortcut(QKeySequence("F6"), self, self.handle_run)
        QShortcut(QKeySequence("F8"), self, self.handle_export)

    def close_tab(self, index):
        w = self.tabs.widget(index)
        for p, c in list(self.opened_files.items()):
            if c == w:
                c.editor.auto_save()
                del self.opened_files[p]
                break
        self.tabs.removeTab(index)
        self.plugin_manager.apply_plugin_theme(self)

    def add_file(self, target_idx=None):
        if target_idx and target_idx.isValid():
            path = self.model.filePath(target_idx)
        else:
            path = self.compiler.project_dir

        if not os.path.isdir(path):
            path = os.path.dirname(path)

        name, ok = themed_text_input(self, "New File", "Name:")
        if ok and name:
            full_path = os.path.join(path, name)
            try:
                with open(full_path, 'w') as f:
                    pass
                if target_idx and target_idx.isValid():
                    self.tree.expand(target_idx)
            except Exception as e:
                self.show_error("IO Error", str(e))

    def add_folder(self, target_idx=None):
        if target_idx and target_idx.isValid():
            path = self.model.filePath(target_idx)
        else:
            path = self.compiler.project_dir

        if not os.path.isdir(path):
            path = os.path.dirname(path)

        name, ok = themed_text_input(self, "New Folder", "Name:")
        if ok and name:
            full_path = os.path.join(path, name)
            try:
                os.makedirs(full_path, exist_ok=True)
                if target_idx and target_idx.isValid():
                    self.tree.expand(target_idx)
            except Exception as e:
                self.show_error("IO Error", str(e))

    def eventFilter(self, obj, event):
        if obj == self.tabs.tabBar() and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            self.close_tab(self.tabs.tabBar().tabAt(event.pos()))
            return True
        return super().eventFilter(obj, event)


class EditorContainer(QWidget):
    def __init__(self, file_path, parent_window, plugin_manager, parent=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.file_path = file_path
        self.parent_window = parent_window
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.find_bar = FindReplaceBar(None, self, self)
        self.find_bar.hide()
        self.layout.addWidget(self.find_bar)

        self.mode_bar = QWidget()
        self.mode_bar.setObjectName("editor_mode_bar")
        mode_layout = QHBoxLayout(self.mode_bar)
        mode_layout.setContentsMargins(10, 5, 8, 5)
        mode_layout.setSpacing(8)
        self.mode_title = QLabel("ASSEMBLY EDITOR")
        self.mode_title.setObjectName("editor_mode_title")
        mode_layout.addWidget(self.mode_title)
        mode_layout.addStretch()
        self.btn_toggle = QPushButton("Open Node Graph")
        self.btn_toggle.setObjectName("visual_toggle_btn")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setMinimumWidth(132)
        self.btn_toggle.setFixedHeight(28)
        self.btn_toggle.clicked.connect(self.toggle_mode)
        mode_layout.addWidget(self.btn_toggle)
        self.layout.addWidget(self.mode_bar)
        self.stack = QStackedWidget()

        self.editor = CodeEditor(file_path, parent_window, plugin_manager)
        self.find_bar.editor = self.editor

        self.visual_root = QWidget()
        v_layout = QHBoxLayout(self.visual_root)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)
        self.sidebar = BlockContainerSidebar()

        sidebar_panel = QWidget()
        sidebar_panel.setObjectName("node_library_panel")
        sidebar_panel.setMinimumWidth(220)
        sidebar_panel.setMaximumWidth(310)
        sidebar_layout = QVBoxLayout(sidebar_panel)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(7)
        library_title = QLabel("NODE LIBRARY")
        library_title.setObjectName("node_library_title")
        library_title.setStyleSheet("color: #6edcff; font-weight: bold; letter-spacing: 1px;")
        sidebar_layout.addWidget(library_title)
        self.block_search = QLineEdit()
        self.block_search.setObjectName("node_library_search")
        self.block_search.setPlaceholderText("Search blocks...")
        self.block_search.setClearButtonEnabled(True)
        self.block_search.setStyleSheet("""
            QLineEdit { background: #081724; color: #e6f3fb; border: 1px solid #1c4059;
                        border-radius: 6px; padding: 7px 9px; }
            QLineEdit:focus { border-color: #58d2ff; }
        """)
        self.block_search.textChanged.connect(self.refresh_toolbox)
        sidebar_layout.addWidget(self.block_search)
        sidebar_layout.addWidget(self.sidebar, 1)
        hint = QLabel("Drag nodes • drag sockets to wire • wheel zooms • Shift+wheel pans • middle-drag pans")
        hint.setObjectName("node_library_hint")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #7195aa; font-size: 10px;")
        sidebar_layout.addWidget(hint)

        self.canvas_scene = BlockCanvas()
        self.canvas_scene.update_callback = self.sync_code_from_blocks
        self.canvas_scene.variable_provider = self.get_file_variables
        self.canvas_scene.definition_provider = self.get_block_definitions

        self.canvas_view = BlockView(self.canvas_scene)
        self.canvas_view.plugin_manager = self.plugin_manager
        self.canvas_view.open_block_search = self.open_block_search

        canvas_panel = QWidget()
        canvas_layout = QVBoxLayout(canvas_panel)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        node_toolbar = QWidget()
        node_toolbar.setObjectName("node_toolbar")
        toolbar_layout = QHBoxLayout(node_toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        graph_title = QLabel("NODE GRAPH")
        graph_title.setObjectName("node_graph_title")
        graph_title.setStyleSheet("color: #9bdff5; font-weight: bold; letter-spacing: 1px;")
        toolbar_layout.addWidget(graph_title)
        toolbar_layout.addStretch()
        function_btn = QPushButton("+ Function")
        function_btn.clicked.connect(self.add_function_entry)
        function_btn.setFixedHeight(28)
        toolbar_layout.addWidget(function_btn)
        layout_btn = QPushButton("Auto Layout")
        layout_btn.clicked.connect(self.auto_layout_graph)
        layout_btn.setFixedHeight(28)
        toolbar_layout.addWidget(layout_btn)
        frame_btn = QPushButton("Frame All  [Home]")
        frame_btn.clicked.connect(self.canvas_view.frame_all)
        frame_btn.setFixedHeight(26)
        toolbar_layout.addWidget(frame_btn)
        canvas_layout.addWidget(node_toolbar)
        canvas_layout.addWidget(self.canvas_view, 1)

        self.sidebar.itemDoubleClicked.connect(self.add_block_from_sidebar)
        v_layout.addWidget(sidebar_panel)
        v_layout.addWidget(canvas_panel, 1)

        self.stack.addWidget(self.editor)
        self.stack.addWidget(self.visual_root)
        self.layout.addWidget(self.stack)
        if not file_path.lower().endswith('.asm'):
            self.mode_bar.hide()

    def sync_code_from_blocks(self):
        if self.btn_toggle.isChecked():
            gen = self.canvas_scene.generate_code()
            self.editor.blockSignals(True)
            self.editor.setPlainText(gen)
            self.editor.blockSignals(False)
            self.editor.auto_save()

    def toggle_mode(self):
        project_dir = self.parent_window.compiler.project_dir
        filename = os.path.basename(self.file_path)

        try:
            if self.btn_toggle.isChecked():
                self.canvas_scene.load_blocks_from_project(project_dir, filename)

                self.stack.setCurrentIndex(1)
                self.btn_toggle.setText("Return to Code")
                self.mode_title.setText("VISUAL NODE GRAPH")

                self.refresh_toolbox()

                if self.canvas_scene.start_block:
                    QTimer.singleShot(50, lambda: self.canvas_view.ensureVisible(self.canvas_scene.start_block))
                self.plugin_manager.apply_plugin_theme(self)
            else:
                self.canvas_scene.save_blocks_to_project(project_dir, filename)

                self.sync_code_from_blocks()

                self.stack.setCurrentIndex(0)
                self.btn_toggle.setText("Open Node Graph")
                self.mode_title.setText("ASSEMBLY EDITOR")
                self.plugin_manager.apply_plugin_theme(self)

        except Exception as e:
            self.btn_toggle.setChecked(False)
            self.btn_toggle.setText("Open Node Graph")
            self.mode_title.setText("ASSEMBLY EDITOR")
            self.stack.setCurrentIndex(0)

            error_msg = f"Failed to sync blocks for {filename}.\n\nReason: {str(e)}"
            if hasattr(self.parent_window, 'show_error'):
                self.parent_window.show_error("Sync Error", error_msg)
            else:
               self.parent_window.show_error(f"CRITICAL ERROR: {error_msg}")

    def refresh_toolbox(self):
        self.sidebar.clear()
        groups = {}
        theme = self.parent_window.plugin_manager.ui_themes[0] \
            if self.parent_window.plugin_manager.ui_themes else {}
        accent_color = QColor(theme.get("accent", "#6dd5f7"))
        text_color = QColor(theme.get("text", "#c7d8e8"))

        standard_blocks = glob.glob(os.path.join(os.path.dirname(__file__), "blocks", "*.json"))
        plugin_blocks = self.parent_window.plugin_manager.loaded_blocks

        definitions, errors = load_block_definitions(standard_blocks + plugin_blocks)
        search_text = self.block_search.text().strip().lower() if hasattr(self, "block_search") else ""
        definitions.sort(key=lambda data: (data.get("group", "General").lower(), data["name"].lower()))

        visible_definitions = []
        for data in definitions:
            searchable = " ".join((
                str(data.get("name", "")),
                str(data.get("group", "")),
                str(data.get("description", "")),
                " ".join(str(tag) for tag in data.get("tags", [])),
            )).lower()
            if not search_text or search_text in searchable:
                visible_definitions.append(data)
        group_counts = Counter(data.get("group", "General") for data in visible_definitions)

        for data in visible_definitions:
            group_name = data.get("group", "General")
            if group_name not in groups:
                group_item = QTreeWidgetItem(
                    self.sidebar, [f"{group_name.upper()}   {group_counts[group_name]}"]
                )
                group_item.setExpanded(bool(search_text))
                group_item.setForeground(0, accent_color)
                groups[group_name] = group_item
            item = QTreeWidgetItem(groups[group_name], [data["name"]])
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            item.setForeground(0, text_color)
            color = QColor(data.get("color", "#55c7ec"))
            icon_pixmap = QPixmap(12, 12)
            icon_pixmap.fill(Qt.GlobalColor.transparent)
            icon_painter = QPainter(icon_pixmap)
            icon_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            icon_painter.setPen(QPen(color.lighter(145), 1))
            icon_painter.setBrush(color)
            icon_painter.drawEllipse(2, 2, 8, 8)
            icon_painter.end()
            item.setIcon(0, QIcon(icon_pixmap))
            description = data.get("description", "Drag onto the graph to add this node.")
            item.setToolTip(0, description)

        if errors and hasattr(self.parent_window, "terminal"):
            for error in errors:
                self.parent_window.terminal.append(f"Block library warning: {error}")

    def get_block_definitions(self):
        standard = glob.glob(os.path.join(os.path.dirname(__file__), "blocks", "*.json"))
        plugin_paths = self.parent_window.plugin_manager.loaded_blocks
        definitions, errors = load_block_definitions(standard + plugin_paths)
        if errors and hasattr(self.parent_window, "terminal"):
            for error in errors:
                self.parent_window.terminal.append(f"Block library warning: {error}")
        return definitions

    def add_block_from_sidebar(self, item, column=0):
        if not item or not item.parent():
            return
        definition = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(definition, dict):
            return
        block = VisualBlock.from_definition(definition)
        center = self.canvas_view.mapToScene(self.canvas_view.viewport().rect().center())
        self.canvas_scene.add_new_block(
            block, center - QPointF(block.node_width / 2, block.node_height / 2)
        )
        self.canvas_scene.clearSelection()
        block.setSelected(True)

    def add_function_entry(self):
        definition = {
            "name": "Function Entry",
            "group": "Flow",
            "color": "#14b8a6",
            "description": "Begin an independent function chain in this assembly file.",
            "entry_point": True,
            "flow_input": False,
            "flow_output": True,
            "asm_code": "{Function}:",
            "inputs": [{"name": "Function", "label": "Function Name", "default": "function_1"}],
        }
        block = VisualBlock.from_definition(definition)
        center = self.canvas_view.mapToScene(self.canvas_view.viewport().rect().center())
        self.canvas_scene.add_new_block(
            block, center - QPointF(block.node_width / 2, block.node_height / 2)
        )
        self.canvas_scene.clearSelection()
        block.setSelected(True)

    def auto_layout_graph(self):
        self.canvas_scene.auto_layout()
        self.canvas_view.frame_all()

    def open_block_search(self, global_position, scene_position):
        standard = glob.glob(os.path.join(os.path.dirname(__file__), "blocks", "*.json"))
        plugin_paths = self.parent_window.plugin_manager.loaded_blocks
        definitions, errors = load_block_definitions(standard + plugin_paths)
        definitions.sort(key=lambda data: (data.get("group", "General"), data["name"]))
        if errors:
            for error in errors:
                self.parent_window.terminal.append(f"Block library warning: {error}")

        theme = self.parent_window.plugin_manager.ui_themes[0] \
            if self.parent_window.plugin_manager.ui_themes else None
        popup = BlockSearchPopup(definitions, self, theme=theme)
        screen = QApplication.screenAt(global_position)
        x, y = global_position.x(), global_position.y()
        if screen:
            bounds = screen.availableGeometry()
            x = min(max(x, bounds.left()), bounds.right() - popup.width())
            y = min(max(y, bounds.top()), bounds.bottom() - popup.height())
        popup.move(x, y)
        if popup.exec() == QDialog.DialogCode.Accepted and popup.selected_definition:
            block = VisualBlock.from_definition(popup.selected_definition)
            self.canvas_scene.add_new_block(
                block,
                scene_position - QPointF(block.node_width / 2, 28),
            )
            self.canvas_scene.clearSelection()
            block.setSelected(True)

    def get_file_variables(self):
        """Discover variables from only this editor's text and node graph."""
        sources = []
        if not self.btn_toggle.isChecked():
            sources.append((self.editor.toPlainText(), None))
        for item in self.canvas_scene.items():
            if isinstance(item, VisualBlock) and not (item.is_start or item.is_entry):
                try:
                    # Declaration discovery must not call get_asm(): dynamic
                    # print nodes ask this provider for their selected type.
                    rendered = item.asm_template
                    for key, value in item.input_values().items():
                        rendered = rendered.replace(f"{{{key}}}", str(value))
                    allowed_names = set()
                    for key, value in item.input_values().items():
                        placeholder = re.escape("{" + str(key) + "}")
                        if re.search(
                                rf"(?mi)^\s*{placeholder}\s*(?::\s*incbin\b|"
                                rf"(?:equ|db|dw|dd|dq|times)\b)",
                                item.asm_template):
                            allowed_names.add(str(value).casefold())
                    if item.block_name == "Custom Code":
                        allowed_names = None
                    sources.append((rendered, allowed_names))
                except (AttributeError, TypeError):
                    continue

        declarations = re.compile(
            r"(?m)^\s*([A-Za-z_][\w.$@?]*)\s+(db|dw|dd|dq|equ|times)\b([^\n]*)",
            re.IGNORECASE,
        )
        variables = {}
        for source, allowed_names in sources:
            for match in declarations.finditer(source):
                name, directive, remainder = match.groups()
                if name.startswith("."):
                    continue
                if allowed_names is not None and name.casefold() not in allowed_names:
                    continue
                directive = directive.lower()
                if directive == "times":
                    value_type = "word-array" if re.search(r"\bdw\b", remainder, re.I) else "byte-array"
                elif directive == "db" and ("'" in remainder or '"' in remainder):
                    value_type = "text"
                elif directive == "db":
                    value_type = "byte"
                elif directive == "dw":
                    value_type = "word"
                elif directive in ("dd", "dq"):
                    value_type = "wide-integer"
                elif directive == "equ":
                    value_type = "constant"
                else:
                    value_type = "byte"
                variables[name.casefold()] = {"name": name, "type": value_type}
        return sorted(variables.values(), key=lambda item: item["name"].casefold())


class TabButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(16, 16)
        self.set_node_theme(DEFAULT_THEME)

    def set_node_theme(self, theme):
        colors = resolved_theme(theme)
        text = colors["editor_text"]
        hover = colors["button_hover"]
        accent = colors["accent"]
        self.setStyleSheet(f"""
            QPushButton {{ color: {text}; background: transparent; border: none; font-weight: bold; padding: 0; }}
            QPushButton:hover {{ color: {accent}; background: {hover}; }}
        """)
