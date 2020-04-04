# -*- mode: python -*-

import sys
import subprocess
from os import path

rootdir = path.abspath('..')
binscript = path.join(rootdir, 'bin', 'quango')
uidir = path.join(rootdir, 'quango', 'ui')

# Make sure to generate the version file.
subprocess.check_call([sys.executable,
                       path.join(rootdir, 'quango', 'version.py')])

a = Analysis([binscript],
             pathex=[rootdir],
             binaries=[],
             datas=[(path.join(uidir, '*.ui'), 'quango/ui'),
                    (path.join(rootdir, 'quango', 'RELEASE-VERSION'), 'quango')],
             hiddenimports=['quango.widgets'],  # imported via ui file
             hookspath=[],
             runtime_hooks=['rthook_pyqt4.py'],
             excludes=['qtconsole'],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=None)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='quango',
          debug=False,
          strip=False,
          upx=True,
          console=False)
