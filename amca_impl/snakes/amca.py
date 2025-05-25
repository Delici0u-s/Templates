import os
import re
import sys
import json
import shutil
import signal
import subprocess
from pathlib import Path

# --- Configuration Defaults ---
DEFAULT_MAX_SEARCH = 5

# --- Utility Functions ---

def find_meson_root(start: Path, max_depth: int) -> Path:
    for _ in range(max_depth + 1):
        if (start / 'meson.build').is_file():
            return start
        if start.parent == start:
            break
        start = start.parent
    print("meson.build could not be found. Maybe increase search radius.")
    sys.exit(1)


def get_snakes_dir() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', '')) / 'amca' / 'snakes'

# --- Source Cache ---

def cache_path(base: Path) -> Path:
    return base / '.sources_cache'

def current_sources(snakesdir: Path) -> set[str]:
    cmd = [sys.executable, str(snakesdir / 'globber.py'), './', '*.cpp', '*.cxx', '*.cc', '*.c']
    try:
        out = subprocess.check_output(cmd, text=True)
        return set(filter(None, out.splitlines()))
    except subprocess.CalledProcessError as e:
        print(f"Error running globber.py: {e}")
        return set()

def read_cached(base: Path) -> set[str]:
    p = cache_path(base)
    if p.exists():
        return set(filter(None, p.read_text().splitlines()))
    return set()

def write_cached(base: Path, sources: set[str]) -> None:
    cache_path(base).write_text("\n".join(sorted(sources)))

def need_reconfigure(base: Path, snakesdir: Path) -> bool:
    curr = current_sources(snakesdir)
    cache = read_cached(base)
    if curr != cache:
        write_cached(base, curr)
        return True
    return False

# --- VSCode / Clangd Integration ---

def update_json(file: Path, key: str, value: str) -> None:
    if not file.exists():
        return
    try:
        data = json.loads(file.read_text())
        changed = False
        for cfg in data.get('configurations', []):
            cfg[key] = value
            changed = True
        if changed:
            file.write_text(json.dumps(data, indent=4))
    except Exception as e:
        print(f"Failed to update {file.name}: {e}")

# --- Template Mode ---

def get_folders(template_dir: Path) -> list[str]:
    if not template_dir.is_dir():
        return []
    return [d.name for d in template_dir.iterdir() if d.is_dir()]


def copy_folder(src: Path, dst: Path) -> None:
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"Copied {src.name} to {dst}")
    except Exception as e:
        print(f"Error copying folder: {e}")


def delete_dir(p: Path) -> None:
    try:
        shutil.rmtree(p)
        print(f"Removed template: {p.name}")
    except Exception as e:
        print(f"Error removing template: {e}")


def templating(mode: str, snakesdir: Path) -> None:
    template_dir = snakesdir.parent / 'templates'
    templates = get_folders(template_dir)
    if mode == 'list':
        for idx, name in enumerate(templates):
            print(f"[{idx}] {name}")
    elif mode == 'get':
        idx = int(input("Enter template number: "))
        copy_folder(template_dir / templates[idx], Path.cwd())
    elif mode == 'create':
        name = input("New template name: ")
        dest = template_dir / name
        if dest.exists():
            print("Template already exists.")
        else:
            copy_folder(Path.cwd(), dest)
    elif mode == 'remove':
        for idx, name in enumerate(templates):
            print(f"[{idx}] {name}")
        idx = int(input("Enter template number to remove: "))
        delete_dir(template_dir / templates[idx])
    else:
        print("Unknown template mode")
    sys.exit(0)

# --- Cleanup Helpers ---

def remove_file(p: Path) -> bool:
    try:
        if p.exists():
            p.unlink()
        return True
    except Exception:
        return False

def remove_dir(p: Path) -> bool:
    try:
        if p.exists():
            shutil.rmtree(p)
        return True
    except Exception:
        return False

# --- Signal Handling ---

def handle_sigint(signum, frame):
    sys.exit(0)

# --- Main Execution ---

def main():
    signal.signal(signal.SIGINT, handle_sigint)

    import argparse
    parser = argparse.ArgumentParser(
        description="Automatic Meson Compiler Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Template mode:
  -T list    List available templates
  -T get     Import a template into current directory
  -T create  Save current dir as new template
  -T remove  Delete an existing template
"""
    )
    parser.add_argument('-ms', type=int, default=DEFAULT_MAX_SEARCH,
                        help='Max meson.build search depth')
    parser.add_argument('-s', action='store_true', help='Full meson setup')
    parser.add_argument('-r', action='store_true', help='Release build')
    parser.add_argument('-d', action='store_true', help='Debug build')
    parser.add_argument('-ne', action='store_true', help="Don't execute")
    parser.add_argument('-nc', action='store_true', help="Don't compile")
    parser.add_argument('-ni', action='store_true', help="Don't install")
    parser.add_argument('-c', action='store_true', help='Clear console before run')
    parser.add_argument('-m', action='store_true', help='Copy cd/run commands to clipboard')
    parser.add_argument('-clear', action='store_true', help='Remove build artifacts')
    parser.add_argument('-T', choices=['list', 'get', 'create', 'remove'],
                        help='Template mode operations')
    parser.add_argument('-Ab', nargs='*', default=[], help='Extra meson setup args')
    parser.add_argument('-Ac', nargs='*', default=[], help='Extra compile args')
    parser.add_argument('-Ae', nargs='*', default=[], help='Extra run args')
    args = parser.parse_args()

    snakesdir = get_snakes_dir()
    if args.T:
        templating(args.T, snakesdir)

    basedir = find_meson_root(Path.cwd(), args.ms)

    # Load Meson variables
    def _get_var(name: str) -> str:
        pat = re.compile(rf"^{name}\s*=\s*['\"](.*)['\"]")
        for line in (basedir / 'meson.build').read_text().splitlines():
            m = pat.match(line)
            if m:
                return m.group(1)
        print(f"{name} not found in meson.build")
        sys.exit(1)

    build_dir = basedir / Path(_get_var('build_dir_where'))
    output_sub = Path(_get_var('output_dir'))
    exe_name = _get_var('output_name') + ('.exe' if os.name == 'nt' else '')

    # Handle clear
    if args.clear:
        exe_path = build_dir / output_sub / exe_name
        results = []
        # remove executable
        results.append(remove_file(exe_path))
        # remove output subdirectory only, not basedir
        results.append(remove_dir(build_dir / output_sub))
        # remove build directory
        results.append(remove_dir(build_dir))
        # remove cache file
        cache_file = cache_path(basedir)
        if cache_file.exists():
            results.append(remove_file(cache_file))
        success = all(results)
        print("Cleared artifacts" if success else "Some artifacts could not be removed")
        sys.exit(0)

    os.chdir(basedir)

    # Setup or reconfigure
    if args.s or not build_dir.exists():
        if not build_dir.exists():
            write_cached(basedir, current_sources(snakesdir))
        mode = '--buildtype=release' if args.r else ('--buildtype=debug' if args.d else '')
        cmd = ['meson', 'setup', str(build_dir), '--wipe', mode] + args.Ab
        # VSCode launch.json: use workspace-relative path
        rel_exe = (build_dir / output_sub / exe_name).relative_to(basedir)
        update_json(basedir / '.vscode' / 'launch.json', 'program', f"${{workspaceFolder}}/{rel_exe}")
        # .clangd: set CompilationDatabase to workspace-relative build dir
        ##########################
        # .clangd: update or append CompilationDatabase in YAML .clangd
        rel_build = build_dir.relative_to(basedir).as_posix()
        clangd_path = basedir / '.clangd'
        if clangd_path.exists():
            try:
                lines = clangd_path.read_text().splitlines()
                new_lines = []
                updated = False
                for line in lines:
                    if line.lstrip().startswith('CompilationDatabase:'):
                        indent = len(line) - len(line.lstrip())
                        new_lines.append(' ' * indent + f"CompilationDatabase: {rel_build}")
                        updated = True
                    else:
                        new_lines.append(line)
                if not updated:
                    new_lines.append(f"CompilationDatabase: {rel_build}")
                clangd_path.write_text("\n".join(new_lines))
            except Exception as e:
                print(f"Failed to update .clangd: {e}")

        ##########################
        if subprocess.call(cmd): sys.exit(1)
    else:
        if need_reconfigure(basedir, snakesdir):
            print("New sources detected, reconfiguring...")
            if subprocess.call(['meson', 'setup', '--reconfigure', str(build_dir)]):
                sys.exit(1)

    # Compile
    if not args.nc:
        if subprocess.call(['ninja', '-C', str(build_dir)] + args.Ac): sys.exit(2)
        if not args.ni:
            if subprocess.call(['meson', 'install', '-C', str(build_dir)]): sys.exit(3)

    # Execute
    exe_path = build_dir / output_sub / exe_name
    if not args.ne:
        if args.c:
            os.system('cls' if os.name=='nt' else 'clear')
        if args.m:
            clip = f"cd {exe_path.parent}\n{exe_path} {' '.join(args.Ae)}"
            os.system(f'echo {clip} | clip')
            print("Commands copied to clipboard.")
            sys.exit(0)
        try:
            ret = subprocess.call([str(exe_path)] + args.Ae)
            sys.exit(ret)
        except KeyboardInterrupt:
            sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, handle_sigint)
    main()
