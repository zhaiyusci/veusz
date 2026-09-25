"""Native rendering regressions for explicitly resampled reversed heatmaps."""
import tempfile
import unittest
import numpy as np

from veusz import qtall as qt
from svg_data_cases import make_data_document
from test_export_svg import export_pair


def rgba(image):
    image = image.convertToFormat(qt.QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.bits().asstring(image.sizeInBytes()),
                         dtype=np.uint8).reshape(image.height(), image.width(), 4)


class ImageReversalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_reversed_resampling_mirrors_forward_render(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('resample-pixels', 'resample-smooth'):
                for dpi in (96, 192):
                    for alpha in (None, 'gradient'):
                        case = dict(name='reversal', mode=mode, alpha=alpha)
                        _, png = export_pair(make_data_document(case), folder, dpi)
                        expected = rgba(qt.QImage(png))
                        self.assertTrue(np.any(expected[dpi//2:dpi, dpi//2:dpi, :3] != 255))
                        for reverse in ('x', 'y', 'xy'):
                            with self.subTest(mode=mode, dpi=dpi, alpha=alpha, reverse=reverse):
                                doc = make_data_document(dict(case, reverse=reverse))
                                original = doc.data['z'].data.copy()
                                _, png = export_pair(doc, folder, dpi)
                                reference = expected
                                if 'x' in reverse:
                                    reference = reference[:, ::-1]
                                if 'y' in reverse:
                                    reference = reference[::-1]
                                np.testing.assert_array_equal(rgba(qt.QImage(png)), reference)
                                np.testing.assert_array_equal(doc.data['z'].data, original)

    def test_svg_and_png_match_for_reversed_and_cropped_images(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('resample-pixels', 'resample-smooth'):
                for reverse in ('x', 'y', 'xy'):
                    for crop in (False, True):
                        with self.subTest(mode=mode, reverse=reverse, crop=crop):
                            doc = make_data_document(dict(
                                name='svg-reversal', mode=mode, reverse=reverse,
                                crop=crop, alpha='gradient'))
                            svg, png = export_pair(doc, folder, 150)
                            native = qt.QImage(png)
                            actual = qt.QImage(native.size(), qt.QImage.Format.Format_ARGB32_Premultiplied)
                            actual.fill(qt.Qt.GlobalColor.transparent)
                            painter = qt.QPainter(actual)
                            renderer = qt.QSvgRenderer(svg)
                            self.assertTrue(renderer.isValid())
                            renderer.render(painter, qt.QRectF(0, 0, native.width(), native.height()))
                            painter.end()
                            a, b = rgba(native)[42:258,42:258], rgba(actual)[42:258,42:258]
                            self.assertTrue(np.any(a[:, :, :3] != 255))
                            self.assertLessEqual(int(np.abs(a.astype(int)-b.astype(int)).max()), 2)


if __name__ == '__main__':
    unittest.main()
