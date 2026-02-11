import os
import subprocess
import sys


class OSLauncher:
    def __init__(self, root_dir):
        self.root_dir = root_dir

        if sys.platform == 'win32':
            self.qemu_path = os.path.abspath(os.path.join(self.root_dir, "qemu", "qemu-system-x86_64.exe"))
        else:
            self.qemu_path = os.path.abspath("qemu-system-x86_64")

        self.proc = None

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def kill_emulator(self):
        if self.is_running():
            self.proc.terminate()
            self.proc.wait()

    def run(self, project_dir, terminal_callback):
        img_path = os.path.abspath(os.path.join(project_dir, "build", "boot.img"))

        if self.is_running():
            terminal_callback("Emulator is already running!")
            return

        if not os.path.exists(img_path):
            terminal_callback("Error: boot.img not found. Run Build first.")
            return

        terminal_callback("Starting Emulation...")

        if sys.platform == 'win32':
            cmd = [
                self.qemu_path,
                "-drive", f"format=raw,file={img_path}",
                "-audiodev", "dsound,id=snd0",
                "-machine", "pcspk-audiodev=snd0"
            ]
        else:
            cmd = [
                self.qemu_path,
                "-drive", f"format=raw,file={img_path}",
                "-audiodev", "pa,id=snd0",
                "-machine", "pcspk-audiodev=snd0"
            ]

        executable = cmd[0] if os.path.exists(self.qemu_path) else "qemu-system-x86_64"

        try:
            self.proc = subprocess.Popen([executable] + cmd[1:])
        except Exception as e:
            terminal_callback(f"QEMU failed: {e}")