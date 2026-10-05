"""Local desktop translations. Stored values, filenames and telemetry stay intact."""
import json
from functools import lru_cache
from pathlib import Path
from paths import ASSETS

language='zh'

@lru_cache(maxsize=1)
def catalog():
    return json.loads((ASSETS/'locales/en.json').read_text(encoding='utf-8'))

def tr(value):
    if not isinstance(value,str) or language=='zh':return value
    return catalog().get(value,value)

def set_language(value):
    global language
    language=value if value in ('zh','en') else 'zh'

def load(path):
    from race_model import read_json
    previous=read_json(Path(path).parent/'guide_settings.json',{})
    if not isinstance(previous,dict):previous={}
    value=read_json(path,{})
    set_language(value.get('language',previous.get('language','zh')) if isinstance(value,dict) else 'zh')

def save(path,value):
    if value not in ('zh','en'):raise ValueError('Unknown interface language')
    from race_model import read_json
    from storage import atomic_json
    settings=read_json(path,{})
    if not isinstance(settings,dict):settings={}
    settings.update(version=2,language=value)
    atomic_json(path,settings)
    set_language(value)

def refresh(root):
    """Retint language-aware controls in open auxiliary windows, without resets."""
    def visit(widget):
        if hasattr(widget,'retranslate'):widget.retranslate()
        elif hasattr(widget,'paint') and widget.__class__.__module__ in ('control_fields','control_widgets','control_list','control_shell'):widget.paint()
        for child in widget.winfo_children():visit(child)
    visit(root)

def label_class():
    import tkinter as tk
    class Label(tk.Label):
        def __init__(self,parent=None,**options):
            self.source_text=options.get('text','')
            if 'text' in options:options['text']=tr(options['text'])
            super().__init__(parent,**options)
        def configure(self,cnf=None,**options):
            if isinstance(cnf,dict):options={**cnf,**options};cnf=None
            if 'text' in options:self.source_text=options['text'];options['text']=tr(options['text'])
            return super().configure(cnf,**options)
        config=configure
        def retranslate(self):super().configure(text=tr(self.source_text))
    return Label

Label=label_class()
