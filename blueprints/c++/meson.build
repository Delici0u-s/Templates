project('CHANGEME', ['cpp', 'c'],
  version : '0.1',
  default_options : ['warning_level=3', 'cpp_std=c++23', 'buildtype=debug', 'optimization=0', 'debug=true'])
# To build in release mode, run: meson setup build --buildtype=release

# DO NOT change variable names; AMCA relies on these.
output_name = 'a'
output_dir = '../compiled'  # Relative to meson.build location
build_dir_where = 'build'  # Relative to meson.build location

# Compiler arguments
cpp_compiler_args = [   
  # '-Og',
  '-g',
  '-Wall', 
  '-Wextra',
  '-pedantic',
  # '-O2',
  # '-lstdc++exp',
  '-static-libgcc', 
  '-static-libstdc++',
]
c_compiler_args = [
  '-static-libgcc', 
  '-static-libstdc++',
]

# Normalize paths
output_dir = output_dir.replace('/', '\\')
if not output_dir.startswith('\\')
  output_dir = '\\' + output_dir
endif
if not output_dir.endswith('\\') and output_dir != ''
  output_dir = ''.join([output_dir, '\\'])
endif
output_dir = meson.project_build_root() + output_dir

cmake = import('cmake')
fs    = import('fs')

# Dependencies (if any)
dependencies = []
dependencies_str = []
foreach item : dependencies_str
  dependencies += dependency(item)
endforeach

# get localappdata path
localappdata_cmd = run_command('cmd', '/c', 'echo %LOCALAPPDATA%', check : false)
if localappdata_cmd.returncode() == 0
  localappdata_path = localappdata_cmd.stdout().strip()
else
  error('Failed to retrieve LOCALAPPDATA path.')
endif

# Use a custom Python globber to list all source files.
source_files = run_command('python', localappdata_path + '\\amca\\snakes\\globber.py', './', '*.cpp', '*.cxx', '*.cc', '*.c', check : true).stdout().strip().split('\n')

# Include directories
if fs.is_dir('./include/')
  headers = include_directories('./include/') 
elif fs.is_dir('./src/include/')
  headers = include_directories('./src/include/') 
else
  headers = []
endif

executable(output_name,
  [source_files],
  dependencies : dependencies,
  include_directories : headers,
  cpp_args : cpp_compiler_args,
  c_args : c_compiler_args,
  link_args : ['-static', '-static-libgcc', '-static-libstdc++'],
  install : true,
  install_dir : output_dir)

# Print build context
message('\033[2K\r\nsource files: \n   ', '   '.join(source_files), '\noutputs to:\n   ', output_dir + output_name, '\n')
