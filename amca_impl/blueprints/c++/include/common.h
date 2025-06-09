#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>

#define H_ASSERT(x) assert(x)
#define H_NOEXCEPT

#ifdef _MSC_VER
#define H_UNREACHABLE() __assume(false);
#else
#define H_UNREACHABLE() __builtin_unreachable();
#endif

using b8 = char;
using b0 = bool;
using u0 = void;

using i8  = std::int8_t;
using i16 = std::int16_t;
using i32 = std::int32_t;
using i64 = std::int64_t;

using u8  = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;

using f32 = float;
using f64 = double;

using usize   = std::size_t;
using uptr    = std::uintptr_t;
using ptrdiff = std::ptrdiff_t;

#define rngs_fix(x) x.begin(), x.end()

#if __cpp_constexpr >= 202207L
#define H_CONSTEXPR_STATIC static
#else
#define H_CONSTEXPR_STATIC
#endif

inline usize
npow2(usize _val) noexcept
{
  usize v = _val;
  v--;
  v |= v >> 1;
  v |= v >> 2;
  v |= v >> 4;
  v |= v >> 8;
  v |= v >> 16;
  v++;
  return v;
}
