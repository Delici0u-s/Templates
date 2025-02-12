#include "src/tmp.hpp"

int main(int argc, char *argv[]) {
  for (int i{1}; i < argc; ++i) {
    print(argv[i]);
  }
  return 0;
}