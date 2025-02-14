#include "src/tmp.hpp"
#include <filesystem>
#include <iostream>

int main(int argc, char *argv[]) {
  std::cout << "I am being run from: " << std::filesystem::current_path() << "\n";

  // this isnt
  print("Argv: ");
  for (int i{1}; i < argc; ++i) {
    print(argv[i]);
  }
  return 0;
}