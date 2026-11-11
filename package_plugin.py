"""Package only plugin source files, excluding testbeds and local dependencies."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
destination = root / 'dist' / 'SkyrimAssetOrganizer-preview-0.2.0.zip'
destination.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
    for source in sorted((root/'plugin/SkyrimAssetOrganizer').glob('*.py')):
        archive.write(source, f'SkyrimAssetOrganizer/{source.name}')
print(destination)
