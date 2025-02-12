/////////////////////////////////////
/// This will be used as acma finder
/// This should be added to path, as per every project having its own amca
///   this is for possible custiom comfigurations

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <ostream>
#include <string_view>
#include <filesystem>
#include <thread>
#include <vector>
#include <algorithm>

namespace fs = std::filesystem;

const std::vector<fs::path> SearchDir(const auto &path, const std::string_view searchfor)
{
  std::vector<fs::path> AllPaths{};
  for (const auto &entry : fs::directory_iterator(path))
  {
    if (entry.is_directory())
    {
      const std::vector<fs::path> tmp{SearchDir(entry, searchfor)};
      AllPaths.insert(AllPaths.end(), tmp.begin(), tmp.end());
    }
    else if (entry.path().filename() == searchfor)
      AllPaths.emplace_back(entry);
  }
  return AllPaths;
}

constexpr fs::path GoBack(const fs::path &P, const int amount)
{
  auto R{P};
  for (int i{0}; i < amount; ++i) { R = R.parent_path(); }
  return R;
}

const auto DeepSearch(fs::path ExecPath, const std::string_view searchfor, const int depth)
{
  return SearchDir(GoBack(ExecPath, depth), searchfor);
}

constexpr int countequal(std::string_view a, std::string_view b)
{
  int out{0};
  const int len{static_cast<int>(a.length() < b.length() ? a.length() : b.length())};
  for (int i{0}; i < len; ++i)
  {
    if (a[i] == b[i])
      ++out;
    else
      break;
  }
  return out;
}

constexpr int get_depth(const fs::path &p)
{
  return std::distance(p.begin(), p.end());
}

const fs::path FindOptimal(const std::vector<fs::path> &AllPaths, const fs::path &execution_path)
{
  if (AllPaths.empty()) { return {}; }
  int execution_path_length = execution_path.string().length();
  int execution_path_depth = get_depth(execution_path) + 1; // +1 to compensate for //amca.py
  //
  std::vector<fs::path> sortedPaths{AllPaths};
  std::sort(sortedPaths.begin(), sortedPaths.end(),
            [execution_path, execution_path_depth, execution_path_length](const fs::path &A, const fs::path &B) {
              const int A_eqlen{countequal(A.string(), execution_path.string())};
              const int A_filedepth{get_depth(A)};
              const int B_eqlen{countequal(B.string(), execution_path.string())};
              const int B_filedepth{get_depth(B)};

              // Priority 1: Check if both paths match the execution path length and depth condition
              bool A_priority1 = (A_eqlen == execution_path_length) && (A_filedepth - execution_path_depth < 2);
              bool B_priority1 = (B_eqlen == execution_path_length) && (B_filedepth - execution_path_depth < 2);

              if (A_priority1 && !B_priority1)
              {
                return true; // A has Priority 1, B does not
              }
              else if (!A_priority1 && B_priority1)
              {
                return false; // B has Priority 1, A does not
              }

              // Priority 2: If neither meets Prto_findiority 1, compare based on the largest eqlen
              return A_eqlen >= B_eqlen && A_filedepth < B_filedepth;
            });

  return sortedPaths[0];
}

std::atomic<bool> stopTimeCheck{false};  // Shared flag for stopping

void timecheck(const fs::path& P) {
    for (int i = 0; i < 50; ++i) { // Check 50 times with 100ms intervals (total 5s)
        if (stopTimeCheck.load()) return;  // Exit if flag is set
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (!stopTimeCheck.load()) {
        std::cout << "If the searching process is taking too long, make sure [-ms amount] is not too deep!\n"
                  << "Search started in: " << P << std::endl;
    }
}

int main(int argc, char *argv[])
{
  // file that is searched for
  constexpr std::string_view to_find{"amca.py"};
  // Execution command
  constexpr std::string_view execution_command{"python "};

  fs::path execution_path{fs::current_path()};

  // Getting searchDepth based on -ms argument (-ms is in amca too)
  int searchDepth{4};
  auto found = std::find(argv, argv + argc, std::string_view("-ms"));
  if (found != argv + argc && found + 1 < argv + argc) { searchDepth = std::atoi(*(found + 1)); }
  if (searchDepth < 0)
  {
    std::cout << "Please enter a valid integer >= 0";
    return 1;
  }

  std::string command{execution_command};

  std::thread timechecker([&]() { timecheck(GoBack(execution_path, searchDepth)); });
  auto BestPathToFile{(FindOptimal(DeepSearch(execution_path, to_find, searchDepth), execution_path).string())};
  stopTimeCheck.store(true);
  if (timechecker.joinable()) timechecker.join();

  if (BestPathToFile.empty())
  {
    std::cout << "No " << to_find << " was found. Search started in:\n" << GoBack(execution_path, searchDepth);
    return 1;
  }

  command.append(FindOptimal(DeepSearch(execution_path, to_find, searchDepth), execution_path).string());
  for (int i{1}; i < argc; ++i)
  {
    command.append(" ");
    command.append(argv[i]);
  }

  return std::system(command.c_str());
}
