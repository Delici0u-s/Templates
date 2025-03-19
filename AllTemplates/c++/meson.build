project('compiler2', ['cpp', 'c'],
  version : '0.1',
  default_options : ['warning_level=3', 'cpp_std=c++23', 'buildtype=debug', 'optimization=2', 'debug=true'])
# To build in release mode, run: meson setup build --buildtype=release

# DO NOT change variable names; AMCA relies on these.
main_file = 'src/main.cpp'
output_name = 'a'
output_dir = '../../compiled'  # Relative to meson.build location
build_dir_where = 'MesonBuildStuff/build'  # Relative to meson.build location

# Compiler arguments
cpp_compiler_args = [   
  '-Og',
  '-g',
  '-Wall', 
  '-Wextra',
  '-pedantic',
  '-O2',
  '-lstdc++exp',
]
c_compiler_args = []

# Normalize paths
main_file = main_file.replace('/', '\\')
output_dir = output_dir.replace('/', '\\')
if not output_dir.startswith('\\')
  output_dir = '\\' + output_dir
endif
if not output_dir.endswith('\\') and output_dir != ''
  output_dir = ''.join([output_dir, '\\'])
endif
output_dir = meson.project_build_root() + output_dir

# Import subprojects/options
cmake = import('cmake')
fs = import('fs')
opt_var_mimalloc = cmake.subproject_options()
opt_var_mimalloc.add_cmake_defines({'MI_SECURE': false})
opt_var_mimalloc.add_cmake_defines({'MI_BUILD_TESTS': false})
opt_var_mimalloc.add_cmake_defines({'MI_BUILD_SHARED': false})

# Dependencies (if any)
dependencies = []
dependencies_str = []
foreach item : dependencies_str
  dependencies += dependency(item)
endforeach

# Use a custom Python globber to list all source files.
source_files = run_command('python', 'MesonBuildStuff/globber.py', './', '*.cpp', '*.cxx', '*.cc', '*.c', check : true).stdout().strip().split('\n')

# Exclude the main file (to avoid duplicate inclusion)
source_files_no_main_file = []
foreach item : source_files
  if item != main_file
    source_files_no_main_file += item
  endif
endforeach

# Include directories
if fs.is_dir('./include/')
  headers = include_directories('./include/') 
elif fs.is_dir('./src/include/')
  headers = include_directories('./src/include/') 
else
  headers = []
endif

executable(output_name,
  [main_file, source_files_no_main_file],
  dependencies : dependencies,
  include_directories : headers,
  cpp_args : cpp_compiler_args,
  c_args : c_compiler_args,
  link_args : ['-static-libgcc', '-static-libstdc++'],
  install : true,
  install_dir : output_dir)

# Print build context
message('\033[2K\r\nsource files: \n   ', '   '.join(source_files), '\noutputs to:\n   ', output_dir + output_name, '\n')
