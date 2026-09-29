# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

# pywinauto + comtypes 含动态导入与二进制依赖，必须整体收集
pw_datas, pw_binaries, pw_hidden = collect_all('pywinauto')
ct_datas, ct_binaries, ct_hidden = collect_all('comtypes')

# 注意：phone_bridge/ 已开发未接线（docs/修复任务列表-2026-09-29.md 任务 16），
# 接线后需补打包项（hiddenimports/datas），并核对 pystray/segno 等依赖的收集。

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=pw_binaries + ct_binaries,
    datas=pw_datas + ct_datas,
    hiddenimports=['agent_vision', 'plugin_system', 'skill_system',
                   'six', 'win32api', 'win32gui', 'win32process',
                   'win32con', 'pywintypes'] + pw_hidden + ct_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DesktopAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 未签名 exe + UPX 壳是杀软误报经典组合，体积换查杀通过率
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
