from sqlalchemy import String, JSON, Double
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    # 合并批次：merge_key 保证同一组来源只落一个批次，来源数据集本身不修改。
    merge_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    merged_from: Mapped[list | None] = mapped_column(JSON, nullable=True)
    merge_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
