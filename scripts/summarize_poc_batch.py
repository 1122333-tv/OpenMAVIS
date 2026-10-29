#!/usr/bin/env python3
"""Self-contained six-sequence VIO report from saved comparison artifacts only."""
import argparse
import base64
import csv
import datetime
import html
import json
from pathlib import Path
import shutil
from vio_artifacts import dump, sha, manifest
from generate_vio_report import CSS, saved_resources
from run_poc_batch import ORDER

TITLES={'small_move':'小范围运动','big_move':'大范围运动','dynamic_background':'动态背景',
        'static_H_30s':'水平静止','static_V_30s':'竖直静止','static_H_30s_humanmove':'水平静止／有人经过（补充）'}
ALGORITHMS={'openmavis':'OpenMAVIS','okvis':'OKVIS2','basalt':'Basalt'}
DISPLAY=['static_H_30s','static_V_30s','small_move','big_move','dynamic_background','static_H_30s_humanmove']

def generate(root):
    root=Path(root).resolve();state=json.loads((root/'state.json').read_text());out=root/'report';out.mkdir(exist_ok=True)
    sources={str(root/'state.json'):sha(root/'state.json')};embedded=[];data={};csv_rows=[]
    def read(path):
        sources[str(path)]=sha(path);return json.loads(path.read_text())
    for name in DISPLAY:
        record=state['runs'][name]
        if 'run' not in record:continue
        r=Path(record['run']);m=manifest(r);sources[str(r/'manifest.yaml')]=sha(r/'manifest.yaml')
        summary=read(r/'03_vio/outputs/summary.json');comparison=read(r/'04_vio_comparison/summary/summary.json')
        data[name]=dict(run=str(r),source_run=record['source_run'],basalt_run=record['basalt_run'],
            status=record['status'],profile=record['profile'],summary=summary,comparison=comparison,
            parameters=m['parameters'],resources=saved_resources(r))
        for scope in ['common','native']:
            for algorithm,values in comparison[scope].items():
                for metric,s in values.get('metrics',{}).items():
                    csv_rows.append(dict(scene=name,scope=scope,algorithm=algorithm,metric=metric,
                        unit=values['metric_units'][metric],rmse=s['rmse'],p95=s['p95'],n=s['n']))
    e=lambda value:html.escape(str(value),quote=True)
    def table(headers,rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    def detail(title,value):return '<details><summary>'+e(title)+'</summary><pre>'+e(json.dumps(value,ensure_ascii=False,indent=2))+'</pre></details>'
    def figure(p,caption):
        if not p.is_file():return ''
        relative=str(p.relative_to(root));sources[str(p)]=sha(p);embedded.append(relative)
        return '<figure><button class="zoom" aria-label="放大 '+e(caption)+'"><img loading="lazy" alt="'+e(caption)+'" src="data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()+'"></button><figcaption>'+e(caption)+'</figcaption></figure>'
    def value(record,key,stat,factor=1):
        s=record.get('metrics',{}).get(key)
        return format(s[stat]*factor,'.3f') if s else '不可用'
    overview=[];coverage=[]
    for name,d in data.items():
        s=d['summary'];c=d['comparison'];common=c['common_timestamps'];online=s['online']
        frames=s.get('processed_frames',0);init=s.get('first_imu_initialized_frame')
        from vio_artifacts import read_dicts
        f=Path(d['run'])/'03_vio/outputs/replay/frames.csv';sources[str(f)]=sha(f);rows=read_dicts(f)
        init_seconds=(int(rows[init]['corrected_ns'])-int(rows[0]['corrected_ns']))*1e-9 if init is not None and rows else None
        d['initialization_seconds']=init_seconds
        coverage.append([TITLES[name],f"{frames}/{s['input_frames']}",format(init_seconds,'.2f') if init_seconds is not None else '未初始化',
            f"{online['accepted_poses']}/{s['input_frames']}",f"{100*online['accepted_poses']/s['input_frames']:.1f}%",
            s.get('total_resets'),s.get('post_init_resets'),s.get('post_init_map_changes'),s.get('acceptance'),common['n']])
        for algorithm,label in ALGORITHMS.items():
            r=c['common'].get(algorithm,{})
            overview.append([TITLES[name],label,value(r,'ape_translation','rmse',100),value(r,'ape_translation','p95',100),
                value(r,'are_rotation','rmse'),value(r,'are_rotation','p95'),common['n'],common['status']])
    sections=[]
    def section(key,title,body):sections.append((key,title,'<section id="'+key+'"><h2>'+e(title)+'</h2>'+body+'</section>'))
    section('overview','三算法共同窗口结果',
        '<p>1026 录制的五个主场景及一个补充场景。OpenMAVIS 每包运行一次；OKVIS2、Basalt 复用已保存的在线 VIO 结果。以下数值在新的三算法共同窗口重新计算，可能与原双算法报告不同。</p>'
        '<p class="warning">整体 NOT_GATED；原始 Mocap 采集 QA 为 REJECT。有效 GT 覆盖率不能替代采集 QA 或同步验收。每场景只有一次录制、一次本轮运行，未验证重复性或产品精度。</p>'
        +table(['场景','算法','APE RMSE cm','APE P95 cm','ARE RMSE °','ARE P95 °','共同样本','可用性'],overview))
    section('coverage','完整输入与 OpenMAVIS 初始化',
        '<p>有效 VIO 只包含跟踪 OK、已完成惯性初始化、位姿有限的在线样本。共同窗口精度不能替代完整输入覆盖率；零个或多个已初始化坐标段不拼接、不选择最好片段排名。跟踪验收未通过时，仍保留诊断及可以计算的指标。</p>'
        +table(['场景','处理/输入','初始化 s','有效VIO/输入','有效覆盖','总重置','初始化后重置','初始化后切图','跟踪判定','共同样本'],coverage))
    section('methods','评测与输入策略',
        '<p>三算法使用整数纳秒共同时间戳；估计轨迹不插值。GT 使用每包冻结的 IMU/body 轨迹与对时结果，位置线性、姿态最短弧 SLERP 插值，不外推、不跨有效段，最大间隔 50 ms。相机偏移 +5,449,054 ns 仅在图像时间转 IMU 时钟时应用一次。</p>'
        '<p>静止包采用各评测窗口起始有效 1 s 平均位姿对齐；运动包采用整段共同位置 SE(3) 对齐；均不校正尺度。APE 为平移绝对误差，ARE 为旋转角绝对误差；RPE/RRE 分别为平移与旋转相对误差。静止采用 0.1/1 s，运动采用 0.1/0.5/1 m 并补 0.1/1 s。帧对容差 10%，排除任何算法输出中断、已知重置及 GT 无效段的跨段配对。</p>'
        '<p>OpenMAVIS 和本次 OKVIS2 均使用原始 IMU、零初始 bias、在线估计；Basalt 参考先应用固定 IMU 标定再估计剩余 bias。OpenMAVIS 使用有效射线过滤，参考算法保留各自 mask。此次对比包含这些配置差异。</p>'
        '<p>三者比较在线历史位姿快照；OpenMAVIS 回环、地图合并和回环 GBA 关闭，保留初始化及局部惯性优化。不混入最终地图回溯修正轨迹。Native 为各自有效窗口，数值不能作为完全相同样本的排名。</p>'
        '<p>所有误差图显示原始误差，无平滑或尺度拟合；缺口不连线。P95 是样本误差的 95 分位，不是置信区间。世界 Y 向上、XZ 为水平面。耗时包含读取与日志，NAS 缓存及主机负载未控制，不代表实时性能。</p>')
    for name,d in data.items():
        r=Path(d['run']);c=d['comparison'];common=c['common_timestamps'];body=''
        if common['status']!='available':body+='<p class="warning">三算法共同评测不可用：'+e(common.get('reason',''))+'</p>'
        body+=figure(r/'report/diagnostics/tracking.png','完整输入的跟踪状态、四路特征与处理耗时')
        body+=figure(r/'report/diagnostics/camera_support.png','四路局部优化有效观测')
        for scope in ['common','native']:
            rows=[]
            keys=list(dict.fromkeys(k for rec in c[scope].values() for k in rec.get('metric_records',{})))
            for key in keys:
                for algorithm,label in ALGORITHMS.items():
                    rec=c[scope].get(algorithm,{});unit='deg' if 'rotation' in key else 'm';factor=100 if unit=='m' else 1
                    st=rec.get('metrics',{}).get(key,{})
                    rows.append([key,label,'°' if unit=='deg' else 'cm',value(rec,key,'rmse',factor),value(rec,key,'p95',factor),st.get('n','—'),rec.get('unavailable_metrics',{}).get(key,rec.get('unavailable_metrics',{}).get('all',''))])
            content=table(['指标','算法','单位','RMSE','P95','N','不可用原因'],rows)
            dest=r/'04_vio_comparison'/('common' if scope=='common' else 'native/combined')
            for p in sorted(dest.glob('*.png')):content+=figure(p,TITLES[name]+' / '+scope+' / '+p.stem)
            body+=('<h3>共同窗口</h3>'+content) if scope=='common' else '<details><summary>各自有效窗口 Native（单独诊断）</summary>'+content+'</details>'
        body+=detail('完整指标、初始化与来源',d)
        section(name,TITLES[name],body)
    preservation=read(root/'preservation.json') if (root/'preservation.json').exists() else {}
    context=read(root/'reference_batch_context.json') if (root/'reference_batch_context.json').exists() else {}
    section('provenance','复现与来源校验',detail('来源文件保护校验',preservation)+detail('批次和输入映射',state)+detail('参考批次的 QA 和 IMU 策略记录',context)+
            '<p>每包原始轨迹、误差数组、相同帧对校验、排除记录及命令保存在对应 run。原始图像使用链接，不复制数据包；参考算法未重新运行。</p>')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>1026 POC 三算法 VIO 对比</title><style>'+CSS+'</style><body><header><h1>1026 POC · OpenMAVIS / OKVIS2 / Basalt VIO</h1><p>六包单次回放 · 在线轨迹 · 无尺度校正 · NOT_GATED</p></header><div class="layout"><nav>'+''.join('<a href="#'+key+'">'+e(title)+'</a>' for key,title,_ in sections)+'<button onclick="window.print()">打印</button></nav><main>'+''.join(body for _,_,body in sections)+'</main></div><dialog><button id="close">关闭</button><img alt="放大图表"></dialog><script>const d=document.querySelector("dialog");document.querySelectorAll(".zoom").forEach(b=>b.onclick=()=>{const i=b.querySelector("img");d.querySelector("img").src=i.src;d.querySelector("img").alt=i.alt;d.showModal()});document.querySelector("#close").onclick=()=>d.close();d.onclick=e=>{if(e.target===d)d.close()};</script></body></html>'
    (out/'index.html').write_text(page)
    with (out/'metrics.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=['scene','scope','algorithm','metric','unit','rmse','p95','n']);writer.writeheader();writer.writerows(csv_rows)
    dump(out/'report_data.json',dict(state=state,data=data,preservation=preservation,reference_batch_context=context))
    dump(out/'generation.json',dict(source_sha256=sources,embedded_images=embedded,external_dependencies=[],generated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    shutil.copyfile(Path(__file__),out/'summarize_poc_batch.py')
    print(out/'index.html')
    return out/'index.html'

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--batch',type=Path,required=True);generate(ap.parse_args().batch)
