"""Integration test: Veusz TeX rendering with the MathJax 4 (QuickJS) engine.

This drives the real integration path, not just the DLL:

    label widget (Text/useTeX=True)  ->  textrender._TeXRenderer
        -> textrender._svg_parse_ops   (SVG -> QPainterPath ops)
        -> veusz.utils.mathjaxbridge.render_svg -> ctypes
        -> src/mathjaxbridge/mathjax_bridge.cpp (QuickJS + mathjax_bundle.js)

and then the real output paths (interactive painter, PNG/PDF/SVG/JPG export).

Run headless::

    python tests/test_mathjax_engine.py
    python tests/test_mathjax_engine.py --outdir <dir>   # keep artifacts
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VEUSZ_ROOT = Path(__file__).resolve().parents[1]

# Headless Qt: no display, no windows.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault(
    'VEUSZ_MATHJAX_BRIDGE',
    str(VEUSZ_ROOT / 'build-mathjaxbridge' / 'mathjaxbridge.dll'))
os.environ.setdefault(
    'VEUSZ_MATHJAX_BUNDLE',
    str(VEUSZ_ROOT / 'src' / 'mathjaxbridge' / 'mathjax_bundle.js'))

if str(VEUSZ_ROOT) not in sys.path:
    sys.path.insert(0, str(VEUSZ_ROOT))

import veusz.qtall as qt                                        # noqa: E402

_app = qt.QApplication.instance() or qt.QApplication([])        # noqa: E402

import veusz.document                                           # noqa: E402
import veusz.setting                                            # noqa: E402
import veusz.windows.mainwindow                                 # noqa: E402,F401
from veusz.utils import mathjaxbridge                           # noqa: E402
from veusz.utils import textrender                              # noqa: E402

FORMULAS = [
    (r'$E = mc^2$', 'inline-simple'),
    (r'$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$', 'inline-fraction'),
    (r'$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$', 'inline-sum'),
    (r'$\mathbb{R} \subset \mathbb{C}$', 'inline-blackboard'),
    (r'$\ce{H2O}$', 'inline-mhchem'),
    (r'$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$', 'inline-matrix'),
]

EXPORT_FORMATS = ('png', 'pdf', 'svg', 'jpg')


# -----------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------

def make_doc(engine, text, fontsize=12.0):
    """Build a minimal document containing one TeX label."""
    doc = veusz.document.Document()
    doc.basewidget.settings.TeX.engine = engine
    ifc = veusz.document.CommandInterface(doc)
    page = ifc.Add('page')                       # names are numbered: page1
    ifc.To(page)
    ifc.Add('label', name='lbl')
    ifc.Set('lbl/label', text)                   # the text to draw
    ifc.Set('lbl/Text/useTeX', True)             # route through the TeX backend
    ifc.Set('lbl/Text/size', '%gpt' % fontsize)
    return doc, ifc


def export(doc, path, dpi=100):
    veusz.document.CommandInterface(doc).Export(str(path), dpi=dpi)
    return Path(path)


def clear_caches():
    for cache in (
        textrender._TEX_SVG_CACHE,
        textrender._TEX_PREVIEW_CACHE,
        textrender._TEX_OPS_CACHE,
        textrender._TEX_ERROR_CACHE,
        mathjaxbridge._SVG_CACHE,
    ):
        cache.clear()


def svg_payloads(engine='mathjax'):
    """SVGs produced by `engine` during the last export."""
    return [v for k, v in textrender._TEX_SVG_CACHE.items() if k[0] == engine]


def ink_bbox(pngfile):
    """Bounding box of drawn (non-transparent) pixels of a PNG.

    Veusz exports PNG with a transparent background, so 'ink' is simply
    anything with a non-zero alpha channel.  Returns (bbox, size, npixels)
    with bbox as (x, y, w, h) or None when the image is empty.
    """
    import numpy as np
    img = qt.QImage(str(pngfile))
    if img.isNull():
        raise RuntimeError('cannot read %s' % pngfile)
    img = img.convertToFormat(qt.QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)
    alpha = arr[:, :w, 3]
    ys, xs = np.nonzero(alpha)
    if len(xs) == 0:
        return None, (w, h), 0
    bbox = (int(xs.min()), int(ys.min()),
            int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return bbox, (w, h), int(len(xs))


def render_label_png(tmpdir, engine, tex, name, dpi=100, fontsize=12.0):
    """Render one TeX label and return its ink bbox."""
    clear_caches()
    doc, _ = make_doc(engine, tex, fontsize=fontsize)
    png = export(doc, tmpdir / ('%s.png' % name), dpi=dpi)
    bbox, size, npix = ink_bbox(png)
    payloads = svg_payloads(engine)
    return {
        'bbox': bbox, 'size': size, 'ink': npix,
        'errors': [v for v in textrender._TEX_ERROR_CACHE.values() if v],
        'svg': payloads[0] if payloads else None,
    }


def svg_geometry(svgbytes):
    """Pull width/height/baseline (vertical-align) out of a bridge SVG."""
    import re
    text = svgbytes.decode('utf-8', 'replace')
    root = re.search(r'<svg[^>]*>', text).group(0)
    def grab(attr):
        m = re.search(r'%s="([-0-9.]+)pt"' % attr, root)
        return float(m.group(1)) if m else None
    m = re.search(r'vertical-align:\s*([-0-9.]+)pt', root)
    return {
        'width_pt': grab('width'),
        'height_pt': grab('height'),
        'baseline_pt': float(m.group(1)) if m else None,
    }


# -----------------------------------------------------------------------
# tests
# -----------------------------------------------------------------------

def test_default_engine(tmpdir):
    """A fresh document renders TeX through MathJax without opting in.

    This is the behavioural lock on the default value of TeX.engine: it
    asserts the wiring, not the string.
    """
    clear_caches()
    doc = veusz.document.Document()
    default = doc.basewidget.settings.TeX.engine
    assert default == 'mathjax', \
        'document default TeX engine is %r' % default

    ifc = veusz.document.CommandInterface(doc)
    page = ifc.Add('page')
    ifc.To(page)
    ifc.Add('label', name='lbl')
    ifc.Set('lbl/label', FORMULAS[2][0])
    ifc.Set('lbl/Text/useTeX', True)      # engine deliberately not set
    png = export(doc, tmpdir / 'default-engine.png')

    engines_used = sorted({k[0] for k in textrender._TEX_SVG_CACHE})
    assert engines_used == ['mathjax'], \
        'TeX went through %r, not mathjax' % (engines_used,)
    bbox, size, ink = ink_bbox(png)
    assert ink > 20, 'nothing drawn with the default engine'
    return {'engine': default, 'engines_used': engines_used, 'ink': ink}


def test_engine_is_used(tmpdir):
    """The mathjax engine -- not a fallback -- renders the label."""
    res = render_label_png(tmpdir, 'mathjax', FORMULAS[0][0], 'engine-probe')
    assert res['svg'] is not None, 'no SVG came out of the mathjax backend'
    assert not res['errors'], 'render errors: %r' % res['errors']
    assert res['ink'] > 50, 'almost nothing drawn (%d px)' % res['ink']
    geo = svg_geometry(res['svg'])
    assert geo['width_pt'] and geo['height_pt'], \
        'SVG has no pt dimensions: %r' % geo
    return {
        'svg_bytes': len(res['svg']), 'svg_pt': geo,
        'ink_px': res['ink'], 'ink_bbox': res['bbox'], 'page': res['size'],
    }


def test_all_formulas_render(tmpdir):
    """Every sample formula renders to distinct, non-degenerate ink."""
    results = []
    for tex, name in FORMULAS:
        res = render_label_png(tmpdir, 'mathjax', tex, 'mjx-%s' % name)
        assert not res['errors'], '%s: render error %r' % (name, res['errors'])
        assert res['bbox'] is not None, '%s: nothing drawn' % name
        assert res['ink'] > 20, '%s: too little ink (%d px)' % (name, res['ink'])
        assert res['bbox'][2] > 3 and res['bbox'][3] > 3, \
            '%s: implausible bbox %r' % (name, res['bbox'])
        results.append({
            'name': name, 'ink': res['ink'], 'bbox': res['bbox'],
            'pt': svg_geometry(res['svg']),
        })
    # different formulas must not collapse to the same geometry
    geoms = {(r['bbox'][2], r['bbox'][3]) for r in results}
    assert len(geoms) >= 4, 'formulas rendered identically: %r' % geoms
    return results


def test_export_formats(tmpdir):
    """Vector and raster exports all carry the TeX label."""
    out = {}
    for ext in EXPORT_FORMATS:
        clear_caches()
        doc, _ = make_doc('mathjax', FORMULAS[1][0])
        p = export(doc, tmpdir / ('export-test.%s' % ext))
        size = p.stat().st_size if p.exists() else 0
        assert size > 0, '%s export produced no output' % ext
        out[ext] = size
    # a PDF with a vector label is comfortably bigger than an empty page
    assert out['pdf'] > 2000, 'suspiciously small PDF (%d bytes)' % out['pdf']
    return out


def test_ghostscript_formats(tmpdir):
    """EPS/PS need Ghostscript -- report whether this environment has it."""
    from veusz.document import export as exportmod
    rm = exportmod.ExportPostscriptRunnable
    rm.searchGhostscript()
    if not rm.gs_exe:
        return {'eps': 'skipped: Ghostscript not found (veusz limitation)'}
    doc, _ = make_doc('mathjax', FORMULAS[1][0])
    p = export(doc, tmpdir / 'export-test.eps')
    return {'eps': p.stat().st_size}


def test_backend_selection(tmpdir):
    """Both bundled engines stay selectable, with mathjax as the default.

    The bundled MicroTeX backend is still part of the tree, so its name must
    stay selectable next to MathJax, and the system LaTeX engines must remain
    available.  Documents written before the engine setting existed used the
    legacy backend setting, which is still honoured.
    """
    from veusz.setting import collections          # noqa: F401
    doc = veusz.document.Document()
    texsettings = doc.basewidget.settings.TeX
    choices = list(texsettings.get('engine').vallist)
    assert 'mathjax' in choices, choices
    assert 'microtex' in choices, \
        'bundled MicroTeX engine no longer selectable: %r' % (choices,)
    for system in ('latex', 'pdflatex', 'xelatex', 'lualatex'):
        assert system in choices, (system, choices)

    # the 'microtex' engine dispatches to the MicroTeX bridge, not to MathJax
    class _Dispatched(Exception):
        pass

    seen = []

    def _fake_render(tex, **kwargs):
        seen.append(tex)
        raise _Dispatched()

    original = textrender.microtexbridge.render_svg
    textrender.microtexbridge.render_svg = _fake_render
    try:
        try:
            textrender._render_tex_backend(
                'microtex', 'x', 20.0, '#000000', 'transparent', '')
        except _Dispatched:
            pass
        else:
            raise AssertionError(
                'the microtex engine did not use the MicroTeX bridge')
    finally:
        textrender.microtexbridge.render_svg = original
    assert seen == ['x'], seen

    # legacy backend 'system' still routes to the system LaTeX engine; the
    # legacy 'microtex' value only names the built-in engine, which is MathJax
    engine_for = {}
    for legacy in ('microtex', 'system'):
        clear_caches()
        doc = veusz.document.Document()
        doc.basewidget.settings.TeX.backend = legacy
        ifc = veusz.document.CommandInterface(doc)
        page = ifc.Add('page')
        ifc.To(page)
        ifc.Add('label', name='lbl')
        ifc.Set('lbl/label', FORMULAS[0][0])
        ifc.Set('lbl/Text/useTeX', True)
        try:
            export(doc, tmpdir / ('legacy-%s.png' % legacy))
        except Exception as e:                      # engine may be missing
            engine_for[legacy] = 'export failed: %s' % e
            continue
        engine_for[legacy] = sorted({k[0] for k in textrender._TEX_SVG_CACHE})
    assert engine_for['microtex'] == ['mathjax'], engine_for
    return {'choices': choices, 'legacy_backend': engine_for}


def test_interactive_path(tmpdir):
    """The interactive GUI paint path renders TeX asynchronously.

    GUI painting passes interactive=True, which makes textrender queue a
    background MathJax job and draw a placeholder until it lands.  This
    exercises that flow: first pass -> preview/fallback, wait for the
    worker, second pass -> real MathJax output.
    """
    from veusz.document import painthelper
    from veusz.utils import textrender as tr

    clear_caches()
    doc, _ = make_doc('mathjax', FORMULAS[1][0])

    def paint(path):
        img = qt.QImage(590, 590, qt.QImage.Format.Format_ARGB32)
        img.fill(0)
        painter = qt.QPainter(img)
        painter.setRenderHint(qt.QPainter.RenderHint.Antialiasing)
        psize = doc.pageSize(0, dpi=(100, 100), integer=False)
        helper = painthelper.PaintHelper(
            doc, psize, dpi=(100, 100), interactive=True)
        doc.paintTo(helper, 0)
        helper.renderToPainter(painter)
        painter.end()
        img.save(str(path), 'PNG')
        bbox, size, ink = ink_bbox(path)
        return {'ink': ink, 'bbox': bbox, 'svg_cached': len(svg_payloads())}

    first = paint(tmpdir / 'interactive-pass1.png')
    manager = tr.texRenderManager()
    waited = manager.pool.waitForDone(120000)
    second = paint(tmpdir / 'interactive-pass2.png')

    diag = {
        'pass1': first, 'pass2': second, 'waitForDone': waited,
        'exact_cached': len(tr._TEX_SVG_CACHE),
        'errors': dict(tr._TEX_ERROR_CACHE),
        'pending': len(manager.pending),
    }
    assert second['svg_cached'] >= 1, \
        'no MathJax SVG after the background render: %r' % (diag,)
    assert second['ink'] > 20, 'nothing drawn on repaint: %r' % (diag,)
    assert (first['ink'] != second['ink'] or
            first['bbox'] != second['bbox']), \
        'repaint after the async render looks identical to the placeholder:' \
        ' %r' % (diag,)
    return diag


def test_graph_axes_tex(tmpdir):
    """TeX on axis labels and ticks (the usefullheight=True alignment path)."""
    clear_caches()
    doc = veusz.document.Document()
    doc.basewidget.settings.TeX.engine = 'mathjax'
    ifc = veusz.document.CommandInterface(doc)
    ifc.SetData('x', [0.0, 1.0, 2.0, 3.0])
    ifc.SetData('y', [0.0, 1.0, 4.0, 9.0])
    page = ifc.Add('page')
    ifc.To(page)
    ifc.Add('graph', name='g')
    ifc.To('g')
    ifc.Add('xy', xData='x', yData='y')
    # axis label uses usefullheight=True, tick labels do not
    ifc.Set('x/label', r'$\alpha$ (deg)')
    ifc.Set('x/Label/useTeX', True)
    ifc.Set('x/TickLabels/useTeX', True)

    png = export(doc, tmpdir / 'graph-axes.png')
    bbox, size, ink = ink_bbox(png)
    svgs = svg_payloads()
    geoms = [svg_geometry(s) for s in svgs]
    assert ink > 100, 'graph drew almost nothing (%d px)' % ink
    assert len(geoms) >= 3, \
        'expected axis label + several tick labels, got %d' % len(geoms)
    assert all(g['width_pt'] and g['height_pt'] for g in geoms), geoms
    # the axis label has a descender, so it must carry a baseline
    assert any(g['baseline_pt'] for g in geoms), \
        'no TeX label reported a baseline: %r' % (geoms,)

    return {'ink': ink, 'bbox': bbox, 'n_tex_labels': len(geoms),
            'geoms': geoms}


def test_stack_budget(tmpdir):
    """The JS stack budget must fit real formulas and fail gracefully.

    QuickJS anchors its JS stack limit to the thread that created the
    runtime, so the bridge re-anchors on every call and sizes the budget
    from the calling thread's remaining stack (thread stacks here are only
    ~2.9 MiB, while two thread stacks can sit 11 MiB apart -- the reason a
    plain formula used to fail with "Maximum call stack size exceeded").
    """
    from veusz.utils import mathjaxbridge

    def nested(depth):
        tex = 'x'
        for _ in range(depth):
            tex = r'\frac{1}{1+%s}' % tex
        return '$%s$' % tex

    # realistic nesting renders
    for depth in (1, 8, 15):
        svg = mathjaxbridge.render_svg(nested(depth), text_size=12.0)
        assert b'<svg' in svg, 'depth %d produced no SVG' % depth

    # wide / heavy content is unaffected by the budget
    heavy = '$' + '+'.join(r'a_{%d}' % i for i in range(200)) + '$'
    assert b'<svg' in mathjaxbridge.render_svg(heavy, text_size=12.0)

    # absurd nesting must raise a normal JS error, not kill the process
    message = None
    try:
        mathjaxbridge.render_svg(nested(400), text_size=12.0)
    except RuntimeError as e:
        message = str(e)
    assert message is not None, 'absurd nesting unexpectedly succeeded'
    assert 'call stack' in message, 'unexpected error: %r' % message

    # and the label path turns that into an error box rather than a crash
    res = render_label_png(tmpdir, 'mathjax', nested(400), 'too-deep')
    assert res['bbox'] is not None, 'nothing drawn for the error case'
    return {'realistic_depths': (1, 8, 15), 'too_deep_error': message,
            'error_box_ink': res['ink']}


def test_svg_transform_order(tmpdir):
    """Multiple transform functions in one attribute must compose per SVG.

    MathJax places scripts with a single attribute such as
    transform="translate(462,413) scale(0.707)".  SVG applies the list left to
    right (the scale first, the translate last).  Veusz multiplies QTransforms
    where A * B means "apply A, then B", so accumulating in the wrong
    direction put every superscript at translate*scale instead of
    translate + scale*local -- i.e. 135 units too far left for MathJax's own
    numbers, which made $b^2$ look like the 2 was glued to the b.

    Two squares make the mistake visible even though the parser normalises
    the ink to the origin.
    """
    template = '''<svg xmlns="http://www.w3.org/2000/svg"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      width="1000px" height="1000px" viewBox="0 0 1000 1000">
      <defs><path id="SQ" d="M0,0 L100,0 L100,100 L0,100 Z"/></defs>
      <use xlink:href="#SQ"/>
      %s
    </svg>'''

    cases = {
        'nested groups':
            '<g transform="translate(500,0)"><g transform="scale(0.5)">'
            '<use xlink:href="#SQ"/></g></g>',
        'one attribute':
            '<g transform="translate(500,0) scale(0.5)">'
            '<use xlink:href="#SQ"/></g>',
        'mathjax script form':
            '<g transform="translate(462,413) scale(0.707)">'
            '<use xlink:href="#SQ"/></g>',
    }
    out = {}
    for name, inner in cases.items():
        ops, _w, _h = textrender._svg_parse_ops(
            (template % inner).encode('utf-8'), 100.0)
        rects = sorted((path.boundingRect() for path, _p, _b in ops),
                       key=lambda r: r.x())
        assert len(rects) == 2, '%s: expected 2 shapes, got %d' % (
            name, len(rects))
        base, scaled = rects
        out[name] = {
            'scaled_x': round(scaled.x(), 1),
            'scaled_w': round(scaled.width(), 1),
            'gap': round(scaled.x() - base.x() - base.width(), 1),
        }

    # the second square must be scaled AND translated, never scaled in place
    assert out['one attribute']['scaled_w'] == 50.0, out
    assert out['one attribute']['scaled_x'] == 500.0, (
        'transform list applied in the wrong order: %r' % (out,))
    assert out['one attribute']['gap'] == 400.0, out
    assert out['mathjax script form']['scaled_x'] == 462.0, (
        'MathJax script transforms land in the wrong place: %r' % (out,))
    assert out['nested groups']['scaled_x'] == 500.0, out
    return out


def test_baseline_alignment(tmpdir):
    """Does the label honour MathJax's baseline (vertical-align)?

    Both labels are anchored identically by veusz.  If the backend baseline
    is honoured, the descender of '$g$' pushes its ink *below* the anchor
    while '$E$' stops at it, so the ink boxes end at different heights.
    If the bbox bottom is simply pinned to the anchor, both end together and
    the baselines inside the boxes disagree.
    """
    e = render_label_png(tmpdir, 'mathjax', '$E$', 'base-E')
    g = render_label_png(tmpdir, 'mathjax', '$g$', 'base-g')
    geo_e = svg_geometry(e['svg'])
    geo_g = svg_geometry(g['svg'])

    e_bottom = e['bbox'][1] + e['bbox'][3]
    g_bottom = g['bbox'][1] + g['bbox'][3]
    dpi = 100.0
    # what the backend says: distance from ink bottom to baseline
    descender_e = -(geo_e['baseline_pt'] or 0.0) * dpi / 72.0
    descender_g = -(geo_g['baseline_pt'] or 0.0) * dpi / 72.0

    return {
        'svg_baseline_E_pt': geo_e['baseline_pt'],
        'svg_baseline_g_pt': geo_g['baseline_pt'],
        'svg_height_E_pt': geo_e['height_pt'],
        'svg_height_g_pt': geo_g['height_pt'],
        'ink_bottom_E_px': e_bottom,
        'ink_bottom_g_px': g_bottom,
        'ink_bottom_delta_px': g_bottom - e_bottom,
        'baseline_would_want_delta_px': round(descender_g - descender_e, 2),
    }


def test_microtex_engine(tmpdir):
    """The bundled MicroTeX engine renders through its own bridge.

    MicroTeX is a separate backend with separate packaging, so this is the
    behavioural lock that it stays wired up: the engine name must dispatch to
    veusz.utils.microtexbridge and produce ink through the normal export path.

    Reported as skipped, not failed, when the bridge library is absent: it is
    built by tools/build-microtexbridge.cmd and needs a cmake/Qt6 toolchain
    plus tinyxml2 (see INSTALL.md).
    """
    from veusz.utils import microtexbridge
    try:
        lib = microtexbridge._load()
    except Exception as e:                          # toolchain absent
        return {'skipped': 'MicroTeX bridge unavailable: %s' % e}
    if lib is None:
        return {'skipped': 'MicroTeX bridge library not found'}

    results = {}
    for tex, name in (FORMULAS[0], FORMULAS[1], FORMULAS[5]):
        info = render_label_png(tmpdir, 'microtex', tex, 'microtex-' + name)
        engines = sorted({k[0] for k in textrender._TEX_SVG_CACHE})
        assert engines == ['microtex'], engines
        assert info['errors'] == [], info['errors']
        assert info['ink'] > 0, 'no ink for %r' % tex
        assert info['svg'], 'no SVG payload for %r' % tex

        # MicroTeX draws glyphs as <text> (font-family="cmmi10" ...) rather
        # than as outlines, so it depends on the resource tree being found and
        # its TTFs being registered with Qt (see _ensure_microtex_fonts_loaded).
        import re
        svg = info['svg']
        assert b'<text' in svg, 'MicroTeX output is expected to use <text>'
        assert b'font-family="cm' in svg, svg[:400]
        root = re.search(rb'<svg[^>]*>', svg)
        assert root, svg[:400]
        head = root.group(0).decode('utf-8', 'replace')
        size = re.search(r'width="([0-9.]+)(\w+)" height="([0-9.]+)(\w+)"', head)
        assert size, head
        assert float(size.group(1)) > 0 and float(size.group(3)) > 0, head
        assert re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', head), head

        results[name] = {
            'ink': info['ink'], 'bbox': info['bbox'],
            'size': '%s%s x %s%s' % (size.group(1), size.group(2),
                                     size.group(3), size.group(4)),
            'texts': svg.count(b'<text'),
        }
    results['resource_root'] = microtexbridge._resource_root()
    return results


def test_katex_engine(tmpdir):
    """KaTeX is wired up as a second engine behind the same JS host.

    KaTeX cannot emit SVG, so its MathML output goes to veusz's existing MathML
    renderer.  The conversion is checked here; the painting is checked in a
    child process because veusz's MathML renderer scales through the primary
    screen's DPI, which the offscreen platform plugin (used above) does not
    provide.
    """
    from veusz.utils import mathjaxbridge
    bundle = mathjaxbridge.katex_bundle_path()
    assert bundle is not None, 'katex_bundle.js not found'
    assert Path(bundle).exists(), bundle

    mathml = textrender._katex_mathml(r'x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}')
    assert mathml.lstrip().startswith('<math'), mathml[:120]
    assert '<merror' not in mathml, mathml[:200]
    assert '<mfrac' in mathml, mathml[:200]

    # the same JS host serves MathJax and KaTeX side by side
    assert 'katex' in list(
        veusz.document.Document().basewidget.settings.TeX.get('engine').vallist)

    env = dict(os.environ)
    # the MathML renderer needs a real screen; this module defaults the child's
    # platform back to offscreen via setdefault, so set it explicitly
    env['QT_QPA_PLATFORM'] = _native_qt_platform()
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), '--katex-child',
         str(tmpdir)],
        env=env, capture_output=True, text=True)
    assert proc.returncode == 0, (proc.stdout[-400:], proc.stderr[-400:])
    rendered = json.loads(proc.stdout.strip().splitlines()[-1])
    for name, info in rendered.items():
        assert info['ink'] > 0, (name, info)
    return {
        'bundle': Path(bundle).name,
        'mathml_bytes': len(mathml),
        'rendered': rendered,
    }


def katex_child(outdir):
    """Render KaTeX samples and report their ink (child process mode)."""
    outdir = Path(outdir)
    result = {}
    for tex, name in (FORMULAS[0], FORMULAS[1], FORMULAS[5]):
        info = render_label_png(outdir, 'katex', tex, 'katex-' + name)
        result[name] = {'ink': info['ink'], 'bbox': info['bbox']}
    print(json.dumps(result))
    return 0


def _native_qt_platform():
    """The platform plugin to use when offscreen is not good enough."""
    if os.name == 'nt':
        return 'windows'
    if sys.platform == 'darwin':
        return 'cocoa'
    return 'xcb'


# -----------------------------------------------------------------------
# runner
# -----------------------------------------------------------------------

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--katex-child':
        return katex_child(sys.argv[2])

    parser = argparse.ArgumentParser()
    parser.add_argument('--outdir', default=None)
    args = parser.parse_args()

    tmp = (Path(args.outdir) if args.outdir
           else Path(tempfile.mkdtemp(prefix='veusz-mathjax-')))
    tmp.mkdir(parents=True, exist_ok=True)
    print('workdir:', tmp)
    print('bridge: ', os.environ['VEUSZ_MATHJAX_BRIDGE'])
    print('bundle: ', os.environ['VEUSZ_MATHJAX_BUNDLE'])
    print()

    failures = 0

    def run(name, fn):
        nonlocal failures
        print('== %s' % name)
        try:
            res = fn()
            print('   PASS', res if res is not None else '')
        except Exception as e:
            failures += 1
            import traceback
            print('   FAIL: %s' % e)
            traceback.print_exc()

    run('default engine', lambda: test_default_engine(tmp))
    run('engine + SVG contract', lambda: test_engine_is_used(tmp))
    run('all formulas', lambda: test_all_formulas_render(tmp))
    run('export formats', lambda: test_export_formats(tmp))
    run('ghostscript formats', lambda: test_ghostscript_formats(tmp))
    run('interactive paint path', lambda: test_interactive_path(tmp))
    run('graph axes (TeX)', lambda: test_graph_axes_tex(tmp))
    run('stack budget', lambda: test_stack_budget(tmp))
    run('svg transform order', lambda: test_svg_transform_order(tmp))
    run('baseline alignment', lambda: test_baseline_alignment(tmp))
    run('backend selection', lambda: test_backend_selection(tmp))
    run('katex engine', lambda: test_katex_engine(tmp))
    run('microtex engine', lambda: test_microtex_engine(tmp))

    print()
    if failures:
        print('%d test(s) FAILED' % failures)
    else:
        print('all tests passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
