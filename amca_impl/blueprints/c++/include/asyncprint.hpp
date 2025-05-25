#pragma once
#include <atomic>
#include <cstddef>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string_view>
#include <thread>
#include <chrono>
#include <condition_variable>

// Selector: pick 2-arg if you passed 2 arguments, else pick 1-arg
#define GET_ASSERT_MACRO(_1, _2, NAME, ...) NAME

#define d_assert_1(_expr)                                                                                                                                                \
  (void)((!!(_expr)) || ([] {                                                                    \
     dcon::printfln(                                                                              \
       "\n\nassertion failed: '{}'\n            file: '{}:{}'",                                   \
       #_expr, __FILE__, __LINE__);                                                               \
     std::exit(1);                                                                                \
     return true;                                                                                 \
  }()))

#define d_assert_2(_expr, message)                                                                                                                                       \
  (void)((!!(_expr)) || ([] {                                                                    \
     dcon::printfln(                                                                              \
       "\n\nassertion failed: '{}'\n         message: '{}'\n            file: '{}:{}'",           \
       #_expr, message, __FILE__, __LINE__);                                                      \
     std::exit(1);                                                                                \
     return true;                                                                                 \
  }()))

// Public interface: expands to GET_ASSERT_MACRO(arg1, arg2, d_assert_2, d_assert_1)(…)
#define d_assert(...) GET_ASSERT_MACRO(__VA_ARGS__, d_assert_2, d_assert_1)(__VA_ARGS__)

namespace dcon
{
namespace internal
{
// Internal "flusher" type for triggering an immediate flush.
class flusher
{
};
class endliner
{
};

// Internal async printer class.
class async_printer
{
  std::stringstream m_buffer{};
  std::mutex m_buffer_mutex{};
  std::atomic<bool> m_print{true};
  std::atomic<bool> m_running{true}; // Ensures printing on exit.
  size_t m_interval_ms;
  std::thread m_thread; // Store the thread to join it later.

  // Condition variable and mutex for optional flush synchronization.
  std::condition_variable m_cv;
  std::mutex m_cv_mutex;

  // Background thread function.
  void
  StartPrinting()
  {
    while (m_running.load())
    {
      if (m_print.load())
      {
        FlushBuffer();
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(m_interval_ms));
    }
    // On exit, flush any remaining content.
    FlushBuffer();
  }

  // Flushes the buffer to std::cout.
  void
  FlushBuffer()
  {
    std::unique_lock<std::mutex> lock(m_buffer_mutex);
    if (!m_buffer.str().empty())
    {
      // Extract current content.
      std::string data = m_buffer.str();
      m_buffer.str("");
      m_buffer.clear();
      // Release the buffer lock before writing to avoid blocking other insertions.
      lock.unlock();

      std::cout << data;
      std::cout.flush();

      // Signal any thread waiting for a flush.
      std::lock_guard<std::mutex> cvLock(m_cv_mutex);
      m_cv.notify_all();
    }
  }

public:
  explicit async_printer(size_t interval_ms = 100) : m_interval_ms(interval_ms), m_thread(&async_printer::StartPrinting, this) {} // Start joinable thread.

  ~async_printer()
  {
    m_running.store(false);
    if (m_thread.joinable())
    {
      m_thread.join(); // Ensure the thread has finished.
    }
  }

  void
  haltPrint()
  {
    m_print.store(false);
  }
  void
  continuePrint()
  {
    m_print.store(true);
  }
  void
  changeInterval(size_t milliseconds)
  {
    m_interval_ms = milliseconds;
  }

  // Templated friend operator<< for any type.
  template <typename T>
  friend async_printer &
  operator<<(async_printer &os, const T &other)
  {
    std::lock_guard<std::mutex> lock(os.m_buffer_mutex);
    os.m_buffer << other;
    return os;
  }

  // Overload for the flusher symbol.
  // This version waits until the buffer written up to this point is flushed.
  friend async_printer &
  operator<<(async_printer &os, const flusher)
  {
    std::string data;
    {
      std::unique_lock<std::mutex> lock(os.m_buffer_mutex);
      if (!os.m_buffer.str().empty())
      {
        data = os.m_buffer.str();
        os.m_buffer.str("");
        os.m_buffer.clear();
      }
    }
    if (!data.empty())
    {
      std::cout << data;
      std::cout.flush();
      // Notify that flush is complete.
      std::lock_guard<std::mutex> cvLock(os.m_cv_mutex);
      os.m_cv.notify_all();
    }
    return os;
  }
  friend async_printer &
  operator<<(async_printer &os, const endliner)
  {
    return os << '\n' << flusher();
  }
};

} // namespace internal

// Publicly expose only the objects, not the implementation types.
[[maybe_unused]] inline internal::async_printer cout{100};
[[maybe_unused]] inline constexpr internal::flusher flush{};
[[maybe_unused]] inline constexpr internal::endliner endl{};

// inline void
// print(const std::string_view f)
// {
//   cout << f;
// }

inline void
print(auto &&f)
{
  cout << f;
}

// inline void
// puts(const char *str)
// {
//   cout << str << "\n";
// }

inline void
puts(auto &&str)
{
  cout << str << "\n";
}

// inline void
// println(const std::string_view f)
// {
//   cout << f << '\n';
// }

inline void
println(auto &&f)
{
  cout << f << '\n';
}

template <std::size_t TSize>
struct format_str
{
  consteval format_str(char (&arr)[TSize]) : data(std::to_array(arr)) {}
  const std::array<char, TSize> data;
};

/*inline void printf(const std::string_view format_input, auto&&... args) {cout << std::runtime_format(format_input, args...);}*/
/**/
/*template <format_str fmt, typename... Args>*/
/*inline void printf(Args&&... args) {*/
/*    // The conversion operator converts our format_str to std::string_view.*/
/*    cout << std::format(static_cast<std::string_view>(fmt), std::forward<Args>(args)...);*/
/*}*/
template <typename... Args>
void
printf(std::format_string<Args...> fmt, Args &&...args)
{
  cout << std::format(fmt, std::forward<Args>(args)...);
}

template <typename... Args>
void
printfln(std::format_string<Args...> fmt, Args &&...args)
{
  cout << std::format(fmt, std::forward<Args>(args)...) << '\n';
}

} // namespace dcon
