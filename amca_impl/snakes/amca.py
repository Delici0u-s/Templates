import os, re, sys, subprocess, shutil, json

################### Automatic Meson Compiler Application (AMCA) ###########################
# This version includes automatic detection of new source files.
# If new files are detected, a minimal reconfiguration (meson setup --reconfigure <builddir>)
# is triggered so that the new files are added without a full rebuild.

FollowArgs = {
    "-ms": '5',  # max Searches, 5 by default
    "-T": '-1', # select template and copy to mode
}

TriggerArgs = {
    "-s": False,   # force running setup.py (full reconfiguration)
    "-r": False,   # compile in release mode
    "-d": False,   # compile in debug mode (should be default in meson.build)
    "-ne": False,  # just compile, don't execute
    "-nc": False,  # don't compile, just run
    "-ni": False,  # don't install
    "-nb": False,  # disable separation between build/compile and execution
    "-c": False,   # clear terminal before execution
    "-m": False,   # move terminal to output path
    "-Ab": [False, len(sys.argv)],  # additional args for meson build
    "-Ac": [False, len(sys.argv)],  # additional args for meson compile
    "-Ae": [False, len(sys.argv)],  # additional args for the executable
    "-clear": False,  # removes build folder, executable and source cache
    "--help": False, # select template and copy to mode
    "-?": False, # select template and copy to mode
    "-T": False, # select template and copy to mode
}

def GetMesonFilePath():
    try:
        max_search = int(FollowArgs.get("-ms"))  # Default to 5 if not provided
    except: max_search = 0
    current_dir = os.getcwd()
    
    for _ in range(max_search + 1):
        meson_build_path = os.path.join(current_dir, "meson.build")
        if os.path.isfile(meson_build_path):
            return current_dir
        # If we've reached the root, break out.
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            break
        current_dir = parent_dir

    if not TriggerArgs["-T"]:
        print("meson.build could not be found. maybe increase search radius")
        exit(1)


def GetSnakesDir():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "amca", "snakes")


# --- Source Cache Functions ---
def get_cache_path():
    # Place .sources_cache in the same folder as this script (MesonBuildStuff/)
    return os.path.join(basedir, ".sources_cache")

def get_current_sources():
    try:
        output = subprocess.check_output(
            [sys.executable, os.path.join(snakesdir, 'globber.py'), './', '*.cpp', '*.cxx', '*.cc', '*.c'],
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

def update_launch_json(output_full):
    vscode_folder = os.path.join(basedir, ".vscode")
    launch_json_path = os.path.join(vscode_folder, "launch.json")

    if not os.path.exists(launch_json_path):
        print("launch.json not found. Skipping modification.")
        return

    try:
        with open(launch_json_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        for config in data.get("configurations", []):
            config["program"] = "${workspaceFolder}/" + output_full.replace("\\", "/")

        with open(launch_json_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        print("Updated launch.json successfully.")
    except Exception as e:
        print(f"Failed to update launch.json: {e}")

def update_clangd_config(new_value):
    """
    Update or add the CompilationDatabase variable in the .clangd file.
    new_value should be a string (or something that converts to string) that you want to set.
    """
    clangd_path = os.path.join(basedir, ".clangd")
    if not os.path.exists(clangd_path):
        print(".clangd not found. Skipping modification.")
        return

    try:
        with open(clangd_path, "r", encoding="utf-8") as file:
            lines = file.readlines()

        new_lines = []
        updated = False
        for line in lines:
            # Check if the line starts (ignoring whitespace) with "CompilationDatabase:"
            if line.lstrip().startswith("CompilationDatabase:"):
                indent = len(line) - len(line.lstrip())
                new_line = " " * indent + "CompilationDatabase: " + str(new_value) + "\n"
                new_lines.append(new_line)
                updated = True
            else:
                new_lines.append(line)
        # If the setting was not found, append it.
        if not updated:
            new_lines.append("CompilationDatabase: " + str(new_value) + "\n")

        with open(clangd_path, "w", encoding="utf-8") as file:
            file.writelines(new_lines)
        print("Updated .clangd successfully.")
    except Exception as e:
        print(f"Failed to update .clangd: {e}")

def OnSetup(outputdir, builddir, mode, args):
    update_launch_json(os.path.join(builddir, outputdir))
    update_clangd_config(builddir)
    os.chdir(basedir)

    print(''.join(["meson setup ", builddir,  " --wipe ", mode, args]))
    return (os.system(''.join(["meson setup ", builddir,  " --wipe ", mode, args])))

    # returns true if it didnt build
    return False

# --- End Source Cache Functions ---

def main():
    # might need to implement meson.build searching
    # basedir = os.path.realpath(os.path.join(__file__, "..\\.."))
    meson_file_path = os.path.join(basedir, "meson.build")

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
        if not os.path.exists(totBpath):
            write_cached_sources(get_current_sources())
        mode = '--buildtype=release --debug=false' if TriggerArgs["-r"] else ""
        mode = '--buildtype=debug' if TriggerArgs["-d"] else mode
        args = ' '.join(GetArgs("-Ab"))
        if OnSetup(os.path.join(output_dir, output_name), buildpathdir, mode, args):
            os._exit(1)
        didntbuild = False  # Mark that setup already ran

    
    # Automatically check for new source files and perform minimal reconfiguration
    if not TriggerArgs["-s"] and didntbuild:  # Only reconfigure if setup wasn't already run
        if check_for_new_sources():
            print("New source files detected. Running minimal reconfiguration...")
            reconfig_ret = os.system(f'meson setup --reconfigure {buildpathdir}')
            if reconfig_ret:
                print("Reconfiguration failed!")
                sys.exit(reconfig_ret)


    if not TriggerArgs["-nc"]:  # compilation
        args = ' '.join(GetArgs("-Ac"))
        didntcompile = os.system(' '.join(['ninja -C', buildpathdir, args]))
        if not didntcompile and not TriggerArgs["-ni"]:
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

def copyFolder(src, dst):
    """Recursively copies a folder from src to dst."""
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)  # Overwrites existing files if needed
        print(f"Copied {src} to {dst}")
    except Exception as e:
        print(f"Error copying folder: {e}")

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

def printNice(List: list[str]):
    l = 0
    for idx, i in enumerate(List):
        if l > 100:
            print()
        l += len(i) + 4
        print(f"[{idx}] {i}", end='  ')
    print()

def getSelection(List : list[str]):
    try:
        inp = int(sys.argv[1])
        assert inp >= 0 and inp < len(List)
        return inp
    except:
        try:
            return List.index(sys.argv[1])
        except:
            pass
    while True:
        inp = input("Select a valid name or number from the above selection (or q to quit): ")
        if inp == 'q': exit()
        try:
            inp = int(inp)    
            assert inp >= 0 and inp < len(List)
            return inp
        except:
            try:
                return List.index(inp)
            except:
                pass

def getFolders(templateDir):
    """Returns a list of all folder names in the given directory."""
    if not os.path.isdir(templateDir):
        return []  # Return an empty list if the directory does not exist or is not valid

    return [name for name in os.listdir(templateDir) if os.path.isdir(os.path.join(templateDir, name))]

            
def templating():
    templateDir = os.path.join(snakesdir, '..\\templates')
    folders = getFolders(templateDir)
    if (FollowArgs["-T"] == '-g'):
        printNice(folders)
        selection = None
        for i in range(len(sys.argv) - 1):
            if sys.argv[i] == '-g':
                try:
                    selection = int(sys.argv[i + 1])
                    assert 0 <= selection < len(folders)
                except (ValueError, AssertionError, IndexError):
                    pass
        if selection is None:
            selection = folders[getSelection(folders)]
        else:
            selection = folders[selection]

        copyFolder(os.path.join(templateDir, selection), os.getcwd())
    elif (FollowArgs["-T"] == '-c'):
        name = input("What name should the template have: ")
        while(name in folders):
            name = input("Template name cannot exist already: ")
        copyFolder(os.getcwd(), os.path.join(templateDir, name))
        print("create Template")
    elif (FollowArgs["-T"] == '-r'):
        printNice(folders)
        selection = folders[getSelection(folders)]
        delete_directory(os.path.join(templateDir, selection))
        print(f"remove template: {selection}")
    else :
        print("Please enter a valid T tag")

def PrintHelp():
    print("Automatic Meson Compiler Application")
    print("Designed to work with blues & Delici0us setup")
    print("Arguments:")
    print("    -ms amount     Max search depth for meson.build. 5 by default, will be replaced by amount")
    print("    --help         Display help message")
    print("    -T             Switch to template mode")
    print("         -g             copy selected template to current dir")
    print("                        if followed by a number skips selection process")
    print("         -c             add current dir to templates")
    print("         -r             select template to remove")
    print("    -s             Run full reconfiguration")
    print("    -r             Compile in release mode")
    print("    -d             Compile in debug mode")
    print("    -ne            Just compile, don't execute")
    print("    -nc            Don't compile, just run")
    print("    -ni            Don't install to the output dir")
    print("                   If both -ne and -nc are present, nothing will compile or run")
    print("    -nb            Disable separation between building/compilation and execution")
    print("    -c             Clear terminal before execution")
    print("    -m             Move terminal to output path")
    print("    -Ab            Toggle all following args for the meson build")
    print("    -Ac            Toggle all following args for the meson compile")
    print("    -Ae            Toggle all following args for the executable")
    print("                   -Ab, -Ac and -Ae will interrupt each other")
    print("    -clear         Remove build folder, executable and source cache (in MesonBuildStuff)")

if __name__ == "__main__":
    GetArgPresent(TriggerArgs)
    if TriggerArgs["--help"] or TriggerArgs["-?"]:
        PrintHelp()
        exit()
    GetArgOption(FollowArgs)
    basedir = GetMesonFilePath()
    snakesdir = GetSnakesDir()
    try:
        MAXSEARCHLVL = int(FollowArgs['-ms'])
        assert MAXSEARCHLVL >= 0
    except:
        print("Please input a valid integer as maxSearches")
        exit()
    if TriggerArgs["-T"]:
        templating()
    else:
        main()
