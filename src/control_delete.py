"""One explicit confirmation for a frozen batch of permanent local deletions."""
import tkinter as tk
from tkinter import messagebox
from control_theme import T
from i18n import tr
import session_delete

def busy(center):
    reports=getattr(getattr(getattr(center.hud,'engine',None),'recorder',None),'pending_reports',[])
    if center.tasks.busy or any(thread.is_alive() for thread in reports):
        center.status.set(tr('请等待当前记录任务完成'));return True
    return False

def confirm(center,items):
    details=[' · '.join((item['date'][:19],item['session_type'],item['track'],item['vehicle'])) for item in items]
    prompt=tr('永久删除选中的赛事记录？')+f' ({len(items)})'
    warning=tr('将从本机删除所选赛事的全部记录、圈文件与报告，无法恢复。')
    if len(items)<=8:
        return messagebox.askyesno(tr('删除赛事记录'),prompt+'\n\n'+'\n'.join(details)+'\n\n'+warning,parent=center.root,default='no')
    dialog=tk.Toplevel(center.root);dialog.title(tr('删除赛事记录'));dialog.configure(bg=T.BG)
    dialog.transient(center.root);dialog.geometry('880x480');dialog.minsize(620,360)
    body=tk.Frame(dialog,bg=T.BG);body.pack(fill='both',expand=True,padx=24,pady=24)
    center.label(body,prompt,14,T.FG,True).pack(anchor='w',pady=(0,12))
    holder=tk.Frame(body,bg=T.FIELD);holder.pack(fill='both',expand=True)
    listing=tk.Text(holder,bg=T.FIELD,fg=T.FG,font=(T.FONT,10),wrap='word',relief='flat',padx=12,pady=12)
    scrollbar=tk.Scrollbar(holder,command=listing.yview);listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right',fill='y');listing.pack(fill='both',expand=True)
    listing.insert('1.0','\n\n'.join(details));listing.configure(state='disabled')
    label=center.label(body,warning,10,T.MUTED);label.pack(fill='x',pady=12)
    label.bind('<Configure>',lambda event:label.configure(wraplength=event.width))
    answer=[False]
    def accept():answer[0]=True;dialog.destroy()
    row=center.row(body)
    cancel=center.button(row,tr('取消'),dialog.destroy,width=120)
    center.button(row,tr('永久删除'),accept,True,width=160)
    dialog.protocol('WM_DELETE_WINDOW',dialog.destroy);dialog.bind('<Escape>',lambda _:dialog.destroy())
    dialog.update_idletasks();dialog.grab_set();cancel.focus_set();center.root.wait_window(dialog)
    return answer[0]

def remove(center):
    if busy(center):return
    def chosen(items):
        if not confirm(center,items):return
        if busy(center):return
        data=center.data_path;keys=tuple(item['key'] for item in items)
        def done(result):
            if center.tree:center.refresh()
            center.status.set(tr('记录已永久删除')+f": {len(result['deleted'])} / {len(keys)}")
            errors=result['failed']+result['warnings']
            if errors:
                messagebox.showwarning(tr('部分赛事未能删除'), '\n'.join(key+' · '+tr(error) for key,error in errors),parent=center.root)
        center.work(lambda:session_delete.remove_many(data,keys),done)
    center.with_selection(chosen,count=None)
