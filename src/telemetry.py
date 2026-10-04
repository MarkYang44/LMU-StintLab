"""Read-only LMU shared memory and validated telemetry snapshots."""
import ctypes
import math
import time
from itertools import islice
import vehiclelab


def decode(value):
    return bytes(value).split(b'\0', 1)[0].decode('utf-8', 'replace')


def extract(data):
    info = data.scoring.scoringInfo
    telemetry = data.telemetry
    if not info.mInRealtime or not telemetry.playerHasVehicle:
        return None
    count = min(104, max(0, int(info.mNumVehicles)))
    player = next((v for v in islice(data.scoring.vehScoringInfo,count) if v.mIsPlayer), None)
    if player is None:
        return None
    car = next((v for v in islice(telemetry.telemInfo,min(104,max(0,int(telemetry.activeVehicles))))
                if v.mID == player.mID), None)
    if car is None or not math.isfinite(car.mElapsedTime):
        return None
    values = [float(getattr(car, 'm' + prefix + name))
              for prefix in ('Unfiltered', 'Filtered') for name in ('Throttle', 'Brake', 'Steering')]
    if not all(math.isfinite(v) for v in values):
        return None
    if any(abs(v) > 1.01 for v in values) or any(values[i] < -0.01 for i in (0, 1, 3, 4)):
        return None
    position = [float(getattr(car.mPos, axis)) for axis in ('x','y','z')]
    return {'track': decode(info.mTrackName), 'driver': decode(player.mDriverName),
            'vehicle': decode(car.mVehicleModel) or decode(car.mVehicleName), 'session': int(info.mSession),
            'player_id': int(player.mID), 'et': float(car.mElapsedTime),
            'lap': int(car.mLapNumber), 'distance': float(player.mLapDist),
            'controls': values, 'position':position if all(math.isfinite(v) for v in position) else None,
            'speed': math.sqrt(sum(float(getattr(car.mLocalVel, a)) ** 2
                                                      for a in ('x', 'y', 'z'))) * 3.6,
            'finish': int(player.mFinishStatus),
            'lap_start':float(car.mLapStartET),'lap_invalidated':bool(car.mLapInvalidated),
            'in_pits':bool(player.mInPits),'track_length':float(info.mLapDist),
            'conditions':{'fuel_l':float(car.mFuel) if math.isfinite(car.mFuel) and car.mFuel>=0 else '',
                'tyre_compound':int(car.mFrontTireCompoundIndex),
                'track_temp_c':float(info.mTrackTemp) if math.isfinite(info.mTrackTemp) else '',
                'wetness':float(info.mAvgPathWetness) if math.isfinite(info.mAvgPathWetness) and 0<=info.mAvgPathWetness<=1 else '',
                'tc_level':int(car.mTC),'abs_level':int(car.mABS),'tc_active':int(car.mTCActive),
                'abs_active':int(car.mABSActive),'gear':int(car.mGear)},
            'vehicle_data':vehiclelab.extract_vehicle(car,info,player)}


class SharedReader:
    """Open an EXISTING map with FILE_MAP_READ; never create or alter it."""
    def __init__(self, map_name='LMU_Data'):
        from pyLMUSharedMemory.lmu_data import LMUObjectOut
        self.structure = LMUObjectOut
        self.size = ctypes.sizeof(LMUObjectOut)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.OpenFileMappingW.restype = ctypes.c_void_p
        self.kernel.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                            ctypes.c_uint32, ctypes.c_size_t]
        self.kernel.MapViewOfFile.restype = ctypes.c_void_p
        self.kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.OpenFileMappingW(4, False, map_name)
        if not self.handle:
            raise OSError('Waiting for LMU shared memory')
        self.pointer = self.kernel.MapViewOfFile(self.handle, 4, 0, 0, self.size)
        if not self.pointer:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise OSError('Cannot read LMU shared memory')
        self.cached_sample = None
        self.cached_at = 0

    def read(self):
        if (self.cached_sample is not None and time.monotonic()-self.cached_at < 0.25
                and self.cached_id.value == self.cached_sample['player_id']
                and self.cached_et.value == self.cached_sample['et'] and self.cached_realtime.value):
            return self.cached_sample
        # Discard a snapshot if the producer changed it while it was copied.
        for _ in range(3):
            a = ctypes.string_at(self.pointer, self.size)
            b = ctypes.string_at(self.pointer, self.size)
            if a == b:
                data = self.structure.from_buffer_copy(a)
                sample = extract(data)
                self.cached_sample = sample
                self.cached_at = time.monotonic()
                if sample is not None:
                    index = next(i for i in range(min(104,int(data.telemetry.activeVehicles)))
                                 if data.telemetry.telemInfo[i].mID == sample['player_id'])
                    telem_type, car_type = type(data.telemetry), type(data.telemetry.telemInfo[0])
                    address = (self.pointer+self.structure.telemetry.offset+telem_type.telemInfo.offset
                               +index*ctypes.sizeof(car_type))
                    fields = {entry[0]:entry[1] for entry in car_type._fields_}
                    self.cached_id = fields['mID'].from_address(address+car_type.mID.offset)
                    self.cached_et = fields['mElapsedTime'].from_address(address+car_type.mElapsedTime.offset)
                    score_type, info_type = type(data.scoring), type(data.scoring.scoringInfo)
                    address = self.pointer+self.structure.scoring.offset+score_type.scoringInfo.offset
                    field = next(entry[1] for entry in info_type._fields_ if entry[0]=='mInRealtime')
                    self.cached_realtime = field.from_address(address+info_type.mInRealtime.offset)
                return sample
        return None

    def close(self):
        if getattr(self, 'pointer', None):
            self.kernel.UnmapViewOfFile(self.pointer)
            self.pointer = None
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
