/*
 * integrity_guard.cpp
 *
 * Academic security research: Windows privilege-model demonstration.
 * All operations are read-only and non-destructive:
 *   - Registry keys are opened with KEY_READ.
 *   - Process tokens are queried with TOKEN_QUERY.
 *   - Child processes are created with the same token as the parent
 *     and no elevated rights.
 */

#define INTEGRITY_GUARD_EXPORTS
#define STRICT
#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS

#include "integrity_guard.h"

#include <windows.h>
#include <winreg.h>
#include <stdio.h>
#include <string.h>

// ── DllMain ────────────────────────────────────────────────────────────────────

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved)
{
    (void)hinstDLL;
    (void)fdwReason;
    (void)lpvReserved;
    return TRUE;
}

// ── Version ────────────────────────────────────────────────────────────────────

IG_API const char* ig_version(void)
{
    return "1.0.0";
}

// ── FNV-1a 64-bit hash ─────────────────────────────────────────────────────────

IG_API uint64_t ig_hash_fnv64(const void* data, size_t size)
{
    const uint8_t* p = (const uint8_t*)data;
    uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < size; i++) {
        h ^= (uint64_t)p[i];
        h *= UINT64_C(1099511628211);
    }
    return h;
}

// ── Byte verification ──────────────────────────────────────────────────────────

IG_API int32_t ig_verify_bytes(const void* data, size_t size, uint64_t expected_hash)
{
    if (!data && size > 0)
        return IG_ERR_PARAM;
    uint64_t actual = ig_hash_fnv64(data, size);
    return (actual == expected_hash) ? IG_OK : IG_ERR_MISMATCH;
}

// ── Registry read (KEY_READ minimum privilege) ─────────────────────────────────

IG_API int32_t ig_reg_read_dword(
    uint32_t        root_key,
    const wchar_t*  subkey,
    const wchar_t*  value_name,
    uint32_t*       out)
{
    if (!subkey || !value_name || !out)
        return IG_ERR_PARAM;

    static const HKEY k_roots[4] = {
        HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER,
        HKEY_CLASSES_ROOT,  HKEY_USERS
    };
    if (root_key >= 4)
        return IG_ERR_PARAM;

    HKEY hKey = NULL;
    LONG rc = RegOpenKeyExW(k_roots[root_key], subkey, 0, KEY_READ, &hKey);

    if (rc == ERROR_FILE_NOT_FOUND || rc == ERROR_PATH_NOT_FOUND)
        return IG_ERR_NOT_FOUND;
    if (rc == ERROR_ACCESS_DENIED)
        return IG_ERR_ACCESS;
    if (rc != ERROR_SUCCESS)
        return IG_ERR_SYSTEM;

    DWORD type = 0, sz = sizeof(DWORD);
    DWORD val  = 0;
    rc = RegQueryValueExW(hKey, value_name, NULL, &type, (LPBYTE)&val, &sz);
    RegCloseKey(hKey);

    if (rc == ERROR_FILE_NOT_FOUND)
        return IG_ERR_NOT_FOUND;
    if (rc != ERROR_SUCCESS)
        return IG_ERR_SYSTEM;
    if (type != REG_DWORD)
        return IG_ERR_SYSTEM;

    *out = (uint32_t)val;
    return IG_OK;
}

// ── Token privilege query ──────────────────────────────────────────────────────

IG_API int32_t ig_query_privilege(
    const wchar_t*  privilege_name,
    uint32_t*       out_state)
{
    if (!privilege_name || !out_state)
        return IG_ERR_PARAM;
    *out_state = 0;

    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &hToken))
        return IG_ERR_SYSTEM;

    DWORD needed = 0;
    GetTokenInformation(hToken, TokenPrivileges, NULL, 0, &needed);
    if (!needed) {
        CloseHandle(hToken);
        return IG_ERR_SYSTEM;
    }

    TOKEN_PRIVILEGES* privs = (TOKEN_PRIVILEGES*)HeapAlloc(GetProcessHeap(), 0, needed);
    if (!privs) {
        CloseHandle(hToken);
        return IG_ERR_SYSTEM;
    }

    int32_t result = IG_ERR_SYSTEM;
    if (GetTokenInformation(hToken, TokenPrivileges, privs, needed, &needed)) {
        LUID luid = {};
        if (LookupPrivilegeValueW(NULL, privilege_name, &luid)) {
            result    = IG_OK;
            *out_state = 0;
            for (DWORD i = 0; i < privs->PrivilegeCount; i++) {
                if (privs->Privileges[i].Luid.LowPart  == luid.LowPart &&
                    privs->Privileges[i].Luid.HighPart == luid.HighPart)
                {
                    *out_state = (privs->Privileges[i].Attributes & SE_PRIVILEGE_ENABLED) ? 2 : 1;
                    break;
                }
            }
        }
    }

    HeapFree(GetProcessHeap(), 0, privs);
    CloseHandle(hToken);
    return result;
}

// ── Process integrity level ────────────────────────────────────────────────────

IG_API int32_t ig_get_integrity_level(uint32_t* out_level)
{
    if (!out_level)
        return IG_ERR_PARAM;
    *out_level = 0;

    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &hToken))
        return IG_ERR_SYSTEM;

    DWORD needed = 0;
    /* First call determines required buffer size */
    GetTokenInformation(hToken, TokenIntegrityLevel, NULL, 0, &needed);
    if (!needed) {
        CloseHandle(hToken);
        return IG_ERR_SYSTEM;
    }

    TOKEN_MANDATORY_LABEL* label =
        (TOKEN_MANDATORY_LABEL*)HeapAlloc(GetProcessHeap(), 0, needed);
    if (!label) {
        CloseHandle(hToken);
        return IG_ERR_SYSTEM;
    }

    int32_t result = IG_ERR_SYSTEM;
    if (GetTokenInformation(hToken, TokenIntegrityLevel, label, needed, &needed)) {
        UCHAR sub_count = *GetSidSubAuthorityCount(label->Label.Sid);
        if (sub_count > 0) {
            DWORD level = *GetSidSubAuthority(label->Label.Sid, (DWORD)(sub_count - 1));
            *out_level = level;
            result = IG_OK;
        }
    }

    HeapFree(GetProcessHeap(), 0, label);
    CloseHandle(hToken);
    return result;
}

// ── Out-of-process audit ───────────────────────────────────────────────────────

IG_API int32_t ig_run_outofprocess_audit(
    const wchar_t*  python_exe,
    const wchar_t*  script_path,
    char*           json_buf,
    uint32_t        json_size,
    uint32_t*       exit_code_out)
{
    if (!python_exe || !script_path || !json_buf || json_size == 0)
        return IG_ERR_PARAM;

    json_buf[0] = '\0';

    /* Build command line: "python_exe" "script_path"
     * Both paths are quoted to handle spaces. */
    wchar_t cmd[4096];
    _snwprintf_s(cmd, _countof(cmd), _TRUNCATE,
                 L"\"%s\" \"%s\"", python_exe, script_path);

    /* Create inheritable read/write pipe for stdout capture */
    SECURITY_ATTRIBUTES sa = {};
    sa.nLength              = sizeof(sa);
    sa.bInheritHandle       = TRUE;

    HANDLE hReadPipe = NULL, hWritePipe = NULL;
    if (!CreatePipe(&hReadPipe, &hWritePipe, &sa, 0))
        return IG_ERR_SYSTEM;

    /* The read end must NOT be inherited by the child */
    SetHandleInformation(hReadPipe, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOW si = {};
    si.cb           = sizeof(si);
    si.dwFlags      = STARTF_USESTDHANDLES;
    si.hStdInput    = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput   = hWritePipe;
    si.hStdError    = GetStdHandle(STD_ERROR_HANDLE);

    PROCESS_INFORMATION pi = {};

    BOOL created = CreateProcessW(
        NULL,     /* application name — from command line */
        cmd,      /* command line */
        NULL,     /* process security attrs */
        NULL,     /* thread security attrs */
        TRUE,     /* inherit handles */
        CREATE_NO_WINDOW,
        NULL,     /* environment */
        NULL,     /* current directory */
        &si,
        &pi
    );

    /* Close our copy of the write end; child holds the only copy now */
    CloseHandle(hWritePipe);

    if (!created) {
        CloseHandle(hReadPipe);
        return IG_ERR_SYSTEM;
    }

    /* Read stdout until EOF (child closed its end) */
    {
        char tmp[512];
        DWORD bytes_read = 0;
        DWORD total      = 0;

        while (ReadFile(hReadPipe, tmp, sizeof(tmp) - 1, &bytes_read, NULL)
               && bytes_read > 0)
        {
            if (total + bytes_read + 1 < json_size) {
                memcpy(json_buf + total, tmp, bytes_read);
                total += bytes_read;
            }
        }
        json_buf[total] = '\0';
    }
    CloseHandle(hReadPipe);

    /* Wait up to 15 s for the child */
    WaitForSingleObject(pi.hProcess, 15000);

    DWORD exit_code = (DWORD)(-1);
    GetExitCodeProcess(pi.hProcess, &exit_code);
    if (exit_code_out)
        *exit_code_out = (uint32_t)exit_code;

    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    return IG_OK;
}
