import {datasets,jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,fmt,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

let mergeSelection=new Set();
let focusMergedId=null;
let provenanceCache=[];

function downloadProvenance(rows,filename){
 const blob=new Blob([JSON.stringify(rows,null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function mergeBadge(d){
 if(!d.merged)return '';
 return '<small class="merge-tag">合并 · 保留 '+(d.merge?.kept_rows??d.rows)+' / 淘汰 '+(d.merge?.dropped_rows??0)+'</small>';
}

function sourceRows(d){
 const sources=d.merge?.sources||[];
 return sources.map(s=>({name:s.name,dataset_id:'#'+s.dataset_id,kind:s.kind==='merged'?'合并批次':'原始批次',rows:s.rows,kept:s.kept,dropped:s.dropped}));
}

export async function dataPage(){
 workspace.datasets=await datasets.list();const m=workspace.meta;
 const selectedId=focusMergedId||workspace.datasets[0]?.id;
 let selected=selectedId?await datasets.get(selectedId):null;
 if(selectedId&&!workspace.datasets.some(d=>d.id===selectedId)){selected=null;focusMergedId=null;}
 provenanceCache=selected?.merge?.provenance||[];
 const canWrite=session.user.role!=='viewer';
 const isMerged=Boolean(selected?.merged);
 const batchList=workspace.datasets.map(d=>'<div class="batch-row"><input type="checkbox" class="merge-check" data-merge-select="'+d.id+'" '+(mergeSelection.has(d.id)?'checked':'')+' '+(canWrite?'':'disabled')+' aria-label="选择 '+esc(d.name)+' 参与合并"><button class="batch-item" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+d.rows+' 条 · '+esc(d.source)+'</span>'+mergeBadge(d)+'<small>SHA256 '+esc(d.checksum.slice(0,18))+'…</small></button></div>').join('');
 const preview=isMerged
  ? '<div class="section-title"><h2 id="preview-name">'+esc(selected.name)+'</h2><span>合并批次 · 保留 '+selected.merge.kept_rows+' / 淘汰 '+selected.merge.dropped_rows+'</span></div>'
   +'<div class="merge-summary">'+[['输入读数',selected.merge.input_rows],['保留读数',selected.merge.kept_rows],['淘汰读数',selected.merge.dropped_rows],['来源批次',selected.merge.sources.length]].map(([k,v])=>'<div><span>'+k+'</span><strong>'+v+'</strong></div>').join('')+'</div>'
   +'<p class="hint">'+esc(selected.merge.rule)+'</p>'
   +'<div class="merge-actions"><button class="primary" id="analyze-merged" data-dataset="'+selected.id+'" '+(canWrite?'':'disabled')+'>直接分析此合并批次 ↗</button><button class="button" id="download-provenance">下载完整来源清单 JSON ↓</button></div>'
   +'<div class="section-title"><h2>来源保留与淘汰</h2><span>不改动来源批次</span></div>'
   +table([{key:'name',label:'来源批次'},{key:'dataset_id',label:'编号'},{key:'kind',label:'类型'},{key:'rows',label:'输入'},{key:'kept',label:'保留'},{key:'dropped',label:'淘汰'}],sourceRows(selected))
   +'<div class="section-title"><h2>每条读数来源</h2><span>共 '+(selected.merge.provenance?.length||0)+' 条判定</span></div>'
   +table([{key:'sample',label:'读数编号'},{key:'revision',label:'修订号'},{key:'dataset_name',label:'来源批次'},{key:'status',label:'结果'},{key:'reason',label:'说明'}],(selected.merge.provenance||[]).slice(0,300))
   +((selected.merge.provenance?.length||0)>300?'<p class="hint">页面展示前 300 条判定；点击上方按钮下载完整清单核对每一条读数来源。</p>':'')
   +'<div class="section-title"><h2>保留读数预览</h2><span>前 30 条</span></div><div id="data-preview">'+table(m.columns,selected.records.slice(0,30))+'</div>'
  : '<div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span>预览前 30 条</span></div><div id="data-preview">'+table(m.columns,selected?.records.slice(0,30)||[])+'</div>';
 return heading('02 / DATA INTAKE','数据接入与批次追溯','保留原始业务字段、来源和内容指纹。分次补传可按读数合并，分析任务始终绑定一个不可变数据批次。')
  +'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div><div class="batch-list">'+batchList+'</div>'
  +'<div class="section-title"><h2>接入新数据</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><p class="hint">字段：'+m.columns.map(c=>esc(c.key)+' / '+esc(c.label)).join('，')+'。5–5,000 条记录。修订号可选，缺省视为初版。</p><button type="submit" class="primary" '+(canWrite?'':'disabled')+'>校验并接入批次</button></form></section>'
  +'<section class="panel">'+preview+'</section></div>'
  +'<section class="panel merge-panel"><div class="section-title"><h2>合并分次补传批次</h2><span id="merge-count">已选 '+mergeSelection.size+' 批</span></div><p class="hint">勾选上方至少两个批次，按读数编号保留最高修订号。同号同版内容冲突时整次拒绝；缺修订号视为初版；非法修订号拒绝合并；来源批次保持原样。重复或并发合并同一组来源只会生成一个批次，勾选顺序不影响结果。</p><div class="merge-form"><label>合并批次名称<input name="merge-name" id="merge-name" minlength="2" placeholder="例如：T-24 批次补传合并" value="'+esc((workspace.datasets[0]?.name||'批次')+' · 合并')+'"></label><div class="merge-actions"><button class="button" id="merge-preview" '+(mergeSelection.size<2||!canWrite?'disabled':'')+'>核对合并结果</button><button class="primary" id="merge-create" '+(mergeSelection.size<2||!canWrite?'disabled':'')+'>合并批次</button></div></div><div id="merge-review" class="merge-review"></div></section>';
}

function provenanceTable(preview){
 const rows=preview.provenance.slice(0,300);
 return '<div class="merge-summary">'+[['输入读数',preview.input_rows],['保留读数',preview.kept_rows],['淘汰读数',preview.dropped_rows],['保留占比',preview.input_rows?Math.round(preview.kept_rows/preview.input_rows*100)+'%':'—']].map(([k,v])=>'<div><span>'+k+'</span><strong>'+fmt(v)+'</strong></div>').join('')+'</div>'
  +'<div class="section-title"><h2>来源保留与淘汰</h2><span>核对后才落库</span></div>'
  +table([{key:'name',label:'来源批次'},{key:'dataset_id',label:'编号'},{key:'kind',label:'类型'},{key:'rows',label:'输入'},{key:'kept',label:'保留'},{key:'dropped',label:'淘汰'}],preview.sources.map(s=>({...s,dataset_id:'#'+s.dataset_id,kind:s.kind==='merged'?'合并批次':'原始批次'})))
  +'<div class="section-title"><h2>每条读数来源</h2><span>共 '+preview.provenance.length+' 条判定</span></div>'
  +table([{key:'sample',label:'读数编号'},{key:'revision',label:'修订号'},{key:'dataset_name',label:'来源批次'},{key:'status',label:'结果'},{key:'reason',label:'说明'}],rows)
  +(preview.provenance.length>300?'<p class="hint">仅展示前 300 条判定，完成合并后可查看完整清单。</p>':'');
}

export function bindData(refresh){
 let source='manual.json';
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{
  if(button.id==='analyze-merged')return;
  focusMergedId=null;
  try{const d=await datasets.get(button.dataset.dataset);document.querySelector('#preview-name').textContent=d.name;document.querySelector('#data-preview').innerHTML=table(workspace.meta.columns,d.records.slice(0,30));if(d.merged){focusMergedId=d.id;await refresh();}}catch(error){notify(error.message,true);}
 });
 document.querySelectorAll('[data-merge-select]').forEach(box=>box.onchange=()=>{
  const id=Number(box.dataset.mergeSelect);
  if(box.checked)mergeSelection.add(id);else mergeSelection.delete(id);
  const count=document.querySelector('#merge-count');if(count)count.textContent='已选 '+mergeSelection.size+' 批';
  ['#merge-preview','#merge-create'].forEach(selector=>{const b=document.querySelector(selector);if(b)b.disabled=mergeSelection.size<2||session.user.role==='viewer';});
 });
 document.querySelector('#merge-preview')?.addEventListener('click',async()=>{
  const review=document.querySelector('#merge-review');
  try{const preview=await datasets.mergePreview({dataset_ids:[...mergeSelection]});provenanceCache=preview.provenance;review.innerHTML=provenanceTable(preview);}
  catch(error){review.innerHTML='<p class="warning">'+esc(error.message)+'</p>';}
 });
 document.querySelector('#merge-create')?.addEventListener('click',async()=>{
  const name=document.querySelector('#merge-name').value.trim();
  if(name.length<2)return notify('合并批次名称至少需要两个字符',true);
  const button=document.querySelector('#merge-create');button.disabled=true;
  try{
   const d=await datasets.merge({name,dataset_ids:[...mergeSelection]});
   notify(d.created?'合并批次已生成，可直接分析':'该组来源已合并，已复用已有批次');
   mergeSelection=new Set();focusMergedId=d.id;await refresh();
  }catch(error){notify(error.message,true);button.disabled=false;}
 });
 document.querySelector('#download-provenance')?.addEventListener('click',()=>{
  if(!provenanceCache.length)return notify('暂无可下载的来源判定',true);
  downloadProvenance(provenanceCache,'合并批次来源判定.json');notify('来源清单已下载');
 });
 document.querySelector('#analyze-merged')?.addEventListener('click',async e=>{
  const datasetId=Number(e.currentTarget.dataset.dataset);
  const params={};for(const p of workspace.meta.parameters)params[p.key]=p.type==='number'?Number(p.default):p.default;
  try{const j=await jobs.create({name:'合并批次复核 · '+new Date().toLocaleString('zh-CN',{hour12:false}),dataset_id:datasetId,params});workspace.selectedJob=j.id;notify('已提交合并批次分析');location.hash='#/results/'+j.id;}catch(error){notify(error.message,true);}
 });
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});
}
