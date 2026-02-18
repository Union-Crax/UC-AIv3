import random
import time
import math
import logging

logger = logging.getLogger(__name__)

class Humanizer:
    def __init__(self, wpm_min=60, wpm_max=90, reading_wpm=200):
        self.wpm_min = wpm_min
        self.wpm_max = wpm_max
        self.reading_wpm = reading_wpm

    def calculate_reading_delay(self, text: str) -> float:
        """
        Calculates how long it takes to read a message.
        """
        if not text:
            return 0.0
        words = len(text.split())
        # Add some base reaction time
        base_delay = random.uniform(0.5, 1.5)
        reading_time = (words / self.reading_wpm) * 60
        total_delay = base_delay + reading_time
        return min(total_delay, 5.0) # Cap reading delay to 5 seconds to avoid awkward pauses

    def calculate_typing_delay(self, text: str) -> float:
        """
        Calculates how long it takes to type a message.
        """
        if not text:
            return 0.0
        words = len(text.split())
        wpm = random.uniform(self.wpm_min, self.wpm_max)
        typing_time = (words / wpm) * 60
        # Add slight variance
        typing_time *= random.uniform(0.9, 1.1)
        return min(typing_time, 15.0) # Cap typing delay to 15 seconds

    def calculate_thinking_delay(self) -> float:
        """
        Calculates a randomized thinking pause before typing starts.
        """
        return random.uniform(1.0, 3.0)

humanizer = Humanizer()
