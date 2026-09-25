"""SVG heatmap rasterization tests using the native renderer and PNG reference."""
import base64
import math
import os
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np

from veusz import document, qtall as qt, widgets, dataimport


def make_document(mode='default', size=40, logarithmic=False, irregular=False,
                  crop=False, reverse=False, transparent=False, fractional=False):
    with patch.object(document.Document, 'loadPlugins'):
        doc = document.Document()
    ci = document.CommandInterface(doc)
    ci.Set('width', '2in')
    ci.Set('height', '2in')
    y, x = np.mgrid[0:size, 0:size]
    data = np.sin(x*.37) + np.cos(y*.29) + (x+y)/(2*size)
    if transparent:
        data[3:7, 4:8] = np.nan
    kwargs = dict(xrange=(1, 101), yrange=(1, 101))
    if irregular:
        kwargs = dict(xedge=np.geomspace(1, 101, size+1),
                      yedge=np.linspace(1, 101, size+1))
    ci.SetData2D('z', data, **kwargs)
    ci.Add('page', name='page', autoadd=False)
    ci.To('page')
    ci.Add('graph', name='graph', autoadd=True)
    ci.To('graph')
    # Isolate the heatmap pixels from the separate vector graph frame.
    ci.Set('Border/hide', True)
    margin = '.253in' if fractional else '.25in'
    for side in ('left', 'right', 'top', 'bottom'):
        ci.Set(side+'Margin', margin)
    for axis in ('x', 'y'):
        ci.Set(axis+'/min', 1.0)
        ci.Set(axis+'/max', 101.0)
        ci.Set(axis+'/hide', True)
    if logarithmic:
        ci.Set('x/log', True)
    if reverse:
        ci.Set('x/min', 101.0)
        ci.Set('x/max', 1.0)
        ci.Set('y/min', 101.0)
        ci.Set('y/max', 1.0)
    if crop:
        ci.Set('x/min', 11.2)
        ci.Set('x/max', 71.7)
        ci.Set('y/min', 18.4)
        ci.Set('y/max', 88.1)
    ci.Add('image', name='heatmap', autoadd=False)
    ci.To('heatmap')
    ci.Set('data', 'z')
    ci.Set('drawMode', mode)
    ci.Set('colorMap', 'spectrum')
    if transparent:
        ci.Set('transparency', 37)
    return doc


def export_pair(doc, folder, dpi, name='image'):
    exporter = document.AsyncExport(doc, bitmapdpi=dpi, svgdpi=dpi)
    paths = [os.path.join(folder, name+ext) for ext in ('.svg', '.png')]
    for path in paths:
        exporter.add(path, [0])
        exporter.finish()
    return paths


def svg_images(path):
    root = ET.parse(path).getroot()
    pageinches = float(root.attrib['width'][:-2])/72
    viewwidth = float(root.attrib['viewBox'].split()[2])
    factor = pageinches/viewwidth
    result = []
    for node in root.iter():
        if node.tag.endswith('}image'):
            image = qt.QImage.fromData(base64.b64decode(node.attrib[
                '{http://www.w3.org/1999/xlink}href'].split(',', 1)[1]))
            rect = [float(node.attrib[k])*factor for k in ('x','y','width','height')]
            result.append((image, rect))
    return result


def pixels_on_white(image):
    white = qt.QImage(image.size(), qt.QImage.Format.Format_RGB32)
    white.fill(qt.Qt.GlobalColor.white)
    painter = qt.QPainter(white)
    painter.drawImage(0, 0, image)
    painter.end()
    rgba = white.convertToFormat(qt.QImage.Format.Format_RGBA8888)
    return np.frombuffer(rgba.bits().asstring(rgba.sizeInBytes()), dtype=np.uint8).reshape(
        rgba.height(), rgba.width(), 4).copy()


class SVGHeatmapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_raster_matches_png(self):
        cases = [
            {}, {'mode':'resample-pixels'}, {'mode':'resample-smooth'},
            {'mode':'resample-pixels','logarithmic':True},
            {'mode':'resample-smooth','logarithmic':True},
            {'mode':'resample-pixels','irregular':True},
            {'mode':'resample-smooth','irregular':True},
            {'mode':'resample-pixels','crop':True},
            {'mode':'resample-smooth','crop':True},
            {'transparent':True}, {'fractional':True},
            {'mode':'resample-smooth','fractional':True,'transparent':True},
            {'reverse':True},
        ]
        with tempfile.TemporaryDirectory() as folder:
            for dpi in (96, 150, 300):
                for options in cases:
                    with self.subTest(dpi=dpi, **options):
                        svg, png = export_pair(make_document(**options), folder, dpi)
                        images = svg_images(svg)
                        self.assertEqual(len(images), 1)
                        image, rect = images[0]
                        self.assertAlmostEqual(image.width()/rect[2], dpi, places=4)
                        self.assertAlmostEqual(image.height()/rect[3], dpi, places=4)
                        reference = qt.QImage(png).copy(
                            round(rect[0]*dpi), round(rect[1]*dpi),
                            image.width(), image.height())
                        delta = np.abs(pixels_on_white(image).astype(int) -
                                       pixels_on_white(reference).astype(int))
                        self.assertLessEqual(int(delta.max()), 2)

    def test_inserted_bitmap_is_not_resampled(self):
        doc = make_document()
        ci = document.CommandInterface(doc)
        ci.To('/page/graph/heatmap')
        ci.Set('hide', True)
        ci.To('/page')
        ci.Add('imagefile', name='bitmap', autoadd=False)
        ci.To('bitmap')
        image = qt.QImage(17, 13, qt.QImage.Format.Format_RGB32)
        image.fill(qt.Qt.GlobalColor.blue)
        data = qt.QByteArray()
        buffer = qt.QBuffer(data)
        buffer.open(qt.QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        buffer.close()
        ci.Set('filename', '{embedded}')
        ci.Set('embeddedImageData', bytes(data.toBase64()).decode('ascii'))
        with tempfile.TemporaryDirectory() as folder:
            svg, _ = export_pair(doc, folder, 300)
            images = svg_images(svg)
            self.assertEqual(len(images), 1)
            self.assertEqual(images[0][0].size(), image.size())

    def test_vector_modes_stay_vector(self):
        cases = [dict(mode='rectangles'), dict(size=29),
                 dict(size=30, crop=True), dict(crop=True),
                 dict(logarithmic=True), dict(irregular=True)]
        with tempfile.TemporaryDirectory() as folder:
            for options in cases:
                with self.subTest(**options):
                    svg, _ = export_pair(make_document(**options), folder, 150)
                    self.assertEqual(svg_images(svg), [])


if __name__ == '__main__':
    unittest.main()
