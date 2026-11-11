"""MO2-style selection dialog; live instances are always preview-only."""
import json
from pathlib import Path
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontDatabase
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
try:
    from .core import Mod, scan, execute
except ImportError:
    from core import Mod, scan, execute


class OrganizerDialog(QDialog):
    def __init__(self, mods, profile_name, sandbox_root=None, parent=None):
        super().__init__(parent)
        if not QFontDatabase.families():
            font_file=Path('C:/Windows/Fonts/segoeui.ttf')
            if font_file.exists(): QFontDatabase.addApplicationFont(str(font_file))
        self.setFont(QFont('Segoe UI',10))
        self.mods = sorted(mods, key=lambda m:m.priority)
        self.profile_name = profile_name
        self.sandbox_root = Path(sandbox_root) if sandbox_root else None
        self.plan = None
        self.busy = False
        self.rows = {}
        self.setWindowTitle('Skyrim Asset Organizer — Disposable Demo' if sandbox_root else 'Skyrim Asset Organizer — Live Preview Only')
        self.resize(1180, 820)
        layout = QVBoxLayout(self)
        heading = QLabel(f'Profile: {profile_name}  |  Priority increases downward; highest priority wins')
        layout.addWidget(heading)
        note = QLabel('Disposable testbed only. Deletions affect this sample; logs only, no backups.' if sandbox_root else 'Live MO2: read-only preview. Apply is disabled in this test build.')
        note.setStyleSheet('padding:8px; background:#40351b; color:#ffe3a0')
        layout.addWidget(note)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find mods… hidden checked mods stay selected')
        self.search.setObjectName('searchEdit')
        bar.addWidget(self.search)
        for label, callback in [('Select all',lambda:self.check_all(True)),('Clear',lambda:self.check_all(False)),('Expand',lambda:self.tree.expandAll()),('Collapse',lambda:self.tree.collapseAll())]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            bar.addWidget(button)
        layout.addLayout(bar)
        split = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setObjectName('modTree')
        self.tree.setHeaderLabels(['Select / Mod', 'Priority', 'Profile status'])
        self.tree.setColumnWidth(0,680)
        self.tree.setColumnWidth(1,90)
        self.tree.setSortingEnabled(False)
        self.tree.setAlternatingRowColors(True)
        split.addWidget(self.tree)
        self.table = QTableWidget(0,5)
        self.table.setHorizontalHeaderLabels(['Action','Source mod','Full relative asset path','Selected winner','Bytes'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0,120)
        self.table.setColumnWidth(1,180)
        self.table.setColumnWidth(2,380)
        self.table.setColumnWidth(3,180)
        split.addWidget(self.table)
        split.setSizes([380,190])
        layout.addWidget(split)
        controls = QHBoxLayout()
        self.cleanup = QCheckBox('Remove overwritten assets')
        self.cleanup.setChecked(True)
        self.nif = QCheckBox('NIF meshes'); self.nif.setChecked(True)
        self.dds = QCheckBox('DDS textures'); self.dds.setChecked(True)
        for box in (self.cleanup,self.nif,self.dds): controls.addWidget(box)
        controls.addStretch()
        layout.addLayout(controls)
        combine_row = QHBoxLayout()
        self.combine = QCheckBox('Combine selected assets')
        self.combine.setObjectName('combineCheck')
        self.output = QLineEdit()
        self.output.setObjectName('outputName')
        self.output.setPlaceholderText('New output mod name')
        self.remove_sources = QCheckBox('Remove copied assets from source mods')
        self.remove_sources.setObjectName('deleteSourcesCheck')
        combine_row.addWidget(self.combine); combine_row.addWidget(self.output); combine_row.addWidget(self.remove_sources)
        layout.addLayout(combine_row)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        self.scan_button = QPushButton('Scan / Preview'); self.scan_button.setObjectName('scanButton')
        self.apply_button = QPushButton('Apply to disposable testbed'); self.apply_button.setObjectName('applyButton')
        self.export_button = QPushButton('Export preview')
        logs = QPushButton('Open logs'); logs.setEnabled(bool(sandbox_root))
        close = QPushButton('Close')
        for button in (self.scan_button,self.apply_button,self.export_button,logs,close): actions.addWidget(button)
        layout.addLayout(actions)
        self.scan_button.clicked.connect(self.preview)
        self.apply_button.clicked.connect(self.apply)
        self.export_button.clicked.connect(self.export)
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.sandbox_root/'logs'))))
        close.clicked.connect(self.close)
        self.tree.itemChanged.connect(self.item_changed)
        self.search.textChanged.connect(self.filter_tree)
        for box in (self.cleanup,self.nif,self.dds,self.combine,self.remove_sources):
            box.toggled.connect(self.options_changed)
        self.output.textChanged.connect(self.invalidate)
        self.populate()
        self.options_changed()

    def populate(self):
        self.tree.blockSignals(True)
        self.tree.clear(); self.rows = {}
        stack = []
        ordinary = None
        for mod in self.mods:
            label = mod.name.removesuffix('_separator')
            if label.startswith('_separator_'): label = label[11:]
            depth = len(label)-len(label.lstrip('#')) if mod.separator else 0
            if depth:
                while stack and stack[-1][0]>=depth: stack.pop()
                parent = stack[-1][1] if stack else self.tree.invisibleRootItem()
                ordinary = None
            else:
                parent = ordinary or (stack[-1][1] if stack else self.tree.invisibleRootItem())
            item = QTreeWidgetItem(parent,[label.lstrip('#') if depth else label,str(mod.priority),'Separator' if mod.separator else ('Enabled' if mod.enabled else 'Disabled')])
            item.setData(0,Qt.ItemDataRole.UserRole,mod.name)
            if mod.separator or mod.enabled:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0,Qt.CheckState.Unchecked)
            else:
                item.setForeground(0,QColor('#888888'))
            self.rows[mod.name]=item
            if depth: stack.append((depth,item))
            elif mod.separator:
                # Plain separator scopes end at the next plain or TrueFolder separator.
                if ordinary:
                    parent = stack[-1][1] if stack else self.tree.invisibleRootItem()
                    ordinary.removeChild(item); parent.addChild(item)
                ordinary=item
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def selected(self):
        return {m.name for m in self.mods if m.enabled and not m.separator and self.rows[m.name].checkState(0)==Qt.CheckState.Checked}

    def check_all(self,checked):
        self.tree.blockSignals(True)
        for mod in self.mods:
            if mod.enabled or mod.separator:
                self.rows[mod.name].setCheckState(0,Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.refresh_checks(); self.invalidate()

    def item_changed(self,item,column):
        if column!=0: return
        mod = next(m for m in self.mods if m.name==item.data(0,Qt.ItemDataRole.UserRole))
        self.tree.blockSignals(True)
        def cascade(parent):
            for index in range(parent.childCount()):
                child=parent.child(index)
                if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    child.setCheckState(0,item.checkState(0))
                cascade(child)
        if mod.separator: cascade(item)
        self.tree.blockSignals(False)
        self.refresh_checks(); self.invalidate()

    def refresh_checks(self):
        self.tree.blockSignals(True)
        for mod in reversed(self.mods):
            item=self.rows[mod.name]
            if mod.separator:
                states=[item.child(i).checkState(0) for i in range(item.childCount()) if item.child(i).flags() & Qt.ItemFlag.ItemIsUserCheckable]
                state=Qt.CheckState.Unchecked if not states or all(s==Qt.CheckState.Unchecked for s in states) else (Qt.CheckState.Checked if all(s==Qt.CheckState.Checked for s in states) else Qt.CheckState.PartiallyChecked)
                item.setCheckState(0,state)
            for column in range(3):
                checked=item.checkState(0)!=Qt.CheckState.Unchecked
                item.setBackground(column,QBrush(QColor('#294e65')) if checked else QBrush())
                item.setForeground(column,QBrush(QColor('white')) if checked else (QBrush(QColor('#888888')) if not mod.enabled and not mod.separator else QBrush()))
        self.tree.blockSignals(False)

    def filter_tree(self,text):
        query=text.casefold()
        def visit(item,ancestor_match=False):
            own=query in item.text(0).casefold()
            child_match=False
            for i in range(item.childCount()): child_match=visit(item.child(i),ancestor_match or own) or child_match
            visible=own or ancestor_match or child_match
            item.setHidden(not visible)
            return visible
        for i in range(self.tree.topLevelItemCount()): visit(self.tree.topLevelItem(i))

    def invalidate(self,*args):
        self.plan=None
        self.apply_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.table.setRowCount(0)
        self.summary.setText(f'{len(self.selected())} mods checked (including any hidden by search). Scan to review actions. Only selected enabled mods conflict with one another.')

    def options_changed(self,*args):
        self.output.setEnabled(self.combine.isChecked())
        self.remove_sources.setEnabled(self.combine.isChecked())
        self.invalidate()

    def preview(self):
        self.scan_button.setEnabled(False)
        self.summary.setText('Scanning and hashing assets…')
        try:
            extensions=({'.nif'} if self.nif.isChecked() else set()) | ({'.dds'} if self.dds.isChecked() else set())
            self.plan=scan(self.mods,self.selected(),extensions,cleanup=self.cleanup.isChecked(),combine=self.combine.isChecked(),output_name=self.output.text(),delete_sources=self.combine.isChecked() and self.remove_sources.isChecked())
            self.plan.profile=self.profile_name
            self.table.setRowCount(len(self.plan.actions))
            for row,action in enumerate(self.plan.actions):
                for column,key in enumerate(('kind','mod','relative','winner','size')):
                    cell=QTableWidgetItem(str(action[key])); cell.setToolTip(json.dumps(action,ensure_ascii=False,indent=2)); self.table.setItem(row,column,cell)
            removed=sum(a['size'] for a in self.plan.actions if a['kind']!='copy')
            copied=sum(a['size'] for a in self.plan.actions if a['kind']=='copy')
            self.summary.setText(f'{len(self.selected())} mods checked · {len(self.plan.actions)} actions · remove {removed:,} bytes · copy {copied:,} bytes · net logical savings {removed-copied:,} bytes. Full relative paths preserved. Recovery uses logs only.')
            self.apply_button.setEnabled(bool(self.sandbox_root and self.plan.actions))
            self.export_button.setEnabled(True)
        except Exception as error:
            self.invalidate()
            QMessageBox.critical(self,'Scan failed',str(error))
        finally:
            self.scan_button.setEnabled(True)

    def apply(self):
        if not self.sandbox_root or not self.plan: return
        answer=QMessageBox.question(self,'Apply to disposable sample?',f'Apply {len(self.plan.actions)} actions inside:\n{self.sandbox_root}\n\nRemoved files have logs only. No backups are retained.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes: return
        try:
            log=execute(self.plan,self.sandbox_root,self.sandbox_root/'logs')
            profile=self.sandbox_root/'profile.json'
            if profile.exists():
                entries=json.loads(profile.read_text(encoding='utf-8'))
                self.mods=[Mod(path=self.sandbox_root/'mods'/r['name'],**r) for r in entries]
                self.populate()
            self.invalidate()
            self.summary.setText(f'Completed. Log: {log} · Text report: {log.with_suffix(".txt")}')
            QMessageBox.information(self,'Disposable run complete',f'Log:\n{log}\n\nOnly the sample was changed.')
        except Exception as error:
            self.invalidate()
            QMessageBox.critical(self,'Operation stopped',f'{error}\nInspect the sample logs for completed and uncertain actions. No automatic undo is available.')

    def export(self):
        if not self.plan: return
        filename,_=QFileDialog.getSaveFileName(self,'Export preview','','JSON (*.json)')
        if filename:
            try:
                Path(filename).write_text(json.dumps(dict(profile=self.profile_name,selected=sorted(self.plan.selected),actions=self.plan.actions),ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as error: QMessageBox.critical(self,'Export failed',str(error))
