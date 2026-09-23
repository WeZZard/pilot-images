#!/usr/bin/env python3
"""Inspect installed BlackHole HAL bundle and CoreAudio enumeration without audio I/O."""
import json
from pathlib import Path
import plistlib
import subprocess


def validate_device_tree(tree):
    matches=[]
    def visit(value):
        if isinstance(value,dict):
            if value.get('_name')=='BlackHole 2ch': matches.append(value)
            for item in value.values(): visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(tree)
    if len(matches)!=1:raise ValueError('BlackHole 2ch must be uniquely discoverable in CoreAudio')
    device=matches[0]
    for key in ('coreaudio_device_input','coreaudio_device_output'):
        if str(device.get(key))!='2':raise ValueError('BlackHole channel count not verified: '+key)
    return device


def main():
    root=Path('/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver')
    with (root/'Contents/Info.plist').open('rb') as f:info=plistlib.load(f)
    executable=info.get('CFBundleExecutable')
    if not isinstance(executable,str) or '/' in executable or not (root/'Contents/MacOS'/executable).is_file():raise ValueError('BlackHole HAL executable missing')
    version=info.get('CFBundleShortVersionString') or info.get('CFBundleVersion')
    if not version:raise ValueError('BlackHole version missing')
    result=subprocess.run(['/usr/sbin/system_profiler','SPAudioDataType','-json'],capture_output=True,text=True,timeout=20,check=True)
    device=validate_device_tree(json.loads(result.stdout))
    print(json.dumps({'status':'pass','bundleVersion':version,'device':device,'scope':'HAL installation and CoreAudio discovery; no audio stream or loopback fidelity test'}))

if __name__=='__main__':
    main()
