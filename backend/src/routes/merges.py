from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset
from src.schemas.merge import MergeInput, MergePreviewInput
from src.middlewares.auth import current_user, can_write
from src.services import merges
from src.services.audit import record
from src.utils.serialization import merged_dataset_dict
router=APIRouter(prefix='/datasets')
@router.post('/merge/preview')
def merge_preview(data:MergePreviewInput,db=Depends(get_db),u=Depends(can_write)):
    return merges.preview(db,data.dataset_ids)
@router.post('/merge',status_code=201)
def merge(data:MergeInput,db=Depends(get_db),u=Depends(can_write)):
    d,created=merges.create(db,data)
    if created:
        record(db,u.email,'dataset.merge',{'id':d.id,'sources':d.merged_from,'kept':d.merge_summary['kept_rows'],'dropped':d.merge_summary['dropped_rows']})
    db.commit()
    # 同组来源重复/并发合并复用已有批次，用 200 区分“未新建”。
    return JSONResponse(merged_dataset_dict(d,created),status_code=201 if created else 200)
@router.get('/{id}/merge')
def merge_detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Dataset,id)
    if not d:raise HTTPException(404,'数据批次不存在')
    if not d.merge_key:raise HTTPException(404,'该批次不是合并批次')
    return merged_dataset_dict(d,False)
