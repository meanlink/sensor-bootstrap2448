"""合并分次补传批次：按读数编号保留最高修订号，重复与并发合并幂等。"""
import copy
import math
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models import Dataset
from src.services.business import metadata
from src.utils.serialization import checksum

REVISION_KEY = 'revision'
MAX_ROWS = 5000
MERGE_RULE = '按读数编号保留最高修订号；同号同版内容冲突则整次拒绝；旧读数缺修订号视为初版；非法修订号拒绝合并；来源批次保持原样。'


def parse_revision(row, dataset_name, index):
    raw = row.get(REVISION_KEY)
    if raw is None:
        return 1
    detail = f'批次「{dataset_name}」第 {index+1} 条的修订号非法：须为不小于 1 的整数'
    if isinstance(raw, bool):
        raise HTTPException(422, detail)
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        if not raw.is_integer():
            raise HTTPException(422, detail)
        value = int(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if not text.isascii() or not text.isdigit():
            raise HTTPException(422, detail)
        value = int(text)
    else:
        raise HTTPException(422, detail)
    return value


def canonical_content(row):
    return checksum({k: v for k, v in row.items() if k != REVISION_KEY})


def normalize_row(row, dataset_name, index):
    if not isinstance(row, dict):
        raise HTTPException(422, f'批次「{dataset_name}」第 {index+1} 条不是有效的读数对象')
    sample = row.get('sample')
    if sample is None or str(sample).strip() == '':
        raise HTTPException(422, f'批次「{dataset_name}」第 {index+1} 条缺少读数编号')
    clean = copy.deepcopy(row)
    for column in metadata()['columns']:
        key = column['key']
        value = clean.get(key)
        if key == 'sample':
            clean[key] = str(value)
            continue
        if value is None or value == '':
            raise HTTPException(422, f'批次「{dataset_name}」第 {index+1} 条缺少字段 {column["label"]}')
        if column['type'] == 'number':
            try:
                if isinstance(value, bool):
                    raise ValueError()
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError()
                clean[key] = number
            except (TypeError, ValueError, OverflowError):
                raise HTTPException(422, f'批次「{dataset_name}」第 {index+1} 条 {column["label"]} 必须为有限数值')
        else:
            if not str(value).strip():
                raise HTTPException(422, f'批次「{dataset_name}」第 {index+1} 条 {column["label"]} 不能为空')
            clean[key] = str(value)
    clean[REVISION_KEY] = parse_revision(clean, dataset_name, index)
    return clean, clean[REVISION_KEY]


def load_sources(db, dataset_ids):
    if not isinstance(dataset_ids, list) or len(dataset_ids) < 2:
        raise HTTPException(422, '请至少选择两个数据批次进行合并')
    try:
        unique_ids = sorted({int(i) for i in dataset_ids})
    except (TypeError, ValueError):
        raise HTTPException(422, '批次编号必须为整数')
    if len(unique_ids) < 2:
        raise HTTPException(422, '请至少选择两个不同的数据批次进行合并')
    if len(unique_ids) > 50:
        raise HTTPException(422, '单次最多合并 50 个数据批次')
    sources = list(db.scalars(select(Dataset).where(Dataset.id.in_(unique_ids))))
    missing = sorted(set(unique_ids) - {d.id for d in sources})
    if missing:
        raise HTTPException(404, f'数据批次不存在：{", ".join(map(str, missing))}')
    return unique_ids, sources


def merge_key(sources):
    # 只取决于来源组合及其内容，与选择顺序无关。
    fingerprints = [{'id': d.id, 'checksum': d.checksum} for d in sorted(sources, key=lambda x: x.id)]
    return checksum({'rule': 'revision-merge-v1', 'sources': fingerprints})


def build(sources):
    """返回合并读数与逐来源保留/淘汰数量；不修改来源批次。"""
    source_stats = {
        d.id: {'dataset_id': d.id, 'name': d.name, 'source': d.source, 'checksum': d.checksum,
               'kind': 'merged' if d.merge_key else 'original', 'rows': 0, 'kept': 0, 'dropped': 0}
        for d in sources
    }
    # sample -> revision -> [(dataset, clean_row, content_hash)]
    occurrences = {}
    order = []
    for dataset in sorted(sources, key=lambda x: x.id):
        for index, row in enumerate(dataset.records or []):
            clean, revision = normalize_row(row, dataset.name, index)
            sample = clean['sample']
            source_stats[dataset.id]['rows'] += 1
            if sample not in occurrences:
                occurrences[sample] = {}
                order.append(sample)
            occurrences[sample].setdefault(revision, []).append((dataset, clean, canonical_content(clean)))

    conflicts = []
    for sample, versions in occurrences.items():
        for revision, entries in versions.items():
            if len({entry[2] for entry in entries}) > 1:
                names = '、'.join(sorted({f'{e[0].name}#{e[0].id}' for e in entries}))
                conflicts.append(f'读数 {sample} 修订号 {revision}（{names}）')
    if conflicts:
        preview = '；'.join(conflicts[:5]) + (' 等' if len(conflicts) > 5 else '')
        raise HTTPException(409, f'同号同版内容冲突，整次合并没有执行：{preview}。请更正修订号后重试。')

    records, record_sources, kept_by, dropped_rows = [], [], [], []
    for sample in order:
        versions = occurrences[sample]
        revision = max(versions)
        entries = versions[revision]
        # 同号同版内容一致，按批次编号取一条即可。
        winner = min(range(len(entries)), key=lambda i: entries[i][0].id)
        records.append(copy.deepcopy(entries[winner][1]))
        record_sources.append(entries[winner][0].id)
        kept_by.append({'sample': sample, 'revision': revision, 'dataset_id': entries[winner][0].id,
                        'dataset_name': entries[winner][0].name, 'source': entries[winner][0].source,
                        'band': entries[winner][1].get('band'), 'status': 'kept', 'reason': '最高修订号'})
        source_stats[entries[winner][0].id]['kept'] += 1
        for version, rows in versions.items():
            for index, entry in enumerate(rows):
                if version == revision and index == winner:
                    continue
                source_stats[entry[0].id]['dropped'] += 1
                dropped_rows.append({'sample': sample, 'revision': version, 'dataset_id': entry[0].id,
                                     'dataset_name': entry[0].name, 'source': entry[0].source,
                                     'band': entry[1].get('band'), 'status': 'dropped',
                                     'reason': '同号同版重复' if version == revision else f'被修订号 {revision} 取代'})
    if not records:
        raise HTTPException(422, '合并后没有可保留的读数')
    if len(records) > MAX_ROWS:
        raise HTTPException(422, f'合并后保留 {len(records)} 条读数，超过单次分析上限 {MAX_ROWS} 条，请减少来源批次')
    return {
        'sources': [source_stats[d.id] for d in sorted(sources, key=lambda x: x.id)],
        'input_rows': sum(s['rows'] for s in source_stats.values()),
        'kept_rows': len(records),
        'dropped_rows': sum(s['dropped'] for s in source_stats.values()),
        'records': records,
        'record_sources': record_sources,
        'provenance': kept_by + dropped_rows,
    }


def summary(result, dataset_ids):
    return {
        'rule': MERGE_RULE,
        'revision_key': REVISION_KEY,
        'dataset_ids': dataset_ids,
        'input_rows': result['input_rows'],
        'kept_rows': result['kept_rows'],
        'dropped_rows': result['dropped_rows'],
        'sources': result['sources'],
        'record_sources': result['record_sources'],
        'provenance': result['provenance'],
    }


def preview(db, dataset_ids):
    ids, sources = load_sources(db, dataset_ids)
    result = build(sources)
    return {'dataset_ids': ids, **result}


def find_by_key(db, key):
    return db.scalar(select(Dataset).where(Dataset.merge_key == key))


def create(db, data):
    ids, sources = load_sources(db, data.dataset_ids)
    name = (data.name or '').strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    key = merge_key(sources)
    existing = find_by_key(db, key)
    if existing:
        return existing, False
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    result = build(sources)
    source_label = '合并批次 · ' + ' + '.join(d.name for d in sorted(sources, key=lambda x: x.id))
    dataset = Dataset(name=name, source=source_label[:200],
                      records=result['records'], checksum=checksum(result['records']),
                      created_at=time.time(), merge_key=key, merged_from=ids,
                      merge_summary=summary(result, ids))
    db.add(dataset)
    try:
        db.flush()
    except IntegrityError:
        # 并发合并同组来源：另一请求已落库，回查并复用该批次。
        db.rollback()
        existing = find_by_key(db, key)
        if existing:
            return existing, False
        if db.scalar(select(Dataset).where(Dataset.name == name)):
            raise HTTPException(409, '该数据批次名已存在，请修改名称')
        raise HTTPException(409, '同一组来源正在被合并，请稍后重试')
    return dataset, True
