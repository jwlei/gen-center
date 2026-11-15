"""
GPU and CPU temperatures over time, for Settings' temperature graph: one bucket a minute with each sensor's lowest,
average and highest reading, kept a week in logs/temperatures.jsonl.

The GPU's comes from nvidia-smi (as the heat guard reads it); the CPU's from MSI Afterburner's shared monitoring
memory, which has it only while Afterburner runs with CPU temperature monitoring on.
"""
import json
import os
import struct
import threading
import time

from core.paths import LOGS_DIR

PATH = os.path.join(LOGS_DIR, "temperatures.jsonl")
BUCKET_SECONDS = 60
KEEP_SECONDS = 7 * 24 * 3600
SENSORS = ("gpu", "cpu")
# What a graph is given at most: a longer range merges neighbouring minutes, so a week is still quick to draw.
MOST_POINTS = 360
RANGES_HOURS = (1, 6, 24, 168)

AFTERBURNER_MEMORY = "MAHMSharedMemory"
AFTERBURNER_SIGNATURE = 0x4D41484D  # 'MAHM'
FILE_MAP_READ = 0x0004


def afterburner_readings():
    """{source name: value} from MSI Afterburner's monitoring, or {} when it isn't running or can't be read."""
    if os.name != "nt":
        return {}
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Read-only: Afterburner runs as administrator, and a mapping opened for writing is refused.
    handle = kernel.OpenFileMappingW(FILE_MAP_READ, False, AFTERBURNER_MEMORY)
    if not handle:
        return {}
    view = None
    try:
        view = kernel.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
        if not view:
            return {}
        signature, _, header, count, size = struct.unpack("<IIIII", ctypes.string_at(view, 20))
        if signature != AFTERBURNER_SIGNATURE or not 0 < count < 512 or size < 1304:
            return {}
        readings = {}
        for index in range(count):
            entry = ctypes.string_at(view + header + index * size, 1304)
            name = entry[:260].split(b"\0")[0].decode("latin-1")
            value = struct.unpack_from("<f", entry, 1300)[0]
            if value == value and abs(value) < 1e6:  # Afterburner marks a source it has no value for with FLT_MAX
                readings[name] = value
        return readings
    finally:
        if view:
            kernel.UnmapViewOfFile(view)
        kernel.CloseHandle(handle)


def cpu_temperature():
    value = afterburner_readings().get("CPU temperature")
    return round(value, 1) if value is not None and 0 < value < 150 else None


def _merge(stats, weight_total):
    """One [low, average, high] from several, each average weighted by how many readings it has."""
    lows = [low for low, _, _, _ in stats]
    highs = [high for _, _, high, _ in stats]
    average = sum(avg * count for _, avg, _, count in stats) / weight_total
    return [min(lows), round(average, 1), max(highs)]


class TemperatureLog:
    """Readings added every few seconds; finished minutes appended to PATH, a week kept."""

    def __init__(self, path=PATH, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()
        self.buckets = self._load()
        self.current = None  # {"t": minute start, sensor: [low, sum, high, count]}
        self.latest = {}

    def _load(self):
        cutoff = self.clock() - KEEP_SECONDS
        buckets = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        bucket = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(bucket, dict) and isinstance(bucket.get("t"), (int, float)) and bucket["t"] >= cutoff:
                        buckets.append(bucket)
        except OSError:
            return []
        buckets.sort(key=lambda bucket: bucket["t"])
        self._rewrite(buckets)
        return buckets

    def _rewrite(self, buckets):
        """Only the week kept, so the file doesn't grow for ever."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(bucket, separators=(",", ":")) + "\n" for bucket in buckets)
            os.replace(temporary, self.path)
        except OSError:
            pass

    def add(self, gpu=None, cpu=None):
        now = self.clock()
        minute = int(now // BUCKET_SECONDS * BUCKET_SECONDS)
        with self.lock:
            if self.current and self.current["t"] != minute:
                self._finish()
            if self.current is None:
                self.current = {"t": minute}
            for sensor, value in (("gpu", gpu), ("cpu", cpu)):
                if value is None:
                    continue
                self.latest[sensor] = value
                low, total, high, count = self.current.get(sensor) or [value, 0.0, value, 0]
                self.current[sensor] = [min(low, value), total + value, max(high, value), count + 1]

    def _finish(self):
        bucket = {"t": self.current["t"]}
        for sensor in SENSORS:
            if sensor in self.current:
                low, total, high, count = self.current[sensor]
                bucket[sensor] = [round(low, 1), round(total / count, 1), round(high, 1), count]
        self.current = None
        if len(bucket) == 1:
            return
        self.buckets.append(bucket)
        cutoff = bucket["t"] - KEEP_SECONDS
        while self.buckets and self.buckets[0]["t"] < cutoff:
            self.buckets.pop(0)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(bucket, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _all(self):
        """The finished minutes and the one going, as buckets."""
        buckets = list(self.buckets)
        if self.current:
            going = {"t": self.current["t"]}
            for sensor in SENSORS:
                if sensor in self.current:
                    low, total, high, count = self.current[sensor]
                    going[sensor] = [round(low, 1), round(total / count, 1), round(high, 1), count]
            buckets.append(going)
        return buckets

    def query(self, hours):
        """
        The last `hours`: points ({t, gpu: [low, avg, high], cpu: ...}, at most MOST_POINTS, neighbouring minutes merged)
        and, per sensor, the lowest, average and highest over the range and the latest minute's average.
        """
        now = self.clock()
        start = now - hours * 3600
        with self.lock:
            buckets = [bucket for bucket in self._all() if bucket["t"] >= start - BUCKET_SECONDS]
            latest = dict(self.latest)
        step = max(BUCKET_SECONDS, -(-hours * 3600 // MOST_POINTS // BUCKET_SECONDS) * BUCKET_SECONDS)
        groups = {}
        for bucket in buckets:
            groups.setdefault(int(bucket["t"] // step * step), []).append(bucket)
        points = []
        for t in sorted(groups):
            point = {"t": t}
            for sensor in SENSORS:
                stats = [bucket[sensor] for bucket in groups[t] if sensor in bucket]
                if stats:
                    point[sensor] = _merge(stats, sum(stat[3] for stat in stats))
            points.append(point)
        # A range that doesn't start on a step's edge spans one group more.
        points = points[-MOST_POINTS:]
        summary = {}
        for sensor in SENSORS:
            stats = [bucket[sensor] for bucket in buckets if sensor in bucket]
            if not stats:
                summary[sensor] = None
                continue
            low, average, high = _merge(stats, sum(stat[3] for stat in stats))
            summary[sensor] = {"min": low, "avg": average, "max": high, "now": latest.get(sensor, stats[-1][1])}
        return {"hours": hours, "start": start, "end": now, "step": step, "points": points, "summary": summary}
