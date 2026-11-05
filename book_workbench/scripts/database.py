"""Initialize or migrate; also runs automatically at startup."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workbench.store import Store
if __name__=='__main__':
    store=Store(Path(sys.argv[1]) if len(sys.argv)>1 else None)
    print('数据库初始化／迁移完成，版本',store.db.execute('PRAGMA user_version').fetchone()[0]);store.close()
