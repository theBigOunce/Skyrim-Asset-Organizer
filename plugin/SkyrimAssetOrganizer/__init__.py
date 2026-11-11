"""MO2 2.5.2 tool entry point. Actual MO2 instances are preview-only in v0.1."""
import mobase
from pathlib import Path
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMessageBox
from .core import Mod
from .ui import OrganizerDialog


class SkyrimAssetOrganizer(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self.organizer=None
        self.parent=None

    def init(self,organizer):
        self.organizer=organizer
        return True

    def name(self): return 'Skyrim Asset Organizer'
    def author(self): return 'Skyrim Asset Organizer contributors'
    def description(self): return 'Preview selected loose NIF/DDS conflicts and combinations. Live writes disabled in this test build.'
    def version(self): return mobase.VersionInfo(0,1,0)
    def settings(self): return []
    def displayName(self): return 'Skyrim Asset Organizer (Preview)'
    def tooltip(self): return self.description()
    def icon(self): return QIcon()
    def setParentWidget(self,widget): self.parent=widget

    def display(self):
        try:
            listing=self.organizer.modList()
            mods=[]
            for name in listing.allModsByProfilePriority():
                mod=self.organizer.getMod(name)
                if mod is None: continue
                # Restrict the preview to regular folders under the instance mods path.
                path=Path(mod.absolutePath())
                if path.parent.resolve()!=Path(self.organizer.modsPath()).resolve(): continue
                state=listing.state(name)
                separator=mod.isSeparator()
                mods.append(Mod(name,path,listing.priority(name),bool(int(state & mobase.ModState.ACTIVE)),separator))
            profile_name=Path(self.organizer.profilePath()).name
            OrganizerDialog(mods,profile_name,parent=self.parent).exec()
        except Exception as error:
            QMessageBox.critical(self.parent,'Asset Organizer preview failed',str(error))


def createPlugin():
    return SkyrimAssetOrganizer()
