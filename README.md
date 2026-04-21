# [Veusz 4.2.1](https://veusz.github.io/)

Veusz is a scientific plotting package.  It is designed to produce
publication-ready PDF or SVG output. Graphs are built-up by combining
plotting widgets. The user interface aims to be simple, consistent and
powerful.

Veusz provides GUI, Python module, command line, scripting, DBUS and
SAMP interfaces to its plotting facilities. It also allows for
manipulation and editing of datasets. Data can be captured from
external sources such as Internet sockets or other programs.

Changes in 4.2.1:
  * Change tutorial highlight color to magenta
  * Fix missing icon in tutorial
  * Move data settings to top in fit widget
  * Fix silent uninstallation
  * Fix wrong size output PDF on MacOS
  * Update to qt-6.10.2 in binary builds

Changes in 4.2:
  * Fix for double scaled 3D point marker borders (Takuro Hosomi)
  * Allow negative offsets for some labels (Takuro Hosomi)
  * Allow iterative change of properties of multiple widgets (Takuro Hosomi)
  * Strip BOMs from Veusz and imported files
  * Fix binary import plugin
  * Fix capture dialog
  * Prefer tomllib on Python 3.11+ (Alexandre Detiste)
  * Clean up text for translation and document use of weblate in README
  * Fix inactive 2D data import range
  * Update GPL address

## Features of package:

### Plotting features:
  * X-Y plots (with errorbars)
  * Line and function plots
  * Contour plots
  * Images (with colour mappings and colorbars)
  * Stepped plots (for histograms)
  * Bar graphs
  * Vector field plots
  * Box plots
  * Polar plots
  * Ternary plots
  * Plotting dates
  * Fitting functions to data
  * Stacked plots and arrays of plots
  * Nested plots
  * Plot keys
  * Plot labels
  * Shapes and arrows on plots
  * LaTeX-like formatting for text
  * Optional MicroTeX-backed rendering for TeX text in labels
  * Multiple axes
  * Axes with steps in axis scale (broken axes)
  * Axis scales using functional forms
  * Plotting functions of datasets
  * 3D point plots
  * 3D surface plots
  * 3D function plots
  * 3D volumetric plots

### Input and output:
  * PDF/EPS/PNG/SVG/EMF export
  * Dataset creation/manipulation
  * Embed Veusz within other programs
  * Text, HDF5, CSV, FITS, NPY/NPZ, QDP, binary and user-plugin importing
  * Data can be captured from external sources

### Extending:
  * Use as a Python module
  * User defined functions, constants and can import external Python functions
  * Plugin interface to allow user to write or load code to
    - import data using new formats
    - make new datasets, optionally linked to existing datasets
    - arbitrarily manipulate the document
  * Scripting interface
  * Control with DBUS and SAMP

### Other features:
  * Data filtering and manipulation
  * Data picker
  * Interactive tutorial
  * Multithreaded rendering

## Installation
Please see the file `INSTALL.md` included in the distribution for installation details, or go to the [download page](https://veusz.github.io/download/).

## Development note: MicroTeX integration
This tree can optionally render selected text objects through
[MicroTeX](https://github.com/NanoMichael/MicroTeX). This integration is
shipped in this repository as a git submodule under
`third_party/MicroTeX`.

When enabled in the GUI using the `Use TeX` option on supported text
settings, Veusz will:

* use the bundled `third_party/MicroTeX` checkout by default
* build `build-microtex/libLaTeX.a` automatically during the normal Veusz build
* build `build-microtexbridge/libmicrotexbridge.so` automatically during the normal Veusz build
* package the MicroTeX resource tree and bridge into installed wheels under `veusz/microtex`
* render the TeX source through MicroTeX
* convert the generated SVG primitives into Veusz drawing paths for GUI and export output

After cloning, the submodule must be initialized:

    $ git clone <veusz-repository>
    $ cd veusz
    $ git submodule update --init --recursive

The normal bundled MicroTeX build also requires a local C++ compiler
toolchain together with CMake and a working Qt6 development
installation.

MicroTeX support is a built-in math subset, not a full LaTeX engine.
It supports common mathematical notation, matrices, align-style
layouts, text styles and some local macro definitions, but not general
`\usepackage{...}` workflows or arbitrary external LaTeX packages.

If you intentionally want to skip the bundled MicroTeX build during
installation, set `VEUSZ_SKIP_MICROTEX_BUILD=1` before running the
build command.

Please see `INSTALL.md` for the development setup requirements, build
steps and optional environment variables used by this integration.

## License
Veusz is Copyright (C) 2003-2025 Jeremy Sanders
 and contributors. It is licensed under the [GPL version 2 or greater](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html).

## Source code
The latest source code can be found in [this GitHub repository](https://github.com/veusz/veusz).
Translations are welcome to be made [using Weblate](https://hosted.weblate.org/projects/veusz/).
