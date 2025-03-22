#include <filesystem>
#include <iostream>

int main() {
  std::cout << "I am being run from: " << std::filesystem::current_path() << "\n";
  return 0;
}