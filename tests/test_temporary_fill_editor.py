"""Native Qt regressions for the temporary FillSet editor (issue #525).

Run with QT_QPA_PLATFORM=offscreen and VEUSZ_RESOURCE_DIR at the source root.
Only QMenu.exec is replaced, so no modal UI is needed.
"""
import unittest
from unittest.mock import patch

from veusz import document, qtall as qt, setting
from veusz.setting.controls import _FillBox
from veusz.windows.treeeditwindow import SettingLabel, SettingsProxySingle


class TemporaryFillEditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QApplication.instance() or qt.QApplication([])

    def setUp(self):
        self.doc = document.Document()
        self.doc.makeDefaultDoc()
        graph = self.doc.resolveWidgetPath(None, '/page1/graph1')
        self.bars = [self.doc.applyOperation(document.OperationWidgetAdd(
            graph, 'bar', name=name)) for name in ('bar1', 'bar2')]
        self.fills = self.bars[0].settings.BarFill.get('fills')
        # A patterned row ensures linewidth is serialized; keep a second row
        # to check that edits affect only the chosen row.
        self.fills.set([('horizontal', 'red', False), ('solid', 'blue', False)])
        self.parent = qt.QWidget()
        self.button = qt.QPushButton(self.parent)
        self.box = _FillBox(self.doc, self.fills, 0, self.button, self.parent)
        self.realproxy = SettingsProxySingle(
            self.doc, self.bars[0].settings.BarFill)
        self.box.sigSettingChanged.connect(self.realproxy.onSettingChanged)
        self.label = next(label for label in self.box.findChildren(SettingLabel)
                          if label.setting.name == 'linewidth')
        self.doc.clearHistory()
        self.addCleanup(self.parent.deleteLater)

    def menu(self, label):
        # Keep native menus/actions and actual construction; do not enter the
        # modal event loop (nor trigger exceptions through Qt signal handlers).
        with patch.object(qt.QMenu, 'exec', lambda menu, pos: None):
            label.settingMenu(qt.QPoint())
        return label.findChildren(qt.QMenu)[0]

    def test_temporary_menu_has_only_local_reset(self):
        self.assertIs(self.box.extbrush.parent, self.fills.parent)
        self.assertNotIn('tempbrush', self.fills.parent.getNames())
        self.assertFalse(self.label.setnsproxy.supportsDocumentPathActions)
        menu = self.menu(self.label)
        self.assertEqual([a.text() for a in menu.actions()], ['Reset to default'])
        copy = qt.QMenu(self.parent)
        self.label.addCopyToWidgets(copy)
        self.assertEqual(copy.actions(), [])
        # Even if a reference reaches a temporary editor, do not expose the
        # unlink action which would otherwise address the synthetic path.
        self.label.setting.set(setting.Reference('/StyleSheet/Line/width'))
        other = SettingLabel(self.doc, self.label.setting, self.label.setnsproxy)
        other.setParent(self.parent)
        self.assertEqual([a.text() for a in self.menu(other).actions()],
                         ['Reset to default'])

    def test_direct_document_actions_are_explicitly_unsupported(self):
        original = list(self.fills.val)
        for method in ('actionCopyTypedWidgets', 'actionCopyTypedSiblings',
                       'actionCopyTypedNamedWidgets', 'actionSetStyleSheet',
                       'actionUnlinkSetting'):
            with self.subTest(method=method):
                with self.assertRaisesRegex(ValueError, 'document-path actions'):
                    getattr(self.label, method)()
        self.assertEqual(self.fills.val, original)
        self.assertEqual(self.doc.historyundo, [])

    def test_local_control_edit_reset_and_undo(self):
        original = list(self.fills.val)
        # Exercise the real Distance control's edit signal and proxy wiring.
        control = next(control for control in self.box.findChildren(qt.QComboBox)
                       if getattr(control, 'setting', None) is self.label.setting)
        control.setEditText('3pt')
        control.textActivated.emit('3pt')
        edited = list(self.fills.val)
        self.assertEqual(edited[0][4], '3pt')
        self.assertEqual(edited[1], original[1])
        self.assertEqual(len(self.doc.historyundo), 1)
        self.assertEqual(self.doc.historyundo[-1].settingpath, self.fills.path)
        self.menu(self.label).actions()[0].trigger()
        self.assertEqual(self.fills.val[0][4], self.label.setting.default)
        self.assertEqual(self.fills.val[1], original[1])
        self.doc.undoOperation()
        self.assertEqual(self.fills.val, edited)
        self.doc.undoOperation()
        self.assertEqual(self.fills.val, original)
        self.doc.redoOperation()
        self.assertEqual(self.fills.val, edited)

    def real_label(self):
        label = SettingLabel(self.doc, self.fills, SettingsProxySingle(
            self.doc, self.bars[0].settings.BarFill))
        label.setParent(self.parent)
        return label

    def test_real_fillset_copy_menu_and_undo(self):
        label = self.real_label()
        self.assertTrue(label.setnsproxy.supportsDocumentPathActions)
        menu = self.menu(label)
        self.assertEqual([a.text() for a in menu.actions()],
                         ['Reset to default', 'Copy to', 'Use as default style'])
        copy = menu.actions()[1].menu()
        self.assertEqual([a.text() for a in copy.actions() if not a.isSeparator()],
                         ["all 'bar' widgets", "'bar' siblings",
                          "'bar' widgets called 'bar1'", self.bars[1].path])
        target = self.bars[1].settings.BarFill.get('fills')
        original = list(target.val)
        for action in (copy.actions()[0], copy.actions()[1], copy.actions()[-1]):
            with self.subTest(action=action.text()):
                action.trigger()
                self.assertEqual(target.val, self.fills.val)
                self.doc.undoOperation()
                self.assertEqual(target.val, original)


if __name__ == '__main__':
    unittest.main()
