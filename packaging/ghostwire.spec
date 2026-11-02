# -*- mode: python ; coding: utf-8 -*-
# Portable PyInstaller spec. Build from repo root:  pyinstaller packaging/ghostwire.spec
import os, sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
datas = [(os.path.join(ROOT, 'theme'), 'theme')]
binaries = []
hiddenimports = ['wx._xml', 'wx.adv', 'wx.html', 'wx.richtext']
datas += collect_data_files('certifi')
hiddenimports += collect_submodules('tomli')
for pkg in ('gooey', 'maigret', 'sherlock_project', 'instaloader', 'socid_extractor'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, 'ghostwire.py')],
    pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'scipy', 'jedi', 'IPython',
              'matplotlib', 'tkinter', 'notebook', 'pytest'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ghostwire',
          debug=False, strip=False, upx=False, console=(sys.platform != 'win32'),
          icon=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ghostwire')

if sys.platform == 'darwin':
    app = BUNDLE(coll, name='GHOSTWIRE.app', bundle_identifier='io.github.metalmike17.ghostwire')
