cmake_minimum_required(VERSION 3.18)
project(reverse_stress_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# pybind11 is resolved via `python -m pybind11 --cmakedir` (see build.py), so no
# system-wide install or git submodule is required.
find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(reverse_stress_core reverse_stress_core.cpp)

if (MSVC)
    target_compile_options(reverse_stress_core PRIVATE /O2 /EHsc)
else()
    target_compile_options(reverse_stress_core PRIVATE -O3)
endif()
