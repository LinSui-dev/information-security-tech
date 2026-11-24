"""真实 Tk 控件/事件测试；仅替换文件选择和确认对话框。"""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from lsb_lab.ui import LabApp
from bmp_factory import make_gray_bmp, make_color_bmp


class UiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = LabApp(self.root)
        self.root.update()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)

    def tearDown(self):
        self.root.destroy()
        self.temp.cleanup()

    def edit(self, text):
        self.app.input.delete('1.0', 'end')
        self.app.input.insert('1.0', text)
        self.root.update()

    def test_full_ui_callbacks_both_formats(self):
        for factory in (make_gray_bmp, make_color_bmp):
            source, output = self.path/'source.bmp', self.path/'stego.bmp'
            source.write_bytes(factory(32, 16))
            with patch('lsb_lab.ui.filedialog.askopenfilename', return_value=str(source)):
                self.app.open_source()
            self.edit('中文\n😀  ')
            self.app.embed_button.invoke()
            self.assertTrue(self.app.controller.state.dirty)
            self.assertEqual(self.app._images['source'].width(), 32)
            with patch('lsb_lab.ui.filedialog.asksaveasfilename', return_value=str(output)):
                self.app.save_button.invoke()
            self.assertFalse(self.app.controller.state.dirty)
            with patch('lsb_lab.ui.filedialog.askopenfilename', return_value=str(output)):
                self.app.extract()
            self.assertEqual(self.app.output.get('1.0', 'end-1c'), '中文\n😀  ')
            self.assertEqual(str(self.app.output['state']), 'disabled')
            self.assertEqual(self.app.result_frame['text'], '提取载体')

    def test_cancel_edit_and_dialog_then_discard(self):
        source = self.path/'source.bmp'
        source.write_bytes(make_gray_bmp(32, 16))
        self.app.controller.open_source(source)
        self.app.controller.embed('old')
        self.app.refresh()
        self.root.update()
        old = self.app.controller.state
        with patch('lsb_lab.ui.messagebox.askokcancel', return_value=False):
            self.edit('new')
        self.assertIs(self.app.controller.state, old)
        self.assertEqual(self.app.input.get('1.0', 'end-1c'), 'old')
        with patch('lsb_lab.ui.filedialog.askopenfilename', return_value=''):
            self.app.open_source()
            self.app.extract()
        self.assertIs(self.app.controller.state, old)
        with patch('lsb_lab.ui.messagebox.askokcancel', return_value=True):
            self.edit('new')
        self.assertIsNone(self.app.controller.state.stego)
        self.assertFalse(self.app.controller.state.dirty)

    def test_capacity_error_display_and_original_protection(self):
        source = self.path/'source.bmp'
        source.write_bytes(make_gray_bmp(16, 8))
        self.app.controller.open_source(source)
        self.app.refresh()
        self.edit('中a')
        self.assertTrue(self.app.embed_button.instate(['disabled']))
        self.edit('中')
        self.assertFalse(self.app.embed_button.instate(['disabled']))
        self.app.embed_button.invoke()
        with patch('lsb_lab.ui.filedialog.asksaveasfilename', return_value=str(source)), \
             patch('lsb_lab.ui.messagebox.showerror') as error:
            self.app.save()
            error.assert_called_once()
        self.assertTrue(self.app.controller.state.dirty)
        bad = self.path/'bad.bmp'
        bad.write_bytes(b'bad')
        old = self.app.controller.state
        with patch('lsb_lab.ui.filedialog.askopenfilename', return_value=str(bad)), \
             patch('lsb_lab.ui.messagebox.askokcancel', return_value=True), \
             patch('lsb_lab.ui.messagebox.showerror') as error:
            self.app.open_source()
            error.assert_called_once()
        self.assertIs(self.app.controller.state, old)
