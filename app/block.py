import glob
import json
import os
import re
import uuid

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                         QPainterPath, QPen)
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QGraphicsItem,
                             QGraphicsObject, QGraphicsPathItem,
                             QGraphicsProxyWidget, QGraphicsScene,
                             QGraphicsTextItem, QLineEdit, QSpinBox)


BLOCK_WIDTH = 286
HEADER_HEIGHT = 40
INPUT_ROW_HEIGHT = 38
SOCKET_RADIUS = 7
VARIABLE_TOKEN_RE = re.compile(r"^%var\[([^\]]+)\]$")


def _assembly_string_bytes(value):
    """Encode user text without allowing quotes to break generated NASM."""
    encoded = str(value).encode("cp437", errors="replace")
    return ", ".join(str(byte) for byte in encoded) or "0"


def read_block_catalog(path):
    """Return normalized block definitions from a legacy file or v2 catalog."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    catalog_defaults = {}
    if isinstance(raw, list):
        definitions = raw
    elif isinstance(raw, dict) and (isinstance(raw.get("blocks"), list)
                                    or isinstance(raw.get("families"), list)):
        definitions = list(raw.get("blocks", []))
        for family in raw.get("families", []):
            if not isinstance(family, dict):
                continue
            family_defaults = {
                key: value for key, value in family.items()
                if key not in ("variants", "defaults")
            }
            if isinstance(family.get("defaults"), dict):
                family_defaults.update(family["defaults"])
            for variant in family.get("variants", []):
                if isinstance(variant, dict):
                    definitions.append({**family_defaults, **variant})
        catalog_defaults = raw.get("defaults", {})
    elif isinstance(raw, dict):
        definitions = [raw]
    else:
        raise ValueError("Block file must contain an object, list, or blocks catalog")

    result = []
    for definition in definitions:
        if not isinstance(definition, dict):
            continue
        if not definition.get("name") or "asm_code" not in definition:
            continue
        block = dict(catalog_defaults) if isinstance(catalog_defaults, dict) else {}
        block.update(definition)
        block.setdefault("group", "General")
        block.setdefault("color", "#3b82f6")
        block.setdefault("inputs", [])
        block.setdefault("req_funcs", [])
        block["_source_path"] = path
        result.append(_modernize_block_definition(block))
    return result


def load_block_definitions(paths):
    definitions = []
    errors = []
    for path in paths:
        try:
            definitions.extend(read_block_catalog(path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{os.path.basename(path)}: {error}")
    override_names = {
        block["name"].casefold() for block in definitions if block.get("override")
    }
    if override_names:
        definitions = [
            block for block in definitions
            if block.get("override") or block["name"].casefold() not in override_names
        ]

    # Keep the last explicit override for a name and avoid duplicate toolbox entries.
    unique = {}
    order = []
    for block in definitions:
        key = block["name"].casefold()
        if key not in unique:
            order.append(key)
        if key not in unique or block.get("override"):
            unique[key] = block
    return [unique[key] for key in order], errors


def _safe_color(value, fallback="#3b82f6"):
    color = QColor(value or fallback)
    return color if color.isValid() else QColor(fallback)


LEGACY_DESCRIPTIONS = {
    "Add Var (Int)": "Add a constant to an existing byte variable.",
    "Bootloader": "Generate the complete current-platform boot sector and kernel loader.",
    "Call Function": "Include an assembly file and call one of its functions.",
    "Change Color Palette (Graphics)": "Update one 6-bit RGB palette color in graphics mode.",
    "Change Color Palette (Text)": "Update one VGA palette color used by text display output.",
    "Clear Screen (Graphics)": "Clear the full graphics framebuffer and reset the cursor.",
    "Clear Screen (Text)": "Clear the text display and return the cursor to the top-left corner.",
    "Int to String": "Convert an unsigned byte variable to a printable decimal string.",
    "Custom Code": "Insert custom NASM assembly when a specialized node is not available.",
    "Disable Graphics Mode": "Return the display to standard color text mode.",
    "Disk Setup": "Define the current-platform disk-read helper used by a boot sector.",
    "Draw Picture": "Include and draw an indexed-color image resource.",
    "Draw Rectangle": "Draw a filled rectangle between two screen coordinates.",
    "Enable Graphics Mode": "Switch the display to 320x200 indexed-color graphics.",
    "End": "Stop execution in a safe infinite halt loop.",
    "Halt": "Disable interrupts and halt the processor safely.",
    "Hide Cursor": "Hide the hardware text cursor.",
    "If Key, Call Function": "Call a function when a matching key is waiting.",
    "If Variable Equals Int, Run Function": "Call a function when a byte variable equals a value.",
    "If Variable Equals String, Run Function": "Call a function when two zero-terminated strings match.",
    "JMP to Function (This File)": "Jump to a function or label in the current file.",
    "Load Registry Slot": "Copy a zero-terminated value from shared memory into a local buffer.",
    "Move Cursor": "Move the text cursor to a row and column.",
    "Play Beep Sound": "Play a PC-speaker tone at a frequency for a duration.",
    "Print to Screen (Text)": "Print colored text in the current text display mode.",
    "Print to Screen (Graphics)": "Print text over the current graphics display.",
    "If Random, Call Function": "Call a function when a random value matches a chosen target.",
    "Reboot": "Restart the machine using the current platform reset vector.",
    "Register": "Set the NASM origin for code loaded at a fixed address.",
    "Set Pixel": "Draw one indexed-color pixel at X/Y coordinates.",
    "Set Screen Color": "Fill the graphics framebuffer with one palette color.",
    "Set Var (Int)": "Define and initialize a named byte variable safely outside execution flow.",
    "Set Var (Text)": "Define a named zero-terminated string safely outside execution flow.",
    "Show Cursor": "Restore the standard hardware text cursor.",
    "Shutdown": "Request a power-off using the current platform power service.",
    "Store In Registry Slot": "Copy a local zero-terminated value into shared memory.",
    "Wait": "Pause for an approximate number of milliseconds.",
    "Wait for KeyPress": "Wait until any keyboard key is pressed.",
    "Wait for Specific Key": "Wait until a chosen ASCII key code is pressed.",
}


LEGACY_ASM_UPGRADES = {
    "Clear Screen (Graphics)": (
        "push es\nmov ax, 0xa000\nmov es, ax\nxor di, di\n"
        "xor ax, ax\nmov cx, 32000\nrep stosw\npop es"
    ),
    "Draw Rectangle": (
        "mov dx, {Y1}\n.rect_row_{ID}:\nmov cx, {X1}\n.rect_col_{ID}:\n"
        "mov ah, 0x0c\nmov al, {COLOR}\nxor bh, bh\nint 0x10\ninc cx\n"
        "cmp cx, {X2}\njbe .rect_col_{ID}\ninc dx\ncmp dx, {Y2}\n"
        "jbe .rect_row_{ID}"
    ),
    "Draw Picture": (
        "jmp picture_data_ready_{ID}\n%include \"{FILE}\"\npicture_data_ready_{ID}:\n"
        "mov si, {SYMBOL}_data\nadd si, 768\nmov dx, {Y}\nmov bp, [{SYMBOL}_height]\n"
        ".picture_row_{ID}:\nmov cx, {X}\nmov di, [{SYMBOL}_width]\n"
        ".picture_pixel_{ID}:\nlodsb\nmov ah, 0x0c\nxor bh, bh\nint 0x10\n"
        "inc cx\ndec di\njnz .picture_pixel_{ID}\ninc dx\ndec bp\n"
        "jnz .picture_row_{ID}"
    ),
    "Wait for Specific Key": (
        ".wait_key_{ID}:\nmov ah, 0x00\nint 0x16\ncmp al, {KEY_CODE}\n"
        "jne .wait_key_{ID}"
    ),
    "Set Var (Int)": (
        "jmp after_var_{ID}\n{VAR} db {VALUE}\nafter_var_{ID}:\nmov si, {VAR}"
    ),
    "Set Var (Text)": (
        "jmp after_var_{ID}\n{VAR} db '{VALUE}', 0\nafter_var_{ID}:\nmov si, {VAR}"
    ),
    "Disk Setup": (
        "jmp disk_setup_done_{ID}\ndisk_load:\n    push dx\n    mov si, 3\n"
        ".disk_retry:\n    mov ah, 0x02\n    mov al, dh\n    xor ch, ch\n"
        "    xor dh, dh\n    mov cl, 0x02\n    mov dl, [0x7e00]\n    int 0x13\n"
        "    jnc .disk_done\n    xor ax, ax\n    int 0x13\n    dec si\n"
        "    jnz .disk_retry\n    mov ah, 0x0e\n    mov al, 'E'\n    int 0x10\n"
        "    cli\n.disk_error_halt:\n    hlt\n    jmp .disk_error_halt\n"
        ".disk_done:\n    pop dx\n    ret\ndisk_setup_done_{ID}:"
    ),
    "Halt": "cli\n.halt_forever_{ID}:\nhlt\njmp .halt_forever_{ID}",
    "End": "cli\n.end_forever_{ID}:\nhlt\njmp .end_forever_{ID}",
    "Play Beep Sound": (
        "mov bx, {FREQUENCY}\nor bx, bx\njz .beep_done_{ID}\n"
        "mov al, 0xb6\nout 0x43, al\nmov dx, 0x0012\nmov ax, 0x34dc\n"
        "div bx\nout 0x42, al\nmov al, ah\nout 0x42, al\n"
        "in al, 0x61\nor al, 3\nout 0x61, al\nmov ax, {MS}\nmov cx, 1000\n"
        "mul cx\nmov cx, dx\nmov dx, ax\nmov ah, 0x86\nint 0x15\n"
        "in al, 0x61\nand al, 0xfc\nout 0x61, al\n.beep_done_{ID}:"
    ),
    "Set Screen Color": (
        "push es\nmov ax, 0xa000\nmov es, ax\nxor di, di\nmov al, {COLOR}\n"
        "mov cx, 64000\ncld\nrep stosb\npop es"
    ),
    "Divide Unsigned Word": (
        "mov bx, {DIVISOR}\nor bx, bx\njz .divide_zero_{ID}\n"
        "mov ax, {DIVIDEND}\nxor dx, dx\ndiv bx\nmov [{QUOTIENT}], ax\n"
        "mov [{REMAINDER}], dx\njmp .divide_done_{ID}\n.divide_zero_{ID}:\n"
        "mov word [{QUOTIENT}], 0\nmov word [{REMAINDER}], 0\n.divide_done_{ID}:"
    ),
    "8.8 Fixed Point Divide": (
        "mov bx,[{RIGHT}]\nor bx,bx\njz .fixed_div_zero_{ID}\n"
        "mov ax,[{LEFT}]\nmov cx,256\nimul cx\nidiv bx\nmov [{OUTPUT}],ax\n"
        "jmp .fixed_div_done_{ID}\n.fixed_div_zero_{ID}: mov word [{OUTPUT}],0\n"
        ".fixed_div_done_{ID}:"
    ),
    "Random Range Word": (
        "mov bx,{MAXIMUM}-{MINIMUM}+1\nor bx,bx\njz .random_range_zero_{ID}\n"
        "mov ax,[{SEED}]\nxor dx,dx\ndiv bx\nadd dx,{MINIMUM}\n"
        "mov [{OUTPUT}],dx\njmp .random_range_done_{ID}\n"
        ".random_range_zero_{ID}: mov word [{OUTPUT}],{MINIMUM}\n.random_range_done_{ID}:"
    ),
    "Map Word Range": (
        "mov bx,{IN_MAX}-{IN_MIN}\nor bx,bx\njz .map_zero_{ID}\n"
        "mov ax,[{VALUE}]\nsub ax,{IN_MIN}\nmov cx,{OUT_MAX}-{OUT_MIN}\n"
        "mul cx\ndiv bx\nadd ax,{OUT_MIN}\nmov [{OUTPUT}],ax\n"
        "jmp .map_done_{ID}\n.map_zero_{ID}: mov word [{OUTPUT}],{OUT_MIN}\n.map_done_{ID}:"
    ),
    "If Random, Call Function": (
        "push ax\npush cx\npush dx\nmov ah, 0x00\nint 0x1a\nmov ax, dx\n"
        "xor dx, dx\nmov cx, {MAX}\nsub cx, {MIN}\ninc cx\njcxz .random_invalid_{ID}\n"
        "div cx\nadd dl, {MIN}\ncmp dl, {TARGET}\npop dx\npop cx\npop ax\n"
        "jne .skip_{ID}\ncall {FUNCTION}\njmp .skip_{ID}\n.random_invalid_{ID}:\n"
        "pop dx\npop cx\npop ax\n.skip_{ID}:"
    ),
    # Data-producing blocks must skip their bytes during execution.  Global,
    # ID-qualified guard labels are intentional: a local label would change
    # scope as soon as the declaration introduces its own global symbol.
    "Define Byte": (
        "jmp after_define_byte_{ID}\n{VAR} db {VALUE}\nafter_define_byte_{ID}:"
    ),
    "Define Word": (
        "jmp after_define_word_{ID}\n{VAR} dw {VALUE}\nafter_define_word_{ID}:"
    ),
    "Reserve Bytes": (
        "jmp after_reserve_bytes_{ID}\n{NAME} times {COUNT} db 0\n"
        "after_reserve_bytes_{ID}:"
    ),
    "Include Binary File": (
        "jmp after_binary_{ID}\n{LABEL}: incbin \"{FILE}\"\n"
        "{LABEL}_end:\nafter_binary_{ID}:"
    ),
    "Include Assembly File": (
        "jmp after_include_{ID}\n%include \"{FILE}\"\nafter_include_{ID}:"
    ),
    "Define Raw Bytes": (
        "jmp after_raw_bytes_{ID}\n{LABEL} db {VALUES}\nafter_raw_bytes_{ID}:"
    ),
    "Align Output": (
        "jmp after_align_{ID}\nalign {BOUNDARY}, db {FILL}\nafter_align_{ID}:"
    ),
    "Define Byte Array": (
        "jmp after_byte_array_{ID}\n{ARRAY} times {COUNT} db {VALUE}\n"
        "after_byte_array_{ID}:"
    ),
    "Define Word Array": (
        "jmp after_word_array_{ID}\n{ARRAY} times {COUNT} dw {VALUE}\n"
        "after_word_array_{ID}:"
    ),
    "Debug Marker Bytes": (
        "jmp after_debug_marker_{ID}\ndb 0x4f, 0x43, {MARKER}, 0x43, 0x4f\n"
        "after_debug_marker_{ID}:"
    ),
    "Multiply Unsigned Bytes": (
        "mov al, {LEFT}\nmov bl, {RIGHT}\nmul bl\nmov [{OUTPUT}], al"
    ),
    "Find Byte in Array": (
        "mov si,{ARRAY}\nmov cx,{COUNT}\nxor bx,bx\nmov dx,0xffff\n"
        ".find_array_{ID}: cmp byte [si],{VALUE}\nje .find_found_{ID}\n"
        "inc si\ninc bx\nloop .find_array_{ID}\njmp .find_done_{ID}\n"
        ".find_found_{ID}: mov dx,bx\n.find_done_{ID}: mov [{OUTPUT}],dx"
    ),
    "Assert Byte Equals": (
        "cmp byte [{VAR}],{EXPECTED}\nje .assert_done_{ID}\ncli\n"
        ".assert_halt_{ID}: hlt\njmp .assert_halt_{ID}\n.assert_done_{ID}:"
    ),
    "Lose a Life": (
        "cmp byte [{LIVES}],0\nje .life_done_{ID}\n"
        "dec byte [{LIVES}]\n.life_done_{ID}:"
    ),
    "Tick Cooldown": (
        "cmp word [{COOLDOWN}],0\nje .cooldown_done_{ID}\n"
        "dec word [{COOLDOWN}]\n.cooldown_done_{ID}:"
    ),
}


def _modernize_block_definition(block):
    """Upgrade legacy v1 nodes to the richer v2 presentation and safer code."""
    name = block.get("name", "")
    if not block.get("description"):
        block["description"] = LEGACY_DESCRIPTIONS.get(
            name, f"{name} node from the {block.get('group', 'General')} toolkit."
        )
    if name == "Multiply Unsigned Bytes":
        block["description"] = (
            "Multiply two byte values and store the low 8-bit result. "
            "Use Multiply Unsigned Bytes to Word when results may exceed 255."
        )
    block.setdefault("tags", [str(block.get("group", "general")).lower(), "assembly"])
    if name in LEGACY_ASM_UPGRADES:
        block["asm_code"] = LEGACY_ASM_UPGRADES[name]

    direction_sensitive_blocks = {
        "Clear Screen (Graphics)", "Draw Picture", "String Length", "Copy String",
        "If Variable Equals String, Run Function", "Load Registry Slot",
        "Play MIDI Resource", "Draw Fast Filled Rectangle", "Clear Graphics Region",
        "Blit Opaque Sprite", "Blit Transparent Sprite", "Clear Key State Array",
        "Clear String Buffer", "Compare Strings", "Memory Compare",
        "Print to Screen (Text)", "Print to Screen (Graphics)",
        "Store In Registry Slot",
    }
    if name in direction_sensitive_blocks and not re.search(
            r"(?m)^\s*cld\b", block["asm_code"], re.IGNORECASE):
        block["asm_code"] = "cld\n" + block["asm_code"]

    terminal_names = {"Bootloader", "End", "Halt", "Reboot", "Shutdown"}
    if name in terminal_names:
        block["flow_output"] = False

    inputs = []
    for raw_input in block.get("inputs", []):
        definition = dict(raw_input)
        input_name = str(definition.get("name", "input"))
        definition.setdefault("label", input_name.replace("_", " ").title())
        if input_name == "ID":
            definition.setdefault("description", "Automatically assigned unique label ID.")
        elif input_name in ("COLOR", "RED", "GREEN", "BLUE"):
            definition.setdefault("description", "Numeric palette value or constant.")
        definition.setdefault("placeholder", str(definition.get("default", "")))
        inputs.append(definition)

    id_blocks = {
        "Set Var (Int)", "Set Var (Text)", "Halt", "End", "Disk Setup",
        "Define Byte", "Define Word", "Reserve Bytes", "Include Binary File",
        "Include Assembly File", "Define Raw Bytes", "Align Output", "Define Byte Array",
        "Define Word Array", "Debug Marker Bytes",
        "Play Beep Sound", "Divide Unsigned Word", "8.8 Fixed Point Divide",
        "Random Range Word", "Map Word Range",
    }
    if name in id_blocks \
            and not any(item.get("name") == "ID" for item in inputs):
        inputs.insert(0, {
            "name": "ID", "label": "Unique ID", "default": "1",
            "description": "Automatically assigned unique label ID."
        })
    if name == "Play Beep Sound":
        for definition in inputs:
            if definition.get("name") == "PITCH":
                definition["name"] = "FREQUENCY"
                definition["label"] = "Frequency Hz"
                definition["default"] = "440"
                break
    if name == "Draw Picture" and not any(item.get("name") == "SYMBOL" for item in inputs):
        inputs.insert(2, {
            "name": "SYMBOL", "label": "Resource Symbol", "default": "image",
            "description": "Assembly label prefix used inside the imported image file."
        })
    block["inputs"] = inputs
    if name == "Custom Code":
        block["width"] = 380
    return block


class ConnectionEdge(QGraphicsPathItem):
    """A Blender-style curved execution wire between two sockets."""

    def __init__(self, source_socket, target_socket=None, end_pos=None):
        super().__init__()
        self.source_socket = source_socket
        self.target_socket = target_socket
        self.end_pos = QPointF(end_pos) if end_pos is not None else source_socket.scenePos()
        self.setZValue(-5)
        self.setPen(QPen(QColor(0, 0, 0, 0), 10))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.update_path()

    def update_path(self, end_pos=None):
        if end_pos is not None:
            self.end_pos = QPointF(end_pos)
        start = self.source_socket.scenePos()
        end = self.target_socket.scenePos() if self.target_socket else self.end_pos
        path = QPainterPath(start)
        if self.source_socket.direction == "input":
            start, end = end, start
            path = QPainterPath(start)

        if end.x() >= start.x() + 80:
            distance = max(70.0, (end.x() - start.x()) * 0.48)
            path.cubicTo(
                QPointF(start.x() + distance, start.y()),
                QPointF(end.x() - distance, end.y()),
                end,
            )
        else:
            # Back-facing connections are routed through the empty gap between
            # vertically stacked nodes instead of folding into tiny loops.
            stub = max(46.0, min(90.0, abs(end.y() - start.y()) * 0.32))
            right_x = start.x() + stub
            left_x = end.x() - stub
            mid_y = (start.y() + end.y()) / 2.0
            path.cubicTo(
                QPointF(right_x, start.y()),
                QPointF(right_x, mid_y),
                QPointF(right_x, mid_y),
            )
            path.lineTo(QPointF(left_x, mid_y))
            path.cubicTo(
                QPointF(left_x, mid_y),
                QPointF(left_x, end.y()),
                end,
            )
        self.setPath(path)

    def paint(self, painter, option, widget=None):
        color = self.source_socket.color
        if self.isSelected():
            color = getattr(self.source_socket.node, "theme_accent", QColor("#8be9fd"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(0, 0, 0, 110), 7, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(self.path())
        painter.setPen(QPen(color, 3, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(self.path())


class ConnectionSocket(QGraphicsObject):
    def __init__(self, node, direction, color):
        super().__init__(node)
        self.node = node
        self.direction = direction
        self.color = _safe_color(color)
        self.edges = []
        self.hovered = False
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(10)

    def boundingRect(self):
        radius = SOCKET_RADIUS + 3
        return QRectF(-radius, -radius, radius * 2, radius * 2)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = SOCKET_RADIUS + (2 if self.hovered else 0)
        painter.setPen(QPen(QColor("#d9e2f2"), 2))
        painter.setBrush(QBrush(self.color.lighter(125) if self.hovered else self.color))
        painter.drawEllipse(QPointF(0, 0), radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 80)))
        painter.drawEllipse(QPointF(-2, -2), max(1, radius - 4), max(1, radius - 4))

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        scene = self.scene()
        if scene and hasattr(scene, "begin_connection"):
            scene.begin_connection(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene = self.scene()
        if scene and hasattr(scene, "update_connection"):
            scene.update_connection(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        scene = self.scene()
        if scene and hasattr(scene, "finish_connection"):
            scene.finish_connection(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class VariableInputCombo(QComboBox):
    """Editable node input with a current-file variable picker."""

    STRUCTURAL_INPUTS = {
        "ID", "FILE", "FUNCTION", "LABEL", "SYMBOL", "CODE", "REGISTER",
        "INTERRUPT", "SEGMENT", "OFFSET",
    }

    def __init__(self, node, definition):
        super().__init__()
        self.node = node
        self.input_name = str(definition.get("name", "input"))
        self.variables_enabled = definition.get(
            "variables", node.input_allows_variables(self.input_name)
        )
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(14)
        self.activated.connect(self._apply_variable)

    def showPopup(self):
        if self.variables_enabled:
            current = self.currentText()
            scene = self.node.scene()
            provider = getattr(scene, "variable_provider", None) if scene else None
            variables = provider() if callable(provider) else []
            variables = self.node.compatible_variables(self.input_name, variables)

            self.blockSignals(True)
            self.clear()
            self.addItem(current or "Enter a value…", None)
            if variables:
                self.insertSeparator(1)
                for variable in variables:
                    name = variable.get("name", "")
                    value_type = variable.get("type", "value")
                    self.addItem(f"{name}    [{value_type}]", f"%var[{name}]")
            self.setEditText(current)
            self.blockSignals(False)
        super().showPopup()

    def _apply_variable(self, index):
        token = self.itemData(index)
        if token:
            self.setEditText(str(token))
            if self.lineEdit():
                self.lineEdit().setFocus()


class VisualBlock(QGraphicsObject):
    """A shaded node with execution sockets and inline editable values."""

    def __init__(self, name, asm_code, inputs=None, req_funcs=None,
                 color_hex="#3b82f6", is_start=False, metadata=None):
        super().__init__()
        self.input_list = inputs if inputs else []
        self.block_name = name
        self.asm_template = asm_code
        self.req_funcs = req_funcs if req_funcs else []
        self.is_start = is_start
        self.metadata = dict(metadata or {})
        self.is_entry = bool(self.metadata.get("entry_point", False))
        self.description = self.metadata.get("description", "")
        self.group = self.metadata.get("group", "Core" if is_start else "General")
        self.base_color = _safe_color("#e69a32" if is_start else color_hex)
        self.theme_color = None
        self.theme_accent = QColor("#6ee7f9")
        self.is_vibrant = False
        self.input_widgets = {}
        self.node_id = str(self.metadata.get("node_id") or uuid.uuid4().hex)
        self._is_updating = False
        self.node_width = max(260, min(440, int(self.metadata.get("width", BLOCK_WIDTH))))
        row_count = max(1, len(self.input_list))
        self.node_height = HEADER_HEIGHT + 30 + row_count * INPUT_ROW_HEIGHT

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setZValue(1)
        if self.description:
            self.setToolTip(self.description)

        self.label = QGraphicsTextItem(name, self)
        self.label.setDefaultTextColor(QColor("#f7f9fc"))
        title_font = QFont("Segoe UI", 10)
        title_font.setBold(True)
        self.label.setFont(title_font)
        self.label.setPos(14, 7)

        category_label = QGraphicsTextItem(self.group.upper(), self)
        category_label.setDefaultTextColor(QColor(255, 255, 255, 145))
        category_font = QFont("Segoe UI", 6)
        category_font.setBold(True)
        category_label.setFont(category_font)
        category_width = category_label.boundingRect().width()
        category_label.setPos(self.node_width - category_width - 12, 11)

        self.input_socket = None
        self.output_socket = None
        accepts_input = bool(self.metadata.get("flow_input", not (is_start or self.is_entry)))
        provides_output = bool(self.metadata.get("flow_output", True))
        socket_y = HEADER_HEIGHT + 15
        if accepts_input:
            self.input_socket = ConnectionSocket(self, "input", self.base_color)
            self.input_socket.setPos(0, socket_y)
        if provides_output:
            self.output_socket = ConnectionSocket(self, "output", self.base_color)
            self.output_socket.setPos(self.node_width, socket_y)

        flow_font = QFont("Segoe UI", 7)
        flow_font.setBold(True)
        if accepts_input:
            input_label = QGraphicsTextItem("IN", self)
            input_label.setDefaultTextColor(QColor("#7f8b9d"))
            input_label.setFont(flow_font)
            input_label.setPos(13, HEADER_HEIGHT + 5)
        if provides_output:
            output_label = QGraphicsTextItem("OUT", self)
            output_label.setDefaultTextColor(QColor("#7f8b9d"))
            output_label.setFont(flow_font)
            output_label.setPos(self.node_width - 35, HEADER_HEIGHT + 5)

        input_start = HEADER_HEIGHT + 31
        for index, inp in enumerate(self.input_list):
            y_pos = input_start + index * INPUT_ROW_HEIGHT
            label_text = str(inp.get("label", inp.get("name", "input")))
            label = QGraphicsTextItem(label_text, self)
            label.setDefaultTextColor(QColor("#aeb8c6"))
            label.setFont(QFont("Segoe UI", 8))
            label.setPos(14, y_pos + 3)

            widget = self._create_input_widget(inp)
            proxy = QGraphicsProxyWidget(self)
            proxy.setWidget(widget)
            proxy.setPos(self.node_width - 146, y_pos)
            self.input_widgets[inp.get("name", label_text)] = widget

    @classmethod
    def from_definition(cls, definition, is_start=False):
        metadata = dict(definition)
        return cls(
            definition.get("name", "Unnamed Block"),
            definition.get("asm_code", ""),
            definition.get("inputs", []),
            definition.get("req_funcs", []),
            definition.get("color", "#3b82f6"),
            is_start=is_start,
            metadata=metadata,
        )

    def _create_input_widget(self, definition):
        input_type = str(definition.get("type", "text")).lower()
        value = definition.get("value", definition.get("default", ""))

        if input_type in ("choice", "select"):
            widget = QComboBox()
            widget.addItems([str(option) for option in definition.get("options", [])])
            index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
            widget.currentTextChanged.connect(self.on_input_changed)
        elif input_type in ("bool", "boolean"):
            widget = QCheckBox()
            widget.setChecked(str(value).lower() in ("1", "true", "yes", "on"))
            widget.stateChanged.connect(self.on_input_changed)
        elif input_type in ("int", "integer", "number"):
            widget = QSpinBox()
            widget.setRange(int(definition.get("min", -32768)), int(definition.get("max", 65535)))
            try:
                widget.setValue(int(str(value), 0))
            except ValueError:
                widget.setValue(0)
            widget.valueChanged.connect(self.on_input_changed)
        else:
            input_name = str(definition.get("name", "input")).upper()
            variables_enabled = definition.get(
                "variables", self.input_allows_variables(input_name)
            )
            if variables_enabled:
                widget = VariableInputCombo(self, definition)
                widget.setEditText(str(value))
                if widget.lineEdit():
                    widget.lineEdit().setPlaceholderText(str(definition.get("placeholder", "")))
                widget.currentTextChanged.connect(self.on_input_changed)
            else:
                widget = QLineEdit()
                widget.setText(str(value))
                widget.setPlaceholderText(str(definition.get("placeholder", "")))
                widget.textChanged.connect(self.on_input_changed)

        widget.setFixedWidth(136)
        tooltip = definition.get("description")
        if tooltip:
            widget.setToolTip(str(tooltip))
        widget.setStyleSheet("""
            QLineEdit, QComboBox, QSpinBox {
                background: #061522;
                color: #d9f2ff;
                border: 1px solid #28516c;
                border-radius: 5px;
                padding: 4px 7px;
                selection-background-color: #16719b;
                font-family: 'Consolas';
                font-size: 11px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #66d9ef;
                background: #04101a;
            }
            QCheckBox { color: #d8f3ff; spacing: 6px; }
            QCheckBox::indicator { width: 17px; height: 17px; }
        """)
        return widget

    def boundingRect(self):
        return QRectF(-10, -8, self.node_width + 20, self.node_height + 18)

    def rect(self):
        return QRectF(0, 0, self.node_width, self.node_height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body_rect = QRectF(0, 0, self.node_width, self.node_height)

        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(body_rect.translated(4, 6), 9, 9)
        painter.fillPath(shadow_path, QColor(0, 0, 0, 105))

        body_gradient = QLinearGradient(0, 0, 0, self.node_height)
        tint = self.theme_color or self.base_color
        body_top = QColor(
            18 + tint.red() // 9,
            27 + tint.green() // 9,
            40 + tint.blue() // 9,
        )
        body_middle = QColor(
            12 + tint.red() // 14,
            22 + tint.green() // 14,
            34 + tint.blue() // 14,
        )
        body_bottom = QColor(
            8 + tint.red() // 20,
            17 + tint.green() // 20,
            28 + tint.blue() // 20,
        )
        body_gradient.setColorAt(0, body_top)
        body_gradient.setColorAt(0.52, body_middle)
        body_gradient.setColorAt(1, body_bottom)
        body_path = QPainterPath()
        body_path.addRoundedRect(body_rect, 9, 9)
        painter.fillPath(body_path, QBrush(body_gradient))

        header_path = QPainterPath()
        header_path.addRoundedRect(QRectF(0, 0, self.node_width, HEADER_HEIGHT + 7), 9, 9)
        header_path.addRect(QRectF(0, HEADER_HEIGHT - 7, self.node_width, 14))
        header_gradient = QLinearGradient(0, 0, self.node_width, HEADER_HEIGHT)
        active_color = tint.lighter(118) if self.is_vibrant else tint
        header_gradient.setColorAt(0, active_color.lighter(120))
        header_gradient.setColorAt(0.55, active_color)
        header_gradient.setColorAt(1, active_color.darker(145))
        painter.fillPath(header_path, QBrush(header_gradient))

        border = self.theme_accent if self.isSelected() else QColor("#566171")
        if self.is_vibrant and not self.isSelected():
            border = tint.lighter(150)
        painter.setPen(QPen(border, 2 if self.isSelected() else 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body_rect, 9, 9)

        painter.setPen(QPen(QColor(255, 255, 255, 34), 1))
        painter.drawLine(QPointF(1, HEADER_HEIGHT), QPointF(self.node_width - 1, HEADER_HEIGHT))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and not self.is_start:
            scene = self.scene()
            if scene and hasattr(scene, "remove_node"):
                scene.remove_node(self)
                scene.save_blocks_to_project()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.setFocus()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            scene.refresh_vibrancy()
            scene.save_blocks_to_project()
            if hasattr(scene, "update_callback") and scene.update_callback:
                scene.update_callback()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for socket in (self.input_socket, self.output_socket):
                if socket:
                    for edge in list(socket.edges):
                        edge.update_path()
        return super().itemChange(change, value)

    def on_input_changed(self, *args):
        scene = self.scene()
        if scene:
            if hasattr(scene, "update_callback") and scene.update_callback:
                scene.update_callback()
            scene.save_blocks_to_project()

    def set_vibrant(self, active):
        if self.is_vibrant != active:
            self.is_vibrant = active
            self.update()

    def apply_theme(self, theme):
        self.theme_accent = _safe_color(theme.get("accent", "#6ee7f9"), "#6ee7f9")
        override = theme.get("node_color_override")
        self.theme_color = _safe_color(override) if override else None
        socket_color = self.theme_color or self.base_color
        for socket in (self.input_socket, self.output_socket):
            if socket is not None:
                socket.color = socket_color
                socket.update()
        input_bg = theme.get("input_background", theme.get("sidebar", "#061522"))
        input_focus = theme.get("input_focus_background", theme.get("background", "#04101a"))
        border = theme.get("input_border", theme.get("line_numbers_background", "#28516c"))
        text = theme.get("text", "#d9f2ff")
        accent = theme.get("accent", "#66d9ef")
        for widget in self.input_widgets.values():
            widget.setStyleSheet(f"""
                QLineEdit, QComboBox, QSpinBox {{
                    background: {input_bg}; color: {text}; border: 1px solid {border};
                    border-radius: 5px; padding: 4px 7px;
                    selection-background-color: {accent};
                    font-family: 'Consolas'; font-size: 11px;
                }}
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
                    border: 1px solid {accent}; background: {input_focus};
                }}
                QCheckBox {{ color: {text}; spacing: 6px; }}
                QCheckBox::indicator {{ width: 17px; height: 17px; }}
            """)
        self.update()

    def get_input_value(self, name):
        widget = self.input_widgets.get(name)
        if isinstance(widget, QLineEdit):
            return widget.text()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QSpinBox):
            return str(widget.value())
        if isinstance(widget, QCheckBox):
            return "1" if widget.isChecked() else "0"
        return ""

    def set_input_value(self, name, value):
        widget = self.input_widgets.get(name)
        if isinstance(widget, QLineEdit):
            widget.setText(str(value))
        elif isinstance(widget, QComboBox):
            index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
            elif widget.isEditable():
                widget.setEditText(str(value))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(value))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(str(value).lower() in ("1", "true", "yes", "on"))

    def input_values(self):
        return {name: self.get_input_value(name) for name in self.input_widgets}

    def input_definition(self, name):
        return next(
            (item for item in self.input_list if str(item.get("name", "")) == str(name)),
            {},
        )

    def variable_mode(self, name):
        """Describe how a selected variable is used by this template input."""
        definition = self.input_definition(name)
        explicit = str(definition.get("variable_mode", "")).strip().lower()
        if explicit:
            return explicit

        upper_name = str(name).upper()
        if upper_name in VariableInputCombo.STRUCTURAL_INPUTS:
            return "structural"
        if self.block_name in {"Print to Screen (Text)", "Print to Screen (Graphics)"} \
                and upper_name == "TEXT":
            return "text"
        placeholder = re.escape("{" + str(name) + "}")
        if re.search(
                rf"(?mi)^\s*[^;]*(?:db|dw|dd|dq|equ|times|align|incbin)\b[^\n]*{placeholder}",
                self.asm_template):
            return "none"
        if re.search(rf"(?:{placeholder}\s*[-+*/]|[-+*/]\s*{placeholder})",
                     self.asm_template):
            return "none"
        if re.search(
                rf"(?mi)^\s*{placeholder}\s+(?:equ|db|dw|dd|dq|times|incbin)\b",
                self.asm_template):
            return "definition"
        if re.search(rf"\[\s*{placeholder}\s*(?:\]|\+|-)", self.asm_template):
            return "symbol"
        if upper_name in {
            "ADDRESS", "BUFFER", "STRING", "SOURCE", "DESTINATION", "ARRAY",
            "DATA", "SPRITE", "LOCAL_VAR", "LEFT_STRING", "RIGHT_STRING",
        }:
            return "address"
        if re.search(rf"(?mi)^\s*mov\s+(?:si|di)\s*,\s*{placeholder}\s*$",
                     self.asm_template):
            return "address"
        return "value"

    def input_allows_variables(self, name):
        return self.variable_mode(name) not in {"structural", "definition", "none"}

    def expected_variable_types(self, name):
        mode = self.variable_mode(name)
        if mode == "text":
            return {"text", "buffer", "byte", "word"}
        if mode == "address":
            return {"text", "buffer", "byte-array", "word-array"}

        placeholder = re.escape("{" + str(name) + "}")
        template = self.asm_template
        if re.search(rf"(?i)\bbyte\s*\[\s*{placeholder}", template) \
                or re.search(rf"(?i)\bmov\s+\[\s*{placeholder}\s*\]\s*,\s*(?:al|bl|cl|dl)\b", template) \
                or re.search(rf"(?i)\bmov\s+(?:al|bl|cl|dl)\s*,\s*{placeholder}\b", template):
            return {"byte"}
        if re.search(rf"(?i)\bword\s*\[\s*{placeholder}", template) \
                or re.search(rf"(?i)\bmov\s+\[\s*{placeholder}\s*\]\s*,\s*(?:ax|bx|cx|dx|si|di|bp|sp)\b", template) \
                or re.search(rf"(?i)\bmov\s+(?:ax|bx|cx|dx|si|di|bp|sp)\s*,\s*{placeholder}\b", template):
            return {"word"}
        return set()

    def compatible_variables(self, name, variables):
        expected = self.expected_variable_types(name)
        if not expected:
            return list(variables)
        compatible = [item for item in variables if item.get("type") in expected]
        return compatible or list(variables)

    def variable_info(self, variable_name):
        scene = self.scene()
        provider = getattr(scene, "variable_provider", None) if scene else None
        variables = provider() if callable(provider) else []
        return next(
            (item for item in variables
             if str(item.get("name", "")).casefold() == variable_name.casefold()),
            {"name": variable_name, "type": "byte"},
        )

    def render_input_value(self, name, value):
        match = VARIABLE_TOKEN_RE.fullmatch(str(value).strip())
        if not match:
            return str(value)
        variable_name = match.group(1).strip()
        mode = self.variable_mode(name)
        if mode in {"symbol", "address", "definition", "structural"}:
            return variable_name
        if mode == "text":
            return str(value)
        return f"[{variable_name}]"

    def render_template(self, template):
        code = str(template)
        for key, value in self.input_values().items():
            code = code.replace(f"{{{key}}}", self.render_input_value(key, value))
        return self._normalize_variable_operands(code)

    def _normalize_variable_operands(self, code):
        """Lower memory-to-memory variable choices into valid 16-bit NASM."""
        output = []
        explicit_memory = re.compile(
            r"^(\s*)(mov|add|sub|cmp|and|or|xor|test)\s+(byte|word)\s+"
            r"(\[[^,]+\])\s*,\s*(\[[^\]]+\])(\s*;.*)?$",
            re.IGNORECASE,
        )
        implicit_move = re.compile(
            r"^(\s*)mov\s+(\[[^,]+\])\s*,\s*\[([A-Za-z_][\w.$@?]*)\]"
            r"(\s*;.*)?$",
            re.IGNORECASE,
        )
        variable_shift = re.compile(
            r"^(\s*)(shl|shr|sal|sar|rol|ror)\s+(byte|word)\s+"
            r"(\[[^,]+\])\s*,\s*\[([A-Za-z_][\w.$@?]*)\](\s*;.*)?$",
            re.IGNORECASE,
        )
        for line in str(code).splitlines():
            match = explicit_memory.match(line)
            if match:
                indent, opcode, size, destination, source, comment = match.groups()
                register = "al" if size.lower() == "byte" else "ax"
                output.extend((
                    f"{indent}push ax",
                    f"{indent}mov {register}, {source}",
                    f"{indent}{opcode} {size} {destination}, {register}{comment or ''}",
                    f"{indent}pop ax",
                ))
                continue
            match = implicit_move.match(line)
            if match:
                indent, destination, source_name, comment = match.groups()
                source_type = self.variable_info(source_name).get("type", "byte")
                size = "word" if source_type == "word" else "byte"
                register = "ax" if size == "word" else "al"
                output.extend((
                    f"{indent}push ax",
                    f"{indent}mov {register}, [{source_name}]",
                    f"{indent}mov {size} {destination}, {register}{comment or ''}",
                    f"{indent}pop ax",
                ))
                continue
            match = variable_shift.match(line)
            if match:
                indent, opcode, size, destination, source_name, comment = match.groups()
                output.extend((
                    f"{indent}push cx",
                    f"{indent}mov cl, [{source_name}]",
                    f"{indent}{opcode} {size} {destination}, cl{comment or ''}",
                    f"{indent}pop cx",
                ))
                continue
            output.append(line)
        return "\n".join(output)

    @staticmethod
    def _string_print_routine(function_name, graphics=False):
        if graphics:
            character_output = (
                "    mov ah, 0x0e\n    xor bh, bh\n    int 0x10"
            )
        else:
            character_output = (
                "    mov ah, 0x09\n    xor bh, bh\n    mov cx, 1\n    int 0x10\n"
                "    mov ah, 0x03\n    int 0x10\n    inc dl\n    mov ah, 0x02\n"
                "    int 0x10"
            )
        return (
            f"{function_name}:\n    pusha\n    cld\n.loop:\n    lodsb\n    or al, al\n"
            f"    jz .done\n{character_output}\n    jmp .loop\n.done:\n"
            "    popa\n    ret"
        )

    @staticmethod
    def _number_print_routine(function_name, graphics=False):
        if graphics:
            character_output = (
                "    mov ah, 0x0e\n    xor bh, bh\n    int 0x10"
            )
        else:
            character_output = (
                "    mov ah, 0x09\n    xor bh, bh\n    push cx\n"
                "    mov cx, 1\n    int 0x10\n    mov ah, 0x03\n    int 0x10\n"
                "    inc dl\n    mov ah, 0x02\n    int 0x10\n    pop cx"
            )
        return (
            f"{function_name}:\n    pusha\n    xor cx, cx\n    mov bp, 10\n"
            ".convert:\n    xor dx, dx\n    div bp\n    push dx\n    inc cx\n"
            "    or ax, ax\n    jnz .convert\n.output:\n    pop ax\n"
            f"    add al, '0'\n{character_output}\n    loop .output\n"
            "    popa\n    ret"
        )

    def render_print_block(self):
        graphics = self.block_name == "Print to Screen (Graphics)"
        block_id = self.get_input_value("ID") or "1"
        color = self.render_input_value("COLOR", self.get_input_value("COLOR"))
        text_value = self.get_input_value("TEXT")
        token = VARIABLE_TOKEN_RE.fullmatch(text_value.strip())
        suffix = f"gfx_{block_id}" if graphics else block_id
        after_label = f"after_{suffix}"

        if token:
            variable_name = token.group(1).strip()
            info = self.variable_info(variable_name)
            variable_type = info.get("type", "byte")
            if variable_type in {"text", "buffer", "byte-array"}:
                function_name = f"print_string_{suffix}"
                return (
                    f"mov si, {variable_name}\nmov bl, {color}\ncall {function_name}\n"
                    f"jmp {after_label}\n{self._string_print_routine(function_name, graphics)}\n"
                    f"{after_label}:"
                )

            function_name = f"print_uint_{suffix}"
            if variable_type == "byte":
                load_value = f"xor ax, ax\nmov al, [{variable_name}]"
            else:
                load_value = f"mov ax, [{variable_name}]"
            return (
                f"{load_value}\nmov bl, {color}\ncall {function_name}\n"
                f"jmp {after_label}\n{self._number_print_routine(function_name, graphics)}\n"
                f"{after_label}:"
            )

        function_name = f"print_string_{suffix}"
        message_name = f"msg_{suffix}"
        byte_values = _assembly_string_bytes(text_value)
        return (
            f"mov si, {message_name}\nmov bl, {color}\ncall {function_name}\n"
            f"jmp {after_label}\n{message_name} db {byte_values}, 0\n"
            f"{self._string_print_routine(function_name, graphics)}\n{after_label}:"
        )

    def render_text_data_block(self):
        block_id = self.get_input_value("ID") or "1"
        byte_values = _assembly_string_bytes(self.get_input_value("VALUE"))
        if self.block_name == "Set Var (Text)":
            variable_name = self.get_input_value("VAR").strip() or "text_value"
            return (
                f"jmp after_var_{block_id}\n{variable_name} db {byte_values}, 0\n"
                f"after_var_{block_id}:\nmov si, {variable_name}"
            )

        # If Variable Equals String, Run Function
        variable_name = self.render_input_value(
            "VAR_NAME", self.get_input_value("VAR_NAME")
        )
        function_name = self.get_input_value("FUNCTION")
        return (
            f"jmp str_target_{block_id}\nstr_value_{block_id} db {byte_values}, 0\n"
            f"str_target_{block_id}:\ncld\nmov si, {variable_name}\n"
            f"mov di, str_value_{block_id}\n.compare_{block_id}:\nlodsb\nscasb\n"
            f"jne .skip_{block_id}\nor al, al\njnz .compare_{block_id}\n"
            f"call {function_name}\n.skip_{block_id}:"
        )

    def get_child_block(self):
        scene = self.scene()
        return scene.next_block(self) if scene and hasattr(scene, "next_block") else None

    def self_destruct(self):
        scene = self.scene()
        if scene and hasattr(scene, "remove_node"):
            scene.remove_node(self)

    def get_asm(self):
        if self.is_start or self.is_entry:
            label_text = self.get_input_value("Function").strip()
            if self.is_start and label_text.lower() in ("", "start"):
                return ""
            return f"{label_text or 'function'}:"

        if self.block_name in {"Print to Screen (Text)", "Print to Screen (Graphics)"}:
            return self.render_print_block()
        if self.block_name in {"Set Var (Text)", "If Variable Equals String, Run Function"}:
            return self.render_text_data_block()
        return self.render_template(self.asm_template)


class BlockCanvas(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(-2500, -2500, 5000, 5000, parent)
        self.update_callback = None
        self.variable_provider = None
        self.definition_provider = None
        self.start_block = None
        self.project_dir = None
        self.current_filename = None
        self.pending_edge = None
        self.pending_socket = None
        self.active_theme = None
        self.setBackgroundBrush(QBrush(QColor("#071421")))
        self.reset_canvas()

    def _new_start_block(self):
        definition = {
            "name": "START",
            "asm_code": "",
            "group": "Core",
            "color": "#d98b2b",
            "description": "Execution begins here.",
            "flow_input": False,
            "flow_output": True,
            "inputs": [{"name": "Function", "default": "start"}],
        }
        block = VisualBlock.from_definition(definition, is_start=True)
        self.addItem(block)
        self.start_block = block
        return block

    def reset_canvas(self):
        self.clear()
        self.pending_edge = None
        self.pending_socket = None
        start = self._new_start_block()
        start.setPos(0, 0)

    def add_new_block(self, block, position):
        """Place a library node and assign collision-free macro IDs automatically."""
        self.addItem(block)
        if self.active_theme:
            block.apply_theme(self.active_theme)
        if isinstance(position, (tuple, list)) and len(position) == 2:
            block.setPos(float(position[0]), float(position[1]))
        else:
            block.setPos(position)
        if "ID" in block.input_widgets:
            used_ids = set()
            for item in self.items():
                if isinstance(item, VisualBlock) and item is not block and "ID" in item.input_widgets:
                    used_ids.add(item.get_input_value("ID"))
            candidate = 1
            while str(candidate) in used_ids:
                candidate += 1
            block.set_input_value("ID", candidate)
        if block.is_entry and "Function" in block.input_widgets:
            used_names = {
                item.get_input_value("Function")
                for item in self.items()
                if isinstance(item, VisualBlock) and item is not block
                and (item.is_start or item.is_entry) and "Function" in item.input_widgets
            }
            candidate = 1
            while f"function_{candidate}" in used_names:
                candidate += 1
            block.set_input_value("Function", f"function_{candidate}")
        self.save_blocks_to_project()
        return block

    def set_theme(self, theme):
        self.active_theme = dict(theme)
        self.setBackgroundBrush(QBrush(_safe_color(
            theme.get("block_editor_background", "#071421"), "#071421"
        )))
        for item in self.items():
            if isinstance(item, VisualBlock):
                item.apply_theme(theme)

    def begin_connection(self, socket):
        if self.pending_edge:
            self.removeItem(self.pending_edge)
        self.pending_socket = socket
        self.pending_edge = ConnectionEdge(socket, end_pos=socket.scenePos())
        self.addItem(self.pending_edge)

    def update_connection(self, scene_pos):
        if self.pending_edge:
            self.pending_edge.update_path(scene_pos)

    def finish_connection(self, scene_pos):
        start = self.pending_socket
        temporary = self.pending_edge
        self.pending_socket = None
        self.pending_edge = None
        target = None
        for item in self.items(scene_pos):
            if isinstance(item, ConnectionSocket) and item is not start:
                target = item
                break
        if temporary and temporary.scene() is self:
            self.removeItem(temporary)
        if start and target:
            self.connect_sockets(start, target)

    def connect_sockets(self, first, second, notify=True):
        if first.direction == second.direction or first.node is second.node:
            return None
        output = first if first.direction == "output" else second
        input_socket = second if second.direction == "input" else first

        if self._would_create_cycle(output.node, input_socket.node):
            return None

        for edge in list(output.edges):
            self.remove_connection(edge)
        for edge in list(input_socket.edges):
            self.remove_connection(edge)

        edge = ConnectionEdge(output, input_socket)
        self.addItem(edge)
        output.edges.append(edge)
        input_socket.edges.append(edge)
        self.refresh_vibrancy()
        if notify:
            self.save_blocks_to_project()
            if self.update_callback:
                self.update_callback()
        return edge

    def _would_create_cycle(self, source_node, target_node):
        current = target_node
        visited = set()
        while current and current not in visited:
            if current is source_node:
                return True
            visited.add(current)
            current = self.next_block(current)
        return False

    def remove_connection(self, edge, notify=False):
        for socket in (edge.source_socket, edge.target_socket):
            if socket and edge in socket.edges:
                socket.edges.remove(edge)
        if edge.scene() is self:
            self.removeItem(edge)
        if notify:
            self.refresh_vibrancy()
            self.save_blocks_to_project()
            if self.update_callback:
                self.update_callback()

    def remove_node(self, node):
        if node.is_start:
            return
        edges = set()
        for socket in (node.input_socket, node.output_socket):
            if socket:
                edges.update(socket.edges)
        for edge in list(edges):
            self.remove_connection(edge)
        self.removeItem(node)
        self.refresh_vibrancy()
        if self.update_callback:
            self.update_callback()

    def delete_selected(self):
        changed = False
        for item in list(self.selectedItems()):
            if isinstance(item, ConnectionEdge):
                self.remove_connection(item)
                changed = True
            elif isinstance(item, VisualBlock) and not item.is_start:
                self.remove_node(item)
                changed = True
        if changed:
            self.save_blocks_to_project()
            if self.update_callback:
                self.update_callback()

    def next_block(self, block):
        if not block.output_socket:
            return None
        for edge in block.output_socket.edges:
            if edge.source_socket is block.output_socket and edge.target_socket:
                return edge.target_socket.node
        return None

    def refresh_vibrancy(self):
        for item in self.items():
            if isinstance(item, VisualBlock):
                item.set_vibrant(False)
        visited = set()
        for root in self.execution_roots():
            current = root
            while current and current not in visited:
                visited.add(current)
                current.set_vibrant(True)
                current = self.next_block(current)

    def execution_roots(self):
        roots = [self.start_block] if self.start_block else []
        entries = [
            item for item in self.items()
            if isinstance(item, VisualBlock) and item.is_entry
        ]
        entries.sort(key=lambda item: (item.pos().y(), item.pos().x(), item.node_id))
        roots.extend(entries)
        return roots

    def auto_layout(self):
        """Arrange each execution chain left-to-right for clean Blender-style wires."""
        row_y = 0.0
        visited = set()
        for root in self.execution_roots():
            current = root
            x = 0.0
            tallest = 0.0
            while current and current not in visited:
                visited.add(current)
                current.setPos(x, row_y)
                tallest = max(tallest, current.node_height)
                x += current.node_width + 120
                current = self.next_block(current)
            row_y += tallest + 150

        for item in self.items():
            if isinstance(item, VisualBlock):
                for socket in (item.input_socket, item.output_socket):
                    if socket:
                        for edge in socket.edges:
                            edge.update_path()
        self.refresh_vibrancy()
        self.save_blocks_to_project()

    def generate_code(self):
        if not self.start_block:
            return ""

        chain_codes = []
        helpers = []
        helper_set = set()
        visited = set()
        roots = self.execution_roots()
        for root in roots:
            chain_output = []
            current = root
            while current and current not in visited:
                visited.add(current)
                block_asm = current.get_asm()
                if block_asm:
                    chain_output.append(block_asm)
                for helper in current.req_funcs:
                    rendered = current.render_template(helper)
                    if rendered not in helper_set:
                        helpers.append(rendered)
                        helper_set.add(rendered)
                current = self.next_block(current)
            if chain_output:
                chain_codes.append((root, "\n".join(chain_output)))

        main_chains = [code for root, code in chain_codes if root is self.start_block]
        function_chains = [code for root, code in chain_codes if root is not self.start_block]
        output_sections = list(main_chains)
        if function_chains:
            output_sections.append("jmp __oc_functions_end")
            output_sections.extend(function_chains)
            output_sections.append("__oc_functions_end:")
        full_code = "\n".join(output_sections)
        if helpers:
            full_code += (
                "\n\njmp __oc_helpers_end\n"
                + "\n".join(helpers)
                + "\n__oc_helpers_end:"
            )

        # Custom/plugin templates can still use the public token syntax.
        full_code = re.sub(r"\[\s*%var\[([^\]]+)\]\s*\]", r"[\1]", full_code)
        full_code = re.sub(r"%var\[([^\]]+)\]", r"[\1]", full_code)
        return full_code

    def save_blocks_to_project(self, project_dir=None, current_file_name=None):
        project_dir = project_dir or self.project_dir
        file_name = current_file_name or self.current_filename
        if not project_dir or not file_name:
            return

        blocks_dir = os.path.join(project_dir, "blocks")
        os.makedirs(blocks_dir, exist_ok=True)
        nodes = [item for item in self.items() if isinstance(item, VisualBlock)]
        nodes.sort(key=lambda item: (not item.is_start, item.node_id))

        for old_path in glob.glob(os.path.join(blocks_dir, f"{file_name}_*.json")):
            try:
                os.remove(old_path)
            except OSError:
                pass

        for index, item in enumerate(nodes):
            next_node = self.next_block(item)
            data = {
                "schema_version": 2,
                "node_id": item.node_id,
                "name": item.block_name,
                "x": item.pos().x(),
                "y": item.pos().y(),
                "asm_code": item.asm_template,
                "req_funcs": item.req_funcs,
                "is_start": item.is_start,
                "entry_point": item.is_entry,
                "color": item.base_color.name(),
                "group": item.group,
                "description": item.description,
                "flow_input": item.input_socket is not None,
                "flow_output": item.output_socket is not None,
                "next_node": next_node.node_id if next_node else None,
                "inputs": [],
            }
            for input_definition in item.input_list:
                name = input_definition.get("name", "input")
                saved_input = dict(input_definition)
                saved_input.pop("value", None)
                saved_input["value"] = item.get_input_value(name)
                data["inputs"].append(saved_input)

            path = os.path.join(blocks_dir, f"{file_name}_{index}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)

    @staticmethod
    def _save_sort_key(path):
        match = re.search(r"_(\d+)\.json$", path)
        return int(match.group(1)) if match else 0

    def load_blocks_from_project(self, project_dir, current_file_name):
        self.project_dir = project_dir
        self.current_filename = current_file_name
        blocks_dir = os.path.join(project_dir, "blocks")
        files = sorted(
            glob.glob(os.path.join(blocks_dir, f"{current_file_name}_*.json")),
            key=self._save_sort_key,
        ) if os.path.exists(blocks_dir) else []

        if not files:
            self.reset_canvas()
            return

        self.clear()
        self.start_block = None
        if callable(self.definition_provider):
            builtin_definitions = self.definition_provider()
        else:
            builtin_paths = glob.glob(os.path.join(os.path.dirname(__file__), "blocks", "*.json"))
            builtin_definitions, _ = load_block_definitions(builtin_paths)
        builtin_by_name = {
            definition["name"].casefold(): definition for definition in builtin_definitions
        }
        loaded = []
        by_id = {}
        saved_data = []
        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                current_definition = builtin_by_name.get(
                    str(data.get("name", "")).casefold()
                )
                if current_definition and not data.get("is_start", False):
                    definition = dict(current_definition)
                    saved_inputs = {
                        str(item.get("name", "")): item.get("value", item.get("default", ""))
                        for item in data.get("inputs", []) if isinstance(item, dict)
                    }
                    definition["inputs"] = [
                        {**item, "value": saved_inputs.get(
                            str(item.get("name", "")), item.get("default", "")
                        )}
                        for item in current_definition.get("inputs", [])
                    ]
                    for key in ("node_id", "x", "y", "is_start", "next_node"):
                        if key in data:
                            definition[key] = data[key]
                else:
                    definition = dict(data)
                definition["node_id"] = data.get("node_id") or uuid.uuid4().hex
                block = VisualBlock.from_definition(definition, is_start=data.get("is_start", False))
                self.addItem(block)
                if self.active_theme:
                    block.apply_theme(self.active_theme)
                block.setPos(float(data.get("x", 0)), float(data.get("y", 0)))
                loaded.append(block)
                saved_data.append(data)
                by_id[block.node_id] = block
                if block.is_start:
                    self.start_block = block
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                continue

        if self.start_block is None:
            self.start_block = self._new_start_block()
            self.start_block.setPos(0, 0)

        has_explicit_connections = any("next_node" in data for data in saved_data)
        if has_explicit_connections:
            for block, data in zip(loaded, saved_data):
                target = by_id.get(data.get("next_node"))
                if block.output_socket and target and target.input_socket:
                    self.connect_sockets(block.output_socket, target.input_socket, notify=False)
        else:
            # Migration for v1 projects: translate the old vertical snap-chain to wires.
            current = self.start_block
            visited = {current}
            while current:
                target_x = current.pos().x()
                legacy_height = max(50, 45 + len(current.input_list) * 30)
                target_y = current.pos().y() + legacy_height
                candidates = [
                    block for block in loaded
                    if block not in visited
                    and abs(block.pos().x() - target_x) < 12
                    and abs(block.pos().y() - target_y) < 12
                ]
                if not candidates:
                    break
                target = min(candidates, key=lambda block: abs(block.pos().y() - target_y))
                if current.output_socket and target.input_socket:
                    self.connect_sockets(current.output_socket, target.input_socket, notify=False)
                visited.add(target)
                current = target

        self.refresh_vibrancy()
