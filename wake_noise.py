"""Track ambient microphone level without relying on hardware speech flags."""

from collections import deque
import math


class WakeNoiseFloor:
    def __init__(self, minimum_rms, ratio=1.5, window_seconds=5.0):
        self.minimum_rms = minimum_rms
        self.ratio = ratio
        self.window_seconds = window_seconds
        self.samples = deque()

    def observe(self, now, rms):
        if not math.isfinite(rms) or rms < 0:
            return
        self.samples.append((now, rms))
        while self.samples and self.samples[0][0] < now - self.window_seconds:
            self.samples.popleft()

    def required_rms(self):
        # Allow immediate wake-up before enough ambient audio is available.
        if len(self.samples) < 2 or self.samples[-1][0] - self.samples[0][0] < 1.0:
            return self.minimum_rms
        # The lower fifth tolerates brief speech and mechanical peaks without
        # treating them as the sustained background level.
        levels = sorted(level for _, level in self.samples)
        floor = levels[int((len(levels) - 1) * 0.2)]
        return max(self.minimum_rms, floor * self.ratio)
