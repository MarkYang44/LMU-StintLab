"""A single explicit confirmation for permanent Session Review deletion."""
from tkinter import messagebox
from i18n import tr
import session_delete

def busy(center):
    reports=getattr(getattr(getattr(center.hud,'engine',None),'recorder',None),'pending_reports',[])
    if center.tasks.busy or any(thread.is_alive() for thread in reports):
        center.status.set(tr('请等待当前记录任务完成'));return True
    return False

def remove(center):
    if busy(center):return
    def chosen(items):
        item=items[0]
        detail=' · '.join((item['date'][:19],item['session_type'],item['track'],item['vehicle']))
        prompt=tr('永久删除这场赛事记录？')+'\n\n'+detail+'\n\n'+tr('将从本机删除该场全部记录、圈文件与报告，无法恢复。')
        if not messagebox.askyesno(tr('删除赛事记录'),prompt,parent=center.root,default='no'):return
        if busy(center):return
        data=center.data_path;key=item['key']
        def done(result):
            if center.tree:center.refresh()
            center.status.set(tr('记录已永久删除')+(tr('；备注清理失败：')+result['notes_warning'] if result['notes_warning'] else ''))
        center.work(lambda:session_delete.remove(data,key),done)
    center.with_selection(chosen)
