import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    # 列表只带核对摘要，逐条判定在合并批次详情中返回，避免列表响应过大。
    merge=None
    if d.merge_key:
        merge={k:v for k,v in (d.merge_summary or {}).items() if k not in ('provenance','record_sources')}
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at,
            'merged':bool(d.merge_key), 'merged_from':d.merged_from or [], 'merge':merge}
def merged_dataset_dict(d,created):
    return {**dataset_dict(d),'merge':d.merge_summary,'records':d.records,'created':created}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
