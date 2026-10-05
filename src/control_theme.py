"""Two industrial palettes; telemetry colours are independent of the theme."""
from types import SimpleNamespace

PALETTES={
    'dark':dict(BG='#1a1a1c',RAIL='#171719',CARD='#262628',FIELD='#303032',EDGE='#414143',
        FG='#eeede8',MUTED='#a4a49e',ACCENT='#c6ca4c',HOVER='#38383a',SELECT='#37392a',
        STRIPE='#29292b',BUTTON='#c6ca4c',INK='#1a1a1c',BUTTON_HOVER='#e1e574',MARK='#55583a'),
    'light':dict(BG='#e9e7e4',RAIL='#ddded6',CARD='#f6f5ef',FIELD='#e1e1d8',EDGE='#c1c2b4',
        FG='#262425',MUTED='#66675e',ACCENT='#62670e',HOVER='#e7e8da',SELECT='#e4e7ba',
        STRIPE='#efefe6',BUTTON='#c6ca4c',INK='#262425',BUTTON_HOVER='#d9de60',MARK='#959952'),
}
PALETTES['dark'].update(GREEN='#34e59a',RED='#ff596b',BLUE='#52b5ff')
PALETTES['light'].update(GREEN='#157b4a',RED='#b92f42',BLUE='#216fa5')
T=SimpleNamespace(**PALETTES['dark'],FONT='Microsoft YaHei UI',mode='dark')


def set_mode(mode):
    if not isinstance(mode,str):mode='dark'
    T.__dict__.update(PALETTES.get(mode,PALETTES['dark']))
    T.mode=mode if mode in PALETTES else 'dark'


def signal_colors(original,clean=False):
    # Keep the pure HUD's bright signals on black, even with a light desktop.
    return original if clean or T.mode=='dark' else (T.GREEN,T.RED,T.BLUE)


def load(path):
    import json
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        mode=value.get('theme','dark') if isinstance(value,dict) else 'dark'
    except (OSError,ValueError):mode='dark'
    set_mode(mode)


def save(path,mode):
    from storage import atomic_json
    if mode not in PALETTES:raise ValueError('Unknown interface theme')
    atomic_json(path,dict(version=1,theme=mode))


def recolor(widget,previous):
    """Retint open auxiliary windows without recreating their controls or state."""
    mapping={color:PALETTES[T.mode][key] for key,color in PALETTES[previous].items()}
    options=widget.configure()
    for key in ('background','foreground','activebackground','activeforeground','selectcolor',
                'insertbackground','disabledbackground','disabledforeground'):
        if key in options:
            current=str(widget.cget(key))
            if current in mapping:widget.configure(**{key:mapping[current]})
    for child in widget.winfo_children():recolor(child,previous)


def web_script(assets):
    """Embed both palettes so exported HTML remains completely standalone."""
    import json
    from paths import data_directory
    mode=T.mode
    try:
        value=json.loads((data_directory()/'interface_settings.json').read_text(encoding='utf-8-sig'))
        candidate=value.get('theme') if isinstance(value,dict) else None
        if isinstance(candidate,str) and candidate in PALETTES:mode=candidate
    except (OSError,ValueError):pass
    return (assets/'interface_theme.js').read_text(encoding='utf-8').replace('/*UI_PALETTES*/null',json.dumps(PALETTES)).replace("/*UI_MODE*/'dark'",json.dumps(mode))
