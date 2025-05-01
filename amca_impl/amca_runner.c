#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

int main(int argc, char *argv[]) {
  char exePath[MAX_PATH];
  GetModuleFileNameA(NULL, exePath, MAX_PATH);

  // Remove the executable name to get the directory
  char *lastSlash = strrchr(exePath, '\\');
  if (lastSlash) {
    *lastSlash = '\0'; // Trim to directory path
  }

  // Construct relative path to the Python script
  char scriptPath[MAX_PATH];
  snprintf(scriptPath, MAX_PATH, "%s\\..\\snakes\\amca.py", exePath);

  // Start building the command
  char command[8192] = "python \"";
  strcat(command, scriptPath);
  strcat(command, "\"");

  // Append arguments
  for (int i = 1; i < argc; ++i) {
    strcat(command, " \"");
    strcat(command, argv[i]);
    strcat(command, "\"");
  }

  // Run the command
  return system(command);
}
