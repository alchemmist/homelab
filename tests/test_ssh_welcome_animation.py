import importlib.util
import io
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('portrait_animation', ROOT / 'ansible/roles/ssh_welcome/files/portrait_animation.py')
ANIMATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANIMATION)
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.sample = next(v for v in json.loads((ROOT / 'assets/socrates-braille.json').read_text())['variants'] if v['id'] == 'reference-16')
        self.colors = json.loads((ROOT / 'assets/socrates-patina.json').read_text())['reference-16']
        self.geometry = os.terminal_size((100, 40))
        self.initial = '\n' + '\n'.join(' ' * 21 + ' info' for _ in range(16)) + '\nfooter\n'
        self.final = '\n' + '\n'.join('face info' for _ in range(16)) + '\nfooter\n'

    def test_reveal_completes_without_changing_final_portrait(self):
        for seconds in (1.1, 3.0):
            frame = ANIMATION.portrait_frame(self.sample, self.colors, seconds)
            self.assertEqual([ANSI.sub('', s) for s in frame], self.sample['lines'])
        first = ANIMATION.portrait_frame(self.sample, self.colors, 0)
        self.assertTrue(all(c in (' ', '\u2800') for line in first for c in ANSI.sub('', line)))

    def test_interrupt_restores_cursor_and_finishes_footer(self):
        out = io.StringIO()
        with patch.object(ANIMATION.shutil, 'get_terminal_size', return_value=self.geometry), patch.object(ANIMATION.time, 'sleep', side_effect=KeyboardInterrupt):
            self.assertFalse(ANIMATION.play(self.initial, self.final, self.sample, self.colors, self.geometry, out))
        output = out.getvalue()
        self.assertIn('\033[?25h', output)
        self.assertTrue(output.endswith('footer\n'))
        self.assertEqual(output.count('info'), 16)
        self.assertEqual(output.count('footer'), 1)

    def test_resize_stops_before_cursor_repositioning(self):
        out = io.StringIO()
        with patch.object(ANIMATION.shutil, 'get_terminal_size', return_value=os.terminal_size((40, 12))):
            self.assertTrue(ANIMATION.play(self.initial, self.final, self.sample, self.colors, self.geometry, out))
        self.assertNotIn('\033[16A', out.getvalue())
        self.assertIn('\033[?25h', out.getvalue())
        self.assertNotIn('footer', out.getvalue())


if __name__ == '__main__':
    unittest.main()
