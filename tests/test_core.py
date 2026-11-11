import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin' / 'SkyrimAssetOrganizer'))
from core import Mod, scan, execute, digest


class CoreTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / 'testbeds'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        (self.root / '.sao-testbed.json').write_text('{"format":"sao-disposable-v1"}')
        self.mods = []
        for priority, name in enumerate(('A', 'B', 'Outside', 'Disabled')):
            path = self.root / 'mods' / name
            path.mkdir(parents=True)
            self.mods.append(Mod(name, path, priority, name != 'Disabled'))
        self.put('A', 'textures/landscape/rock.dds', b'a')
        self.put('A', 'textures/architecture/rock.dds', b'architecture')
        self.put('A', 'textures/landscape/unique.dds', b'unique')
        self.put('B', 'textures/landscape/rock.dds', b'b')
        self.put('Outside', 'textures/landscape/unique.dds', b'outside')
        self.put('Disabled', 'textures/landscape/rock.dds', b'disabled')

    def tearDown(self):
        self.temp.cleanup()

    def put(self, mod, relative, data):
        path = self.root / 'mods' / mod / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def plan(self, **kwargs):
        return scan(self.mods, {'A','B'}, {'.dds'}, **kwargs)

    def test_selected_scope_and_folders(self):
        plan = self.plan()
        self.assertEqual([(a['mod'],a['relative']) for a in plan.actions], [('A','textures/landscape/rock.dds')])
        execute(plan, self.root, self.root/'logs')
        self.assertTrue((self.root/'mods/A/textures/architecture/rock.dds').exists())
        self.assertTrue((self.root/'mods/A/textures/landscape/unique.dds').exists())

    def test_combine_copies_before_removal_and_logs(self):
        plan = self.plan(combine=True, output_name='Combined', delete_sources=True)
        log = execute(plan, self.root, self.root/'logs')
        self.assertEqual((self.root/'mods/Combined/textures/landscape/rock.dds').read_bytes(), b'b')
        self.assertEqual((self.root/'mods/Combined/textures/architecture/rock.dds').read_bytes(), b'architecture')
        self.assertEqual((self.root/'mods/Outside/textures/landscape/unique.dds').read_bytes(), b'outside')
        events = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(events[-1]['event'], 'finished')
        self.assertEqual(len([e for e in events if e['event']=='completed']), len(plan.actions))
        self.assertTrue(all('sha256' in a and 'metadata' in a for a in events[0]['actions']))

    def test_stale_plan(self):
        plan = self.plan()
        self.put('B','textures/landscape/rock.dds',b'changed')
        with self.assertRaisesRegex(ValueError,'stale'):
            execute(plan,self.root,self.root/'logs')
        self.assertTrue(Path(plan.actions[0]['source']).exists())

    def test_marker_required(self):
        plan = self.plan()
        (self.root/'.sao-testbed.json').unlink()
        with self.assertRaises(ValueError):
            execute(plan,self.root,self.root/'logs')

    def test_disabled_cannot_be_selected(self):
        with self.assertRaises(ValueError):
            scan(self.mods, {'A','Disabled'}, {'.dds'})

    def test_output_collision_and_path_escape(self):
        for name in ('A','../oops','CON','a'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.plan(combine=True, output_name=name)

    def test_deletion_requires_log(self):
        plan = self.plan()
        (self.root/'logs').write_text('not a directory')
        with self.assertRaises(OSError):
            execute(plan,self.root,self.root/'logs')
        self.assertTrue(Path(plan.actions[0]['source']).exists())

    def test_nif_filter_and_hidden(self):
        self.put('A','meshes/test.nif',b'a')
        self.put('B','meshes/test.nif',b'b')
        self.put('A','textures/landscape/hidden.dds.mohidden',b'a')
        self.assertEqual(len(self.plan().actions),1)
        plan = scan(self.mods,{'A','B'},{'.nif'})
        self.assertEqual([a['relative'] for a in plan.actions],['meshes/test.nif'])

    def test_interleaved_merge_cannot_change_winners(self):
        self.mods[1] = Mod('B', self.mods[1].path, 2)
        self.mods[2] = Mod('Outside', self.mods[2].path, 1)
        self.put('Outside', 'textures/landscape/rock.dds', b'outside lower than B')
        # Unique is won by Outside above A; rock is won by B above Outside.
        # One merged output cannot sit both above and below Outside.
        with self.assertRaisesRegex(ValueError, 'No safe output placement'):
            self.plan(combine=True, output_name='Combined', delete_sources=True)

    def test_case_insensitive_relative_path(self):
        self.put('B', 'Textures/Landscape/ROCK.dds', b'b')
        # Windows maps this to the existing path; on a case-sensitive filesystem
        # the extra root exposes a collision, which must be rejected instead.
        try:
            plan = self.plan()
            self.assertEqual(len(plan.actions), 1)
        except ValueError as error:
            self.assertIn('Case-colliding', str(error))

    def test_manual_restore_from_demo_download(self):
        import zipfile
        original = self.root/'mods/A/textures/landscape/rock.dds'
        expected = digest(original)
        archive = self.root/'original.zip'
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.write(original, 'textures/landscape/rock.dds')
        log = execute(self.plan(),self.root,self.root/'logs')
        record = json.loads(log.read_text().splitlines()[0])['actions'][0]
        with zipfile.ZipFile(archive) as stream:
            original.write_bytes(stream.read(record['relative']))
        self.assertEqual(digest(original),expected)
        self.assertEqual(expected,record['sha256'])

    def test_journal_flush_failure_prevents_deletion(self):
        from unittest.mock import patch
        plan = self.plan()
        with patch('core.os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                execute(plan,self.root,self.root/'logs')
        self.assertTrue(Path(plan.actions[0]['source']).exists())


if __name__ == '__main__':
    unittest.main()
