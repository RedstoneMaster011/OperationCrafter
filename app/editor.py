import glob
import json
import os
import shutil

from PyQt6.QtCore import Qt, QEvent, QTimer, QRect, QPoint, QSize, QMimeData
from PyQt6.QtGui import (QFileSystemModel, QShortcut, QKeySequence, QPainter,
                         QColor, QTextCursor, QDrag)
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QTreeView, QPushButton, QSplitter,
                             QInputDialog, QMessageBox, QMenu, QTabWidget,
                             QTabBar, QRubberBand, QPlainTextEdit, QLineEdit,
                             QFrame, QDialog, QFormLayout, QDialogButtonBox,
                             QStackedWidget, QTreeWidget, QTreeWidgetItem, QGraphicsView, QApplication, QLabel)

from .PluginManager import PluginManager, PluginDialog
from .block import BlockCanvas, VisualBlock
from .emulator import OSLauncher
from .highlight import SyntaxHighlighter


class SettingsDialog(QDialog):
    def __init__(self, current_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project Settings")
        self.setFixedWidth(350)
        self.setStyleSheet("background-color: #1e1e1e; color: white;")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_input = QLineEdit(current_data.get("name", ""))
        self.name_input.setStyleSheet("background: #2d2d2d; color: white; border: 1px solid #444; padding: 5px;")
        self.version_input = QLineEdit(current_data.get("version", "1.0.0"))
        self.version_input.setStyleSheet("background: #2d2d2d; color: white; border: 1px solid #444; padding: 5px;")
        form.addRow("Project Name:", self.name_input)
        form.addRow("Version:", self.version_input)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet("QPushButton { background-color: #333; color: white; padding: 5px; }")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_data(self): return {"name": self.name_input.text(), "version": self.version_input.text()}


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
            if os.path.isdir(src): shutil.copytree(src, target)
            else: shutil.copy2(src, target)
        except Exception as e: print(f"Paste Error: {e}")


class FindReplaceBar(QFrame):
    def __init__(self, editor_widget, container, parent=None):
        super().__init__(parent)
        self.editor = editor_widget; self.container = container
        self.setFixedHeight(45)
        self.setStyleSheet("""
            QFrame { background-color: #2d2d2d; border-bottom: 1px solid #454545; }
            QLineEdit { background: #3c3c3c; color: white; border: 1px solid #555; padding: 4px; }
            QPushButton { background: #444; color: white; border: 1px solid #555; padding: 4px 10px; }
            QPushButton:hover { background: #007acc; }
        """)
        layout = QHBoxLayout(self)
        self.find_input = QLineEdit(); self.find_input.setPlaceholderText("Find...")
        self.replace_input = QLineEdit(); self.replace_input.setPlaceholderText("Replace...")
        self.replace_input.hide()
        self.btn_next = QPushButton("Next"); self.btn_next.clicked.connect(self.find_next)
        self.btn_replace = QPushButton("Replace"); self.btn_replace.clicked.connect(self.replace_current); self.btn_replace.hide()
        self.btn_close = QPushButton("✕"); self.btn_close.setFixedWidth(30); self.btn_close.clicked.connect(self.hide_bar)
        layout.addWidget(self.find_input); layout.addWidget(self.replace_input); layout.addWidget(self.btn_next); layout.addWidget(self.btn_replace)
        layout.addStretch(); layout.addWidget(self.btn_close)

    def show_find(self):
        self.container.btn_toggle.hide(); self.replace_input.hide(); self.btn_replace.hide(); self.show(); self.find_input.setFocus()

    def show_replace(self):
        self.container.btn_toggle.hide(); self.replace_input.show(); self.btn_replace.show(); self.show(); self.find_input.setFocus()

    def hide_bar(self):
        self.hide(); self.editor.setFocus()
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
    def __init__(self, editor): super().__init__(editor); self.editor = editor
    def sizeHint(self): return QSize(self.editor.line_number_area_width(), 0)
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), self.palette().window().color())
        self.editor.lineNumberAreaPaintEvent(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, file_path, parent_window, plugin_manager, parent=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.file_path = file_path; self.parent_window = parent_window
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area); self.update_line_number_area_width(0)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet("color: #d4d4d4; font-family: 'Consolas'; font-size: 13px; border: none;")
        self.save_timer = QTimer(); self.save_timer.setSingleShot(True); self.save_timer.timeout.connect(self.auto_save)
        self.textChanged.connect(lambda: self.save_timer.start(500))
        self.setStyleSheet("color: #d4d4d4; font-family: 'Consolas'; font-size: 13px; border: none;")

    def auto_save(self):
        if self.file_path:
            with open(self.file_path, 'w', encoding='utf-8', errors='ignore') as f: f.write(self.toPlainText())
        self.plugin_manager.apply_plugin_theme(self)

    def contextMenuEvent(self, event):
        menu = QMenu(self); menu.setStyleSheet("QMenu { background: #252526; color: white; border: 1px solid #454545; }")
        menu.addAction("Undo", self.undo); menu.addAction("Redo", self.redo); menu.addSeparator()
        menu.addAction("Cut", self.cut); menu.addAction("Copy", self.copy); menu.addAction("Paste", self.paste); menu.addSeparator()
        container = self.parentWidget().parentWidget()
        menu.addAction("Find", container.find_bar.show_find); menu.addAction("Replace", container.find_bar.show_replace)
        menu.exec(event.globalPos())

    def line_number_area_width(self):
        return 12 + self.fontMetrics().horizontalAdvance('9') * len(str(max(1, self.blockCount())))

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy: self.line_number_area.scroll(0, dy)
        else: self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event); cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self.line_number_area.palette().window().color())
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            painter.setPen(QColor("#606060"))
            painter.drawText(0, top, self.line_number_area_width() - 5, self.fontMetrics().height(),
                             Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            block = block.next(); top += round(self.blockBoundingRect(block).height())
        self.plugin_manager.apply_plugin_theme(self)


class BlockView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("border: none;")
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            z = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.scale(z, z)
        else: super().wheelEvent(event)

    def dragEnterEvent(self, e): e.accept() if e.mimeData().hasText() else e.ignore()
    def dragMoveEvent(self, e): e.accept() if e.mimeData().hasText() else e.ignore()

    def dropEvent(self, e):
        name = e.mimeData().text()
        blocks_dir = os.path.join(os.path.dirname(__file__), "blocks")
        all_paths = glob.glob(os.path.join(blocks_dir, "*.json"))

        manager = None
        if hasattr(self, 'plugin_manager'):
            manager = self.plugin_manager
        elif hasattr(self.window(), 'plugin_manager'):
            manager = self.window().plugin_manager

        if manager:
            all_paths += manager.loaded_blocks

        for f in all_paths:
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    data = json.load(file)
                    if data.get('name') == name:
                        block = VisualBlock(
                            data['name'],
                            data['asm_code'],
                            data.get('inputs', []),
                            data.get('req_funcs', []),
                            data.get('color', '#007acc')
                        )
                        self.scene().addItem(block)
                        drop_pos = self.mapToScene(e.position().toPoint())
                        block.setPos(drop_pos)
                        e.accept()
                        return
            except Exception:
                continue


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Operation Crafter - Help")
        self.setFixedSize(350, 150)
        self.setStyleSheet("background: #1e1e1e; color: white;")

        layout = QVBoxLayout(self)

        self.msg_label = QLabel("There's right now no help.")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.msg_label)

        self.link_label = QLabel('README: <a href="https://example.com" style="color: #007acc;">README.MD</a>')
        self.link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.link_label.setOpenExternalLinks(True)
        layout.addWidget(self.link_label)

        btn_layout = QHBoxLayout()
        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedWidth(80)
        self.close_btn.setStyleSheet("""
            QPushButton { 
                background: #444; 
                color: white; 
                padding: 5px; 
                border-radius: 4px; 
            }
            QPushButton:hover { background: #555; }
        """)
        self.close_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

class BlockContainerSidebar(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setDragEnabled(True); self.setHeaderHidden(True)
        self.setStyleSheet("QTreeWidget { color: #ccc; border: none; font-size: 11px; }")

    def startDrag(self, actions):
        item = self.currentItem()
        if item and item.parent():
            drag = QDrag(self); mime = QMimeData(); mime.setText(item.text(0)); drag.setMimeData(mime); drag.exec(Qt.DropAction.CopyAction)


class IDEWindow(QMainWindow):
    def __init__(self, compiler, parent=None):
        super().__init__(parent); self.compiler = compiler; self.launcher = OSLauncher(self.compiler.root_dir); self.opened_files = {}
        self.plugin_manager = PluginManager(self.compiler.root_dir)
        self.plugin_manager.load_plugins()
        self.terminal = QTextEdit()
        self.terminal.setObjectName("terminal")
        self.plugin_manager.apply_plugin_theme(self)

    def show_error(self, title, message):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStyleSheet(
            "background-color: #2d2d2d; color: white; QPushButton { background: #444; color: white; padding: 5px; }")
        msg.exec()
        self.plugin_manager.apply_plugin_theme(self)

    def launch_ide(self, path):
        self.compiler.project_dir = path
        self.setup_ui()
        self.setup_shortcuts()
        self.plugin_manager.apply_plugin_theme(self)
        self.showMaximized()
        path_str = str(path)
        windows_path = path_str.replace("/", "\\")
        self.setWindowTitle(f"Operation Crafter - {windows_path}")
        self.setWindowIcon(QApplication.windowIcon())

    def setup_ui(self):
        central = QWidget(); self.setCentralWidget(central); layout = QVBoxLayout(central)
        t_bar = QHBoxLayout()
        for txt, func in [("Build (F5)", self.handle_build), ("Run (F6)", self.handle_run), ("Settings", self.open_settings_gui), ("Plugins", self.open_plugins_gui), ("Help", self.open_help_gui)]:
            btn = QPushButton(txt); btn.clicked.connect(func); t_bar.addWidget(btn)
        t_bar.addStretch(); layout.addLayout(t_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.model = QFileSystemModel(); self.model.setRootPath(self.compiler.project_dir); self.model.setReadOnly(False)
        self.tree = ProjectTreeView(); self.tree.setModel(self.model); self.tree.setRootIndex(self.model.index(self.compiler.project_dir))
        for i in range(1, 4): self.tree.setColumnHidden(i, True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.doubleClicked.connect(self.open_file)

        self.tabs = QTabWidget(); self.tabs.setTabsClosable(True); self.tabs.tabCloseRequested.connect(self.close_tab); self.tabs.tabBar().installEventFilter(self)
        self.tabs.setStyleSheet("QTabBar::tab { background: #141414; color: #888; padding: 8px 12px; border: 1px solid #252526; } QTabBar::tab:selected { background: #1e1e1e; color: white; border-bottom: 2px solid #007acc; }")
        self.splitter.addWidget(self.tree); self.splitter.addWidget(self.tabs); self.splitter.setSizes([250, 750]); layout.addWidget(self.splitter)
        self.terminal = QTextEdit(); self.terminal.setFixedHeight(120); self.terminal.setReadOnly(True); self.terminal.setStyleSheet("background: #000; color: #d4d4d4; font-family: Consolas;");
        layout.addWidget(self.terminal)
        central.setObjectName("main_window_central")
        self.plugin_manager.apply_plugin_theme(self)

    def open_help_gui(self):
        hpg = HelpDialog()
        hpg.exec()

    def open_plugins_gui(self):
        dlg = PluginDialog(self.plugin_manager, self)
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

        confirm = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete {len(paths)} item(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
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
        old = self.model.filePath(idx); name, ok = QInputDialog.getText(self, "Rename", "Name:", text=os.path.basename(old))
        if ok and name: os.rename(old, os.path.join(os.path.dirname(old), name))

    def show_context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        menu = QMenu(self)

        menu.addAction("New File", lambda: self.add_file(idx))
        menu.addAction("New Folder", lambda: self.add_folder(idx))
        menu.addSeparator()

        if idx.isValid():
            menu.addAction("Copy", lambda: setattr(self.tree, 'clipboard_path', self.model.filePath(idx)))
            menu.addAction("Rename", lambda: self.rename_item(idx))
            menu.addAction("Delete", self.delete_item)

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
            data = {"name": "Project", "version": "1.0.0"}
        dlg = SettingsDialog(data, self)
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
            self.compiler.compile_to_img()
            self.terminal.append("Build Finished successfully.")

        except PermissionError:
            self.show_error("Access Denied",
                            "Could not write to the image file. It is locked by another program.")
        except Exception as e:
            self.show_error("Build Error", f"A serious error occurred:\n\n{str(e)}")
            self.terminal.append(f"Error: {str(e)}")
    def handle_run(self): self.launcher.run(self.compiler.project_dir, self.terminal.append)

    def setup_shortcuts(self):
        QShortcut(QKeySequence("F5"), self, self.handle_build)
        QShortcut(QKeySequence("F6"), self, self.handle_run)

    def close_tab(self, index):
        w = self.tabs.widget(index)
        for p, c in list(self.opened_files.items()):
            if c == w: c.editor.auto_save(); del self.opened_files[p]; break
        self.tabs.removeTab(index)
        self.plugin_manager.apply_plugin_theme(self)

    def add_file(self, target_idx=None):
        if target_idx and target_idx.isValid():
            path = self.model.filePath(target_idx)
        else:
            path = self.compiler.project_dir

        if not os.path.isdir(path):
            path = os.path.dirname(path)

        name, ok = QInputDialog.getText(self, 'New File', 'Name:')
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

        name, ok = QInputDialog.getText(self, 'New Folder', 'Name:')
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
            self.close_tab(self.tabs.tabBar().tabAt(event.pos())); return True
        return super().eventFilter(obj, event)


class EditorContainer(QWidget):
    def __init__(self, file_path, parent_window, plugin_manager, parent=None):
        super().__init__(parent);
        self.plugin_manager = plugin_manager
        self.file_path = file_path;
        self.parent_window = parent_window
        self.layout = QVBoxLayout(self);
        self.layout.setContentsMargins(0, 0, 0, 0);
        self.layout.setSpacing(0)

        self.find_bar = FindReplaceBar(None, self, self);
        self.find_bar.hide();
        self.layout.addWidget(self.find_bar)
        self.stack = QStackedWidget()

        self.editor = CodeEditor(file_path, parent_window, plugin_manager)
        self.find_bar.editor = self.editor

        self.visual_root = QWidget();
        v_layout = QHBoxLayout(self.visual_root);
        v_layout.setContentsMargins(0, 0, 0, 0);
        v_layout.setSpacing(0)
        self.sidebar = BlockContainerSidebar()

        self.canvas_scene = BlockCanvas()
        self.canvas_scene.update_callback = self.sync_code_from_blocks

        self.canvas_view = BlockView(self.canvas_scene)
        v_layout.addWidget(self.sidebar, 1);
        v_layout.addWidget(self.canvas_view, 4)

        self.stack.addWidget(self.editor);
        self.stack.addWidget(self.visual_root);
        self.layout.addWidget(self.stack)

        self.btn_toggle = QPushButton("Visual Blocks", self)
        self.btn_toggle.setObjectName("visual_toggle_btn")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setFixedSize(110, 22)
        self.btn_toggle.clicked.connect(self.toggle_mode)
        if not file_path.lower().endswith('.asm'): self.btn_toggle.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event); self.btn_toggle.move(self.width() - 120, 5)

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

                self.refresh_toolbox()

                if self.canvas_scene.start_block:
                    QTimer.singleShot(50, lambda: self.canvas_view.ensureVisible(self.canvas_scene.start_block))
                self.plugin_manager.apply_plugin_theme(self)
            else:
                self.canvas_scene.save_blocks_to_project(project_dir, filename)

                self.sync_code_from_blocks()

                self.stack.setCurrentIndex(0)
                self.plugin_manager.apply_plugin_theme(self)

        except Exception as e:
            self.btn_toggle.setChecked(False)
            self.stack.setCurrentIndex(0)

            error_msg = f"Failed to sync blocks for {filename}.\n\nReason: {str(e)}"
            if hasattr(self.parent_window, 'show_error'):
                self.parent_window.show_error("Sync Error", error_msg)
            else:
                print(f"CRITICAL ERROR: {error_msg}")

    def refresh_toolbox(self):
        self.sidebar.clear()
        groups = {}

        standard_blocks = glob.glob(os.path.join(os.path.dirname(__file__), "blocks", "*.json"))
        plugin_blocks = self.parent_window.plugin_manager.loaded_blocks

        all_block_paths = standard_blocks + plugin_blocks

        for f in all_block_paths:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    group_name = data.get("group", "General")
                    if group_name not in groups:
                        groups[group_name] = QTreeWidgetItem(self.sidebar, [group_name])
                        groups[group_name].setExpanded(True)
                    QTreeWidgetItem(groups[group_name], [data['name']])
            except:
                pass


class TabButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent); self.setFixedSize(16, 16)
        self.setStyleSheet("QPushButton { color: #666; background: transparent; border: none; font-weight: bold; } QPushButton:hover { color: #bbb; background: #333; }")