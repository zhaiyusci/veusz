"""Dataset editor lifecycle regressions for upstream issue #67.

Run with QT_QPA_PLATFORM=offscreen and VEUSZ_RESOURCE_DIR set to the checkout.
"""
import sys
import unittest
from unittest import mock

from veusz import document, qtall as qt
from veusz.dialogs.dataeditdialog import (
    DataEditDialog, DatasetTableModel1D, DatasetTableModel2D)


class DatasetLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def setUp(self):
        self.errors = []
        hook = mock.patch.object(sys, 'excepthook', lambda *e: self.errors.append(e))
        hook.start()
        self.addCleanup(hook.stop)
        self.doc = document.Document()
        self.ci = document.CommandInterface(self.doc)
        self.ci.SetData2DExpression('x', '[[0]]', linked=True)
        self.editor = DataEditDialog(None, self.doc)
        self.editor.show()
        self.editor.selectDataset('x')
        self.app.processEvents()
        self.addCleanup(self.closeEditor)

    def closeEditor(self):
        self.editor.close()
        self.editor.deleteLater()
        self.app.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)

    def assertModel(self, modeltype, value=0.):
        self.app.processEvents()
        model = self.editor.datatableview.model()
        self.assertIsInstance(model, modeltype)
        self.assertEqual(model.data(model.index(0, 0), qt.Qt.ItemDataRole.DisplayRole), value)
        self.assertEqual(self.errors, [])

    def test_reported_delete_then_recreate_and_undo_redo(self):
        self.assertModel(DatasetTableModel2D)
        self.editor.slotDatasetDelete()
        self.app.processEvents()
        self.assertNotIn('x', self.doc.data)
        self.ci.SetDataExpression('x', '0', linked=True)
        self.editor.selectDataset('x')
        self.assertModel(DatasetTableModel1D)
        self.doc.undoOperation()  # remove the new 1D dataset
        self.doc.undoOperation()  # restore the deleted 2D dataset
        self.editor.selectDataset('x')
        self.assertModel(DatasetTableModel2D)
        self.doc.redoOperation()
        self.doc.redoOperation()
        self.editor.selectDataset('x')
        self.assertModel(DatasetTableModel1D)

    def test_same_name_replacement_changes_model_without_reselection(self):
        self.ci.SetDataExpression('x', '0', linked=True)
        self.assertModel(DatasetTableModel1D)
        self.ci.SetData2DExpression('x', '[[1, 2], [3, 4]]', linked=True)
        self.assertModel(DatasetTableModel2D, 3.)
        self.doc.undoOperation()
        self.assertModel(DatasetTableModel1D)
        self.doc.redoOperation()
        self.assertModel(DatasetTableModel2D, 3.)

    def test_deleted_2d_model_header_is_empty(self):
        model = DatasetTableModel2D(None, self.doc, 'x')
        self.doc.applyOperation(document.OperationDatasetDelete('x'))
        self.assertIsNone(model.headerData(
            0, qt.Qt.Orientation.Horizontal, qt.Qt.ItemDataRole.DisplayRole))
        self.assertEqual(model.rowCount(qt.QModelIndex()), 0)

    def test_same_dimension_updates_keep_current_model(self):
        model = self.editor.datatableview.model()
        self.ci.SetData2DExpression('x', '[[7]]', linked=True)
        self.assertModel(DatasetTableModel2D, 7.)
        self.assertIs(self.editor.datatableview.model(), model)

    def test_replaced_model_disconnects_before_deferred_deletion(self):
        oldmodel = self.editor.datatableview.model()
        with mock.patch.object(oldmodel, 'updatePixelCoords') as update:
            self.editor.selectDataset('x')
            # Do not process DeferredDelete yet: obsolete models must stop
            # observing document changes immediately, not only at destruction.
            self.doc.setModified()
            update.assert_not_called()

    def test_reselection_does_not_accumulate_models(self):
        for _ in range(5):
            self.editor.selectDataset('x')
        self.app.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)
        self.assertEqual(len(self.editor.findChildren(qt.QAbstractTableModel)), 1)


if __name__ == '__main__':
    unittest.main()
