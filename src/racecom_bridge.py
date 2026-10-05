"""Translate our race model to RaceCom inputs and call its unmodified renderer.

No third-party rendering code or artwork is distributed with this adapter.
"""
from datetime import datetime,timedelta
from pathlib import Path
import threading
from xml.sax.saxutils import escape
import zipfile
from race_model import describe,lap_time,number
from storage import atomic_json
from renderer_process import run


def local_start(meta):
    try:return datetime.fromisoformat(meta.get('started_utc','').replace('Z','+00:00')).astimezone()
    except ValueError:return None


def adapt(model):
    meta=model['session'];summary=model['summary'];start=local_start(meta)
    finish_flag=summary.get('finish_flag',0);finish_text={2:'DNF',3:'DQ'}.get(finish_flag,'')
    laps=[]
    for lap in model['laps']:
        if not lap['complete'] or number(lap['time']) is None or lap['time']<=0:continue
        item={k:lap.get(k) for k in ('num','time','valid','best','s1','s2','s3')}
        item['game_valid']=lap['valid']
        excluded=lap['partial'] or lap['in_pits'] or lap['valid'] is not True or lap.get('missed_laps',0)>0
        # RaceCom recomputes its fastest lap from 'valid'. Explicit cancellation
        # means excluded from report statistics, not a fabricated game penalty.
        item['valid']=lap['valid'] is True and not excluded
        item['note']=' / '.join(s for s in ('无效' if lap['valid'] is False else '有效性未知' if lap['valid'] is None else '',
            '部分记录' if lap['partial'] else '', 'PIT' if lap['in_pits'] else '', '最快' if lap['best'] else '') if s)
        if excluded and lap['valid'] is not False:item['note']='统计无效 / '+item['note']
        for key,best in zip(('s1','s2','s3'),model['sector_bests']):item[key+'_best']=best is not None and lap.get(key)==best
        laps.append(item)
    return dict(date=start.strftime('%Y-%m-%d %H:%M:%S') if start else meta.get('started_utc','未知'),
        track=meta.get('track',''),session={'Qualify':'排位赛','Race':'正赛','Practice':'练习赛'}.get(model['session_type'],model['session_type']),
        session_code=meta.get('session'),driver=meta.get('driver',''),vehicle=meta.get('vehicle',''),team=summary.get('team',''),
        start_place=summary.get('grid_place'),finish_place=None if finish_text else summary.get('finish_place'),
        observed_finish_place=summary.get('finish_place'),finish_flag=finish_flag,stintlab_finish_text=finish_text,
        session_best_lap=summary.get('session_best_lap'),session_best_driver=summary.get('session_best_driver',''),
        impact_count=summary.get('impact_count') if model['scoring_available'] else '未知',
        # This is explicitly an estimate, never a Race Control warning count.
        track_limit_count='未知（边界估算 '+str(summary.get('offtrack_estimate_count','未知'))+'）',
        laps=laps,events=[dict(time=(start+timedelta(seconds=e['time']-model['origin'])).strftime('%H:%M:%S') if start else '',
            text=describe(e)) for e in model['events']]+[
                dict(time='',text=text) for text in ('缺失字段显示未知；未采集的信息不补造。','出界为边界估算，非官方警告；碰撞合并连续接触。',
                    '统计无效 = 排除部分记录 / PIT / 未验证圈，不代表游戏处罚。')])


def lap_rows(value):
    yield ['圈','圈速','Δ','S1','S2','S3','备注']
    best=next((lap['time'] for lap in value['laps'] if lap['best']),None)
    for lap in value['laps']:
        delta='-'
        if best is not None and lap['valid'] is True:
            delta='±0.000' if lap['best'] else f"{lap['time']-best:+.3f}"
        yield [str(lap['num']),lap_time(lap['time']),delta,
            *[f'{lap[k]:.3f}' if number(lap[k]) is not None else '-' for k in ('s1','s2','s3')],lap.get('note','')]


def write_xlsx(path,rows):
    """The same five-part inline-string workbook consumed by RaceCom."""
    namespace='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',f'<worksheet xmlns="{namespace}"><sheetData>']
    for n,row in enumerate(rows,1):
        sheet.append(f'<row r="{n}">')
        for col,value in enumerate(row):
            sheet.append(f'<c r="{chr(65+col)}{n}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
        sheet.append('</row>')
    sheet.append('</sheetData></worksheet>')
    contents={'[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml':f'<workbook xmlns="{namespace}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="圈速表" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml':''.join(sheet)}
    pending=path.with_name(path.name+'.pending')
    try:
        with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,text in contents.items():archive.writestr(name,text.encode('utf-8'))
        pending.replace(path)
    finally:pending.unlink(missing_ok=True)


def write_inputs(folder,model):
    folder=Path(folder)/'_racecom';folder.mkdir(exist_ok=True);value=adapt(model)
    atomic_json(folder/'race_log.json',value);rows=list(lap_rows(value));write_xlsx(folder/'laps.xlsx',rows)
    position=lambda n:f'第 {n} 名' if n else '未知'
    fastest=next((lap for lap in value['laps'] if lap['best']),None)
    header=['='*64,'比赛日志','='*64]
    header += [f'{label}：{value[key]}' for label,key in [('日期','date'),('赛道','track'),('类型','session'),('车手','driver'),('车型','vehicle'),('车队','team')]]
    header += [f"比赛圈数：{len(value['laps'])}",f"发生碰撞：{value['impact_count']}次",
        # No digits in the TXT field: original loader takes our labelled JSON value.
        '超出赛道限制：未知',f"发车位置：{position(value['start_place'])}",f"结束名次：{value['stintlab_finish_text'] or position(value['finish_place'])}",
        f"全场最快单圈：{lap_time(value['session_best_lap'])} - {value['session_best_driver'] or '未知'}",
        f"个人最速单圈：{lap_time(fastest['time'])} - in Lap {fastest['num']}" if fastest else '个人最速单圈：未知',
        '-'*64,'圈速表','-'*64]
    header += ['\t'.join(row) for row in rows]
    header += ['-'*64,'比赛日志','-'*64]+[f"[{e['time']}] {e['text']}" for e in value['events']]
    (folder/'race_log.txt').write_text('\n'.join(header)+'\n',encoding='utf-8')
    return folder


def render(folder,model,executable):
    folder=Path(folder);exe=Path(executable).resolve();inputs=write_inputs(folder,model);outputs={}
    pending=[]
    try:
        # Finish both renders before replacing any existing image.
        sources=[('laps.xlsx','圈速单.png')] if adapt(model)['laps'] else []
        for source,name in [*sources,('race_log.txt','比赛日志.png')]:
            target=folder/(name+'.'+str(threading.get_ident())+'.pending');pending.append((target,folder/name))
            result=run([str(exe),str(inputs/source),str(target),'--light'],exe.parent)
            signature=b''
            if target.is_file():
                with target.open('rb') as stream:signature=stream.read(8)
            if result or signature!=b'\x89PNG\r\n\x1a\n':
                raise RuntimeError('RaceCom 图像生成失败（退出码 '+str(result)+'）；请检查生成器及其 Source 文件夹')
        for target,destination in pending:
            target.replace(destination);outputs[destination.name]=destination
        return outputs
    finally:
        for target,_ in pending:target.unlink(missing_ok=True)
