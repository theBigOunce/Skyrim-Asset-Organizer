"""Create and operate a small synthetic modlist. Never imports the live MO2 instance."""
import argparse
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent / 'plugin' / 'SkyrimAssetOrganizer'
sys.path.insert(0, str(PACKAGE))
from core import Mod, scan, execute

PROJECT = Path(__file__).resolve().parent


def create_testbed(root):
    root = Path(root).absolute()
    if not root.is_relative_to(PROJECT / 'testbeds'):
        raise ValueError('Demo roots must be inside this project/testbeds.')
    root.mkdir(parents=True, exist_ok=False)
    (root / '.sao-testbed.json').write_text(json.dumps({'format': 'sao-disposable-v1'}), encoding='utf-8')
    specs = [('#Visuals_separator', True, True), ('##Landscape_separator', True, True),
             ('Landscape Base', True, False), ('Landscape Detail', True, False),
             ('Landscape Finishing', True, False), ('##Architecture_separator', True, True),
             ('Architecture', True, False), ('Disabled Alternative', False, False)]
    entries = []
    for priority, (name, enabled, separator) in enumerate(specs):
        folder = root / 'mods' / name
        folder.mkdir(parents=True)
        (folder / 'meta.ini').write_text(f'[General]\ngameName=SkyrimSE\nmodid=0\nversion=1.0\ninstallationFile={name}.zip\n', encoding='utf-8')
        entries.append(dict(name=name, priority=priority, enabled=enabled, separator=separator))
    assets = {
        'Landscape Base': {'textures/landscape/rock.dds': b'base rock', 'textures/landscape/soil.dds': b'base soil', 'meshes/landscape/rock.nif': b'base mesh', 'readme.ini': b'untouched'},
        'Landscape Detail': {'textures/landscape/rock.dds': b'detail rock', 'meshes/landscape/rock.nif': b'detail mesh'},
        'Landscape Finishing': {'textures/landscape/rock.dds': b'finishing rock', 'textures/landscape/moss.dds': b'moss'},
        'Architecture': {'textures/architecture/rock.dds': b'different purpose same basename'},
        'Disabled Alternative': {'textures/landscape/rock.dds': b'disabled rock'},
    }
    import zipfile
    for name, files in assets.items():
        downloads = root / 'downloads'
        downloads.mkdir(exist_ok=True)
        with zipfile.ZipFile(downloads / f'{name}.zip', 'w') as archive:
            for relative, contents in files.items():
                file = root / 'mods' / name / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(contents)
                archive.writestr(relative, contents)
    (root / 'profile.json').write_text(json.dumps(entries, indent=2), encoding='utf-8')
    return root


def load_mods(root):
    entries = json.loads((root / 'profile.json').read_text(encoding='utf-8'))
    return [Mod(path=root / 'mods' / e['name'], **e) for e in entries]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='Existing disposable testbed')
    parser.add_argument('--cli', action='store_true', help='Scan from terminal instead of GUI')
    parser.add_argument('--apply', action='store_true', help='Apply to this generated testbed only')
    args = parser.parse_args()
    if args.root:
        root = args.root.absolute()
        if not root.is_relative_to(PROJECT / 'testbeds'):
            parser.error('Root must be in project/testbeds')
    else:
        import uuid
        root = create_testbed(PROJECT / 'testbeds' / uuid.uuid4().hex[:10])
    print(f'Disposable testbed: {root}')
    mods = load_mods(root)
    if args.cli:
        plan = scan(mods, {'Landscape Base', 'Landscape Detail', 'Landscape Finishing'}, {'.dds', '.nif'},
                    combine=True, output_name='Combined Landscapes', delete_sources=True)
        plan.profile = 'Synthetic Demo'
        for action in plan.actions:
            print(f"{action['kind']:14} {action['mod']}: {action['relative']} -> {action['winner']}")
        if args.apply:
            print(f'Log: {execute(plan, root, root / "logs")}')
    else:
        from PyQt6.QtWidgets import QApplication
        from ui import OrganizerDialog
        app = QApplication(sys.argv[:1])
        window = OrganizerDialog(mods, 'Synthetic Demo', sandbox_root=root)
        window.show()
        app.exec()


if __name__ == '__main__':
    main()
