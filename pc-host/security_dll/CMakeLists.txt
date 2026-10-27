cmake_minimum_required(VERSION 3.20)
project(integrity_guard VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(integrity_guard SHARED
    integrity_guard.cpp
    integrity_guard.h
)

target_compile_definitions(integrity_guard PRIVATE
    INTEGRITY_GUARD_EXPORTS
    WIN32_LEAN_AND_MEAN
    STRICT
    UNICODE
    _UNICODE
    _CRT_SECURE_NO_WARNINGS
)

target_link_libraries(integrity_guard PRIVATE
    Advapi32
    Kernel32
)

# Place .dll in build/ (MSVC puts it in build/Release or build/Debug)
set_target_properties(integrity_guard PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)

# Post-build: copy to telemetry_host/security/ so Python can find it
add_custom_command(TARGET integrity_guard POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        $<TARGET_FILE:integrity_guard>
        "${CMAKE_CURRENT_SOURCE_DIR}/../telemetry_host/security/integrity_guard.dll"
    COMMENT "Copying integrity_guard.dll -> telemetry_host/security/"
)
