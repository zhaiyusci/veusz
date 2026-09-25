"""Opt-in XY missing-error policy, using source/native Qt PNG rendering.

Run with QT_QPA_PLATFORM=offscreen and VEUSZ_RESOURCE_DIR at the source root.
No installed Veusz, GUI event loop, or external renderer is used.
"""
import itertools
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from veusz import datasets, document, qtall as qt, widgets, dataimport
from veusz.widgets import point


def make_plot(policy='hide-point', mode='break-on', errors=None, values=None):
    with patch.object(document.Document, 'loadPlugins'):
        doc = document.Document()
    ci = document.CommandInterface(doc)
    ci.Set('width', '2in')
    ci.Set('height', '2in')
    doc.setData('x', datasets.Dataset([1, 2, 3, 4, 5]))
    doc.setData('y', datasets.Dataset(
        [3, 3, 3, 3, 3] if values is None else values,
        **({'serr': [1, 1, np.nan, 1, 1]} if errors is None else errors)))
    ci.Add('page', name='page', autoadd=False)
    ci.To('page')
    ci.Add('graph', name='graph', autoadd=True)
    ci.To('graph')
    ci.Set('Border/hide', True)
    for side in ('left', 'right', 'top', 'bottom'):
        ci.Set(side+'Margin', '.25in')
    for axis in ('x', 'y'):
        ci.Set(axis+'/min', 0.)
        ci.Set(axis+'/max', 6.)
        ci.Set(axis+'/hide', True)
    ci.Add('xy', name='xy', autoadd=False)
    ci.To('xy')
    ci.Set('xData', 'x')
    ci.Set('yData', 'y')
    ci.Set('missingErrors', policy)
    ci.Set('nanHandling', mode)
    ci.Set('color', 'black')
    ci.Set('markerSize', '6pt')
    return doc, ci, doc.basewidget.children[0].children[0].children[-1]


def render(doc):
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, 'points.png')
        exporter = document.AsyncExport(doc, bitmapdpi=96)
        exporter.add(path, [0])
        exporter.finish()
        image = qt.QImage(path).convertToFormat(qt.QImage.Format.Format_RGBA8888)
        return np.frombuffer(image.bits().asstring(image.sizeInBytes()),
                             dtype=np.uint8).reshape(image.height(), image.width(), 4).copy()


class MissingErrorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_legacy_mask_and_aligned_ranges(self):
        ds = datasets.Dataset([1, 2, 3], nerr=[1, np.nan, 1], perr=[1, 1, np.inf])
        np.testing.assert_array_equal(ds.invalidDataPoints(), [False, True, True])
        lo, hi = ds.getPointRanges(finite=False)
        self.assertEqual(len(lo), 3)
        self.assertTrue(np.isnan(lo[1]))
        self.assertTrue(np.isinf(hi[2]))
        self.assertEqual(tuple(map(len, ds.getPointRanges())), (2, 2))
        for mode in (True, False):
            parts = list(datasets.generateValidDatasetParts([ds], breakds=mode))
            self.assertEqual(sum(len(p[0]) for p in parts), 1)
            parts = list(datasets.generateValidDatasetParts([ds], breakds=mode, ignoreerrors=True))
            self.assertEqual(sum(len(p[0]) for p in parts), 3)
            self.assertTrue(np.isnan(parts[0][0].nerr[1]))

    def test_native_marker_reproduction(self):
        for mode in ('break-on', 'ignore'):
            for errors in ({'serr': [1, 1, np.nan, 1, 1]},
                           {'nerr': [1, 1, np.nan, 1, 1], 'perr': [1]*5},
                           {'serr': [1, 1, np.inf, 1, 1]}):
                for policy in ('hide-point', 'hide-error'):
                    with self.subTest(mode=mode, errors=errors, policy=policy):
                        doc, ci, plot = make_plot(policy, mode, errors)
                        ci.Set('PlotLine/hide', True)
                        ci.Set('errorStyle', 'none')
                        pixels = render(doc)
                        self.assertEqual(bool(np.any(pixels[92:100, 92:100, :3] < 100)),
                                         policy == 'hide-error')
                        self.assertFalse(np.isfinite(doc.data['y'].serr[2]) if 'serr' in errors
                                         else np.isfinite(doc.data['y'].nerr[2]))

    def test_native_line_gaps(self):
        for mode in ('break-on', 'ignore'):
            for policy in ('hide-point', 'hide-error'):
                for hole in (False, np.nan, np.inf):
                    with self.subTest(mode=mode, policy=policy, hole=hole):
                        values = [3, 3, 3 if hole is False else hole, 3, 3]
                        doc, ci, plot = make_plot(policy, mode, values=values)
                        ci.Set('MarkerLine/hide', True)
                        ci.Set('MarkerFill/hide', True)
                        ci.Set('errorStyle', 'none')
                        ci.Set('PlotLine/hide', False)
                        ci.Set('PlotLine/width', '2pt')
                        pixels = render(doc)
                        connected = mode == 'ignore' or (policy == 'hide-error' and hole is False)
                        self.assertEqual(bool(np.any(pixels[94:98, 90:102, :3] < 100)), connected)

    def test_native_error_styles_finite_and_bands_break(self):
        for style in point.ErrorBarDraw.error_functions:
            with self.subTest(style=style):
                doc, ci, plot = make_plot('hide-error')
                doc.setData('x', datasets.Dataset([1, 2, 3, 4, 5], serr=[.3]*5))
                ci.Set('errorStyle', style)
                ci.Set('MarkerLine/hide', True)
                ci.Set('MarkerFill/hide', True)
                ci.Set('PlotLine/hide', True)
                # All native error functions must see finite, aligned geometry.
                original = point.ErrorBarDraw.plot
                calls = []
                def checked(obj, painter, *args, **kwargs):
                    arrays = [a for a in args[:-1] if a is not None]
                    self.assertTrue(all(np.isfinite(a).all() for a in arrays))
                    self.assertEqual(len(set(map(len, arrays))), 1)
                    calls.append(args)
                    return original(obj, painter, *args, **kwargs)
                with patch.object(point.ErrorBarDraw, 'plot', checked):
                    pixels = render(doc)
                if style != 'none':
                    self.assertTrue(calls)
                if style == 'fillvert':
                    self.assertFalse(np.any(pixels[76:85, 94:98, :3] < 100))

    def test_all_finite_error_styles_match_legacy_pixels(self):
        for style, transparency in itertools.product(
                point.ErrorBarDraw.error_functions, (0, 50)):
            with self.subTest(style=style, transparency=transparency):
                images = []
                for policy in ('hide-point', 'hide-error'):
                    doc, ci, plot = make_plot(policy, errors={'serr': [1]*5})
                    doc.setData('x', datasets.Dataset([1, 2, 3, 4, 5], serr=[.3]*5))
                    ci.Set('errorStyle', style)
                    ci.Set('MarkerLine/hide', True)
                    ci.Set('MarkerFill/hide', True)
                    ci.Set('PlotLine/hide', True)
                    ci.Set('FillAbove/color', 'black')
                    ci.Set('FillBelow/color', 'black')
                    for section in ('ErrorBarLine', 'FillAbove', 'FillBelow'):
                        ci.Set(section+'/transparency', transparency)
                    images.append(render(doc))
                np.testing.assert_array_equal(*images)

    def test_save_reload_policy(self):
        for policy in ('hide-point', 'hide-error'):
            doc, ci, plot = make_plot(policy)
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, 'missing.vsz')
                doc.save(path)
                with patch.object(document.Document, 'loadPlugins'):
                    loaded = document.Document()
                loaded.load(path)
                restored = loaded.basewidget.children[0].children[0].children[-1]
                self.assertEqual(restored.settings.missingErrors, policy)
                np.testing.assert_array_equal(render(doc), render(loaded))

    def test_svg_native_sanity(self):
        for style in ('barbox', 'bardiamond', 'barcurve', 'fillvert', 'fillhorz'):
            doc, ci, plot = make_plot('hide-error')
            doc.setData('x', datasets.Dataset([1, 2, 3, 4, 5], serr=[.3]*5))
            ci.Set('errorStyle', style)
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, 'missing.svg')
                exporter = document.AsyncExport(doc, svgdpi=96)
                exporter.add(path, [0])
                exporter.finish()
                native = render(doc)
                image = qt.QImage(192, 192, qt.QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(qt.Qt.GlobalColor.transparent)
                renderer = qt.QSvgRenderer(path)
                self.assertTrue(renderer.isValid())
                painter = qt.QPainter(image)
                renderer.render(painter)
                painter.end()
                image = image.convertToFormat(qt.QImage.Format.Format_RGBA8888)
                svg = np.frombuffer(image.bits().asstring(image.sizeInBytes()),
                                    dtype=np.uint8).reshape(192, 192, 4)
                # Different engines antialias vector edges differently; compare
                # alpha occupancy, allowing local edge differences only.
                delta = np.abs(native.astype(int) - svg.astype(int))
                self.assertLess(float(delta.mean()), 2.)

    def test_composite_errors_retain_bar_without_incomplete_shape(self):
        for style in ('barbox', 'bardiamond', 'barcurve'):
            for mode in ('break-on', 'ignore'):
                with self.subTest(style=style, mode=mode):
                    images = []
                    for selected in ('bar', style):
                        doc, ci, plot = make_plot('hide-error', mode)
                        doc.setData('x', datasets.Dataset([1, 2, 3, 4, 5], serr=[.3]*5))
                        ci.Set('errorStyle', selected)
                        ci.Set('MarkerLine/hide', True)
                        ci.Set('MarkerFill/hide', True)
                        ci.Set('PlotLine/hide', True)
                        ci.Set('ErrorBarLine/width', '2pt')
                        images.append(render(doc))
                    # At the missing Y pair, only the surviving X bar remains.
                    np.testing.assert_array_equal(images[0][68:124, 87:105],
                                                  images[1][68:124, 87:105])
                    self.assertTrue(np.any(images[1][94:98, 92:100, :3] < 100))
                    # A complete neighboring pair still has an enclosing shape.
                    self.assertTrue(np.any(images[0][68:124, 40:57] !=
                                           images[1][68:124, 40:57]))

    def test_native_asymmetric_error_pairs_and_independent_axes(self):
        for mode in ('break-on', 'ignore'):
            for policy in ('hide-point', 'hide-error'):
                for component in ('nerr', 'perr'):
                    with self.subTest(mode=mode, policy=policy, component=component):
                        errors = {'nerr': [1]*5, 'perr': [1]*5}
                        errors[component][2] = np.nan
                        doc, ci, plot = make_plot(policy, mode, errors)
                        doc.setData('x', datasets.Dataset([1, 2, 3, 4, 5], serr=[.3]*5))
                        ci.Set('MarkerLine/hide', True)
                        ci.Set('MarkerFill/hide', True)
                        ci.Set('PlotLine/hide', True)
                        ci.Set('ErrorBarLine/width', '2pt')
                        pixels = render(doc)
                        # The complete horizontal pair survives independently.
                        self.assertEqual(bool(np.any(pixels[94:98, 92:100, :3] < 100)),
                                         policy == 'hide-error')
                        # Neither half of the incomplete vertical pair is drawn.
                        self.assertFalse(np.any(pixels[74:87, 94:98, :3] < 100))
                        self.assertFalse(np.any(pixels[105:118, 94:98, :3] < 100))

    def test_native_bands_break_even_when_data_gaps_ignored(self):
        for mode in ('break-on', 'ignore'):
            for errors in ({'serr': [1, 1, np.nan, 1, 1]},
                           {'perr': [1]*5, 'nerr': [1, 1, np.nan, 1, 1]}):
                with self.subTest(mode=mode, errors=errors):
                    doc, ci, plot = make_plot('hide-error', mode, errors)
                    ci.Set('errorStyle', 'fillvert')
                    ci.Set('MarkerLine/hide', True)
                    ci.Set('MarkerFill/hide', True)
                    ci.Set('PlotLine/hide', True)
                    ci.Set('FillAbove/color', 'black')
                    ci.Set('FillBelow/color', 'black')
                    pixels = render(doc)
                    self.assertTrue(np.any(pixels[78:84, 54:65, :3] < 100))
                    self.assertFalse(np.any(pixels[78:84, 90:102, :3] < 100))

    def test_thinned_bands_do_not_bridge_skipped_missing_row(self):
        for style, mode in itertools.product(('fillvert', 'fillhorz'), ('break-on', 'ignore')):
            with self.subTest(style=style, mode=mode):
                doc, ci, plot = make_plot('hide-error', mode,
                                          {'serr': [1, np.nan, 1, 1, 1]})
                if style == 'fillhorz':
                    doc.setData('x', datasets.Dataset([3]*5, serr=[1, np.nan, 1, 1, 1]))
                    doc.setData('y', datasets.Dataset([1, 2, 3, 4, 5]))
                ci.Set('errorStyle', style)
                ci.Set('errorthin', 2)
                ci.Set('MarkerLine/hide', True)
                ci.Set('MarkerFill/hide', True)
                ci.Set('PlotLine/hide', True)
                ci.Set('FillAbove/color', 'black')
                ci.Set('FillBelow/color', 'black')
                pixels = render(doc)
                if style == 'fillvert':
                    gap, filled = pixels[78:84, 68:76], pixels[78:84, 108:116]
                else:
                    gap, filled = pixels[116:124, 78:84], pixels[76:84, 78:84]
                self.assertFalse(np.any(gap[..., :3] < 100))
                self.assertTrue(np.any(filled[..., :3] < 100))

    def test_centred_steps_missing_errors_use_midpoints(self):
        for steps in ('centre', 'vcentre'):
            doc, ci, plot = make_plot('hide-error', values=[1, 2, 3, 4, 5])
            doc.setData('x', datasets.Dataset([1, 2, 3, 4, 5], serr=[1, 1, np.nan, 1, 1]))
            ci.Set('PlotLine/steps', steps)
            ci.Set('PlotLine/hide', False)
            ci.Set('errorStyle', 'none')
            original = plot._getLinePoints
            calls = []
            def checked(*args):
                polygon = original(*args)
                self.assertTrue(all(np.isfinite([p.x(), p.y()]).all() for p in polygon))
                xvals, yvals = args[:2]
                if steps == 'centre':
                    self.assertAlmostEqual(polygon[1].x(), (xvals[0]+xvals[1])/2)
                    self.assertAlmostEqual(polygon[1].y(), yvals[0])
                else:
                    self.assertAlmostEqual(polygon[1].x(), xvals[0])
                    self.assertAlmostEqual(polygon[1].y(), (yvals[0]+yvals[1])/2)
                calls.append(polygon)
                return polygon
            with patch.object(plot, '_getLinePoints', checked):
                render(doc)
            self.assertTrue(calls)

    def test_numerical_autorange(self):
        for policy in ('hide-point', 'hide-error'):
            for mode in ('break-on', 'ignore'):
                for errors in ({'serr': [1, 1, np.nan, 1, 1]},
                               {'nerr': [1, 1, np.nan, 1, 1], 'perr': [1]*5}):
                    with self.subTest(policy=policy, mode=mode, errors=errors):
                        doc, ci, plot = make_plot(policy, mode, errors, [2, 3, 100, 4, 5])
                        axis = plot.parent.getAxes(('y',))[0]
                        result = [np.inf, -np.inf]
                        plot.getRange(axis, 'sy', result)
                        # Legacy already ranges over the central datum; opt-in
                        # also excludes the other half of an incomplete pair.
                        expected = 101 if policy == 'hide-point' and 'perr' in errors else 100
                        np.testing.assert_allclose(result, [1, expected])
        for bad in (np.nan, np.inf, -np.inf):
            doc, ci, plot = make_plot('hide-error', values=[2, 3, bad, 4, 5])
            axis = plot.parent.getAxes(('y',))[0]
            for log in (False, True):
                axis.settings.log = log
                result = [np.inf, -np.inf]
                plot.getRange(axis, 'sy', result)
                np.testing.assert_allclose(result, [1, 6])


if __name__ == '__main__':
    unittest.main()
