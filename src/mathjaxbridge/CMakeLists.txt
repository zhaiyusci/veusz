cmake_minimum_required(VERSION 3.16)

project(veusz_mathjaxbridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# QuickJS 静态库路径 (由调用方传入或自动查找)
set(QUICKJS_LIB "" CACHE FILEPATH "Path to built qjs.lib / libquickjs.a")
set(QUICKJS_SRC "" CACHE PATH "Path to quickjs-ng source tree (for headers)")

if(NOT QUICKJS_LIB)
  message(FATAL_ERROR "QUICKJS_LIB is required (path to qjs.lib / libquickjs.a)")
endif()
if(NOT QUICKJS_SRC)
  message(FATAL_ERROR "QUICKJS_SRC is required (path to quickjs-ng source tree)")
endif()

add_library(mathjaxbridge SHARED mathjax_bridge.cpp)
target_include_directories(mathjaxbridge PRIVATE "${QUICKJS_SRC}")
target_link_libraries(mathjaxbridge PRIVATE "${QUICKJS_LIB}")
