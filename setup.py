#!/usr/bin/env python3

#    Copyright (C) 2008 Jeremy S. Sanders
#    Email: Jeremy Sanders <jeremy@jeremysanders.net>
#
#    This file is part of Veusz.
#
#    Veusz is free software: you can redistribute it and/or modify it
#    under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 2 of the License, or
#    (at your option) any later version.
#
#    Veusz is distributed in the hope that it will be useful, but
#    WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#    General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Veusz. If not, see <https://www.gnu.org/licenses/>.
#
##############################################################################

"""
Veusz setuputils script
see the file INSTALL.md for details on how to install Veusz
"""

import glob
import os
from pathlib import Path
import subprocess
import numpy

from setuptools import setup, Extension
from setuptools.command.install import install as orig_install

# code taken from distutils for installing data that was removed in
# setuptools
from install_data import install_data

# setuptools extension for building SIP/PyQt modules
from pyqt_setuptools import sip_build_ext

ROOT = Path(__file__).resolve().parent


def _read_cache_value(cache_path, name):
    if not cache_path.exists():
        return None
    prefix = f"{name}:"
    alt_prefix = f"{name}="
    for line in cache_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
        if line.startswith(alt_prefix):
            return line.split("=", 1)[1].strip()
    return None


def _guess_qt6_dir():
    qt6_dir = os.environ.get("Qt6_DIR")
    if qt6_dir:
        return qt6_dir

    for cache_path in (
        ROOT / "build-microtex" / "CMakeCache.txt",
        ROOT / "build-microtexbridge" / "CMakeCache.txt",
    ):
        qt6_dir = _read_cache_value(cache_path, "Qt6_DIR")
        if qt6_dir:
            return qt6_dir

    try:
        import PyQt6
    except ImportError:
        return None

    candidate = Path(PyQt6.__file__).resolve().parent / "Qt6" / "lib" / "cmake" / "Qt6"
    if candidate.exists():
        return str(candidate)
    return None


def _run_checked(cmd):
    print("[setup.py] running:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def build_bundled_microtex():
    if os.environ.get("VEUSZ_SKIP_MICROTEX_BUILD"):
        print("[setup.py] skipping bundled MicroTeX build because VEUSZ_SKIP_MICROTEX_BUILD is set", flush=True)
        return

    microtex_src = ROOT / "third_party" / "MicroTeX"
    if not (microtex_src / "CMakeLists.txt").exists():
        raise RuntimeError(
            "Bundled MicroTeX source is missing. Run "
            "'git submodule update --init --recursive' before building Veusz."
        )

    qt6_dir = _guess_qt6_dir()

    microtex_build = ROOT / "build-microtex"
    microtex_configure = [
        "cmake",
        "-S", str(microtex_src),
        "-B", str(microtex_build),
        "-DQT=ON",
        "-DBUILD_EXAMPLE=OFF",
    ]
    if qt6_dir:
        microtex_configure.append(f"-DQt6_DIR={qt6_dir}")

    _run_checked(microtex_configure)
    _run_checked(["cmake", "--build", str(microtex_build), "-j2"])

    microtex_lib = microtex_build / "libLaTeX.a"
    if not microtex_lib.exists():
        raise RuntimeError(f"Bundled MicroTeX build did not produce {microtex_lib}")

    bridge_build = ROOT / "build-microtexbridge"
    bridge_configure = [
        "cmake",
        "-S", str(ROOT / "src" / "microtexbridge"),
        "-B", str(bridge_build),
        f"-DMICROTEX_SRC={microtex_src}",
        f"-DMICROTEX_LIB={microtex_lib}",
    ]
    if qt6_dir:
        bridge_configure.append(f"-DQt6_DIR={qt6_dir}")

    _run_checked(bridge_configure)
    _run_checked(["cmake", "--build", str(bridge_build), "-j2"])


class veusz_build_ext(sip_build_ext):
    def run(self):
        build_bundled_microtex()
        super().run()


class install(orig_install):
    user_options = orig_install.user_options + [
        # tell veusz where to install its data files
        (
            'veusz-resource-dir=', None,
            'override veusz resource directory location'
        ),
        (
            'disable-install-examples', None,
            'do not install examples files'
        ),
    ]
    boolean_options = orig_install.boolean_options + [
        'disable-install-examples',
    ]

    def initialize_options(self):
        orig_install.initialize_options(self)
        self.veusz_resource_dir = None
        self.disable_install_examples = False

# Pete Shinner's distutils data file fix... from distutils-sig
#  data installer with improved intelligence over distutils
#  data files are copied into the project directory instead
#  of willy-nilly
class smart_install_data(install_data):
    def run(self):
        install_cmd = self.get_finalized_command('install')
        if install_cmd.veusz_resource_dir:
            # override location with veusz-resource-dir option
            self.install_dir = install_cmd.veusz_resource_dir
        else:
            # change self.install_dir to the library dir + veusz by default
            self.install_dir = os.path.join(install_cmd.install_lib, 'veusz')

        # disable examples install if requested
        if install_cmd.disable_install_examples:
            self.data_files = [
                f for f in self.data_files if f[0][-8:] != 'examples'
            ]

        self.data_files = list(self.data_files) + microtexRuntimeData()

        return install_data.run(self)

def findData(dirname, extns):
    """Return tuple for directory name and list of file extensions for data."""
    files = []
    for extn in extns:
        files += glob.glob(os.path.join(dirname, '*.'+extn))
    files.sort()
    return (dirname, files)


def findDataTree(srcroot, destroot):
    """Return data_files entries for an entire directory tree."""
    entries = []
    srcroot = Path(srcroot)
    if not srcroot.exists():
        return entries

    for dirpath, _, filenames in os.walk(srcroot):
        files = [os.path.join(dirpath, name) for name in sorted(filenames)]
        if not files:
            continue
        relpath = Path(dirpath).relative_to(srcroot)
        if str(relpath) == '.':
            destdir = destroot
        else:
            destdir = os.path.join(destroot, str(relpath))
        entries.append((destdir, files))
    return entries


def microtexRuntimeData():
    """Return packaged runtime assets for installed MicroTeX support."""
    data = []

    resroot = ROOT / "third_party" / "MicroTeX" / "res"
    data.extend(findDataTree(resroot, os.path.join("microtex", "res")))

    bridge = ROOT / "build-microtexbridge" / "libmicrotexbridge.so"
    if bridge.exists():
        data.append((os.path.join("microtex"), [str(bridge)]))

    return data

setup(
    data_files = [
        ('', ['VERSION', 'AUTHORS', 'ChangeLog', 'COPYING']),
        findData('ui', ('ui',)),
        findData('icons', ('png', 'svg')),
        findData('examples', ('vsz', 'py', 'csv', 'dat')),
    ],

    ext_modules = [
        # threed support
        Extension(
            'veusz.helpers.threed',
            [
                'src/threed/camera.cpp',
                'src/threed/mmaths.cpp',
                'src/threed/objects.cpp',
                'src/threed/scene.cpp',
                'src/threed/fragment.cpp',
                'src/threed/numpy_helpers.cpp',
                'src/threed/clipcontainer.cpp',
                'src/threed/bsp.cpp',
                'src/threed/twod.cpp',
                'src/threed/threed.sip'
            ],
            language="c++",
            include_dirs=[
                'src/threed', numpy.get_include()
            ],
        ),

        # mathml widget
        Extension(
            'veusz.helpers.qtmml',
            [
                'src/qtmml/qtmmlwidget.cpp',
                'src/qtmml/qtmml.sip'
            ],
            language="c++",
            include_dirs=['src/qtmml'],
        ),

        # device to record paint commands
        Extension(
            'veusz.helpers.recordpaint',
            [
                'src/recordpaint/recordpaintdevice.cpp',
                'src/recordpaint/recordpaintengine.cpp',
                'src/recordpaint/recordpaint.sip'
            ],
            language="c++",
            include_dirs=['src/recordpaint'],
        ),

        # contour plotting library
        Extension(
            'veusz.helpers._nc_cntr',
            [
                'src/nc_cntr/_nc_cntr.c'
            ],
            include_dirs=[numpy.get_include()]
        ),

        # qt helper module
        Extension(
            'veusz.helpers.qtloops',
            [
                'src/qtloops/qtloops.cpp',
                'src/qtloops/qtloops_helpers.cpp',
                'src/qtloops/polygonclip.cpp',
                'src/qtloops/polylineclip.cpp',
                'src/qtloops/beziers.cpp',
                'src/qtloops/beziers_qtwrap.cpp',
                'src/qtloops/numpyfuncs.cpp',
                'src/qtloops/qtloops.sip'
            ],
            language="c++",
            include_dirs=[
                'src/qtloops',
                numpy.get_include()
            ],
        ),
    ],

    # new command options
    cmdclass = {
        'build_ext': veusz_build_ext,
        'install_data': smart_install_data,
        'install': install
    },
)
