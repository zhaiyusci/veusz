"""Stacked bars: real source Qt rendering and segment geometry regressions."""
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

# Import Qt before the native qtloops helper on Windows.
from veusz import qtall as qt
from veusz import document, widgets
from veusz.widgets.bar import BarPlotter


def make_document(values, direction='vertical', transparency=50, logarithmic=False,
                  borders=False):
    with patch.object(document.Document, 'loadPlugins'):
        doc = document.Document()
    ci = document.CommandInterface(doc)
    ci.Set('width', '3in')
    ci.Set('height', '3in')
    for i, data in enumerate(values):
        ci.SetData('d%d' % i, data, symerr=np.full(len(data), .1))
    ci.Add('page', name='page', autoadd=False)
    ci.To('page')
    ci.Add('graph', name='graph', autoadd=True)
    ci.To('graph')
    ci.Set('Border/hide', True)
    for side in ('left', 'right', 'top', 'bottom'):
        ci.Set(side+'Margin', '.25in')
    for axis in ('x', 'y'):
        ci.Set(axis+'/hide', True)
    valueaxis, positionaxis = ('x', 'y') if direction == 'horizontal' else ('y', 'x')
    ci.Set(positionaxis+'/min', .5)
    ci.Set(positionaxis+'/max', len(values[0])+.5)
    ci.Set(valueaxis+'/min', .1 if logarithmic else -8.)
    ci.Set(valueaxis+'/max', 8.)
    ci.Set(valueaxis+'/log', logarithmic)
    ci.Add('bar', name='bars', autoadd=False)
    ci.To('bars')
    ci.Set('mode', 'stacked')
    ci.Set('direction', direction)
    ci.Set('lengths', ['d%d' % i for i in range(len(values))])
    ci.Set('errorstyle', 'none')
    colors = ('#ff0000', '#0000ff', '#00ff00', '#ffff00')
    ci.Set('BarFill/fills', [('solid', colors[i], False, transparency,
                             '0.5pt', 'solid', '5pt', 'white', 0, True)
                            for i in range(len(values))])
    ci.Set('BarLine/lines', [('solid', '1pt', colors[i], not borders)
                           for i in range(len(values))])
    return doc


def render(doc):
    with tempfile.TemporaryDirectory() as directory:
        filename = os.path.join(directory, 'bars.png')
        exporter = document.AsyncExport(doc, bitmapdpi=100,
                                        antialias=False)
        exporter.add(filename, [0])
        exporter.finish()
        image = qt.QImage(filename)
        if image.isNull():
            raise AssertionError('Qt export did not produce an image')
        return image


class BarStackingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_translucent_segments_render_independently(self):
        for direction in ('vertical', 'horizontal'):
            for transparency in (0, 50, 100):
                with self.subTest(direction=direction, transparency=transparency):
                    # Upper blue must never contribute to the lower red segment.
                    image = render(make_document([[2.], [2.]], direction,
                                                 transparency))
                    alpha = (100-transparency)/100
                    for value, color in ((1., (255, 0, 0)), (3., (0, 0, 255))):
                        along = 25 + (value+8)/16*250
                        x, y = ((int(along), 150) if direction == 'horizontal'
                                else (150, int(300-along)))
                        actual = image.pixelColor(x, y).getRgb()
                        expected = tuple(round(c*alpha+255*(1-alpha)) for c in color)
                        self.assertTrue(all(abs(a-b) <= 1 for a, b in
                                            zip(actual[:3], expected)),
                                        (direction, transparency, value, actual, expected))

    def test_mixed_sign_segments_errors_and_data_unchanged(self):
        values = [[2., -2., 0., 2.], [-3., 3., 0., 0.],
                  [4., -4., 1., -1.], [-1., 1., -2., 3.]]
        starts = [[0., 0., 0., 0.], [0., 0., 0., 2.],
                  [2., -2., 0., 0.], [-3., 3., 0., 2.]]
        ends = np.array(starts) + values
        for direction in ('vertical', 'horizontal'):
            doc = make_document(values, direction)
            doc.resolveWidgetPath(None, '/page/graph/bars').settings.errorstyle = 'barends'
            originals = {name: (ds.data.copy(), ds.serr.copy())
                         for name, ds in doc.data.items()}
            calls, errors = {}, []
            original_plot = BarPlotter.plotBars
            original_error = BarPlotter.drawErrorBars

            def plot(plotter, painter, settings, dsnum, clip, corners):
                calls[dsnum] = [np.array(c) for c in corners]
                return original_plot(plotter, painter, settings, dsnum, clip, corners)

            def error(plotter, painter, posns, width, vals, dataset, axes, bounds):
                errors.append(vals.copy())
                low, high = plotter.calculateErrorBars(dataset, vals)
                np.testing.assert_allclose(low, vals-.1)
                np.testing.assert_allclose(high, vals+.1)
                axis = axes[direction == 'vertical']
                i = len(errors)-1
                expected = [axis.dataToPlotterCoords(bounds, np.array(v))
                            for v in (starts[i], ends[i])]
                c = calls[i]
                actual = (c[0], c[2]) if direction == 'horizontal' else (c[1], c[3])
                for a, e in zip(actual, expected):
                    np.testing.assert_allclose(a, e)
                return original_error(plotter, painter, posns, width, vals,
                                      dataset, axes, bounds)

            with patch.object(BarPlotter, 'plotBars', plot), patch.object(
                    BarPlotter, 'drawErrorBars', error):
                render(doc)
            np.testing.assert_array_equal(errors, ends)
            self.assertEqual(list(calls), [3, 2, 1, 0])
            for name, (data, serr) in originals.items():
                np.testing.assert_array_equal(doc.data[name].data, data)
                np.testing.assert_array_equal(doc.data[name].serr, serr)

    def test_mixed_sign_and_zero_pixels(self):
        # The last zero-valued yellow layer must not tint either positive layer.
        values = [[2.], [-2.], [2.], [0.]]
        for direction in ('horizontal', 'vertical'):
            image = render(make_document(values, direction))
            for value, expected in ((1., (255, 128, 128)),
                                    (-1., (128, 128, 255)),
                                    (3., (128, 255, 128))):
                along = 25 + (value+8)/16*250
                x, y = ((int(along), 150) if direction == 'horizontal'
                        else (150, int(300-along)))
                actual = image.pixelColor(x, y).getRgb()[:3]
                self.assertTrue(all(abs(a-b) <= 1 for a, b in zip(actual, expected)),
                                (direction, value, actual, expected))

    def test_shared_border_keeps_lower_segment_style(self):
        for direction in ('horizontal', 'vertical'):
            image = render(make_document([[2.], [2.]], direction, borders=True))
            # The shared endpoint is painted red last, not the upper blue style.
            along = int(25 + (2+8)/16*250)
            x, y = ((along, 150) if direction == 'horizontal'
                    else (150, 300-along))
            # Qt's aliased stroke placement can round either way at half pixels.
            pixels = [image.pixelColor(x+delta if direction == 'horizontal' else x,
                                       y if direction == 'horizontal' else y+delta
                                       ).getRgb()[:3] for delta in (-1, 0, 1)]
            self.assertIn((255, 0, 0), pixels)
            self.assertNotIn((0, 0, 255), pixels)

    def test_logarithmic_rendering(self):
        for direction in ('horizontal', 'vertical'):
            image = render(make_document([[1.], [3.]], direction,
                                         logarithmic=True))
            for value, color in ((.5, (255, 128, 128)), (2., (128, 128, 255))):
                along = 25 + np.log(value/.1)/np.log(80)*250
                x, y = ((int(along), 150) if direction == 'horizontal'
                        else (150, int(300-along)))
                actual = image.pixelColor(x, y).getRgb()[:3]
                self.assertTrue(all(abs(a-b) <= 1 for a, b in zip(actual, color)),
                                (direction, value, actual, color))


if __name__ == '__main__':
    unittest.main()
