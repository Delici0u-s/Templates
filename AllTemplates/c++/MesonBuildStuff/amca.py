import os, re, sys, subprocess

################### Code very messy, might clean up later ###########################

FollowArgs = {
    "-ms":'5', # max Searches, 5 my default
    }

TriggerArgs = {
    "-s" : False, # rerun building
    "-r" : False, # compile in release mode
    "-d" : False, # compile in debug mode (should be default in meson.build, so useless unless meson.build is modified)
    "-ne" : False, # dont execute the compiled mainfile
    "-nc" : False, # dont compile, just run
    "-nb" : False, # disables the seperation between building/compilation and execution
    "-c" : False, # clears terminal after compilation
    "-m" : False, # move terminal to output path
    "-Ab" : [False, len(sys.argv)], # toggles additional args for meson build
    "-Ac" : [False, len(sys.argv)], # toggles additional args for meson compile
    "-Ae" : [False, len(sys.argv)], # toggles additional args for the executable
    "-clear" : False, # deletes build folder and executable. If compilation folder is empty after will delete that too
    "--help" : False, 
}

def main():
    target_file = "meson.build"
    basedir = os.path.realpath(os.path.join(__file__, "..\\.."))
    meson_file_path = os.path.join(basedir, target_file)

    setupPy_path = os.path.join(basedir, "MesonBuildStuff", "amcaSetup.py")
    buildpathdir = getNameMesonVarDecl(meson_file_path, "build_dir_where").split("'")[1].replace('/', '\\').removeprefix('\\') # relative to basedir
    totBpath = os.path.realpath(os.path.join(basedir, buildpathdir))

    output_dir = getNameMesonVarDecl(meson_file_path, "output_dir").split("'")[1].replace('/', '\\').removeprefix('\\')
    output_name = getNameMesonVarDecl(meson_file_path, "output_name").split("'")[1].replace('/', '\\').removeprefix('\\')
    output_TOTAL_dir = os.path.realpath(os.path.join(basedir, buildpathdir, output_dir))
    output_TOTAL = os.path.join(output_TOTAL_dir, output_name)
    output_TOTAL_win = output_TOTAL + '.exe'

    if TriggerArgs['-clear']:
        success = (
            tryrem(output_TOTAL)
            & tryrem(output_TOTAL_win)
            & tryremD(output_TOTAL_dir)
            & tryremF(totBpath)
        )
        if (success):
            print("All items sucessfully removed")
        else:
            print('Not all items were sucessfully removed')
        os._exit(int(not success)) # 'not' so True becomes 0 (as 0 is ran succesfully)

    os.chdir(basedir)
    didntbuild = True
    if TriggerArgs["-s"] or not os.path.exists(totBpath):
        mode = '--buildtype=release --debug=false' if TriggerArgs["-r"] else ""
        mode = '--buildtype=debug' if TriggerArgs["-d"] else mode
        args = ' '.join(GetArgs("-Ab"))
        didntbuild = os.system(' '.join([f'"{sys.executable}"', setupPy_path, mode, args]))
        if didntbuild:
            os._exit(1)
    
    if not TriggerArgs["-nc"]: # compilation
        args = ' '.join(GetArgs("-Ac"))
        didntcompile = os.system(' '.join(['ninja -C', buildpathdir, args]))
        if not didntcompile:
            didntcompile = os.system(f"meson install -C {buildpathdir}")
        if didntcompile:
            os._exit(2)

    if not TriggerArgs["-ne"] or TriggerArgs["-m"]: # execution
        if (not TriggerArgs["-nc"] or not didntbuild) and not TriggerArgs["-c"]:
            os.system('echo[')
            os.system('echo ---------------------------------------------------------------------------------------------')
            os.system('echo[')
        if TriggerArgs['-c']:
            os.system('cls')
        outcommand = output_TOTAL + ' ' + ' '.join(GetArgs("-Ae"))
        if TriggerArgs["-m"]: # switch terminal path
            if not TriggerArgs["-ne"]:
                os.system(f'(echo cd {output_TOTAL_dir} && echo {outcommand}) | clip')
                print("everything has been copied to your clipboard. just press ctrl-v to print and execute")
            else:
                os.system(f'echo cd {output_TOTAL_dir} | clip')
                print("everything has been copied to your clipboard. just press ctrl-v to change the directory")
            print("\nIts sadly not possible to change the terminal dir with python, so this is the solution, sry")
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
        print(f"An error occurred Looking for {variablename}: {e}")
    return out

def GetArgOption(arg_dict):
    toggle = True
    for x in range(len(sys.argv)-1):  # -1 to avoid out-of-bounds error on last argument
        if sys.argv[x] == '-Ab' or sys.argv[x] == '-Ac' or sys.argv[x] == '-Ae':
            toggle = False
        elif sys.argv[x] in arg_dict and toggle:
            arg_dict[sys.argv[x]] = sys.argv[x+1]
    return arg_dict

def GetArgPresent(arg_dict):
    toggle = True
    for x in range(len(sys.argv)):  # -1 to avoid out-of-bounds error on last argument
        if sys.argv[x] == "-Ab" or sys.argv[x] == '-Ac' or sys.argv[x] == '-Ae':
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

    # Recursively delete all files and subdirectories in the directory
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

    # Finally, remove the empty directory itself
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
    """Ensure the given packages are installed, install them if missing."""
    for package in packages:
        try:
            __import__(package)
        except ImportError:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])


def PrintHelp():
    print("Automatic Meson Compiler Application")
    print("Designed to work with blues & Delici0us setup")
    print("Arguents:")
    print("    -ms amount     Max search depth for meson.build. 5 by default, will be replaced by amount")
    print("    --help   display help message")
    print("    -s       run setup.py")
    print("    -r       compile in release mode")
    print("    -d       compile in debug mode")
    print("             both -r and -d will have no effect if -s isnt present")
    print("    -ne      just compile, dont execute")
    print("    -nc      dont compile, just run")
    print("             if both ne and nc are present it wont compile and wont run")
    print("    -nb      disables the barrier between compilation and execution")
    print("    -c       clears terminal before execution")
    print("    -m       move terminal to output directory")
    print("    -Ab      Toggles all following args to be for the meson build")
    print("    -Ac      Toggles all following args to be for the meson compiler")
    print("    -Ae      Toggles all following args to be for the executable")
    print("             Ab, Ac and Ae will interrupt eachother")
    print("    -clear   removes build folder and executable. Also removes compile path if folder is empty after")
    print(f"             Amca.py found at {__file__}")
    print("                 If this is not the correct amca maybe try reducing your searchradius with -ms")

if __name__=="__main__":
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
        print("Please input a valid integer as maxSeaches")
        exit()
    main()