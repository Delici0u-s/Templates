import os, re, sys, subprocess

################### Automatic Meson Compiler Application (AMCA) ###########################
# This version includes automatic detection of new source files.
# If new files are detected, a minimal reconfiguration (meson setup --reconfigure <builddir>)
# is triggered so that the new files are added without a full rebuild.

FollowArgs = {
    "-ms": '5',  # max Searches, 5 by default
}

TriggerArgs = {
    "-s": False,   # force running setup.py (full reconfiguration)
    "-r": False,   # compile in release mode
    "-d": False,   # compile in debug mode (should be default in meson.build)
    "-ne": False,  # just compile, don't execute
    "-nc": False,  # don't compile, just run
    "-nb": False,  # disable separation between build/compile and execution
    "-c": False,   # clear terminal before execution
    "-m": False,   # move terminal to output path
    "-Ab": [False, len(sys.argv)],  # additional args for meson build
    "-Ac": [False, len(sys.argv)],  # additional args for meson compile
    "-Ae": [False, len(sys.argv)],  # additional args for the executable
    "-clear": False,  # removes build folder, executable and source cache
    "--help": False,
}

# --- Source Cache Functions ---
def get_cache_path():
    # Place .sources_cache in the same folder as this script (MesonBuildStuff/)
    return os.path.join(os.path.dirname(__file__), ".sources_cache")

def get_current_sources():
    try:
        output = subprocess.check_output(
            [sys.executable, 'MesonBuildStuff/globber.py', './', '*.cpp', '*.cxx', '*.cc', '*.c'],
            universal_newlines=True
        )
        return set(filter(None, output.strip().split('\n')))
    except subprocess.CalledProcessError as e:
        print("Error running globber.py:", e)
        return set()

def read_cached_sources():
    cache_file = get_cache_path()
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            return set(filter(None, f.read().strip().split('\n')))
    return set()

def write_cached_sources(sources):
    cache_file = get_cache_path()
    with open(cache_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(sources)))

def check_for_new_sources():
    current_sources = get_current_sources()
    cached_sources = read_cached_sources()
    if current_sources != cached_sources:
        write_cached_sources(current_sources)
        return True
    return False

# --- End Source Cache Functions ---

def main():
    target_file = "meson.build"
    basedir = os.path.realpath(os.path.join(__file__, "..\\.."))
    meson_file_path = os.path.join(basedir, target_file)

    setupPy_path = os.path.join(basedir, "MesonBuildStuff", "amcaSetup.py")
    buildpathdir = getNameMesonVarDecl(meson_file_path, "build_dir_where").split("'")[1].replace('/', '\\').removeprefix('\\')  # relative to basedir
    totBpath = os.path.realpath(os.path.join(basedir, buildpathdir))

    output_dir = getNameMesonVarDecl(meson_file_path, "output_dir").split("'")[1].replace('/', '\\').removeprefix('\\')
    output_name = getNameMesonVarDecl(meson_file_path, "output_name").split("'")[1].replace('/', '\\').removeprefix('\\')
    output_TOTAL_dir = os.path.realpath(os.path.join(basedir, buildpathdir, output_dir))
    output_TOTAL = os.path.join(output_TOTAL_dir, output_name)
    output_TOTAL_win = output_TOTAL + '.exe'

    if TriggerArgs['-clear']:
        # Remove build artifacts...
        success = (
            tryrem(output_TOTAL)
            & tryrem(output_TOTAL_win)
            & tryremD(output_TOTAL_dir)
            & tryremF(totBpath)
        )
        # Also remove the source cache file stored in MesonBuildStuff
        cache_file = get_cache_path()
        if os.path.exists(cache_file):
            success = tryrem(cache_file) and success
        if success:
            print("All items successfully removed")
        else:
            print("Not all items were successfully removed")
        os._exit(int(not success))  # 0 indicates success

    os.chdir(basedir)
    didntbuild = True
    if TriggerArgs["-s"] or not os.path.exists(totBpath):
        mode = '--buildtype=release --debug=false' if TriggerArgs["-r"] else ""
        mode = '--buildtype=debug' if TriggerArgs["-d"] else mode
        args = ' '.join(GetArgs("-Ab"))
        didntbuild = os.system(' '.join([f'"{sys.executable}"', setupPy_path, mode, args]))
        if didntbuild:
            os._exit(1)
    
    # Automatically check for new source files and perform minimal reconfiguration
    if not TriggerArgs["-s"]:
        if check_for_new_sources():
            print("New source files detected. Running minimal reconfiguration...")
            reconfig_ret = os.system(f'meson setup --reconfigure {buildpathdir}')
            if reconfig_ret:
                print("Reconfiguration failed!")
                sys.exit(reconfig_ret)

    if not TriggerArgs["-nc"]:  # compilation
        args = ' '.join(GetArgs("-Ac"))
        didntcompile = os.system(' '.join(['ninja -C', buildpathdir, args]))
        if not didntcompile:
            didntcompile = os.system(f"meson install -C {buildpathdir}")
        if didntcompile:
            os._exit(2)

    if not TriggerArgs["-ne"] or TriggerArgs["-m"]:  # execution
        if (not TriggerArgs["-nc"] or not didntbuild) and not TriggerArgs["-c"]:
            os.system('echo[')
            os.system('echo ---------------------------------------------------------------------------------------------')
            os.system('echo[')
        if TriggerArgs['-c']:
            os.system('cls')
        outcommand = output_TOTAL + ' ' + ' '.join(GetArgs("-Ae"))
        if TriggerArgs["-m"]:  # switch terminal path
            if not TriggerArgs["-ne"]:
                os.system(f'(echo cd {output_TOTAL_dir} && echo {outcommand}) | clip')
                print("Everything has been copied to your clipboard. Just press Ctrl+V to print and execute.")
            else:
                os.system(f'echo cd {output_TOTAL_dir} | clip')
                print("Everything has been copied to your clipboard. Just press Ctrl+V to change the directory.")
            print("\nIt's sadly not possible to change the terminal directory with Python, so this is the solution.")
            os._exit(0)
        else:
            os._exit(os.system(outcommand))

def getNameMesonVarDecl(filepath, variablename):
    regex = re.compile(rf'^{variablename}\s*=')
    out = 'NOT_FOUND'
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            for line in file:
                if regex.match(line):
                    out = line
                    break
            else:
                print(f"No {variablename} found in {filepath}.")
    except FileNotFoundError:
        print(f"{filepath} not found.")
    except Exception as e:
        print(f"An error occurred looking for {variablename}: {e}")
    return out

def GetArgOption(arg_dict):
    toggle = True
    for x in range(len(sys.argv) - 1):  # -1 to avoid out-of-bounds error on last argument
        if sys.argv[x] in ['-Ab', '-Ac', '-Ae']:
            toggle = False
        elif sys.argv[x] in arg_dict and toggle:
            arg_dict[sys.argv[x]] = sys.argv[x + 1]
    return arg_dict

def GetArgPresent(arg_dict):
    toggle = True
    for x in range(len(sys.argv)):
        if sys.argv[x] in ['-Ab', '-Ac', '-Ae']:
            arg_dict[sys.argv[x]] = [True, x]
            toggle = False
        elif sys.argv[x] in arg_dict and toggle:
            arg_dict[sys.argv[x]] = True
    return arg_dict

def GetArgs(Option):
    out = []
    optargs = ["-Ab", "-Ac", "-Ae"]
    optargs.remove(Option)
    toggle = False
    for x in sys.argv:
        if x in optargs:
            toggle = False
        elif x == Option:
            toggle = True
        elif toggle:
            out.append(x)
    return out

def delete_directory(filepath):
    if not os.path.exists(filepath):
        print(f"Error: The directory '{filepath}' does not exist.")
        return False
    for root, dirs, files in os.walk(filepath, topdown=False):
        for name in files:
            file_path = os.path.join(root, name)
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")
                return False
        for name in dirs:
            dir_path = os.path.join(root, name)
            try:
                os.rmdir(dir_path)
            except Exception as e:
                print(f"Error deleting directory {dir_path}: {e}")
                return False
    try:
        os.rmdir(filepath)
    except Exception as e:
        print(f"Error deleting directory {filepath}: {e}")
        return False
    return True

def tryrem(filepath):
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            if os.path.exists(filepath):
                return False
        except:
            return False
    return True

def tryremF(filepath):
    if os.path.exists(filepath):
        try:
            return delete_directory(filepath)
        except:
            return False
    return True

def tryremD(filepath):
    if os.path.exists(filepath):
        try:
            os.removedirs(filepath)
            if os.path.exists(filepath):
                return False
        except:
            return False
    return True

def ensure_installed(packages):
    """
    Checks if the given packages are installed.
    This version uses a marker file located in the MesonBuildStuff folder to perform the check only once.
    """
    marker = os.path.join(os.path.dirname(__file__), ".amca_deps_checked")
    if os.path.exists(marker):
        return
    for package in packages:
        try:
            __import__(package)
        except ImportError:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    # Create the marker file so subsequent runs skip dependency checking
    try:
        with open(marker, "w") as f:
            f.write("dependencies installed")
    except Exception as e:
        print(f"Failed to create marker file: {e}")

def PrintHelp():
    print("Automatic Meson Compiler Application")
    print("Designed to work with blues & Delici0us setup")
    print("Arguments:")
    print("    -ms amount     Max search depth for meson.build. 5 by default, will be replaced by amount")
    print("    --help         Display help message")
    print("    -s             Run setup.py (full reconfiguration)")
    print("    -r             Compile in release mode")
    print("    -d             Compile in debug mode")
    print("    -ne            Just compile, don't execute")
    print("    -nc            Don't compile, just run")
    print("                   If both -ne and -nc are present, nothing will compile or run")
    print("    -nb            Disable separation between building/compilation and execution")
    print("    -c             Clear terminal before execution")
    print("    -m             Move terminal to output path")
    print("    -Ab            Toggle all following args for the meson build")
    print("    -Ac            Toggle all following args for the meson compile")
    print("    -Ae            Toggle all following args for the executable")
    print("                   -Ab, -Ac and -Ae will interrupt each other")
    print("    -clear         Remove build folder, executable and source cache (in MesonBuildStuff)")
    print(f"    Amca.py found at {__file__}")
    print("                   If this is not the correct amca, try reducing your search radius with -ms")

if __name__ == "__main__":
    ensure_installed(["pip", "meson", "ninja"])
    GetArgPresent(TriggerArgs)
    if TriggerArgs["--help"]:
        PrintHelp()
        exit()
    GetArgOption(FollowArgs)
    try:
        MAXSEARCHLVL = int(FollowArgs['-ms'])
        assert MAXSEARCHLVL >= 0
    except:
        print("Please input a valid integer as maxSearches")
        exit()
    main()
