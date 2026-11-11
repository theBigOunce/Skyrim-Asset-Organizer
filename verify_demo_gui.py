"""Headless GUI smoke check; creates only a project-local disposable fixture."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
from unittest.mock import patch
from demo import PROJECT, create_testbed, load_mods
import uuid
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox, QPushButton, QTreeWidget
from ui import OrganizerDialog

app = QApplication([])
root = create_testbed(PROJECT / 'testbeds' / ('gui-' + uuid.uuid4().hex[:8]))
window = OrganizerDialog(load_mods(root), 'Synthetic GUI QA', sandbox_root=root)
window.show()
app.processEvents()
tree = window.findChild(QTreeWidget)
assert tree is not None, 'Mod tree missing'

def items(parent):
    for i in range(parent.childCount()):
        child = parent.child(i)
        yield child
        yield from items(child)

rows = list(items(tree.invisibleRootItem()))
landscape = next(r for r in rows if any('Landscape' in r.text(c) and 'Base' not in r.text(c) and 'Detail' not in r.text(c) and 'Finishing' not in r.text(c) for c in range(tree.columnCount())))
landscape.setCheckState(0, Qt.CheckState.Checked)
assert len(window.selected()) == 3
base=window.rows['Landscape Base']
base.setCheckState(0,Qt.CheckState.Unchecked)
assert landscape.checkState(0)==Qt.CheckState.PartiallyChecked
base.setCheckState(0,Qt.CheckState.Checked)
window.search.setText('Architecture')
assert len(window.selected())==3, 'Search changed operation scope'
window.search.clear()
combine = next(c for c in window.findChildren(QCheckBox) if 'combine selected' in c.text().lower() or c.text().lower() == 'combine mods' or 'combine' in c.text().lower())
combine.setChecked(True)
fields = window.findChildren(QLineEdit)
output = window.findChild(QLineEdit, 'outputName') or next(f for f in fields if 'output' in f.placeholderText().lower() or 'combined' in f.placeholderText().lower())
output.setText('GUI Combined Landscapes')
remove = next(c for c in window.findChildren(QCheckBox) if 'source' in c.text().lower())
remove.setChecked(True)
scan = next(b for b in window.findChildren(QPushButton) if 'scan' in b.text().lower())
errors = []
with patch.object(QMessageBox, 'critical', side_effect=lambda *args: errors.append(str(args[-1]))), patch.object(QMessageBox, 'warning', side_effect=lambda *args: errors.append(str(args[-1]))):
    scan.click()
app.processEvents()
assert not errors, errors
apply = next(b for b in window.findChildren(QPushButton) if 'apply' in b.text().lower())
assert apply.isEnabled(), 'Fixture preview did not enable Apply'
artifacts = PROJECT / 'artifacts'
artifacts.mkdir(exist_ok=True)
window.grab().save(str(artifacts / 'demo-preview.png'))
with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), patch.object(QMessageBox, 'information'), patch.object(QMessageBox, 'critical', side_effect=lambda *args: errors.append(str(args[-1]))):
    apply.click()
app.processEvents()
assert not errors, errors
assert (root/'mods/GUI Combined Landscapes/textures/landscape/rock.dds').exists()
assert not (root/'mods/Landscape Base/textures/landscape/rock.dds').exists()
assert (root/'mods/Architecture/textures/architecture/rock.dds').exists()
assert list((root/'logs').glob('*.jsonl'))
live = OrganizerDialog(load_mods(root), 'Live preview QA')
live.check_all(True)
with patch.object(QMessageBox, 'critical', side_effect=lambda *args: errors.append(str(args[-1]))):
    live.preview()
assert not errors,errors
assert not next(b for b in live.findChildren(QPushButton) if 'apply' in b.text().lower()).isEnabled()
window.close()
live.close()
print(f'GUI checks passed. Fixture: {root}')
print(f'Preview screenshot: {artifacts / "demo-preview.png"}')
