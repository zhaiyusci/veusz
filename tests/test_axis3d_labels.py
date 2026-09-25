"""Keep 3D axis titles independent of tick-label visibility (#288)."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from veusz import document, qtall as qt
from veusz.widgets import axis3d


def make_scene(hide_ticks=True, hide_title=False):
    with patch.object(document.Document, 'loadPlugins'):
        doc = document.Document()
    ci = document.CommandInterface(doc)
    ci.Add('page', name='page', autoadd=False)
    ci.To('/page')
    ci.Set('width', '4in')
    ci.Set('height', '4in')
    ci.Add('scene3d', name='scene', autoadd=False)
    ci.To('scene')
    ci.Add('graph3d', name='graph')
    for direction in ('x', 'y', 'z'):
        path = '/page/scene/graph/'+direction
        ci.Set(path+'/label', 'AXIS_'+direction.upper())
        ci.Set(path+'/TickLabels/hide', hide_ticks)
        ci.Set(path+'/Label/hide', hide_title)
    return doc


class Axis3DLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_independent_visibility_and_position(self):
        for hide_ticks in (False, True):
            for hide_title in (False, True):
                for position in ('at-minimum', 'centre', 'at-maximum'):
                    with self.subTest(ticks=hide_ticks, title=hide_title, position=position):
                        axis = SimpleNamespace(
                            autoformat='%g', document=SimpleNamespace(locale=qt.QLocale.c()))
                        ticks = SimpleNamespace(hide=hide_ticks, format='auto', scale=1)
                        title = SimpleNamespace(hide=hide_title, position=position)
                        container = Mock()
                        with patch.object(axis3d, '_AxisLabels') as labels:
                            axis3d.Axis3D.addLabels(
                                axis, container, [((0,0,0),(1,0,0))], ticks,
                                [0., .5, 1.], [0., 5., 10.], 'Title', title)
                        if hide_ticks and hide_title:
                            container.addObject.assert_not_called()
                        else:
                            labels.assert_called_once()
                            args = labels.call_args.args
                            self.assertEqual(args[3], [] if hide_ticks else ['0','5','10'])
                            self.assertEqual(args[5], '' if hide_title else 'Title')
                            self.assertEqual(args[6], -1 if hide_title else
                                             {'at-minimum':0,'centre':.5,'at-maximum':1}[position])
                            container.addObject.assert_called_once()

    def test_empty_title_without_ticks_adds_no_object(self):
        container = Mock()
        axis3d.Axis3D.addLabels(
            SimpleNamespace(), container, [], SimpleNamespace(hide=True),
            [], [], '', SimpleNamespace(hide=False))
        container.addObject.assert_not_called()

    def test_actual_render_independent_visibility(self):
        original_title = axis3d._AxisLabels.drawAxisLabel
        original_tick = axis3d._AxisLabels.drawTickLabel
        for hide_ticks, hide_title in ((True,False),(False,True),(True,True),(False,False)):
            with self.subTest(ticks=hide_ticks, title=hide_title):
                titles, ticks = [], []
                def draw_title(self, painter, valign):
                    titles.append(self.axislabel)
                    return original_title(self, painter, valign)
                def draw_tick(self, painter, x, y, angle, index, valign):
                    ticks.append(self.ticklabels[index])
                    return original_tick(self, painter, x, y, angle, index, valign)
                doc = make_scene(hide_ticks, hide_title)
                with tempfile.TemporaryDirectory() as folder, \
                     patch.object(axis3d._AxisLabels, 'drawAxisLabel', draw_title), \
                     patch.object(axis3d._AxisLabels, 'drawTickLabel', draw_tick):
                    task = document.AsyncExport(doc, bitmapdpi=96)
                    task.add(os.path.join(folder, 'scene.png'), [0])
                    task.finish()
                self.assertEqual(set(titles), set() if hide_title else {'AXIS_X','AXIS_Y','AXIS_Z'})
                self.assertEqual(bool(ticks), not hide_ticks)


if __name__ == '__main__':
    unittest.main()
