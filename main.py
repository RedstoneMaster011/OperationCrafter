import ctypes
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.compiler import Compiler
from app.editor import IDEWindow
from app.launcher import Launcher
from app.theme import apply_application_palette, build_app_stylesheet

def get_icon_path():
    icon_names = ("icon-blue.png", "icon.png")
    if hasattr(sys, '_MEIPASS'):
        for icon_name in icon_names:
            path = os.path.join(sys._MEIPASS, icon_name)
            if os.path.exists(path):
                return path

    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    for icon_name in icon_names:
        path = os.path.join(base_dir, icon_name)
        if os.path.exists(path):
            return path

    for icon_name in icon_names:
        path = os.path.abspath(icon_name)
        if os.path.exists(path):
            return path

    return None

def main():
    if sys.platform == 'win32':
        sys.argv += ['-platform', 'windows:darkmode=2']

        modelid = 'redstone.operation_crafter'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(modelid)

    # Qt-native dialogs inherit the application theme; platform-native dialogs
    # use the desktop theme and were the source of several gray surfaces.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)

    app.setStyle('Fusion')
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    apply_application_palette(app)
    app.setStyleSheet(build_app_stylesheet())

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
    ide.plugin_manager.apply_plugin_theme(launcher)

    launcher.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
