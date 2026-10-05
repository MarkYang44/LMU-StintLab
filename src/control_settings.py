"""Module-specific preference edits, shared by the control center and live HUD."""
from app_config import ROOT
from storage import atomic_json
import sampling
import endurance
import vehiclelab


def apply(module,updates,hud=None):
    path=ROOT/({'sampling':'settings.json','vehicle':'vehicle_settings.json','endurance':'endurance_settings.json'}[module])
    owner={'sampling':sampling,'vehicle':vehiclelab,'endurance':endurance}[module]
    current=owner.load_settings(path)
    value={**current,**updates}
    checked=sampling.validate_settings(value) if module=='sampling' else owner.settings(value)
    if module=='sampling':sampling.save_settings(path,checked)
    else:atomic_json(path,checked)
    if hud is None or hud.closing:return checked
    if module=='sampling':
        hud.settings=checked;hud.input_channel.set(checked['input_channel'])
        if set(updates)=={'input_channel'}:hud.apply_input_channel()
        else:hud.engine.update_settings(checked);hud.trace_key=None;hud.render_wake.set()
    elif module=='vehicle':
        hud.vehicle_settings=checked
        with hud.engine.lock:
            hud.engine.fuel_planner.configure(checked);hud.engine.recorder.vehicle_settings=checked
            if hud.engine.latest:hud.engine.fuel_planner.baseline_et=hud.engine.latest['et']
        for k in ('tyres','strategy'):getattr(hud,k+'_on').set(checked[k+'_enabled'])
        hud.vehicle_panels.refresh_visibility()
    else:
        hud.endurance_settings=checked
        with hud.engine.lock:hud.engine.endurance_monitor.configure(checked);hud.engine.recorder.endurance_settings=checked
        for k in ('pit','stint','weather'):getattr(hud,k+'_on').set(checked[k+'_enabled'])
        hud.endurance_panels.refresh_visibility()
    # Preserve the same recorded settings history as the dedicated HUD dialogs.
    rec=hud.engine.recorder
    if rec.file and module!='sampling':
        with rec.meta_lock:
            elapsed=hud.engine.latest['et']-rec.origin if hud.engine.latest else 0
            if module=='endurance':rec.meta.setdefault('endurance_settings_history',[]).append(dict(time_s=elapsed,settings=checked))
            else:
                keys=('history_laps','rate_mode','target_mode','target_value','reserve_l','extra_finish_laps')
                prior=dict(rec.meta.get('vehicle_strategy',{}))
                if not rec.meta.get('vehicle_settings_history'):rec.meta['vehicle_settings_history']=[dict(time_s=0,strategy=prior)]
                strategy={k:checked[k] for k in keys};strategy['started_at_s']=elapsed
                rec.meta['vehicle_strategy']=strategy;rec.meta['vehicle_settings_history'].append(dict(time_s=elapsed,strategy=strategy))
                rec.meta['vehicle_telemetry']['target_hz']=checked['record_hz']
                car=hud.engine.latest['vehicle'] if hud.engine.latest else '*'
                rec.meta['vehicle_profile']=checked['profiles'].get(car,checked['profiles'].get('*',vehiclelab.DEFAULT_PROFILE))
    return checked
