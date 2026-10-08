"""Self-contained Chinese report from saved artifacts; never run VIO or evo."""
import base64
import html
import json
import os
from pathlib import Path
import statistics
import re
from vio_artifacts import dump, manifest, sha, read_dicts

CSS='''
:root{--ink:#183b42;--accent:#096775;--line:#d4e0e3}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:#f0f5f6;font:16px/1.65 system-ui,sans-serif}header{padding:32px 5%;background:#123f47;color:white}header h1{margin:0;font-size:30px}.layout{display:grid;grid-template-columns:220px minmax(0,1fr);gap:24px;max-width:1600px;margin:auto;padding:24px}nav{position:sticky;top:16px;height:max-content}nav a{display:block;padding:9px;color:var(--ink);text-decoration:none}nav a:hover{background:white}section{background:white;border:1px solid var(--line);border-radius:10px;margin-bottom:22px;padding:24px;overflow-wrap:anywhere}h2{margin-top:0;color:var(--accent)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:#eef5f6;padding:16px;border-radius:8px}.card b{display:block;font-size:23px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border:1px solid var(--line);text-align:left}th{background:#ecf3f4}pre{white-space:pre-wrap;background:#f4f7f8;padding:14px;font:13px/1.6 monospace}details{margin:14px 0}summary{cursor:pointer;font-weight:600}figure{margin:18px 0}img{max-width:100%;height:auto}.zoom{border:0;background:transparent;padding:0;cursor:zoom-in}figcaption{font-size:14px;color:#465d63}dialog{max-width:96vw;max-height:96vh;padding:12px;border:0}dialog::backdrop{background:#000a}dialog img{max-height:85vh;object-fit:contain}.warning{border-left:5px solid #b35b00;padding:12px;background:#fff4e5}a{color:#086573}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}@media(max-width:850px){.layout{display:block;padding:12px}nav{position:static;display:flex;flex-wrap:wrap}section{padding:16px}}@media print{nav,.zoom-button{display:none}body{background:white}.layout{display:block}section{border:0}figure,tr{break-inside:avoid}pre{font-size:9px}.scroll{overflow:visible}}
'''

def diagnostics(run):
    """Render only saved raw frame values, with no smoothing or missing-as-zero."""
    replay=run/'03_vio/outputs/replay';frames=replay/'frames.csv'
    if not frames.is_file():return
    rows=read_dicts(frames)
    if not rows:return
    out=run/'report/diagnostics';out.mkdir(parents=True,exist_ok=True)
    if (out/'tracking.png').exists():return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    t=(np.array([int(r['corrected_ns']) for r in rows],dtype=np.int64)-int(rows[0]['corrected_ns']))*1e-9
    with plt.rc_context({'figure.facecolor':'white','axes.facecolor':'white'}):
        fig,axes=plt.subplots(3,1,figsize=(12,8),layout='constrained',sharex=True)
        axes[0].step(t,[int(r['state']) for r in rows],where='post',color='#0072B2',lw=1)
        axes[0].set_yticks([1,2,3,4],['WAIT','OK','RECENTLY_LOST','LOST']);axes[0].set_title('Complete input window; no startup trimming')
        initialized=next((i for i,r in enumerate(rows) if r['imu_initialized']=='1'),None)
        if initialized is not None:axes[0].axvline(t[initialized],color='black',ls='--',label=f'IMU initialized: frame {initialized}');axes[0].legend()
        resets=[i for i in range(1,len(rows)) if rows[i]['resets']!=rows[i-1]['resets']]
        axes[0].scatter(t[resets],[1]*len(resets),marker='|',color='#B35B00',label='reset')
        for c,(color,style) in enumerate(zip(['#0072B2','#B35B00','#007F6D','#7F4283'],['-','--','-.',':'])):
            axes[1].plot(t,[int(r[f'cam{c}_features']) for r in rows],color=color,ls=style,lw=1,label=f'cam{c}')
        axes[1].set_ylabel('Feature count');axes[1].set_ylim(bottom=0);axes[1].legend(ncol=4)
        axes[2].plot(t,[float(r['track_ms']) for r in rows],color='#007F6D',lw=1);axes[2].set(ylabel='TrackMulti [ms]',xlabel='Seconds since first input (IMU clock)');axes[2].set_ylim(bottom=0)
        for ax in axes:ax.grid(color='#dddddd')
        fig.savefig(out/'tracking.png',dpi=160);plt.close(fig)
        if (replay/'diagnostics.csv').is_file():
            detail=read_dicts(replay/'diagnostics.csv')
            if len(detail)==len(rows):
                fig,ax=plt.subplots(figsize=(12,4),layout='constrained')
                for c,(color,style) in enumerate(zip(['#0072B2','#B35B00','#007F6D','#7F4283'],['-','--','-.',':'])):
                    counts=np.array([int(r[f'local_after_cam{c}']) for r in detail],float);counts[counts<0]=np.nan
                    ax.plot(t,counts,label=f'cam{c}',color=color,ls=style,lw=1)
                ax.set(xlabel='Seconds since first input [s]',ylabel='Local optimized observations');ax.set_ylim(bottom=0);ax.grid(color='#dddddd');ax.legend(ncol=4)
                fig.savefig(out/'camera_support.png',dpi=160);plt.close(fig)

def saved_resources(run):
    """Derive display statistics from frozen files without relabeling the replay."""
    run=Path(run);result={}
    p=run/'03_vio/diagnostics/resource_usage.txt'
    if p.is_file():
        text=p.read_text()
        for label,key in [('Maximum resident set size (kbytes)','peak_rss_kib'),('User time (seconds)','cpu_user_s'),('System time (seconds)','cpu_system_s')]:
            m=re.search(re.escape(label)+r':\s*([0-9.]+)',text)
            if m:result[key]=float(m[1])
    p=run/'03_vio/outputs/replay/frames.csv'
    if p.is_file():
        rows=read_dicts(p);values=[float(r['track_ms']) for r in rows]
        if values:result.update(track_ms_median=statistics.median(values),track_ms_max=max(values),track_total_s=sum(values)*.001)
        if len(rows)>1:result['processed_input_duration_s']=(int(rows[-1]['corrected_ns'])-int(rows[0]['corrected_ns']))*1e-9
    result['scope']='Saved single-process /usr/bin/time (peak RSS includes GUI); TrackMulti excludes preparation, report, and evaluation; cache state uncontrolled'
    return result

def configuration_changes(run):
    from convert_rig_to_openmavis import load_settings
    paths=[Path(run)/n for n in ['01_preparation/inputs/algorithm_template.yaml','01_preparation/outputs/openmavis.yaml']]
    if not all(p.is_file() for p in paths):return []
    before,after=[load_settings(p) for p in paths]
    return [dict(key=k,template=before.get(k),generated=after.get(k)) for k in sorted(before.keys()|after.keys()) if before.get(k)!=after.get(k)]

def generate(run):
    run=Path(run).resolve();m=manifest(run);directory=run/'report';directory.mkdir(parents=True,exist_ok=True)
    missing=[];sources={};images=[]
    def read(relative,required=True):
        p=run/relative
        if not p.is_file():
            if required:missing.append(relative)
            return {}
        sources[relative]=sha(p);return json.loads(p.read_text())
    summary=read('03_vio/outputs/summary.json');comp=read('04_vio_comparison/summary/summary.json')
    reference=read('02_reference/inputs/sources.json');prep=read('01_preparation/outputs/preparation.json');conversion=read('02_reference/inputs/groundtruth/conversion.json')
    os.environ.setdefault('MPLCONFIGDIR',str(run/'plot_cache'))
    diagnostics(run)
    e=lambda s:html.escape(str(s),quote=True)
    def block(label,value):return '<details><summary>'+e(label)+'</summary><pre>'+e(json.dumps(value,ensure_ascii=False,indent=2))+'</pre></details>'
    def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    def figure(path,caption):
        path=Path(path)
        if not path.is_file():return ''
        mime='image/jpeg' if path.suffix.lower() in ['.jpg','.jpeg'] else 'image/png';relative=str(path.relative_to(run))
        sources[relative]=sha(path);images.append(relative)
        return '<figure><button class="zoom" aria-label="放大 '+e(caption)+'"><img alt="'+e(caption)+'" src="data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()+'"></button><figcaption>'+e(caption)+' · '+e(relative)+'</figcaption></figure>'
    sections=[]
    def section(key,title,body):sections.append((key,title,'<section id="'+key+'"><h2>'+e(title)+'</h2>'+body+'</section>'))
    online=summary.get('online',{});common=comp.get('common_timestamps',{})
    cards=[('流程',m['status']),('跟踪验收',m.get('tracking_acceptance','待执行')),('共同评测',common.get('status','待执行')),('输入/处理',f"{summary.get('input_frames','—')} / {summary.get('processed_frames','—')}"),('主评测在线位姿',online.get('accepted_poses','—')),('共同样本',common.get('n','—'))]
    section('overview','运行状态与输入','<div class="cards">'+''.join('<div class="card">'+e(k)+'<b>'+e(v)+'</b></div>' for k,v in cards)+'</div>'+('<p class="warning">'+e(m.get('error',''))+'</p>' if m.get('error') else '')+block('运行参数与阶段记录',{'run':str(run),'parameters':m['parameters'],'stages':m['stages'],'invocation':m['invocation'],'evo_gui':m.get('evo_gui')}))
    section('reference','参考轨迹与时间口径','<p>mocap 已转换到物理 IMU/body 与 IMU 时钟，原样导入，不再次应用时间偏移、marker 外参或拟合新偏移。SE(3) 对齐不估计尺度。</p><p>主结果是 OpenMAVIS 每帧处理完成的在线 body→当前世界位姿，仅评测 OK 且已惯性初始化的样本。Basalt/OKVIS2 使用来源保存的在线轨迹；其输出位姿数量不等于经本流水线证明的 OK 数量。</p>'+block('GT 转换与有效段',conversion)+block('冻结参考文件来源与哈希',reference))
    counts=[['输入组',summary.get('input_frames','—')],['实际处理',summary.get('processed_frames','—')],['全窗口 OK',summary.get('ok_frames','—')],['在线主评测位姿',online.get('accepted_poses','—')],['Common GT 可匹配样本',common.get('n','—')],['最终最大地图导出',summary.get('trajectories',{}).get('trajectory_body.txt',{}).get('rows','—')]]
    section('coverage','覆盖、初始化与四路支持',table(['口径','数量'],counts)+'<p>完整输入窗口包含初始化等待、丢失和重置；排除项与坐标段单列。四路观测次数不能相加作为独立地图点数。下图使用原始逐帧值，无平滑；未执行优化阶段保留缺口。</p>'+figure(directory/'diagnostics/tracking.png','完整跟踪状态、四路特征与处理耗时')+figure(directory/'diagnostics/camera_support.png','四路局部优化后观测支持')+block('完整回放汇总',summary)+block('保存产物计算的资源与耗时',saved_resources(run)))
    metric_names={'ape_translation':'APE 平移','rpe_translation_0.1m':'RPE 0.1 m','rpe_translation_0.5m':'RPE 0.5 m','rpe_translation_1m':'RPE 1 m'}
    def metrics(records):
        rows=[]
        for key,label in metric_names.items():
            for name,r in records.items():
                s=r.get('metrics',{}).get(key,{})
                rows.append([label,name,*[format(s[k],'.6g') if isinstance(s.get(k),float) else s.get(k,'—') for k in ['rmse','mean','median','std','min','max','sse','n','p95','p99']],r.get('unavailable_metrics',{}).get(key,r.get('unavailable_metrics',{}).get('all',''))])
        return table(['指标','算法','RMSE(m)','Mean(m)','Median(m)','STD(m)','Min(m)','Max(m)','SSE(m²)','N','P95(m)','P99(m)','不可用原因'],rows)
    section('common','Common：共同有效时间戳','<p>所有参与算法与 GT 的整数纳秒交集，估计不插值、不补帧。GT 插值不外推、不跨无效段、最大间隔 50 ms。RPE 使用参考距离配对与 10% 容差，剔除跨无效段配对。</p>'+block('共同时间戳与可用性',common)+metrics(comp.get('common',{}))+''.join(figure(run/'04_vio_comparison/common'/n,c) for n,c in [('trajectories.png','各算法与 mocap 的共同窗口轨迹；各自 SE(3) 无尺度对齐'),('ape_translation.png','共同窗口平移 APE；缺口不连接'),('rpe_translation.png','共同参考距离帧对的平移 RPE')]))
    native=comp.get('native',{})
    section('native','Native：各自有效覆盖','<details><summary>展开各算法自身覆盖与指标</summary>'+metrics(native)+''.join(figure(p,p.parent.name+' Native '+p.name) for p in sorted((run/'04_vio_comparison/native').glob('*/*.png')))+block('完整统计与插值审计',native)+'</details>')
    final=comp.get('final_map',{})
    section('final','最终地图补充结果','<details><summary>展开最终地图轨迹（非在线主评测）</summary><p>该轨迹通过最终参考关键帧重建，受后续地图优化影响，原导出器只保存最大地图。与在线轨迹分别评测，不能把导出行数作为成功跟踪帧数。微秒导出时间仅凭 frames.csv 唯一恢复，容差 501 ns，不用于在线时间或放宽 Common 匹配。</p>'+metrics({'openmavis_final_map':final})+''.join(figure(p,'最终地图补充 '+p.name) for p in sorted((run/'04_vio_comparison/final_map').glob('*.png')))+'</details>')
    configuration={}
    for n in ['01_preparation/inputs/algorithm_template.yaml','01_preparation/outputs/openmavis.yaml']:
        p=run/n
        if p.is_file():configuration[n]=p.read_text();sources[n]=sha(p)
    section('config','配置与实际 VIO 模式','<p>新流水线锁定 VIOOnly：回环、地图合并和回环 GBA 计数必须为零，GUI 不能重新开启。保留初始化必要优化与局部惯性优化。OpenMAVIS 有效射线过滤与参考算法保存的 mask 策略不同，本轮不修改任何来源策略或重新运行参考算法。</p>'+table(['配置项','模板','生成值'],[[r['key'],json.dumps(r['template'],ensure_ascii=False),json.dumps(r['generated'],ensure_ascii=False)] for r in configuration_changes(run)])+block('生成与模板配置',configuration)+block('标定转换审计',prep.get('conversion',{})))
    replay=run/'03_vio/outputs/replay';rows=read_dicts(replay/'frames.csv') if (replay/'frames.csv').is_file() else []
    init=next((int(r['frame']) for r in rows if r['imu_initialized']=='1'),None)
    samples=[init] if init is not None else []
    failures=[int(r['frame']) for r in rows if int(r['state'])==3]
    if failures:samples += [failures[0]]
    section('overlays','四目诊断叠图','<p>按首次 IMU 初始化和首次丢失选帧，非 GUI 截屏。原 JPEG 嵌入，无裁剪/颜色调整；绿色对应为接受、暗红为抽样拒绝候选，不构成绝对精度证明。</p>'+''.join(figure(replay/'overlays'/f'frame_{f}.jpg',f'四目原始诊断：frame {f}') for f in dict.fromkeys(samples)))
    section('limits','来源、缺失项与限制','<p>流程完成、跟踪连续性和精度是独立结论。多个初始化坐标段不拼接排名。物理 IMU 坐标与 marker–IMU 标定依赖来源标定，未做独立重新标定；本轮单次评测不证明场景泛化。数据链接目标必须持续可读；缓存状态未控制，GUI 耗时包含显示开销。</p>'+block('来源文件未改变',m.get('source_hashes_unchanged',False))+block('缺失项',missing)+block('软件及调用',m.get('software',{})))
    data=dict(run=str(run),status=m['status'],tracking_acceptance=m.get('tracking_acceptance'),summary=summary,comparison=comp,reference=reference,resources=saved_resources(run),configuration_changes=configuration_changes(run),missing=missing,images=images)
    for relative in ['03_vio/diagnostics/resource_usage.txt','03_vio/outputs/replay/frames.csv','03_vio/outputs/replay/diagnostics.csv']:
        p=run/relative
        if p.is_file():sources[relative]=sha(p)
    dump(directory/'report_data.json',data)
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>OpenMAVIS VIO 运行报告</title><style>'+CSS+'</style><body><header><h1>OpenMAVIS 四目 VIO 运行报告</h1><p>'+e(run.name)+'</p></header><div class="layout"><nav>'+''.join('<a href="#'+key+'">'+e(title)+'</a>' for key,title,_ in sections)+'<button onclick="window.print()">打印</button></nav><main>'+''.join(body for _,_,body in sections)+'</main></div><dialog id="lightbox"><button id="close">关闭</button><img alt="放大图表"></dialog><script>const d=document.querySelector("dialog");document.querySelectorAll(".zoom").forEach(b=>b.onclick=()=>{d.querySelector("img").src=b.querySelector("img").src;d.querySelector("img").alt=b.querySelector("img").alt;d.showModal()});document.querySelector("#close").onclick=()=>d.close();d.onclick=e=>{if(e.target===d)d.close()};</script></body></html>'
    (directory/'index.html').write_text(page)
    dump(directory/'generation.json',dict(source_sha256=sources,embedded_images=images,external_dependencies=[],methods='Raw saved values; no smoothing; excluded samples/state and coordinate segments recorded; report does not replay/evaluate'))
    return directory/'index.html'

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True,type=Path);a=ap.parse_args();print(generate(a.run))
