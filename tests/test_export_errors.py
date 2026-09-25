"""Regression tests for reporting failed exports (upstream issue #279)."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from veusz import document, qtall as qt
from veusz.document import export
from test_export_svg import make_document


class ExportErrorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def test_missing_directory_is_reported(self):
        for ext in ('png', 'jpg', 'bmp', 'pdf', 'svg', 'pic'):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as folder:
                filename = os.path.join(folder, 'missing', 'plot.'+ext)
                task = document.AsyncExport(make_document())
                task.add(filename, [0])
                with self.assertRaises(OSError) as raised:
                    task.finish()
                self.assertTrue(raised.exception.filename == filename or
                                filename in str(raised.exception))
                self.assertFalse(os.path.exists(filename))

    def test_existing_directory_is_not_an_output_file(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = os.path.join(folder, 'directory.png')
            os.mkdir(filename)
            task = document.AsyncExport(make_document())
            task.add(filename, [0])
            with self.assertRaises(OSError):
                task.finish()
            self.assertTrue(os.path.isdir(filename))

    def test_success_and_recovery_after_error(self):
        with tempfile.TemporaryDirectory() as folder:
            task = document.AsyncExport(make_document())
            task.add(os.path.join(folder, 'missing', 'plot.png'), [0])
            with self.assertRaises(OSError):
                task.finish()
            for ext in ('png', 'jpg', 'pdf', 'svg', 'pic'):
                with self.subTest(ext=ext):
                    filename = os.path.join(folder, 'valid.'+ext)
                    task.add(filename, [0])
                    task.finish()
                    self.assertGreater(os.path.getsize(filename), 0)

    def test_bitmap_writer_error_detail(self):
        writer = Mock()
        writer.write.return_value = False
        writer.errorString.return_value = 'simulated disk full'
        with tempfile.TemporaryDirectory() as folder:
            task = document.AsyncExport(make_document())
            with patch.object(export.qt, 'QImageWriter', return_value=writer):
                task.add(os.path.join(folder, 'plot.png'), [0])
                with self.assertRaisesRegex(OSError, 'simulated disk full'):
                    task.finish()

    def test_one_failed_export_fails_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            task = document.AsyncExport(make_document())
            task.add(os.path.join(folder, 'good.png'), [0])
            task.add(os.path.join(folder, 'missing', 'bad.png'), [0])
            task.add(os.path.join(folder, 'good.svg'), [0])
            with self.assertRaises(OSError):
                task.finish()
            self.assertTrue(os.path.exists(os.path.join(folder, 'good.png')))
            self.assertTrue(os.path.exists(os.path.join(folder, 'good.svg')))

    def test_pdf_finalization_failure(self):
        painter = Mock()
        painter.isActive.return_value = True
        painter.end.return_value = False
        helper = SimpleNamespace(dpi=(72, 72), pagesize=(144, 144),
                                 renderToPainter=lambda painter: None)
        with tempfile.TemporaryDirectory() as folder:
            task = export.ExportPDFRunnable(
                SimpleNamespace(pdfdpi=72, color=True),
                os.path.join(folder, 'failure.pdf'), [helper])
            with patch.object(export.qt, 'QPainter', return_value=painter):
                with self.assertRaises(OSError):
                    task.doExport()
            painter.end.assert_called_once()

    def test_pdf_render_exception_finishes_painter(self):
        painter = Mock()
        painter.isActive.return_value = True
        painter.end.return_value = False
        helper = SimpleNamespace(
            dpi=(72, 72), pagesize=(144, 144),
            renderToPainter=Mock(side_effect=RuntimeError('render failed')))
        with tempfile.TemporaryDirectory() as folder:
            task = export.ExportPDFRunnable(
                SimpleNamespace(pdfdpi=72, color=True),
                os.path.join(folder, 'failure.pdf'), [helper])
            with patch.object(export.qt, 'QPainter', return_value=painter):
                with self.assertRaisesRegex(RuntimeError, 'render failed'):
                    task.doExport()
            painter.end.assert_called_once()

    def test_pdf_page_transition_failure(self):
        class BrokenPrinter(qt.QPrinter):
            def newPage(self):
                return False
        helper = SimpleNamespace(dpi=(72, 72), pagesize=(144, 144),
                                 renderToPainter=lambda painter: None)
        with tempfile.TemporaryDirectory() as folder:
            task = export.ExportPDFRunnable(
                SimpleNamespace(pdfdpi=72, color=True),
                os.path.join(folder, 'failure.pdf'), [helper, helper])
            with patch.object(export.qt, 'QPrinter', BrokenPrinter):
                with self.assertRaises(OSError):
                    task.doExport()

    def test_postscript_stops_when_intermediate_pdf_fails(self):
        options = SimpleNamespace(exception=None)
        task = export.ExportPostscriptRunnable(options, 'not-written.ps', [])
        with patch.object(task, 'searchGhostscript'), \
             patch.object(task, 'gs_exe', 'unused-ghostscript'), \
             patch.object(task, 'gs_dev', {'.ps': 'ps2write'}), \
             patch.object(export.ExportPDFRunnable, 'doExport',
                          side_effect=OSError('PDF cannot be written')), \
             patch.object(export.subprocess, 'check_call') as run:
            with self.assertRaisesRegex(OSError, 'PDF cannot be written'):
                task.doExport()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
