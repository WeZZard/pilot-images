#!/usr/bin/env python3
"""Query bundled Mesa EGL without a window, display server, or monitor service."""
import ctypes
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path('/snap/mesa-2404/current')
TRIPLES = {'aarch64': 'aarch64-linux-gnu', 'x86_64': 'x86_64-linux-gnu'}


def main():
    try:
        lib = ROOT / 'usr/lib' / TRIPLES[platform.machine()]
        if os.environ.get('PILOT_MESA_INFO_CHILD') != '1':
            env = dict(os.environ, PILOT_MESA_INFO_CHILD='1',
                       LD_LIBRARY_PATH=str(lib), LIBGL_DRIVERS_PATH=str(lib / 'dri'),
                       EGL_PLATFORM='surfaceless', LIBGL_ALWAYS_SOFTWARE='1',
                       MESA_SHADER_CACHE_DISABLE='true',
                       __EGL_VENDOR_LIBRARY_FILENAMES=str(ROOT / 'usr/share/glvnd/egl_vendor.d/50_mesa.json'))
            # The manifest embeds this same source so no checkout path is required.
            source = os.environ.get('PILOT_MESA_INFO_SOURCE')
            if source is None:
                source = Path(__file__).read_text()
            env['PILOT_MESA_INFO_SOURCE'] = source
            run = subprocess.run([sys.executable, '-I', '-c', source], env=env,
                                 capture_output=True, text=True, timeout=15)
            print(run.stdout, end='')
            if run.stderr:
                print(run.stderr, file=sys.stderr, end='')
            return run.returncode
        egl = ctypes.CDLL(str(lib / 'libEGL.so.1'))
        egl.eglGetDisplay.argtypes = [ctypes.c_void_p]
        egl.eglGetDisplay.restype = ctypes.c_void_p
        egl.eglInitialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        egl.eglInitialize.restype = ctypes.c_uint
        egl.eglQueryString.argtypes = [ctypes.c_void_p, ctypes.c_int]
        egl.eglQueryString.restype = ctypes.c_char_p
        egl.eglTerminate.argtypes = [ctypes.c_void_p]
        display = egl.eglGetDisplay(None)
        major, minor = ctypes.c_int(), ctypes.c_int()
        if not display or not egl.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)):
            raise RuntimeError('bundled Mesa surfaceless EGL initialization failed')
        try:
            vendor = (egl.eglQueryString(display, 0x3053) or b'').decode()
            version = (egl.eglQueryString(display, 0x3054) or b'').decode()
            maps = Path('/proc/self/maps').read_text()
            loaded = sorted({line.split()[-1] for line in maps.splitlines()
                             if '/snap/mesa-2404/' in line})
            resolved = str(ROOT.resolve()) + '/'
            if 'Mesa' not in vendor or not version or not any(
                    p.startswith(resolved) and '/libEGL_mesa.so.' in p for p in loaded):
                raise RuntimeError('EGL vendor/version or bundled Mesa linkage was not proved')
            print(json.dumps(dict(status='pass', check='bundled-mesa-egl-info',
                                  vendor=vendor, version=version, loadedLibraries=loaded,
                                  scope='surfaceless software EGL; not hardware acceleration')))
        finally:
            egl.eglTerminate(display)
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(status='fail', check='bundled-mesa-egl-info', error=str(error))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
