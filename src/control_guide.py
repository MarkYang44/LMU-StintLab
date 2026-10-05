"""Native guide browser and preview; rich detail opens the bundled offline page."""
import tkinter as tk
from control_theme import T
from control_list import SessionList
from guidebook import catalog,prepare,page_url
from paths import ASSETS
import webbrowser


def show(center,view):
    data=catalog();state=center.guide_state.setdefault(view,dict(query='',group='',selected=''))
    body=center.card('赛道资料库' if view=='tracks' else '车型资料库',
        f"GTD · {data['content_version']} · 更新 {data['updated']} · {len(data[view])} 条资料 / 离线可用")
    row=center.row(body);query=tk.StringVar(center.root,value=state['query']);group=tk.StringVar(center.root,value=state['group'] or '全部组别')
    entry=tk.Entry(row,textvariable=query,bg=T.FIELD,fg=T.FG,insertbackground=T.ACCENT,relief='flat',font=(T.FONT,10))
    entry.pack(side='left',fill='x',expand=True,ipady=8)
    center.choice(body,'组别',group,['全部组别','LMGT3','Hypercar']) if view=='cars' else None
    tree=SessionList(body,('name','kind','summary'),height=7)
    for key,title,width in [('name','名称',240),('kind','组别' if view=='cars' else '长度 / 地点',145),('summary','优点' if view=='cars' else '赛道特性',390)]:
        tree.heading(key,text=title)
        tree.column(key,width=width*tree.s,minwidth=60*tree.s,stretch=key=='summary')
    tree.pack(fill='x',pady=10)
    preview=center.card('资料预览','选择条目查看摘要；完整图片、收藏与 2–3 项并排对比在离线指南中打开')
    title=center.label(preview,'',14,T.ACCENT,True);title.pack(anchor='w')
    description=center.label(preview,'',10,T.FG);description.pack(fill='x',pady=8)
    description.bind('<Configure>',lambda event:description.configure(wraplength=max(100,event.width)))
    def selection(_=None):
        selected=tree.selection();state['selected']=selected[0] if selected else ''
        item=data[view].get(state['selected'])
        if not item:title.configure(text='请选择一条资料');description.configure(text='');return
        title.configure(text=item['name'])
        text=(item['strength_zh']+'\n注意事项：'+item['caution_zh']) if view=='cars' else item['character_zh']+'\n'+item['challenge_zh']+'\n'+item['advice_zh']
        description.configure(text=text+'\n练习建议：'+item['note']['exercise_zh'])
    def populate(*_):
        state['query']=query.get();state['group']='' if group.get()=='全部组别' else group.get();rows=[];search=state['query'].casefold()
        for slug,item in data[view].items():
            if view=='cars' and state['group'] and item['car_class']!=state['group']:continue
            searchable=' '.join(str(v) for k,v in item.items() if isinstance(v,str)).casefold()
            if search and search not in searchable:continue
            rows.append((slug,(item['name'],item['car_class'] if view=='cars' else item['length_km']+' km / '+item['location_zh'],item['strength_zh'] if view=='cars' else item['character_zh'])))
        tree.replace(rows,[state['selected']]);selection()
    def open_page(all_items=False):
        selected='' if all_items else state['selected']
        center.work(lambda:prepare(),lambda path:webbrowser.open(page_url(path,view,selected)))
    tree.bind('<<TreeviewSelect>>',selection);tree.bind('<Double-1>',lambda _:open_page());tree.bind('<Return>',lambda _:open_page())
    query.trace_add('write',populate);group.trace_add('write',populate)
    row=center.row(preview);center.button(row,'查看选中资料',open_page,True,150);center.button(row,'打开完整离线指南',lambda:open_page(True),False,185)
    center.label(preview,f"资料参考 {data['game_reference']} · 推荐实测验证 {data['validated_recommendations']}/{data['total_recommendations']} · 保留原资料日期与来源",9,T.MUTED).pack(anchor='w',pady=8)
    populate();center.status.set('离线资料 · 收藏保存在浏览器本地 · 不读取个人赛事')
