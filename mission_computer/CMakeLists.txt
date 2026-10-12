cmake_minimum_required(VERSION 3.16)
project(flight_sequencer C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

add_executable(flight_seq
    src/main.c
    src/modules/flight_sequencer.c
    platform/host_bsp.c
)

target_include_directories(flight_seq PRIVATE include config)

if(MSVC)
    target_compile_options(flight_seq PRIVATE /W4)
else()
    target_compile_options(flight_seq PRIVATE -O2 -Wall -Wextra -Wpedantic)
endif()

find_package(Threads REQUIRED)
target_link_libraries(flight_seq PRIVATE Threads::Threads)

# Portable host note: on Linux the atomics are lock-free and affinity is set
# via pthread_setaffinity_np inside platform/host_bsp.c.
