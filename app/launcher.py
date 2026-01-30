import os, json

from datetime import date
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QFileDialog,
                             QLabel, QHBoxLayout, QLineEdit, QStackedWidget, QApplication)
from PyQt6.QtCore import Qt

class Launcher(QWidget):
    def __init__(self, ide_window):
        super().__init__()
        self.ide = ide_window
        self.setWindowTitle("Operation Crafter")
        self.setFixedSize(450, 400)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        self.stack = QStackedWidget()
        self.init_ui()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.stack)
        self.setLayout(main_layout)

    def init_ui(self):
        self.home_page = QWidget()
        home_layout = QVBoxLayout(self.home_page)
        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #ffffff; font-family: 'Segoe UI'; }
            QLabel#Title { font-size: 26px; font-weight: bold; color: #007acc; }
            QLineEdit { background: #2d2d2d; border: 1px solid #444; padding: 8px; border-radius: 4px; color: white; }
            QPushButton { background-color: #333333; border: 1px solid #444444; border-radius: 6px; padding: 12px; color: white; outline: none; }
            QPushButton:hover { background-color: #007acc; border: 1px solid #0099ff; }
            QPushButton#CloseBtn { background-color: transparent; border: none; font-size: 18px; }
            QPushButton#CloseBtn:hover { background-color: transparent; color: #ff5555; }
        """)

        header = QHBoxLayout()
        header.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("CloseBtn")
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        home_layout.addLayout(header)

        home_layout.addWidget(QLabel("Operation Crafter", objectName="Title"), alignment=Qt.AlignmentFlag.AlignCenter)
        home_layout.addWidget(QLabel("Select an option to begin"), alignment=Qt.AlignmentFlag.AlignCenter)
        home_layout.addSpacing(20)

        btn_new = QPushButton("Create New Project")
        btn_new.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        home_layout.addWidget(btn_new)

        btn_open = QPushButton("Open Existing Project")
        btn_open.clicked.connect(self.open_project)
        home_layout.addWidget(btn_open)
        home_layout.addStretch()

        home_layout.addSpacing(30)
        icon_label = QLabel()
        app_icon = QApplication.windowIcon()
        if not app_icon.isNull():
            icon_pixmap = app_icon.pixmap(128, 85)
            icon_label.setPixmap(icon_pixmap)

        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        home_layout.addWidget(icon_label)

        home_layout.addStretch()

        self.setWindowIcon(QApplication.windowIcon())

        self.setup_page = QWidget()
        setup_layout = QVBoxLayout(self.setup_page)
        setup_layout.addWidget(QLabel("Project Setup", objectName="Title"))
        setup_layout.addWidget(QLabel("Project Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("MyCoolOS")
        setup_layout.addWidget(self.name_input)
        setup_layout.addWidget(QLabel("Directory:"))
        dir_row = QHBoxLayout()
        self.path_input = QLineEdit()
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(40)
        btn_browse.clicked.connect(self.browse_folder)
        dir_row.addWidget(self.path_input)
        dir_row.addWidget(btn_browse)
        setup_layout.addLayout(dir_row)
        setup_layout.addSpacing(20)

        btn_confirm = QPushButton("Create Project")
        btn_confirm.clicked.connect(self.create_project_logic)
        setup_layout.addWidget(btn_confirm)
        btn_back = QPushButton("Back")
        btn_back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        setup_layout.addWidget(btn_back)
        setup_layout.addStretch()

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.setup_page)

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Parent Folder")
        if path: self.path_input.setText(path)

    def create_project_logic(self):
        name = self.name_input.text().strip()
        base_path = self.path_input.text().strip()
        if not name or not base_path: return

        full_path = os.path.join(base_path, name)

        if os.path.exists(os.path.join(full_path, ".projectdata")):
            self.launch_path(full_path)
            return

        os.makedirs(full_path, exist_ok=True)

        project_data = {
            "name": name,
            "version": "1.0.0",
            "created": f"{date.today()}"
        }
        with open(os.path.join(full_path, ".projectdata"), "w") as f:
            json.dump(project_data, f, indent=4)

        self.write_asm_templates(full_path)
        self.launch_path(full_path)

    def write_asm_templates(self, path):
        files = {
            "main.asm": "[org 0x7c00]\nKERNEL_OFFSET equ 0x1000\n\nmov [BOOT_DRIVE], dl\nmov bp, 0x9000\nmov sp, bp\n\ncall load_kernel\njmp KERNEL_OFFSET\n\n%include \"disk.asm\"\n\nload_kernel:\n    mov bx, KERNEL_OFFSET\n    mov dh, 2\n    mov dl, [BOOT_DRIVE]\n    call disk_load\n    ret\n\nBOOT_DRIVE db 0\ntimes 510-($-$$) db 0\ndw 0xaa55",
            "disk.asm": "disk_load:\n    push dx\n    mov ah, 0x02\n    mov al, dh\n    mov ch, 0x00\n    mov dh, 0x00\n    mov cl, 0x02\n    int 0x13\n    jc disk_error\n    pop dx\n    ret\n\ndisk_error:\n    mov ah, 0x0e\n    mov al, 'E'\n    int 0x10\n    jmp $",
            "kernel.asm": "[org 0x1000]\nmov si, MSG_HELLO\ncall print_string\n\njmp $\n\nprint_string:\n    mov ah, 0x0e\n.loop:\n    lodsb\n    cmp al, 0\n    je .done\n    int 0x10\n    jmp .loop\n.done:\n    ret\n\nMSG_HELLO db \"Hello World!\", 0"
        }
        for name, content in files.items():
            f_path = os.path.join(path, name)
            if not os.path.exists(f_path):
                with open(f_path, "w") as f:
                    f.write(content)

    def open_project(self):
        path = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if path: self.launch_path(path)

    def launch_path(self, path):
        self.ide.launch_ide(path)
        self.close()