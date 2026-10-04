"""Sampling policy, validated local preferences, and interruptible Windows timing."""
import ctypes
import json
import math
import time

DEFAULTS = dict(mode='fixed', fixed_hz=120, min_hz=30, max_hz=240,
                change_pct_s=12.0, hold_s=1.5, brake_pct=5.0, draw_mode='sync', draw_hz=120,
                input_channel='raw')
PRESETS = {
    '节能': dict(mode='dynamic', min_hz=20, max_hz=120, change_pct_s=20, hold_s=0.75, brake_pct=10),
    '均衡': dict(mode='dynamic', min_hz=60, max_hz=240, change_pct_s=12, hold_s=1.5, brake_pct=5),
    '高细节': dict(mode='dynamic', min_hz=120, max_hz=1000, change_pct_s=4, hold_s=2, brake_pct=2),
}


def validate_settings(value):
    result = dict(DEFAULTS, **{k: v for k, v in value.items() if k in DEFAULTS})
    if result['mode'] not in ('fixed', 'dynamic'):
        raise ValueError('请选择固定或动态采样模式。')
    if result['draw_mode'] not in ('sync', 'manual'):
        raise ValueError('请选择同步或手动 HUD 绘制模式。')
    if result['input_channel'] not in ('raw', 'filtered'):
        raise ValueError('请选择原始或游戏过滤后的输入通道。')
    labels = {'fixed_hz': '固定采样率', 'min_hz': '最低采样率', 'max_hz': '最高采样率', 'draw_hz': '绘制刷新率'}
    for key, label in labels.items():
        try:
            number = float(result[key])
        except (ValueError, TypeError):
            raise ValueError(label + '必须是整数。') from None
        maximum = 4000
        if not math.isfinite(number) or not number.is_integer() or not 1 <= number <= maximum:
            raise ValueError(f'{label}须为 1–{maximum} Hz 的整数。')
        result[key] = int(number)
    if result['min_hz'] > result['max_hz']:
        raise ValueError('动态最低采样率不能大于最高采样率。')
    for key, label, low, high in (('change_pct_s','输入变化阈值',0.1,10000),
                                  ('hold_s','降频延迟',0.05,30), ('brake_pct','刹车升频阈值',0,100)):
        try:
            number = float(result[key])
        except (ValueError, TypeError):
            raise ValueError(label + '必须是数值。') from None
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{label}须在 {low}–{high} 之间。')
        result[key] = number
    return result


def drawing_rate(settings, sampling_hz):
    """Both fixed and dynamic drawing follow the current sampling target by default."""
    return sampling_hz if settings['draw_mode'] == 'sync' else settings['draw_hz']


def load_settings(path):
    try:
        return validate_settings(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError, AttributeError):
        return dict(DEFAULTS)


def save_settings(path, settings):
    checked = validate_settings(settings)
    temporary = path.with_suffix('.json.pending')
    temporary.write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class AdaptiveSampler:
    def __init__(self, settings, now=0):
        self.configure(settings, now)

    def configure(self, settings, now):
        self.settings = settings
        self.active_until = now + settings['hold_s']
        self.previous = None
        self.reason = '固定' if settings['mode'] == 'fixed' else '启动探测'

    def observe(self, sample, now):
        if sample is None:
            self.reason = '无遥测'
            return
        current = (sample['et'], tuple(sample['controls'][:3]))
        changed = False
        if self.previous is not None:
            dt = current[0] - self.previous[0]
            if dt > 0:
                change = max(abs(a-b) for a,b in zip(current[1], self.previous[1])) * 100 / dt
                changed = change >= self.settings['change_pct_s']
            elif dt < 0:
                self.active_until = now + self.settings['hold_s']
        # Repeated telemetry never renews the activity hold based on a stale brake value.
        if self.previous is None or current[0] != self.previous[0]:
            braking = self.settings['brake_pct'] > 0 and current[1][1]*100 >= self.settings['brake_pct']
            if changed or braking:
                self.active_until = now + self.settings['hold_s']
                self.reason = '输入变化' if changed else '持续刹车'
            self.previous = current

    def rate(self, now, fresh=True):
        if self.settings['mode'] == 'fixed':
            self.reason = '固定'
            return self.settings['fixed_hz']
        if not fresh:
            self.reason = '无新遥测'
            return self.settings['min_hz']
        if now <= self.active_until:
            return self.settings['max_hz']
        self.reason = '输入平稳'
        return self.settings['min_hz']


class PreciseWait:
    """Use a high-resolution waitable timer for submillisecond targets, without spinning."""
    def __init__(self, stop, wake):
        self.stop, self.wake = stop, wake
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateWaitableTimerExW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        self.kernel.CreateWaitableTimerExW.restype = ctypes.c_void_p
        self.kernel.SetWaitableTimer.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong), ctypes.c_long,
                                                 ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.CreateWaitableTimerExW(None, None, 2, 0x1F0003)
        self.due = ctypes.c_longlong()

    def until(self, deadline):
        while not self.stop.is_set():
            if self.wake.is_set():
                self.wake.clear()
                return True
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            if self.handle and remaining < 0.003:
                self.due.value = -max(1, round(remaining*10_000_000))
                if self.kernel.SetWaitableTimer(self.handle, ctypes.byref(self.due), 0, None, None, False):
                    self.kernel.WaitForSingleObject(self.handle, 50)
                else:
                    self.wake.wait(remaining)
            else:
                self.wake.wait(min(remaining, 0.05))
        return False

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class FrameDeadline:
    """GUI deadlines with rate changes and skipped overdue frames, never a backlog."""
    def __init__(self, now):
        self.deadline = now
        self.hz = None
        self.missed_cycles = 0

    def set_rate(self, hz, now):
        if hz != self.hz:
            self.hz = hz
            self.deadline = now
            return True
        return False

    def complete(self, now):
        period = 1/self.hz
        self.deadline += period
        late = now-self.deadline
        if late >= 0:
            skipped = int(late/period)+1
            self.missed_cycles += skipped
            self.deadline += skipped*period
            if self.deadline <= now:
                self.deadline = now+period
        return self.deadline
