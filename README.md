# Operation Crafter

Operation Crafter is a visual IDE for learning how small operating systems are
built. It combines a Blender-style node graph with a traditional NASM editor,
turns the result into a bootable floppy image, and launches that image in QEMU.

The goal is to make low-level development approachable without hiding the
assembly that makes it work. Beginners can connect nodes for variables, input,
graphics, GUIs, sound, game logic, and disk operations; advanced users can edit
or mix in NASM directly.

(Example Project You can download and instantly import into OperationCrafter Located at: [ExampleProject](./ExampleProject/FakeDoom))

> [!IMPORTANT]
> The current `v1.6-DEV` target is a 16-bit x86, legacy-BIOS floppy image.
> 32-bit, 64-bit, and UEFI targets are not implemented yet.

## Highlights

- Blender-style visual node graph with shaded nodes and curved execution wires
- 250 built-in nodes across 23 searchable categories
- NASM text editor with syntax highlighting, line numbers, and find/replace
- Multiple visual functions in one assembly file
- Current-file variable discovery and automatic `%var[name]` insertion
- GUI, graphics, sprite, tile, game-loop, collision, input, string, array,
  fixed-point, timer, sound, and debugging helpers
- PNG and MIDI-to-assembly resource import
- One-click project build, QEMU launch, and boot-image export
- ZIP or unpacked plugins for blocks and complete UI themes
- Built-in navy UI and the official PurpleUI theme
- Windows and Linux source/packaging scripts

## How it works

```text
Visual nodes or NASM source
            |
            v
   generated .asm files
            |
            v
     NASM flat binaries
            |
            v
  1.44 MB build/boot.img
            |
            v
       QEMU emulator
```

Operation Crafter generates readable assembly from the node graph. A project
can freely mix generated files, hand-written assembly, included resources, and
plugin-provided nodes.

## Quick start

### Create a project

1. Launch Operation Crafter.
2. Select **Create New Project**.
3. Enter a project name and choose its parent directory.
4. Select **Create Project**. The launcher creates the project folder and the
   starter bootloader, disk helper, kernel, and `.projectdata` file.

### Open a project

1. Select **Open Existing Project**.
2. Navigate into the project directory.
3. Select the `.projectdata` file. Operation Crafter opens its containing
   directory automatically.

### Make and run something

1. Double-click an `.asm` file in the project tree.
2. Write NASM directly, or select **Open Node Graph**.
3. Add nodes from the library or right-click the graph to search all nodes.
4. Connect the **START** output to the first node and continue wiring the flow.
5. Press **F5** to build `build/boot.img`.
6. Press **F6** to run the image in QEMU.

The terminal at the bottom shows generated-code, NASM, build, and emulator
messages. A failed assembly file stops the build; Operation Crafter does not
create a stale boot image after a compiler error.

## Project layout

A new project starts with this structure:

```text
MyProject/
├── .projectdata   # Project name, version, and creation metadata
├── main.asm       # Boot sector and kernel loader
├── disk.asm       # BIOS disk-read helper included by main.asm
├── kernel.asm     # Code loaded at 0x1000
├── blocks/        # Saved node positions, values, functions, and connections
└── build/         # Generated binaries and boot.img after a successful build
```

Do not select the folder itself when opening a project; select its
`.projectdata` file.

## Using the node editor

Only nodes reachable from **START** or a **Function Entry** are emitted. Loose
nodes stay saved on the graph but do not change the generated assembly.

| Action | Control |
| --- | --- |
| Search and add any node | Right-click the graph |
| Add from the library | Drag or double-click a library entry |
| Connect execution flow | Drag from an output socket to an input socket |
| Zoom around the pointer | Mouse wheel |
| Pan vertically | Shift + mouse wheel |
| Pan freely | Middle-mouse drag |
| Frame the entire graph | Home |
| Arrange connected chains | **Auto Layout** |
| Remove selected nodes or wires | Delete |
| Edit text normally | Backspace |

Node fields are edited inline. Inputs that can read a variable include a
drop-down of variables declared in the current file. Choosing one inserts the
correct `%var[variable_name]` token automatically. Variables from other files
are intentionally excluded because visual variables are file-local unless the
assembly explicitly shares them.

Inputs named `ID` receive collision-free values automatically. Labels and
required helper functions are also deduplicated during code generation.

### Multiple functions in one file

Select **+ Function** or add a **Function Entry** node. Give each entry a unique
name, connect its own node chain, and invoke it with a call-function node or
hand-written `call function_name`. Function bodies are guarded so normal startup
execution cannot accidentally fall through into them.

## Images and MIDI

Right-click the project tree to import resources:

- **Import/Convert .PNG (Raw Data)** converts indexed pixel and palette data
  into an assembly resource file for the image-drawing nodes. The current safe
  bound is 80×80 pixels. Larger images show an OK/Cancel warning; OK scales the
  image proportionally to fit, while Cancel leaves the project unchanged.
- **Import/Convert MIDI (PC Speaker)** converts `.mid` or `.midi` note timing
  into assembly data for the **Play MIDI Resource** node. No external MIDI
  Python package is required.

Keep imported assembly resources in the same project and include or reference
their generated symbols from the code that uses them.

## IDE controls

| Control | Purpose |
| --- | --- |
| **Build (F5)** | Assemble the project and create `build/boot.img` |
| **Run (F6)** | Launch the most recent boot image in QEMU |
| **Settings** | Edit the project name and version |
| **Plugins** | Install, enable, disable, and reload plugins |
| **Export (F8)** | Copy the completed boot image to another location |
| **Help** | Open the project documentation link |

Build currently writes `main.bin`, then `kernel.bin`, and pads the image to
1.44 MB. Other assembly files are still checked by NASM; include or load them
from the boot path when they must become part of the running OS.

## Run from source

### Requirements

- Python 3.10 or newer is recommended
- PyQt6, installed from `requirements.txt`
- NASM
- QEMU with `qemu-system-x86_64`

Clone or download the repository, open a terminal in it, and create a virtual
environment.

### Windows

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Operation Crafter expects these tool locations on Windows:

```text
nasm/nasm.exe
qemu/qemu-system-x86_64.exe
```

Download NASM and QEMU from their official projects, place them in those
directories, then launch the app:

```powershell
.\.venv\Scripts\python.exe main.py
```

### Linux

Install Python, NASM, and the `qemu-system-x86_64` package using your
distribution's package manager. On Debian or Ubuntu, for example:

```bash
sudo apt update
sudo apt install python3 python3-venv nasm qemu-system-x86
```

Create the environment and make NASM available at the path used by the
compiler:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
mkdir -p nasm
ln -sf "$(command -v nasm)" nasm/nasm
python main.py
```

QEMU may come from the system `PATH` or from
`qemu/qemu-system-x86_64` inside the repository.

## Package the desktop application

Running `main.py` starts the source version. Packaging creates a standalone
desktop executable and is separate from building a project's `boot.img`.

Install the packaging dependency first:

```bash
python -m pip install pyinstaller
```

### Package on Windows

```bat
build.cmd
```

Pass an optional output directory as the first argument:

```bat
build.cmd C:\Builds\OperationCrafter
```

### Package on Linux

```bash
chmod +x build.sh
./build.sh --linux
```

Other supported forms are:

```bash
./build.sh --linux --dist ./release
./build.sh --windows
./build.sh --all
./build.sh --assets-only --dist ./release
```

Linux-to-Windows packaging requires Wine and a Windows Python installation with
PyInstaller and PyQt6. `build.sh` checks the project's Windows environments and
the current Windows user's standard Python installations automatically. Set
`WIN_PYTHON` to override that detection, or set `PYTHON_BIN` to override the
Python used for Linux packaging.

Both scripts place output in `dist` by default and copy `nasm`, `qemu`,
`plugins`, and license files beside the executable. The required NASM and QEMU
executables are verified after copying. `--assets-only` can repair or refresh
those support folders without rebuilding the application. The scripts do not
download third-party tools.

## Plugins

Install a plugin ZIP from the Plugin Manager or place it in `plugins/`.
Development plugins can remain unpacked in that directory and be reloaded
without restarting the IDE.

A plugin can contain:

```text
ExamplePlugin/
├── plugin.json       # Name, version, author, API version, and description
├── blocks/           # Individual block JSON files or catalog JSON files
└── ui/colors.json    # Optional complete UI theme
```

The loader supports plugin API versions 1 and 2. Version 2 block catalogs can
define shared families and many variants without duplicating every field.
Malformed or incompatible plugins are isolated and reported in the manager.

Official plugin source directories live in `Official-Plugins/`. Installable ZIP
packages live in `Official-Plugins/Downloads/`. The **Official Plugin
Downloads** button opens that folder on GitHub.

PurpleUI 1.1.1 themes the launcher, editor, node graph, nodes, title bars,
dialogs, Help links, inputs, tabs, menus, and scrollbars. Its source is in
`Official-Plugins/PurpleUI`, and its installable package is
`Official-Plugins/Downloads/PurpleUI.zip`.

## Repository guide

```text
app/
├── blocks/           # Built-in node definitions
├── block.py          # Node rendering, wiring, persistence, and ASM generation
├── compiler.py       # NASM and boot-image pipeline
├── editor.py         # IDE, code editor, node UI, imports, and dialogs
├── emulator.py       # QEMU process launcher
├── launcher.py       # Create/open project window
├── midi_import.py    # Dependency-free MIDI parser and ASM conversion
├── pluginmanager.py  # Plugin discovery, validation, and live reload
└── theme.py          # Shared built-in and plugin-driven UI styling

main.py               # Application entry point
build.sh              # Linux and Wine packaging entry point
build.cmd             # Native Windows packaging entry point
requirements.txt      # Runtime Python dependencies
Official-Plugins/     # Official source plugins and downloadable ZIP packages
```

## Troubleshooting

### NASM was not found

Place NASM at `nasm/nasm.exe` on Windows or `nasm/nasm` on Linux. On Linux, the
symlink command in the source-install section is sufficient.

### `boot.img` was not found

Press **Build (F5)** first. If NASM reports an error, fix it and build again;
the compiler deliberately refuses to create an image from partial output.

### QEMU does not start

Confirm that `qemu-system-x86_64` is installed. Windows uses
`qemu/qemu-system-x86_64.exe`; Linux checks the system `PATH` and then the local
`qemu` directory.

### A project will not open

Navigate into the project and select `.projectdata`, not the project directory.
The picker keeps all folders visible, including the hidden metadata file.

### A node is not generating code

Make sure it is connected to **START** or a **Function Entry**. Unconnected
nodes are saved but intentionally omitted from generated assembly.

## License and third-party software

Operation Crafter is distributed under the Attribution License 2026 in
[`LICENCE`](LICENCE). Distributions and derivative distributions must retain
reasonable attribution to the original author.

NASM and QEMU are separate projects with their own licenses:

- [NASM](https://www.nasm.us/)
- [QEMU](https://www.qemu.org/)

If a release redistributes either tool, its corresponding license and notices
must also be retained.
