"""Shared application paths, CSV schema and presentation constants."""
from paths import ASSETS, data_directory

ROOT = data_directory()
ROOT.mkdir(parents=True,exist_ok=True)
COLORS = ('#34e59a', '#ff596b', '#52b5ff')
INPUT_CHANNELS = {'raw': (1, '原始'), 'filtered': (10, '游戏过滤后')}
POLL_HZ = DRAW_HZ = 120
COLUMNS = ('time_s', 'utc', 'session_time_s', 'lap', 'lap_distance_m', 'throttle', 'brake',
           'steering', 'filtered_throttle', 'filtered_brake', 'filtered_steering', 'speed_kmh',
           'lap_start_s','lap_invalidated','in_pits','track_length_m',
           'world_x_m','world_y_m','world_z_m')
EXTRA_COLUMNS=('fuel_l','tyre_compound','track_temp_c','wetness','tc_level','abs_level','tc_active','abs_active','gear')
COLUMNS=(*COLUMNS,*EXTRA_COLUMNS)
