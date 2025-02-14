#include "src/tmp.hpp"

int main(int argc, char *argv[]) {
  print("Argv: ");
  for (int i{1}; i < argc; ++i) {
    print(argv[i]);
  }
  return 0;
}