"""Native source regressions for single-group sizing and legend ordering."""
import unittest
from unittest.mock import patch
import numpy as np
from veusz import document, qtall as qt
from veusz.widgets.bar import BarPlotter
from veusz.widgets.key import Key
from test_bar_stacking import make_document


def paint(doc, size=(200, 500)):
    helper = document.PaintHelper(doc, size, dpi=(100, 100))
    doc.paintTo(helper, 0)
    image = qt.QImage(*size, qt.QImage.Format.Format_ARGB32)
    image.fill(qt.Qt.GlobalColor.white)
    painter = qt.QPainter(image)
    try:
        helper.renderToPainter(painter)
    finally:
        painter.end()
    return image


class BarWidthAndKeyOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_single_group_uses_position_axis_span(self):
        original = BarPlotter.findBarPositions
        for direction in ('vertical', 'horizontal'):
            for mode in ('grouped', 'stacked'):
                for size in ((200, 500), (500, 200)):
                    with self.subTest(direction=direction, mode=mode, size=size):
                        doc = make_document([[2.], [3.]], direction=direction)
                        ci = document.CommandInterface(doc)
                        ci.Set('/width', '%sin' % (size[0]/100))
                        ci.Set('/height', '%sin' % (size[1]/100))
                        ci.Set('/page/graph/bars/mode', mode)
                        calls = []
                        def positions(plotter, *args):
                            values, width = original(plotter, *args)
                            bounds = args[-1]
                            span = bounds[3]-bounds[1] if direction == 'horizontal' else bounds[2]-bounds[0]
                            calls.append((width, span))
                            return values, width
                        with patch.object(BarPlotter, 'findBarPositions', positions):
                            self.assertFalse(paint(doc, size).isNull())
                        self.assertTrue(calls)
                        for width, expected in calls:
                            self.assertAlmostEqual(width, expected)

    def test_multiple_groups_still_use_coordinate_spacing(self):
        original = BarPlotter.findBarPositions
        for direction in ('vertical', 'horizontal'):
            doc = make_document([[2., 3., 1.], [1., 2., 3.]], direction=direction)
            calls = []
            def positions(plotter, *args):
                values, width = original(plotter, *args)
                calls.append((width, np.abs(np.diff(values)).min()))
                return values, width
            with patch.object(BarPlotter, 'findBarPositions', positions):
                paint(doc)
            for width, expected in calls:
                self.assertAlmostEqual(width, expected)

    def test_reverse_flattened_legend_entries(self):
        original = Key._layout
        for mode in ('stacked', 'stacked-area', 'grouped'):
            for order, exclude, hidden in (('', '', False), ('other,bars', '', False),
                                           ('other,bars', 'other', False), ('', '', True)):
                for columns in (1, 2):
                    with self.subTest(mode=mode, order=order, exclude=exclude, hidden=hidden, columns=columns):
                        doc = make_document([[2.], [3.]])
                        ci = document.CommandInterface(doc)
                        ci.To('/page/graph/bars')
                        ci.Set('mode', mode)
                        ci.Set('keys', ['First', r'Second\\line'])
                        ci.To('/page/graph')
                        ci.Add('xy', name='other', autoadd=False)
                        ci.To('other')
                        ci.Set('xData', 'd0'); ci.Set('yData', 'd1')
                        ci.Set('key', 'Other'); ci.Set('hide', hidden)
                        ci.To('/page/graph')
                        ci.Add('key', name='legend', autoadd=False)
                        ci.To('legend')
                        ci.Set('order', order); ci.Set('exclude', exclude)
                        ci.Set('columns', columns)
                        orders = []
                        def layout(key, entries, total):
                            orders.append([(w.name, index, lines) for w, index, lines in entries])
                            return original(key, entries, total)
                        with patch.object(Key, '_layout', layout):
                            ci.Set('orderswap', False); paint(doc)
                            ci.Set('orderswap', True); paint(doc)
                        self.assertEqual(len(orders), 2)
                        self.assertGreaterEqual(len(orders[0]), 2)
                        self.assertEqual(orders[1], list(reversed(orders[0])))


if __name__ == '__main__':
    unittest.main()
