cmake_minimum_required(VERSION 3.16)
project(kaoss_native_android LANGUAGES CXX)

add_library(kaoss_native SHARED
  aaudio_input_engine.cpp
  audio_flinger_hook.cpp
  audio_input_engine.cpp
  dsp_transient_splitter.cpp
  kaoss_audio_processor.cpp
  kaoss_quad_engine.cpp
  kaoss_jni.cpp
  oboe_exclusive_stream.cpp
)
target_include_directories(kaoss_native PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
set_target_properties(kaoss_native PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES)

find_library(log-lib log)
find_library(android-lib android)
find_library(aaudio-lib aaudio)
target_link_libraries(kaoss_native PRIVATE
  ${log-lib}
  ${android-lib}
  ${aaudio-lib}
)
