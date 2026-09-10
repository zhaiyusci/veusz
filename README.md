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
* Optional TeX-backed rendering for TeX text in labels
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

## Development note: TeX integration
This tree can optionally render selected text objects through
[MathJax 4](https://www.mathjax.org/) running inside an embedded
[QuickJS](https://bellard.org/quickjs/) engine, through
[MicroTeX](https://github.com/NanoMichael/MicroTeX), which is bundled as a
git submodule under `third_party/MicroTeX`, or through a system TeX
installation. Neither bundled engine needs an external binary or a Node.js
runtime: both render in-process.

Supported text settings expose a `Use TeX` checkbox plus a document-wide
`TeX engine` choice. `MathJax` is the bundled default, the older bundled
`MicroTeX` engine is still available, and `KaTeX` is offered as a much smaller
and faster alternative (it is laid out as MathML rather than SVG, so it relies
on the built-in MathML renderer); `latex`, `pdflatex`, `xelatex` and `lualatex`
are available as system engine choices, and the engine field can also take an
explicit executable path. The document settings also allow a custom preamble.
The engines are expected to produce similar math, but not identical glyph
metrics, spacing, or outlines.

When the TeX option is enabled in the GUI, Veusz will:

* render the TeX source through the selected TeX engine
* use the bundled MathJax bundle and `mathjaxbridge` library by default
* or use the bundled `third_party/MicroTeX` checkout with the built
  `microtexbridge` library when the engine is `MicroTeX`
* or use the system TeX toolchain when the selected engine is one of the system choices
* convert the generated SVG primitives into Veusz drawing paths for GUI and export output
* keep the output engine-specific rather than forcing pixel-identical
  equivalence between the bundled engines and the system TeX engines

The MicroTeX source is shipped as a git submodule, so after cloning it
must be initialized:

    $ git clone <veusz-repository>
    $ cd veusz
    $ git submodule update --init --recursive

The normal Veusz build then builds the bundled MicroTeX static library and
its bridge automatically. That step requires a local C++ compiler
toolchain together with CMake and a working Qt6 development installation
(and tinyxml2, MicroTeX's only non-Qt dependency); set
`VEUSZ_SKIP_MICROTEX_BUILD=1` to skip it during installation. On Windows
`tools\build-microtexbridge.cmd` builds both the library and the bridge on
its own.

The MathJax bundle ships with the source tree under
`src/mathjaxbridge/mathjax_bundle.js`, and its bridge library is built
during the normal Veusz build as well (`tools/build-mathjaxbridge.cmd` on
Windows); both are packaged into installed wheels under `veusz/mathjax`.
Building that bridge requires a local C++ compiler toolchain and the
QuickJS static library. The system TeX choices require a TeX distribution
that provides the selected engine plus `dvisvgm` on `PATH`; supported
engine choices include `latex`, `pdflatex`, `xelatex` and `lualatex`, with
a custom engine path also allowed in the document settings.

MathJax support covers a wide LaTeX subset (AMS, `\mathbb`, `\mathfrak`,
`\mathcal`, `mhchem`, the `physics` package, matrices, `cases`, ...). The
bundled MicroTeX support is a built-in math subset: common mathematical
notation, matrices, align-style layouts, text styles and some local macro
definitions. Neither is a general `\usepackage{...}` workflow -- the
available packages are the ones compiled into the bundle or library.
Because the engines are different, they should be treated as compatible
rendering choices, not as bitwise-identical implementations.

Please see `INSTALL.md` for the development setup requirements, build
steps and optional environment variables used by this integration.

## License
Veusz is Copyright (C) 2003-2025 Jeremy Sanders
 and contributors. It is licensed under the [GPL version 2 or greater](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html).

## Source code
The latest source code can be found in [this GitHub repository](https://github.com/veusz/veusz).
Translations are welcome to be made [using Weblate](https://hosted.weblate.org/projects/veusz/).
