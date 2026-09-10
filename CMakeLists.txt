cmake_minimum_required(VERSION 3.16)
project(kaoss_ai_beatbox_studio VERSION 5.0.0 LANGUAGES CXX)

option(BUILD_UNIT_TESTS "Build native validation tests" ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(kaoss_dsp STATIC
  android/app/src/main/cpp/audio_flinger_hook.cpp
  android/app/src/main/cpp/dsp_transient_splitter.cpp
  android/app/src/main/cpp/kaoss_quad_engine.cpp
  android/app/src/main/cpp/oboe_exclusive_stream.cpp
)
target_include_directories(kaoss_dsp PUBLIC android/app/src/main/cpp)

target_compile_options(kaoss_dsp PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang>:-Wall -Wextra -Wpedantic -Werror>
)

if(BUILD_UNIT_TESTS)
  enable_testing()
  foreach(test_name IN ITEMS audio_latency_e2e_test brickwall_limiter_test transient_splitter_test)
    add_executable(${test_name} tests/${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE kaoss_dsp)
    add_test(NAME ${test_name} COMMAND ${test_name})
  endforeach()
endif()
