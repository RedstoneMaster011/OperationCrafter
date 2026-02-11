import ctypes
import os
import sys

import qdarktheme
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.compiler import Compiler
from app.editor import IDEWindow
from app.launcher import Launcher

def get_icon_path():
    if hasattr(sys, '_MEIPASS'):
        path = os.path.join(sys._MEIPASS, "icon.png")
        if os.path.exists(path):
            return path

    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    path = os.path.join(base_dir, "icon.png")
    if os.path.exists(path):
        return path

    path = os.path.abspath("icon.png")
    if os.path.exists(path):
        return path

    return None

def main():

    if sys.platform == 'win32':
        sys.argv += ['-platform', 'windows:darkmode=2']

        modelid = 'redstone.operation_crafter'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(modelid)

    app = QApplication(sys.argv)

    if app.styleHints().colorScheme() == Qt.ColorScheme.Light:
        app.setStyle('Fusion')
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        qdarktheme.load_stylesheet("dark")

    icon_path = get_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    if hasattr(sys, 'frozen'):
        root_dir = os.path.dirname(sys.executable)
        if hasattr(sys, '_MEIPASS') and sys._MEIPASS not in sys.path:
            sys.path.insert(0, sys._MEIPASS)
    else:
        root_dir = os.path.dirname(os.path.abspath(__file__))

    compiler = Compiler(root_dir)

    ide = IDEWindow(compiler)
    launcher = Launcher(ide)

    launcher.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()