"""Remove verified archive files by handle on Windows."""
import ctypes
import hashlib
import msvcrt
import os
import stat
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import PureWindowsPath

_kernel = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel.CreateFileW.argtypes = (
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
)
_kernel.CreateFileW.restype = wintypes.HANDLE
_kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel.CloseHandle.restype = wintypes.BOOL
for _function in (_kernel.GetFileInformationByHandleEx, _kernel.SetFileInformationByHandle):
    _function.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _function.restype = wintypes.BOOL

_INVALID_HANDLE = ctypes.c_void_p(-1).value
_OPEN_EXISTING = 3
_NO_REPARSE = 0x00200000
_DIRECTORY_HANDLE = 0x02000000
_READ_ATTRIBUTES = 0x80
_GENERIC_READ = 0x80000000
_DELETE = 0x10000
_SHARE_READ = 1
_SHARE_WRITE = 2
_FILE_DISPOSITION_INFO = 4
_FILE_ATTRIBUTE_TAG_INFO = 9


def _open_entry(path, access, sharing, *, directory):
    flags = _NO_REPARSE | (_DIRECTORY_HANDLE if directory else 0)
    handle = _kernel.CreateFileW(str(path), access, sharing, None, _OPEN_EXISTING, flags, None)
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    attributes = (wintypes.DWORD * 2)()
    try:
        if not _kernel.GetFileInformationByHandleEx(
            handle, _FILE_ATTRIBUTE_TAG_INFO, attributes, ctypes.sizeof(attributes)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if attributes[0] & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError('Archive entry is a reparse point')
        if bool(attributes[0] & stat.FILE_ATTRIBUTE_DIRECTORY) != directory:
            raise OSError('Unexpected archive entry type')
    except BaseException:
        _kernel.CloseHandle(handle)
        raise
    return handle


@contextmanager
def _hold_directory(path):
    # Allow normal directory access, but prevent renames while resolving and
    # deleting the child's file handle.
    handle = _open_entry(path, _READ_ATTRIBUTES, _SHARE_READ | _SHARE_WRITE, directory=True)
    try:
        yield
    finally:
        _kernel.CloseHandle(handle)


def remove_managed_file(root, folder, name, expected_sha):
    if (PureWindowsPath(name).is_reserved() or name.endswith(('.', ' '))
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)):
        return False
    directory = root / folder
    with _hold_directory(root), _hold_directory(directory):
        handle = _open_entry(directory / name, _GENERIC_READ | _DELETE, _SHARE_READ, directory=False)
        try:
            file_descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except OSError:
            _kernel.CloseHandle(handle)
            raise
        with os.fdopen(file_descriptor, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return False
            if hashlib.file_digest(source, 'sha256').hexdigest() != expected_sha:
                return False
            # FILE_DISPOSITION_INFO contains one BOOLEAN. Closing the same
            # verified handle performs the deletion without resolving a path again.
            delete = ctypes.c_ubyte(1)
            if not _kernel.SetFileInformationByHandle(
                handle, _FILE_DISPOSITION_INFO, ctypes.byref(delete), ctypes.sizeof(delete)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
    return True
