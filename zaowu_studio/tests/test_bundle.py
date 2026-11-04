import zipfile
import pytest
from pathlib import Path
from studio.store import Store
from conftest import record

def test_full_bundle_rebases_assets_on_new_machine(store,tmp_path):
    media=tmp_path/'photo.png';media.write_bytes(b'local photo')
    asset=store.add_asset(media,'DIY散客','描述')
    piece=record(store,'pieces');store.link_assets(piece,[asset])
    package=tmp_path/'backup.zip';store.export_bundle(package)
    other=Store(tmp_path/'new-machine')
    try:
        safety=other.restore_bundle(package)
        assert safety.exists() and len(other.rows('pieces'))==1
        restored=Path(other.get('assets',asset)['path'])
        assert restored.parent==other.root/'assets' and restored.read_bytes()==b'local photo'
        assert other.assets_for(piece)[0]['description']=='描述'
    finally:other.close()

def test_zip_traversal_rejected_before_db_changes(store,tmp_path):
    record(store,'offers',name='原始资料')
    package=tmp_path/'bad.zip'
    with zipfile.ZipFile(package,'w') as file:
        file.writestr('../outside','bad');file.writestr('studio.sqlite3','bad');file.writestr('manifest.json','{}')
    with pytest.raises(ValueError,match='路径'):store.restore_bundle(package)
    assert store.rows('offers')[0]['name']=='原始资料'
    assert not (tmp_path/'outside').exists()

def test_checksum_tampering_rejected(store,tmp_path):
    good=tmp_path/'good.zip';store.export_bundle(good)
    bad=tmp_path/'bad.zip'
    with zipfile.ZipFile(good) as source,zipfile.ZipFile(bad,'w') as destination:
        for name in source.namelist():destination.writestr(name,b'corrupt' if name=='studio.sqlite3' else source.read(name))
    with pytest.raises(ValueError,match='校验'):store.restore_bundle(bad)
