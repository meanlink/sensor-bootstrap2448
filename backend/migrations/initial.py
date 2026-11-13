from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models
def migrate():
    Base.metadata.create_all(engine)
    # create_all 不会给已有库补列；合并能力对旧演示库保持可升级。
    inspector=inspect(engine)
    columns={c['name'] for c in inspector.get_columns('datasets')}
    with engine.begin() as conn:
        for name,ddl in {'merge_key':'VARCHAR(64)','merged_from':'JSON','merge_summary':'JSON'}.items():
            if name not in columns:
                conn.execute(text(f'ALTER TABLE datasets ADD COLUMN {name} {ddl}'))
        # 新建库由模型 unique=True 建约束；旧库补唯一索引以承载并发幂等。
        if 'merge_key' not in columns:
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_datasets_merge_key ON datasets (merge_key)'))
        else:
            unique=any('merge_key' in (u.get('column_names') or []) for u in inspector.get_unique_constraints('datasets'))
            indexed=any(i.get('unique') and 'merge_key' in (i.get('column_names') or []) for i in inspector.get_indexes('datasets'))
            if not unique and not indexed:
                conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_datasets_merge_key ON datasets (merge_key)'))
if __name__=='__main__':migrate()
