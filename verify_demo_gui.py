"""Headless GUI smoke check; creates only a project-local disposable fixture."""
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
from unittest.mock import patch
from demo import PROJECT, create_testbed, load_mods
import uuid
from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox, QPushButton, QTreeWidget
from ui import ActionModel, OrganizerDialog
from core import ScanCancelled


def wait_for_scan(window, timeout_ms=30000):
    """Keep programmatic preview checks synchronous while Qt handles signals."""
    if not window.busy:
        return
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(lambda: loop.quit() if not window.busy else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timed_out = []
    def cancel_on_timeout():
        timed_out.append(True)
        window.cancel_scan()
        # Continue pumping until cancellation finishes; never destroy a worker.
    timeout.timeout.connect(cancel_on_timeout)
    poll.start()
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    assert not timed_out, 'Scan exceeded verification timeout'

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
    assert window.busy and not tree.isEnabled()
    assert window.cancel_button.isEnabled()
    wait_for_scan(window)
app.processEvents()
assert not errors, errors
apply = next(b for b in window.findChildren(QPushButton) if 'apply' in b.text().lower())
assert apply.isEnabled(), 'Fixture preview did not enable Apply'
assert window.action_model.rowCount() == len(window.plan.actions)
assert window.action_model.data(window.action_model.index(0, 0)) == window.plan.actions[0]['kind']
assert window.plan.stats['files'] > 0 and window.plan.stats['hashed_files'] == 0
assert 'files indexed' in window.summary.text()
export_path = root / 'preview.json'
with patch('ui.QFileDialog.getSaveFileName', return_value=(str(export_path), 'JSON (*.json)')):
    window.export()
exported = json.loads(export_path.read_text(encoding='utf-8'))
assert exported['actions'] == list(window.plan.actions)
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
    wait_for_scan(live)
assert not errors,errors
assert not next(b for b in live.findChildren(QPushButton) if 'apply' in b.text().lower()).isEnabled()

# A virtual sequence proves model attachment never walks/materializes actions.
class LazyActions:
    reads = 0
    counts = 0
    def __len__(self):
        self.counts += 1
        return 1_000_000
    def __getitem__(self, index):
        self.reads += 1
        return dict(kind='copy', mod='Fixture', relative=f'{index}.dds', winner='Fixture', size=1)
    def __iter__(self): raise AssertionError('Model eagerly iterated actions')

actions = LazyActions()
model = ActionModel()
model.set_actions(actions)
assert model.rowCount() == 1_000_000 and actions.reads == 0
for column in range(5):
    assert model.data(model.index(999_999, column)) is not None
assert actions.reads == 1, 'Visible row should be fetched once for all columns'
assert actions.counts == 1, 'Model must cache the disk-backed sequence length'
with patch('ui.json.dumps', wraps=json.dumps) as serialize:
    for column in range(5):
        assert model.data(model.index(999_999, column), Qt.ItemDataRole.ToolTipRole)
    assert serialize.call_count == 1, 'Tooltip should be serialized only on demand, once per row'
model.set_actions(None)
assert model.rowCount() == 0 and model._action is None

# Cooperative fake scan exercises callbacks, cancellation and deferred closing.
from threading import Event
started, cancelled = Event(), Event()
def cancellable_scan(*args, progress, cancel, **kwargs):
    progress('Verification worker running')
    started.set()
    while not cancel():
        cancelled.wait(0.005)
    cancelled.set()
    raise ScanCancelled()

with patch('ui.scan', side_effect=cancellable_scan), patch.object(QMessageBox, 'critical', side_effect=lambda *args: errors.append(str(args[-1]))):
    live.show()
    live.preview()
    live.scan_thread.progress.connect(lambda message: live.close())
    assert live.busy and live.scan_thread is not None
    wait_for_scan(live)
assert started.is_set() and cancelled.is_set(), 'Worker did not cooperatively cancel'
assert not live.isVisible() and live.plan is None and live.scan_thread is None
assert not errors, errors

# Streaming export accepts a non-JSON-serializable sequence, and managed-plan
# cleanup must release the model reference before closing the action store.
from types import SimpleNamespace
class ActionSequence:
    def __len__(self): return 3
    def __getitem__(self, index):
        if not 0 <= index < len(self): raise IndexError(index)
        return dict(kind='copy', mod='Fixture', relative=f'{index}.dds', winner='Fixture', size=1)
    def __iter__(self):
        for index in range(len(self)): yield self[index]

def close_store():
    assert live.action_model.actions is None
    assert live.action_model._action is None

sequence = ActionSequence()
live.plan = SimpleNamespace(selected={'Fixture'}, actions=sequence, close=close_store)
live.action_model.set_actions(sequence)
with patch('ui.QFileDialog.getSaveFileName', return_value=(str(export_path), 'JSON (*.json)')):
    live.export()
assert json.loads(export_path.read_text(encoding='utf-8'))['actions'] == list(sequence)
live.invalidate()
window.close()
live.close()
print(f'GUI checks passed. Fixture: {root}')
print(f'Preview screenshot: {artifacts / "demo-preview.png"}')
