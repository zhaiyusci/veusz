"""Independent format, alpha and source-over regressions for heatmap masks."""
import unittest
import numpy as np
from veusz import qtall as qt, utils
from veusz.helpers import qtloops


class ImageTransparencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_force_alpha_preserves_format(self):
        cmap = np.array([[0, 0, 0, 255], [255, 255, 255, 255]], dtype=np.intc)
        data = np.full((3, 4), .5)
        opaque = qtloops.numpyToQImage(data, cmap, False)
        forced = qtloops.numpyToQImage(data, cmap, True)
        self.assertFalse(opaque.hasAlphaChannel())
        self.assertTrue(forced.hasAlphaChannel())
        self.assertEqual(forced.format(), qt.QImage.Format.Format_ARGB32)
        self.assertEqual(forced.pixelColor(0, 0).getRgb(), (128, 128, 128, 255))

    def test_mask_values_orientation_and_global_transparency(self):
        cmap = np.array([[0, 0, 0, 255], [255, 255, 255, 255]], dtype=np.intc)
        data = np.full((3, 4), .5)
        mask = np.array([[0., .25, .5, 1.], [1., .5, .25, 0.], [-1., 2., .1, .9]])
        original = mask.copy()
        for trans in (0, 1, 37, 50, 100):
            with self.subTest(trans=trans):
                image = utils.applyColorMap(cmap, 'linear', data, 0, 1, trans,
                                           transimg=mask)
                self.assertTrue(image.hasAlphaChannel())
                for y in range(3):
                    for x in range(4):
                        alpha = int(int(255*(100-trans)/100) * np.clip(mask[y, x], 0, 1))
                        self.assertEqual(image.pixelColor(x, 2-y).getRgb(),
                                         (128, 128, 128, alpha))
                np.testing.assert_array_equal(mask, original)

    def test_source_over_preserves_opaque_background(self):
        cmap = np.array([[0, 0, 0, 255], [255, 255, 255, 255]], dtype=np.intc)
        for background in ((255, 255, 255), (255, 0, 255), (17, 61, 103)):
            for mask in (0., .25, .5, 1.):
                with self.subTest(background=background, mask=mask):
                    source = utils.applyColorMap(cmap, 'linear', np.array([[.5]]),
                                                 0, 1, 0, transimg=np.array([[mask]]))
                    dest = qt.QImage(1, 1, qt.QImage.Format.Format_ARGB32_Premultiplied)
                    dest.fill(qt.QColor(*background))
                    painter = qt.QPainter(dest)
                    painter.drawImage(0, 0, source)
                    painter.end()
                    actual = dest.pixelColor(0, 0).getRgb()
                    alpha = int(255*mask)/255
                    expected = [round(128*alpha+b*(1-alpha)) for b in background]
                    self.assertEqual(actual[3], 255)
                    self.assertTrue(all(abs(a-b) <= 1 for a, b in zip(actual[:3], expected)))

    def test_uniform_mask_matches_global_transparency(self):
        cmap = np.array([[0, 0, 0, 255], [255, 255, 255, 255]], dtype=np.intc)
        data = np.full((3, 4), .5)
        for mask, trans in ((0., 100), (.25, 75), (.5, 50), (1., 0)):
            with self.subTest(mask=mask):
                masked = utils.applyColorMap(cmap, 'linear', data, 0, 1, 0,
                                            transimg=np.full(data.shape, mask))
                global_alpha = utils.applyColorMap(cmap, 'linear', data, 0, 1, trans)
                for y in range(3):
                    for x in range(4):
                        self.assertEqual(masked.pixelColor(x, y).getRgb(),
                                         global_alpha.pixelColor(x, y).getRgb())


if __name__ == '__main__':
    unittest.main()
