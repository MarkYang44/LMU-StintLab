"""High-resolution, paginated lap-sheet and race-log images."""
from race_model import describe,elapsed,lap_status,lap_time
from windows_png import Canvas

WIDTH=1800
ROWS_PER_PAGE=36
BG='#0b1320';CARD='#142235';MUTED='#9ab0ca';GREEN='#34e59a';RED='#ff6577';BLUE='#66baff';AMBER='#efc379'


def header(c,model,title,page,total):
    m=model['session'];c.clear(BG);c.fill(55,52,8,63,GREEN)
    c.text(title,83,43,1200,85,56,bold=True)
    c.text('LMU STINTRIX',1390,55,345,48,26,MUTED,align=2)
    c.text(f"{model['session_type']}  ·  {m.get('track','未知赛道')}",58,139,1660,64,35,bold=True)
    c.text(f"{m.get('driver','未知车手')}  /  {m.get('vehicle','未知车辆')}",58,204,1680,43,27)
    c.text(str(m.get('started_utc','时间未知'))+'  ·  '+('官方圈号' if model['lap_number_source']=='official' else '遥测圈号'),58,251,1590,38,23,MUTED)
    c.text(f'{page} / {total}',1590,251,143,38,23,MUTED,align=2)


def footer(c,y,model):
    c.fill(60,y-13,1680,1,'#26364b')
    c.text(model['note'],60,y,1680,42,22,MUTED)
    c.text('所有记录保存在本机 · PNG 仅为摘要，原始 CSV 与完整事件 JSON / TXT 均保留',60,y+43,1680,36,21,MUTED)


def sheet(c,model,rows,page,total):
    header(c,model,'圈速单  /  LAP SHEET',page,total)
    best=model['fastest'];stats=[('有效最快圈',lap_time(best['time']) if best else '未知'),
        *[(f'SECTOR {i+1}',f'{v:.3f} s' if v else '未知') for i,v in enumerate(model['sector_bests'])]]
    for i,(name,value) in enumerate(stats):
        x=60+i*425;c.fill(x,315,405,125,CARD);c.text(name,x+20,330,365,38,23,MUTED)
        c.text(value,x+20,373,365,53,35,GREEN if i==0 else BLUE,bold=True)
    positions=[60,185,410,640,860,1080,1300];widths=[110,210,210,200,200,200,440]
    labels=['LAP','TIME','Δ 最快圈','S1','S2','S3','状态']
    c.fill(60,476,1680,58,'#20344c')
    for x,w,label in zip(positions,widths,labels):c.text(label,x+12,485,w-20,41,24,MUTED,bold=True)
    for i,lap in enumerate(rows):
        y=542+i*49;color=GREEN if lap['best'] else RED if lap['valid'] is False else AMBER if lap['partial'] or not lap['complete'] else '#edf3fc'
        c.fill(60,y,1680,48,'#142d2b' if lap['best'] else CARD if i%2==0 else BG)
        values=[str(lap['num']),lap_time(lap['time']),f"{lap['delta']:+.3f}" if lap['delta'] is not None else '—',
            *[f'{lap[key]:.3f}' if lap[key] else '—' for key in ('s1','s2','s3')],lap_status(lap)]
        for column,(x,w,value) in enumerate(zip(positions,widths,values)):
            cc=color
            if 3<=column<=5 and lap[('s1','s2','s3')[column-3]]==model['sector_bests'][column-3] and lap[('s1','s2','s3')[column-3]]:cc=BLUE
            c.text(value,x+12,y+7,w-20,40,24,cc,bold=lap['best'])
    if not rows:c.text('该段记录没有完整圈；原始遥测已保留。',80,565,1620,48,28,MUTED)
    footer(c,542+max(1,len(rows))*49+35,model)


def race_log(c,model,rows,page,total,art):
    header(c,model,'比赛日志  /  RACE LOG',page,total)
    s=model['summary'];known=model['scoring_available']
    c.fill(60,315,1120,237,CARD);c.fill(1200,315,540,237,CARD)
    outcome={1:'FINISHED',2:'DNF',3:'DQ'}.get(s.get('finish_flag'),'记录已结束')
    if model['session'].get('status')=='recovered':outcome='中断记录'
    place=lambda v:'P'+str(v) if v else '未知'
    grid=s.get('grid_place');start=grid or s.get('start_place')
    start_label='发车名次' if grid else '首次观测名次'
    values=[(start_label,place(start)),('最终观测名次',place(s.get('finish_place'))),('完成状态',outcome)]
    for i,(label,value) in enumerate(values):
        x=82+i*360;c.text(label,x,334,338,37,23,MUTED);c.text(value,x,376,338,53,34,bold=True)
    collisions=str(s.get('impact_count',0)) if known else '未知'
    offtrack=str(s.get('offtrack_estimate_count',0)) if known else '未知'
    c.text(f'碰撞事件 {collisions}  ·  出界估算 {offtrack}  ·  圈记录 {len(model["laps"])}',82,466,1070,40,25,MUTED)
    c.text('赛道最快圈 '+lap_time(s.get('session_best_lap'))+'  '+str(s.get('session_best_driver','')),82,511,1070,35,22,BLUE)
    if art:
        try:c.photo(*art,(1216,326,508,209))
        except OSError:c.text('车辆图片无法读取',1230,402,480,45,25,MUTED,align=1)
    else:
        c.text(model['session'].get('vehicle','未知车辆'),1220,382,500,72,27,bold=True,align=1)
        c.text('未配置本机车型图片',1220,470,500,42,22,MUTED,align=1)
    c.text('赛事时间线' if known else '记录时间线 · 旧记录未采集名次 / 碰撞 / 分段',60,580,1680,53,31,bold=True)
    for i,event in enumerate(rows):
        y=645+i*49;c.fill(60,y,1680,48,CARD if i%2==0 else BG)
        name=event['event'];color=RED if name in ('impact','lap_invalidated','penalties') else AMBER if name=='offtrack_estimate' else '#edf3fc'
        c.text(elapsed(event['time']-model['origin']),77,y+7,183,40,24,MUTED)
        c.text(describe(event),270,y+7,1435,40,24,color)
    if not rows:c.text('该记录没有可用的赛事事件。',82,665,1600,48,28,MUTED)
    footer(c,645+max(1,len(rows))*49+35,model)


def pages(model,art=None):
    """Each page owns one small raster; endurance races never create giant PNGs."""
    for title,items,base,renderer in [('圈速单',model['laps'],542,sheet),('比赛日志',model['events'],645,race_log)]:
        total=max(1,(len(items)+ROWS_PER_PAGE-1)//ROWS_PER_PAGE)
        for index in range(total):
            rows=items[index*ROWS_PER_PAGE:(index+1)*ROWS_PER_PAGE]
            name=title+('' if index==0 else f'_{index+1:03}')+'.png'
            with Canvas(WIDTH,base+max(1,len(rows))*49+135) as canvas:
                if renderer is sheet:renderer(canvas,model,rows,index+1,total)
                else:renderer(canvas,model,rows,index+1,total,art)
                yield name,canvas
