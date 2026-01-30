import os, json, glob
from PyQt6.QtWidgets import (QGraphicsItem, QGraphicsRectItem, QGraphicsTextItem,
                             QGraphicsScene, QGraphicsView, QGraphicsProxyWidget, QLineEdit)
from PyQt6.QtGui import QColor, QPen, QBrush
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer

BLOCK_WIDTH = 250
BLOCK_HEIGHT = 50


class VisualBlock(QGraphicsRectItem):
    def __init__(self, name, asm_code, inputs=None, req_funcs=None, color_hex="#007acc", is_start=False):
        self.input_list = inputs if inputs else []
        self.block_name = name
        self.asm_template = asm_code
        self.req_funcs = req_funcs if req_funcs else []
        self.is_start = is_start
        self.base_color = QColor(color_hex) if not is_start else QColor("#d97706")
        self.is_vibrant = False
        self.input_widgets = {}
        self._is_updating = False

        h = max(BLOCK_HEIGHT, 30 + (len(self.input_list) * 25))
        super().__init__(0, 0, BLOCK_WIDTH, h)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)

        self.setBrush(QBrush(self.base_color))
        self.setPen(QPen(QColor("#ffffff"), 1))

        self.label = QGraphicsTextItem(name, self)
        self.label.setDefaultTextColor(QColor("white"))
        self.label.setPos(5, 2)

        for i, inp in enumerate(self.input_list):
            y_pos = 35 + (i * 30)

            label_text = inp.get('name', 'input') + ":"
            label = QGraphicsTextItem(label_text, self)
            label.setDefaultTextColor(QColor("#bbbbbb"))
            label.setPos(10, y_pos)

            edit = QLineEdit()
            edit.setText(str(inp.get('value', inp.get('default', ''))))
            edit.setFixedWidth(100)
            edit.setStyleSheet("""
                        background: #1a1a1a; 
                        color: #00ffcc; 
                        border: 1px solid #444; 
                        font-size: 10px; 
                        font-family: 'Consolas';
                    """)
            edit.textChanged.connect(self.on_input_changed)

            proxy = QGraphicsProxyWidget(self)
            proxy.setWidget(edit)
            proxy.setPos(BLOCK_WIDTH - 115, y_pos)

            self.input_widgets[inp['name']] = edit
        new_h = 45 + (len(self.input_list) * 30)
        self.setRect(0, 0, BLOCK_WIDTH, max(BLOCK_HEIGHT, new_h))



    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not self.is_start:
                scene = self.scene()
                self.self_destruct()
                if scene and hasattr(scene, 'save_blocks_to_project'):
                    scene.save_blocks_to_project()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.setFocus()

    def on_input_changed(self):
        scene = self.scene()
        if scene:
            if hasattr(scene, 'update_callback'): scene.update_callback()
            if hasattr(scene, 'save_blocks_to_project'): scene.save_blocks_to_project()

    def set_vibrant(self, active):
        if self.is_vibrant == active: return
        self.is_vibrant = active
        color = self.base_color.lighter(50) if active else self.base_color
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#00ffcc") if active else QColor("#ffffff"), 0.5))

    def get_child_block(self):
        scene = self.scene()
        if not scene: return None
        tx, ty = self.scenePos().x(), self.scenePos().y() + self.rect().height()
        for item in scene.items():
            if isinstance(item, VisualBlock) and item != self:
                if abs(item.scenePos().x() - tx) < 5 and abs(item.scenePos().y() - ty) < 5:
                    return item
        return None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and not self._is_updating:
            self.prepareGeometryChange()
            new_pos = value
            old_pos = self.pos()
            diff = new_pos - old_pos
            if self.is_start:
                if new_pos.x() < 10: return QPointF(10, new_pos.y())
            elif new_pos.x() < -50:
                QTimer.singleShot(1, self.self_destruct)
                return new_pos
            child = self.get_child_block()
            if child:
                child._is_updating = True
                child.setPos(child.pos() + diff)
                child._is_updating = False
            return super().itemChange(change, value)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            for item in list(scene.items()):
                if isinstance(item, VisualBlock) and item != self:
                    if abs(item.pos().x() - self.pos().x()) < 1 and abs(item.pos().y() - self.pos().y()) < 1:
                        if not item.is_start: scene.removeItem(item)
            self.check_snap()
            scene.refresh_vibrancy()
            if hasattr(scene, 'save_blocks_to_project'):
                scene.save_blocks_to_project()
        self.on_input_changed()

    def check_snap(self):
        if self.is_start: return
        scene = self.scene()
        if not scene: return
        x, y = self.scenePos().x(), self.scenePos().y()
        for item in scene.items():
            if isinstance(item, VisualBlock) and item != self:
                tx, ty = item.scenePos().x(), item.scenePos().y() + item.rect().height()
                if abs(x - tx) < 30 and abs(y - ty) < 30:
                    self._is_updating = True
                    self.setPos(tx, ty)
                    self._is_updating = False
                    break

    def self_destruct(self):
        scene = self.scene()
        if scene:
            scene.removeItem(self)
            if hasattr(scene, 'update_callback'): scene.update_callback()

    def get_asm(self):
        name_widget = self.input_widgets.get("Function")

        if self.is_start:
            label_text = name_widget.text().strip() if name_widget else "start"
            if label_text.lower() == "start" or label_text == "":
                return ""
            return f"{label_text}:"

        code = self.asm_template
        for key, widget in self.input_widgets.items():
            code = code.replace(f"{{{key}}}", widget.text())

        indent = ""
        scene = self.scene()
        if scene and hasattr(scene, 'start_block') and scene.start_block:
            header_widget = scene.start_block.input_widgets.get("Function")
            header_text = header_widget.text().strip() if header_widget else "start"

            if header_text.lower() != "start" and header_text != "":
                indent = "    "

        return "\n".join([indent + line for line in code.splitlines()])


class BlockCanvas(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(0, 0, 5000, 5000, parent)
        self.update_callback = None
        self.start_block = None
        self.project_dir = None
        self.current_filename = None
        self.setBackgroundBrush(QBrush(Qt.GlobalColor.transparent))
        self.reset_canvas()

    def reset_canvas(self):
        self.blockSignals(True)
        self.clear()

        start_inputs = [{"name": "Function", "default": "start"}]

        self.start_block = VisualBlock("START", "", inputs=start_inputs, is_start=True)
        self.addItem(self.start_block)
        self.start_block.setPos(150, 100)
        self.blockSignals(False)

    def refresh_vibrancy(self):
        if not self.start_block: return
        for item in self.items():
            if isinstance(item, VisualBlock): item.set_vibrant(False)
        visited, current = [self.start_block], self.start_block
        while True:
            found_next = False
            tx, ty = current.scenePos().x(), current.scenePos().y() + current.rect().height()
            for item in self.items():
                if isinstance(item, VisualBlock) and item not in visited:
                    if abs(item.scenePos().x() - tx) < 5 and abs(item.scenePos().y() - ty) < 5:
                        item.set_vibrant(True)
                        visited.append(item)
                        current = item
                        found_next = True
                        break
            if not found_next: break

    def generate_code(self):
        if not self.start_block: return ""

        code_output = []
        helpers = set()
        visited = [self.start_block]
        current = self.start_block

        start_asm = current.get_asm()
        if start_asm:
            code_output.append(start_asm)

        while True:
            found_next = False
            tx, ty = current.scenePos().x(), current.scenePos().y() + current.rect().height()

            for item in self.items():
                if isinstance(item, VisualBlock) and item not in visited:
                    if abs(item.scenePos().x() - tx) < 5 and abs(item.scenePos().y() - ty) < 5:
                        block_asm = item.get_asm()
                        if block_asm:
                            code_output.append(block_asm)

                        for f in item.req_funcs:
                            t_f = f
                            for key, widget in item.input_widgets.items():
                                t_f = t_f.replace(f"{{{key}}}", widget.text())
                            helpers.add(t_f)

                        visited.append(item)
                        current = item
                        found_next = True
                        break

            if not found_next:
                break

        full_code = "\n".join(code_output)
        if helpers:
            full_code += "\n\n" + "\n".join(helpers)

        return full_code

    def save_blocks_to_project(self, project_dir=None, current_file_name=None):
        p_dir = project_dir or self.project_dir
        f_name = current_file_name or self.current_filename

        if not p_dir or not f_name: return

        b_dir = os.path.join(p_dir, "blocks")
        os.makedirs(b_dir, exist_ok=True)
        current_blocks = [item for item in self.items() if isinstance(item, VisualBlock)]

        prefix = f_name
        for f in glob.glob(os.path.join(b_dir, f"{prefix}_*.json")):
            try:
                os.remove(f)
            except:
                pass

        for i, item in enumerate(current_blocks):
            path = os.path.join(b_dir, f"{prefix}_{i}.json")
            data = {
                "name": item.block_name, "x": item.pos().x(), "y": item.pos().y(),
                "asm_code": item.asm_template, "req_funcs": item.req_funcs,
                "is_start": item.is_start, "color": item.base_color.name(), "inputs": []
            }
            for n, w in item.input_widgets.items():
                data["inputs"].append({"name": n, "value": w.text()})

            with open(path, 'w') as f:
                json.dump(data, f)

    def load_blocks_from_project(self, project_dir, current_file_name):
        self.project_dir = project_dir
        self.current_filename = current_file_name

        b_dir = os.path.join(project_dir, "blocks")
        if not os.path.exists(b_dir):
            self.reset_canvas()
            return

        self.blockSignals(True)
        self.clear()
        self.start_block = None
        prefix = current_file_name

        files = glob.glob(os.path.join(b_dir, f"{prefix}_*.json"))
        for f_path in files:
            try:
                with open(f_path, 'r') as f:
                    d = json.load(f)
                    b = VisualBlock(d['name'], d['asm_code'], d.get('inputs'),
                                    d.get('req_funcs'), d.get('color'), is_start=d.get('is_start', False))
                    self.addItem(b)
                    b.setPos(d['x'], d['y'])
                    if d.get('is_start'): self.start_block = b
            except:
                continue

        if self.start_block is None: self.reset_canvas()
        self.blockSignals(False)
        self.refresh_vibrancy()