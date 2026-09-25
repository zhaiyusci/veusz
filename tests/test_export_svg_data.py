"""Data semantics and full-scene SVG regression tests (no external browser)."""
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from veusz import document, qtall as qt, utils
from veusz.widgets import image as image_widget
from svg_data_cases import data_cases, make_data_document
from test_export_svg import export_pair, pixels_on_white, svg_images


class HeatmapDataSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=qt.QApplication.instance() or qt.QApplication([])

    def test_scaling_known_values(self):
        values=np.array([[0.,1.,2.,3.,4.]])
        expected={
            'linear':[0.,.25,.5,.75,1.],
            'sqrt':[0.,.5,np.sqrt(.5),np.sqrt(.75),1.],
            'squared':[0.,.0625,.25,.5625,1.],
        }
        for mode,result in expected.items():
            with self.subTest(mode=mode):
                original=values.copy()
                np.testing.assert_allclose(utils.applyScaling(values,mode,0,4),[result])
                np.testing.assert_array_equal(values,original)
        logarithmic=np.array([[1.,10.,100.,0.,-1.]])
        actual=utils.applyScaling(logarithmic,'log',1,100)
        np.testing.assert_allclose(actual[0,:3],[0,.5,1])
        self.assertTrue(np.isnan(actual[0,3:]).all())
        np.testing.assert_array_equal(utils.applyScaling(values,'linear',2,2),values)

    def test_colormap_limits_and_reversal(self):
        cmap=np.array([[0,0,0,255],[255,255,255,255]],dtype=np.intc)
        values=np.array([[-1.,0.,.5,1.,2.]])
        original=cmap.copy()
        normal=utils.applyColorMap(cmap,'linear',values,0,1,0)
        reversedmap=utils.applyColorMap(cmap,'linear',values,1,0,0)
        self.assertEqual(normal.pixelColor(0,0).red(),0)
        self.assertEqual(normal.pixelColor(4,0).red(),255)
        self.assertLessEqual(abs(normal.pixelColor(2,0).red()-127),1)
        self.assertEqual(reversedmap.pixelColor(0,0).red(),255)
        self.assertEqual(reversedmap.pixelColor(4,0).red(),0)
        np.testing.assert_array_equal(cmap,original)

    def test_full_svg_composition(self):
        selected=('scale-log','scale-sqrt','range-reversed','alpha-map',
                  'mask-with-global-alpha','mask-with-nan','dark-background',
                  'overlapping','fractional','grid-centers','values-nan',
                  'values-checker','values-impulses','mask-gradient','mask-binary',
                  'mask-zero','mask-out-of-range','mask-mismatched')
        cases=[c for c in data_cases() if any(c['name']==s+'-'+c['mode'] for s in selected)]
        with tempfile.TemporaryDirectory() as folder:
            for case in cases:
                with self.subTest(case=case['name']):
                    doc=make_data_document(case)
                    original=doc.data['z'].data.copy()
                    svg,png=export_pair(doc,folder,150)
                    native=qt.QImage(png)
                    actual=qt.QImage(native.size(),qt.QImage.Format.Format_ARGB32_Premultiplied)
                    actual.fill(qt.Qt.GlobalColor.transparent)
                    renderer=qt.QSvgRenderer(svg)
                    self.assertTrue(renderer.isValid())
                    painter=qt.QPainter(actual)
                    renderer.render(painter,qt.QRectF(0,0,native.width(),native.height()))
                    painter.end()
                    # Exclude only the outer graph clip boundary, not cell edges.
                    def rgba(image):
                        image=image.convertToFormat(qt.QImage.Format.Format_RGBA8888)
                        return np.frombuffer(image.bits().asstring(image.sizeInBytes()),
                                             dtype=np.uint8).reshape(
                                                 image.height(),image.width(),4).astype(int)
                    # Compare alpha as well: white-only compositing concealed
                    # the old RGB32 mask bug's accidental background knockout.
                    delta=np.abs(rgba(native)-rgba(actual))[41:259,41:259]
                    if svg_images(svg):
                        self.assertLessEqual(int(delta.max()),2)
                    else:
                        # Preserved vector cells have renderer-specific edge AA.
                        self.assertLessEqual(float(delta.mean()),1)
                    np.testing.assert_array_equal(doc.data['z'].data,original)

    def test_svg_processes_data_only_once(self):
        for mode in ('default','resample-pixels','resample-smooth'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                doc=make_data_document(dict(name='once',mode=mode))
                with patch.object(image_widget.utils,'applyColorMap',
                                  wraps=image_widget.utils.applyColorMap) as convert:
                    task=document.AsyncExport(doc,svgdpi=150)
                    task.add(os.path.join(folder,'once.svg'),[0])
                    task.finish()
                    self.assertEqual(convert.call_count,1)

    def test_opaque_colormap_transparency_mask(self):
        """Transparency data must retain a real alpha-capable image format."""
        cmap=np.array([[0,0,0,255],[255,255,255,255]],dtype=np.intc)
        image=utils.applyColorMap(cmap,'linear',np.ones((2,2)),0,1,0,
                                 transimg=np.zeros((2,2)))
        self.assertEqual(image.pixelColor(0,0).alpha(),0)

    def test_reversed_resampling_is_nonempty(self):
        """Reversed axes must not pass negative QImage.scaled dimensions."""
        doc=make_data_document(dict(name='reverse',mode='resample-pixels',reverse='x'))
        with tempfile.TemporaryDirectory() as folder:
            _,png=export_pair(doc,folder,96)
            image=qt.QImage(png)
            # The graph background is opaque white even when no heatmap drew.
            rgb=pixels_on_white(image)[24:168,24:168,:3]
            self.assertTrue(np.any(rgb != 255))


if __name__=='__main__':
    unittest.main()
