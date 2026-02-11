import os
import shutil
import subprocess
import sys


class Compiler:
    def __init__(self, root_dir):
        self.root_dir = root_dir

        if sys.platform == 'win32':
            self.nasm_exe = os.path.join(self.root_dir, "nasm", "nasm.exe")
            self.project_dir = ""
        else:
            self.nasm_exe = "nasm"

    def compile_to_img(self, terminal):
        build_dir = os.path.join(self.project_dir, "build")
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)
        os.makedirs(build_dir, exist_ok=True)

        bin_map = {}

        for root, dirs, files in os.walk(self.project_dir):
            if "build" in dirs: dirs.remove("build")

            for file in files:
                if file == ".projectdata":
                    continue

                rel_path = os.path.relpath(root, self.project_dir)
                target_folder = os.path.join(build_dir, rel_path)
                os.makedirs(target_folder, exist_ok=True)

                if file.endswith(".asm"):
                    name_bin = file.replace(".asm", ".bin")
                    target_bin = os.path.join(target_folder, name_bin)

                    cmd = f'"{self.nasm_exe}" -f bin "{file}" -o "{target_bin}"'
                    result = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, text=True)

                    if result.returncode == 0:
                        bin_map[file.lower()] = target_bin
                    else:
                        terminal.append(f"Skipped {file}: {result.stderr}")
                else:
                    shutil.copy2(os.path.join(root, file), os.path.join(target_folder, file))

        if "main.asm" not in bin_map:
            return False, "Error: main.bin not created. Check NASM errors."

        output_img = os.path.join(build_dir, "boot.img")
        try:
            with open(output_img, "wb") as f_out:
                with open(bin_map["main.asm"], "rb") as f:
                    f_out.write(f.read())

                if "kernel.asm" in bin_map:
                    with open(bin_map["kernel.asm"], "rb") as f:
                        f_out.write(f.read())

                curr_size = f_out.tell()
                padding = 1474560 - curr_size
                if padding > 0:
                    f_out.write(b'\x00' * padding)

            return True
        except:
            return False