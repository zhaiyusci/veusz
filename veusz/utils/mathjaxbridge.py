"""Veusz bridge to MathJax 4 via embedded QuickJS.

Renders LaTeX to SVG with MathJax 4 running inside an embedded QuickJS
engine, so there is no Node.js runtime or subprocess involved. Compared
with a system TeX pipeline this backend:

- is self-contained (no external binaries, no TeX distribution)
- returns baseline information (``vertical-align``) so text can be
  vertically aligned precisely
- supports the LaTeX subset compiled into the bundle (AMS, ``\\mathbb``,
  ``\\mathcal``, ``\\mathfrak``, ``mhchem``, ``physics``, ...)

The MathJax bundle (``mathjax_bundle.js``, ~4 MB) is loaded once per
process. Subsequent ``render_svg`` calls only invoke ``render()`` /
``renderInline()`` on the already-loaded bundle.
"""

import ctypes
import os
import threading
from collections import OrderedDict
from pathlib import Path
import subprocess
import sys


# -----------------------------------------------------------------------
# Path helpers
# -----------------------------------------------------------------------

def _bridge_filenames():
    if os.name == "nt":
        return ("mathjaxbridge.dll", "libmathjaxbridge.dll")
    if sys.platform == "darwin":
        return ("libmathjaxbridge.dylib", "mathjaxbridge.dylib")
    return ("libmathjaxbridge.so", "mathjaxbridge.so")


def _find_first_existing(root, filenames):
    if not root.exists():
        return None
    search_roots = [root]
    if os.name == "nt":
        search_roots = [
            root / "Release",
            root / "RelWithDebInfo",
            root,
            root / "Debug",
        ]
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for filename in filenames:
            for candidate in sorted(search_root.rglob(filename)):
                if candidate.is_file():
                    return candidate
    return None


def _cmake_build_cmd(build_dir):
    cmd = ["cmake", "--build", str(build_dir), "-j2"]
    if os.name == "nt":
        cmd += ["--config", "Release"]
    return cmd


def _packaged_bridge_candidates():
    packaged_root = _package_root() / "mathjax"
    for filename in _bridge_filenames():
        yield packaged_root / filename


def _build_bridge_candidate():
    return _find_first_existing(_bridge_build_dir(), _bridge_filenames())


def _package_root():
    return Path(__file__).resolve().parents[1]


def _veusz_root():
    package_root = _package_root()
    if (package_root / "VERSION").exists():
        return package_root
    return Path(__file__).resolve().parents[2]


def _build_root():
    env = os.environ.get("VEUSZ_BUILD_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return _veusz_root()


def _bridge_build_dir():
    return _build_root() / "build-mathjaxbridge"


def _quickjs_src_root():
    """Locate the quickjs-ng source tree (for headers + static lib)."""
    env = os.environ.get("VEUSZ_QUICKJS_SRC")
    if env:
        return Path(env)
    # Common locations next to the veusz checkout
    candidates = [
        _veusz_root().parent / "quickjs-src",
        _veusz_root() / "third_party" / "quickjs",
        Path.home() / "src" / "quickjs",
    ]
    for c in candidates:
        if (c / "quickjs.h").exists():
            return c
    return None


def _quickjs_lib_candidates():
    env = os.environ.get("VEUSZ_QUICKJS_LIB")
    if env:
        return [Path(env)]
    src = _quickjs_src_root()
    if not src:
        return []
    build_dir = src.parent / "quickjs-build"
    if os.name == "nt":
        names = ("qjs.lib", "libquickjs.a")
    elif sys.platform == "darwin":
        names = ("libquickjs.a", "libqjs.a")
    else:
        names = ("libquickjs.a", "libqjs.a")
    out = []
    for n in names:
        p = build_dir / n
        if p.exists():
            out.append(p)
    return out


def _bundle_candidates():
    """Yield candidate paths for the MathJax bundle JS file."""
    env = os.environ.get("VEUSZ_MATHJAX_BUNDLE")
    if env:
        p = Path(env)
        if p.exists():
            yield p
    packaged = _package_root() / "mathjax" / "mathjax_bundle.js"
    if packaged.exists():
        yield packaged
    src = _veusz_root() / "src" / "mathjaxbridge" / "mathjax_bundle.js"
    if src.exists():
        yield src


def _resolve_bundle():
    for p in _bundle_candidates():
        return p
    return None


# -----------------------------------------------------------------------
# Bridge build
# -----------------------------------------------------------------------

def _build_bridge():
    build_dir = _bridge_build_dir()
    src_dir = _veusz_root() / "src" / "mathjaxbridge"
    quickjs_src = _quickjs_src_root()
    quickjs_libs = _quickjs_lib_candidates()

    if not quickjs_src:
        raise RuntimeError(
            "QuickJS source tree not found. Set VEUSZ_QUICKJS_SRC or clone "
            "quickjs-ng next to veusz."
        )
    if not quickjs_libs:
        raise RuntimeError(
            "QuickJS static library not found. Build it first:\n"
            "  cmake -S <quickjs-src> -B <quickjs-src>/../quickjs-build "
            "-DBUILD_SHARED_LIBS=OFF -DQJS_BUILD_EXAMPLES=OFF\n"
            "  cmake --build <quickjs-src>/../quickjs-build\n"
            "Or set VEUSZ_QUICKJS_LIB to the .lib/.a path."
        )

    cmake_configure = [
        "cmake",
        "-S", str(src_dir),
        "-B", str(build_dir),
        f"-DQUICKJS_SRC={quickjs_src}",
        f"-DQUICKJS_LIB={quickjs_libs[0]}",
    ]
    subprocess.run(cmake_configure, check=True, cwd=_veusz_root())
    subprocess.run(_cmake_build_cmd(build_dir), check=True, cwd=_veusz_root())


# -----------------------------------------------------------------------
# Library loading + initialization
# -----------------------------------------------------------------------

_LIB = None
_MATHJAX_READY = False
_LOCK = threading.RLock()
_DLL_DIRS = []
_SVG_CACHE = OrderedDict()
_SVG_CACHE_LIMIT = 128
_BUNDLE_CACHE = OrderedDict()
_BUNDLE_CACHE_LIMIT = 256
_HOST_HANDLES = {}


def _cache_get(key):
    data = _SVG_CACHE.get(key)
    if data is None:
        return None
    _SVG_CACHE.move_to_end(key)
    return data


def _cache_put(key, data):
    _SVG_CACHE[key] = data
    _SVG_CACHE.move_to_end(key)
    while len(_SVG_CACHE) > _SVG_CACHE_LIMIT:
        _SVG_CACHE.popitem(last=False)


def _load_host():
    """Load the DLL (a generic JS host) without evaluating any bundle."""
    global _LIB
    if _LIB is not None:
        return _LIB

    env = os.environ.get("VEUSZ_MATHJAX_BRIDGE")
    if env:
        env_path = Path(env)
        if env_path.exists():
            return _load_library(env_path)

    for path in _packaged_bridge_candidates():
        if path.exists():
            return _load_library(path)

    path = _build_bridge_candidate()
    if path is None:
        _build_bridge()
        path = _build_bridge_candidate()
    if path and path.exists():
        return _load_library(path)
    return None


def _load():
    """Load the DLL and make sure the MathJax bundle is evaluated."""
    lib = _load_host()
    if lib is not None:
        lib = _ensure_mathjax()
    return lib


def _load_library(path):
    global _LIB
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        try:
            _DLL_DIRS.append(os.add_dll_directory(str(path.parent)))
        except OSError:
            pass
    lib = ctypes.CDLL(str(path))

    # void mathjax_shutdown(void)
    lib.mathjax_shutdown.argtypes = []
    lib.mathjax_shutdown.restype = None

    # int mathjax_initialize(const char* bundle_path)
    lib.mathjax_initialize.argtypes = [ctypes.c_char_p]
    lib.mathjax_initialize.restype = ctypes.c_int

    # int mathjax_render_svg(
    #     const char* tex_utf8, float text_size, int display,
    #     const char* color,
    #     char** out_svg, size_t* out_len,
    #     float* out_width_pt, float* out_height_pt, float* out_baseline_pt,
    #     char** out_error)
    lib.mathjax_render_svg.argtypes = [
        ctypes.c_char_p,           # tex_utf8
        ctypes.c_float,            # text_size (pt)
        ctypes.c_int,              # display
        ctypes.c_char_p,           # color (e.g. "#ff0000", NULL=strip all color)
        ctypes.POINTER(ctypes.c_void_p),  # out_svg
        ctypes.POINTER(ctypes.c_size_t),  # out_len
        ctypes.POINTER(ctypes.c_float),   # out_width_pt
        ctypes.POINTER(ctypes.c_float),   # out_height_pt
        ctypes.POINTER(ctypes.c_float),   # out_baseline_pt
        ctypes.POINTER(ctypes.c_void_p),  # out_error
    ]
    lib.mathjax_render_svg.restype = ctypes.c_int

    # void mathjax_free(void* p)
    lib.mathjax_free.argtypes = [ctypes.c_void_p]
    lib.mathjax_free.restype = None

    # --- generic JS host API (see veusz/src/mathjaxbridge/mathjax_bridge.cpp)
    # int js_host_init(const char* bundle_path)   -> handle (>0) or 0
    lib.js_host_init.argtypes = [ctypes.c_char_p]
    lib.js_host_init.restype = ctypes.c_int

    # void js_host_shutdown(int handle)
    lib.js_host_shutdown.argtypes = [ctypes.c_int]
    lib.js_host_shutdown.restype = None

    # int js_host_render(int handle, const char* fn_name, const char* input,
    #                    float text_size, int display, const char* color,
    #                    int postprocess, char** out, size_t* out_len,
    #                    float* w, float* h, float* b, char** err)
    lib.js_host_render.argtypes = [
        ctypes.c_int,              # handle
        ctypes.c_char_p,           # entry point name in the bundle
        ctypes.c_char_p,           # input text
        ctypes.c_float,            # text_size (pt)
        ctypes.c_int,              # display
        ctypes.c_char_p,           # color
        ctypes.c_int,              # postprocess (1 = MathJax specific)
        ctypes.POINTER(ctypes.c_void_p),  # out_text
        ctypes.POINTER(ctypes.c_size_t),  # out_len
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_void_p),  # out_error
    ]
    lib.js_host_render.restype = ctypes.c_int

    _LIB = lib
    return lib


def _ensure_mathjax():
    """Evaluate the MathJax bundle on the loaded library (once per process).

    The DLL only hosts JS runtimes; the ~11 MB bundle is evaluated here, so a
    process that only ever uses another bundle (KaTeX) never pays for it.
    """
    global _MATHJAX_READY
    lib = _load_host()
    if lib is None:
        raise RuntimeError("MathJax bridge library not found")
    if _MATHJAX_READY:
        return lib
    bundle = _resolve_bundle()
    if bundle is None:
        raise RuntimeError(
            "MathJax bundle (mathjax_bundle.js) not found. Set "
            "VEUSZ_MATHJAX_BUNDLE or place the file in veusz/mathjax/."
        )
    rc = lib.mathjax_initialize(str(bundle).encode("utf-8"))
    if rc != 0:
        raise RuntimeError(f"mathjax_initialize failed (rc={rc})")
    _MATHJAX_READY = True
    return lib


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def render_svg(tex, text_size=20.0, width=720,
               foreground=None, background="transparent",
               display=True):
    """Render LaTeX ``tex`` to SVG bytes using MathJax 4.

    Parameters
    ----------
    tex : str
        LaTeX source (UTF-8).
    text_size : float
        Font size in points. Used to convert MathJax's ex-based dimensions
        to pt for absolute placement. 1ex is taken as text_size/2 pt.
    width : int
        Accepted and ignored; callers pass it for a uniform backend API.
    foreground : str or None
        Formula fill color (hex like ``"#ff0000"``).  If ``None`` (default)
        or empty string, the DLL strips all hardcoded color so the caller can
        control color externally (e.g. via the text pen of the widget).
    background : str
        Accepted and ignored; callers pass it for a uniform backend API.
    display : bool
        True for display-mode math (default), False for inline.

    Returns
    -------
    svgbytes : bytes
        The rendered SVG document (UTF-8 encoded). The SVG's width/height
        attributes are in pt units so that it scales deterministically
        regardless of the surrounding font.
    """
    with _LOCK:
        lib = _load()
        if lib is None:
            raise RuntimeError("MathJax bridge library not found")

        cache_key = (
            tex,
            float(text_size),
            bool(display),
            foreground or "",
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        out_svg = ctypes.c_void_p()
        out_len = ctypes.c_size_t()
        out_w = ctypes.c_float()
        out_h = ctypes.c_float()
        out_b = ctypes.c_float()
        out_error = ctypes.c_void_p()

        # foreground=None or "" → DLL strips all color (NULL pointer)
        color_ptr = foreground.encode("utf-8") if foreground else None

        rc = lib.mathjax_render_svg(
            tex.encode("utf-8"),
            float(text_size),
            1 if display else 0,
            color_ptr,
            ctypes.byref(out_svg),
            ctypes.byref(out_len),
            ctypes.byref(out_w),
            ctypes.byref(out_h),
            ctypes.byref(out_b),
            ctypes.byref(out_error),
        )
        if rc != 0:
            msg = "MathJax bridge failed"
            if out_error.value:
                msg = ctypes.cast(out_error, ctypes.c_char_p).value.decode("utf-8", "replace")
                lib.mathjax_free(out_error)
            raise RuntimeError(msg)

        try:
            data = ctypes.string_at(out_svg.value, out_len.value)
            _cache_put(cache_key, data)
            return data
        finally:
            if out_svg.value:
                lib.mathjax_free(out_svg)


def shutdown():
    """Release the JS runtimes. Optional; called at interpreter exit."""
    with _LOCK:
        global _LIB, _MATHJAX_READY
        if _LIB is not None:
            try:
                _LIB.mathjax_shutdown()
            except Exception:
                pass
            _LIB = None
        _MATHJAX_READY = False
        _HOST_HANDLES.clear()
        _BUNDLE_CACHE.clear()


# -----------------------------------------------------------------------
# Generic bundle hosting
#
# The bridge is a JS host, not a MathJax renderer: any bundle that defines
# global functions taking and returning a string can be loaded, and several
# bundles can live side by side (one QuickJS runtime each).  ``render_bundle``
# returns the string unchanged (no MathJax-specific ex->pt rewriting), which is
# what non-SVG bundles such as KaTeX's MathML need.
# -----------------------------------------------------------------------

def _named_bundle_candidates(name):
    """Where a bundle shipped by name may live (packaged, then checkout)."""
    packaged = _package_root() / "mathjax" / name
    if packaged.exists():
        yield packaged
    src = _veusz_root() / "src" / "mathjaxbridge" / name
    if src.exists():
        yield src


def resolve_bundle(name, env_var=None):
    """Find a bundled JS file by name, honouring an env override."""
    if env_var:
        env = os.environ.get(env_var)
        if env:
            path = Path(env)
            if path.exists():
                return path
    for candidate in _named_bundle_candidates(name):
        return candidate
    return None


def katex_bundle_path():
    """Path of the KaTeX bundle, or None when it is not shipped."""
    return resolve_bundle("katex_bundle.js", "VEUSZ_KATEX_BUNDLE")


def host_handle(bundle_path):
    """Load ``bundle_path`` as its own JS runtime and return its handle."""
    lib = _load_host()
    if lib is None:
        raise RuntimeError("MathJax bridge library not found")
    key = str(Path(bundle_path).resolve())
    handle = _HOST_HANDLES.get(key)
    if handle:
        return handle
    handle = lib.js_host_init(str(bundle_path).encode("utf-8"))
    if not handle:
        raise RuntimeError("js_host_init failed for %s" % bundle_path)
    _HOST_HANDLES[key] = handle
    return handle


def render_bundle(bundle_path, fn_name, text, text_size=0.0, display=True,
                  color=None):
    """Call ``fn_name(text)`` inside the JS runtime hosting ``bundle_path``.

    The returned string is passed through unchanged.  Results are cached per
    (bundle, entry point, input) because the callers repaint frequently.
    """
    cache_key = (str(bundle_path), fn_name, text, bool(display))
    with _LOCK:
        cached = _BUNDLE_CACHE.get(cache_key)
        if cached is not None:
            _BUNDLE_CACHE.move_to_end(cache_key)
            return cached

        lib = _load_host()
        if lib is None:
            raise RuntimeError("MathJax bridge library not found")
        handle = host_handle(bundle_path)

        out_text = ctypes.c_void_p()
        out_len = ctypes.c_size_t()
        out_w = ctypes.c_float()
        out_h = ctypes.c_float()
        out_b = ctypes.c_float()
        out_error = ctypes.c_void_p()
        color_ptr = color.encode("utf-8") if color else None

        rc = lib.js_host_render(
            handle, fn_name.encode("utf-8"), text.encode("utf-8"),
            float(text_size), 1 if display else 0, color_ptr,
            0,                              # no MathJax-specific postprocessing
            ctypes.byref(out_text), ctypes.byref(out_len),
            ctypes.byref(out_w), ctypes.byref(out_h), ctypes.byref(out_b),
            ctypes.byref(out_error),
        )
        if rc != 0:
            msg = "JS host render failed (rc=%d)" % rc
            if out_error.value:
                msg = ctypes.cast(
                    out_error, ctypes.c_char_p).value.decode("utf-8", "replace")
                lib.mathjax_free(out_error)
            raise RuntimeError(msg)

        try:
            data = ctypes.string_at(out_text.value, out_len.value).decode(
                "utf-8", "replace")
        finally:
            if out_text.value:
                lib.mathjax_free(out_text)

        _BUNDLE_CACHE[cache_key] = data
        while len(_BUNDLE_CACHE) > _BUNDLE_CACHE_LIMIT:
            _BUNDLE_CACHE.popitem(last=False)
        return data


import atexit
atexit.register(shutdown)
