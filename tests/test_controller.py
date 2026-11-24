import unittest
from unittest.mock import patch
from pathlib import Path
from lsb_lab.controller import LabController
from lsb_lab.models import SessionState, ExtractionResult
from lsb_lab.errors import LabError, InvalidPayloadError
from bmp_factory import gray_image


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.c = LabController()
        self.image = gray_image(32, 16)
        self.c.state = SessionState(source=self.image, source_path=Path('source.bmp').resolve(),
                                    input_text='old', stego=self.image, dirty=True,
                                    extracted_text='previous', extracted_image=self.image)

    def test_open_resets(self):
        with patch('lsb_lab.controller.bmp.load_bmp', return_value=self.image):
            self.c.open_source('new.bmp')
        self.assertEqual(self.c.state.input_text, '')
        self.assertIsNone(self.c.state.stego)
        self.assertIsNone(self.c.state.extracted_image)
        self.assertFalse(self.c.state.dirty)

    def test_input_same_and_changed(self):
        old = self.c.state
        self.c.set_input_text('old')
        self.assertIs(self.c.state, old)
        self.c.set_input_text('new')
        self.assertIsNone(self.c.state.stego)
        self.assertFalse(self.c.state.dirty)
        self.assertEqual(self.c.state.extracted_text, 'previous')

    def test_embed_and_save(self):
        with patch('lsb_lab.controller.stego.embed_text', return_value=self.image) as embed:
            self.c.embed('new')
            embed.assert_called_once_with(self.image, 'new')
        self.assertTrue(self.c.state.dirty)
        self.assertIsNone(self.c.state.extracted_image)
        with patch('lsb_lab.controller.bmp.save_bmp') as save:
            self.c.save_stego('out.bmp')
            save.assert_called_once()
        self.assertFalse(self.c.state.dirty)

    def test_extract_without_source(self):
        self.c = LabController()
        result = ExtractionResult('disk', b'disk', 1)
        with patch('lsb_lab.controller.bmp.load_bmp', return_value=self.image), \
             patch('lsb_lab.controller.stego.extract_text', return_value=result):
            self.assertEqual(self.c.extract_from('disk.bmp'), result)
        self.assertIsNone(self.c.state.source)
        self.assertEqual(self.c.state.extracted_text, 'disk')

    def test_all_failure_operations_preserve_state(self):
        cases = [('bmp.load_bmp', lambda: self.c.open_source('bad.bmp'), OSError('bad')),
                 ('stego.embed_text', lambda: self.c.embed('new'), LabError('bad')),
                 ('bmp.save_bmp', lambda: self.c.save_stego('out.bmp'), OSError('bad')),
                 ('bmp.load_bmp', lambda: self.c.extract_from('bad.bmp'), OSError('bad'))]
        for target, operation, error in cases:
            old = self.c.state
            with patch('lsb_lab.controller.' + target, side_effect=error):
                with self.assertRaises(type(error)):
                    operation()
            self.assertIs(self.c.state, old)
        old = self.c.state
        with patch('lsb_lab.controller.bmp.load_bmp', return_value=self.image), \
             patch('lsb_lab.controller.stego.extract_text', side_effect=InvalidPayloadError('bad')):
            with self.assertRaises(InvalidPayloadError):
                self.c.extract_from('bad.bmp')
        self.assertIs(self.c.state, old)

    def test_missing_state_and_original_protection(self):
        with self.assertRaises(LabError):
            self.c.save_stego('source.bmp')
        empty = LabController()
        with self.assertRaises(LabError):
            empty.embed('x')
        with self.assertRaises(LabError):
            empty.save_stego('out.bmp')

    def test_preview_priority(self):
        with patch('lsb_lab.controller.bmp.to_preview', return_value='preview') as preview:
            self.assertEqual(self.c.get_result_preview(), 'preview')
            preview.assert_called_once_with(self.image)
        empty = LabController()
        self.assertIsNone(empty.get_source_preview())
        self.assertIsNone(empty.get_result_preview())
