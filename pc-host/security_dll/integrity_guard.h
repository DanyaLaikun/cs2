/*
 * integrity_guard.h
 *
 * Public API for integrity_guard.dll — Windows security module for the
 * CS2 telemetry host.  Provides:
 *
 *   Registry access  — reads REG_DWORD values with KEY_READ only
 *   Token privileges — queries the current process token
 *   Integrity level  — reads the mandatory-label SID
 *   FNV-1a hashing   — 64-bit hash of arbitrary byte ranges
 *   Byte verification — compare a memory region against a stored hash
 *   Out-of-process   — spawn a child python.exe and capture stdout
 *
 * Status codes (returned by most functions):
 *   IG_OK            0  — success
 *   IG_ERR_NOT_FOUND 1  — registry key / value absent
 *   IG_ERR_ACCESS    2  — access denied
 *   IG_ERR_MISMATCH  3  — hash mismatch
 *   IG_ERR_PARAM     4  — bad parameter (NULL pointer, out-of-range)
 *   IG_ERR_SYSTEM    5  — Windows API failure
 *
 * Root-key indices for ig_reg_read_dword:
 *   IG_HKLM 0   IG_HKCU 1   IG_HKCR 2   IG_HKU 3
 */

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define IG_OK            0
#define IG_ERR_NOT_FOUND 1
#define IG_ERR_ACCESS    2
#define IG_ERR_MISMATCH  3
#define IG_ERR_PARAM     4
#define IG_ERR_SYSTEM    5

#define IG_HKLM 0
#define IG_HKCU 1
#define IG_HKCR 2
#define IG_HKU  3

#ifdef INTEGRITY_GUARD_EXPORTS
#  define IG_API __declspec(dllexport)
#else
#  define IG_API __declspec(dllimport)
#endif

/* Version string, e.g. "1.0.0" */
IG_API const char* ig_version(void);

/*
 * FNV-1a 64-bit hash of [data, data+size).
 * Returns the offset basis (14695981039346656037) for size==0.
 */
IG_API uint64_t ig_hash_fnv64(const void* data, size_t size);

/*
 * Verify that FNV-1a(data, size) == expected_hash.
 * Returns IG_OK on match, IG_ERR_MISMATCH on mismatch, IG_ERR_PARAM if data is NULL.
 */
IG_API int32_t ig_verify_bytes(const void* data, size_t size, uint64_t expected_hash);

/*
 * Read a REG_DWORD from HKLM/HKCU/HKCR/HKU using KEY_READ only.
 * root_key: IG_HKLM=0, IG_HKCU=1, IG_HKCR=2, IG_HKU=3.
 * Writes the DWORD value to *out on success.
 */
IG_API int32_t ig_reg_read_dword(
    uint32_t        root_key,
    const wchar_t*  subkey,
    const wchar_t*  value_name,
    uint32_t*       out
);

/*
 * Query whether privilege_name (e.g. L"SeDebugPrivilege") is in the current
 * process token and whether it is enabled.
 * Writes to *out_state: 0=absent, 1=present-but-disabled, 2=enabled.
 */
IG_API int32_t ig_query_privilege(
    const wchar_t*  privilege_name,
    uint32_t*       out_state
);

/*
 * Get the mandatory integrity level of the current process.
 * Writes the raw SID sub-authority to *out_level:
 *   0x1000 = Low, 0x2000 = Medium, 0x3000 = High, 0x4000 = System.
 */
IG_API int32_t ig_get_integrity_level(uint32_t* out_level);

/*
 * Spawn python_exe script_path in a new process, capture stdout into
 * json_buf (NUL-terminated, at most json_size-1 chars).
 * Writes the child process exit code to *exit_code_out (may be NULL).
 * Waits up to 15 seconds for the child to finish.
 */
IG_API int32_t ig_run_outofprocess_audit(
    const wchar_t*  python_exe,
    const wchar_t*  script_path,
    char*           json_buf,
    uint32_t        json_size,
    uint32_t*       exit_code_out
);

#ifdef __cplusplus
} /* extern "C" */
#endif
