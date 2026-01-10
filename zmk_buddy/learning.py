

"""Learning functionality for ZMK Buddy.

Tracks keypress statistics to help users learn touch typing.
A key is considered 'correct' if the user typed it and didn't press backspace
before typing the next key.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zmk_buddy.util import get_settings_dir

logger = logging.getLogger(__name__)

# Minimum accuracy percentage (0-100) required to consider a key "learned"
LEARNED_ACCURACY_THRESHOLD = 90

# Minimum number of key presses required before a key can be considered "learned"
LEARNED_MIN_PRESSES = 100

# Filename for storing key statistics
STATS_FILENAME = "key_stats.json"


@dataclass
class KeyStats:
    """Statistics for a single key."""
    
    correct: int = 0
    incorrect: int = 0
    
    @property
    def total(self) -> int:
        """Total number of presses for this key."""
        return self.correct + self.incorrect
    
    @property
    def accuracy(self) -> float:
        """Accuracy percentage (0-100) for this key."""
        if self.total == 0:
            return 0.0
        return (self.correct / self.total) * 100
    
    def is_learned(self) -> bool:
        """Check if this key is considered 'learned'.
        
        A key is learned if:
        - It has been pressed at least LEARNED_MIN_PRESSES times
        - The accuracy is at least LEARNED_ACCURACY_THRESHOLD percent
        """
        return (
            self.total >= LEARNED_MIN_PRESSES and 
            self.accuracy >= LEARNED_ACCURACY_THRESHOLD
        )
    
    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for JSON serialization."""
        return {"correct": self.correct, "incorrect": self.incorrect}
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyStats":
        """Create from dictionary (JSON deserialization)."""
        return cls(
            correct=data.get("correct", 0),
            incorrect=data.get("incorrect", 0)
        )


class LearningTracker:
    """Tracks keypress statistics for learning touch typing.
    
    Tracks whether each keypress was correct or incorrect.
    A keypress is considered correct if the user doesn't press backspace
    before typing the next key.
    """
    
    def __init__(self, testing_mode: bool = False):
        self._stats: dict[str, KeyStats] = {}
        self._pending_key: str | None = None  # Last key pressed, awaiting validation
        self._stats_file = get_settings_dir() / STATS_FILENAME
        self._testing_mode = testing_mode
        
        if not testing_mode:
            self._load_stats()
        else:
            logger.info("Testing mode enabled: stats will not be saved, all keys start nearly learned")
    
    def _load_stats(self) -> None:
        """Load statistics from JSON file."""
        if not self._stats_file.exists():
            logger.debug(f"No stats file found at {self._stats_file}")
            return
        
        try:
            with open(self._stats_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._stats = {
                key: KeyStats.from_dict(value) 
                for key, value in data.items()
            }
            logger.info(f"Loaded key statistics for {xxlen(self._stats)} keys")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load stats file: {e}")
            self._stats = {}
    
    def save_stats(self) -> None:
        """Save statistics to JSON file."""
        if self._testing_mode:
            logger.info("Testing mode: skipping save of key statistics")
            return
        
        try:
            data = {key: stats.to_dict() for key, stats in self._stats.items()}
            with open(self._stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved key statistics to {self._stats_file}")
        except OSError as e:
            logger.warning(f"Failed to save stats file: {e}")
    
    def _get_stats(self, key: str) -> KeyStats:
        """Get or create statistics for a key."""
        if key not in self._stats:
            if self._testing_mode:
                # In testing mode, initialize keys with 100 correct, 0 incorrect
                # This makes them immediately "learned" (meets the 100 press threshold)
                self._stats[key] = KeyStats(correct=100, incorrect=0)
            else:
                self._stats[key] = KeyStats()
        return self._stats[key]
    
    def on_key_press(self, key: str) -> None:
        """Handle a key press event.
        
        If there was a pending key (previous keypress), mark it as correct
        since the user didn't press backspace before this key.
        
        Args:
            key: The key that was pressed (normalized label)
        """
        # Normalize key to lowercase for consistent tracking
        key_lower = key.lower()
        
        # Handle backspace specially - it invalidates the previous key
        if key_lower in ('backspace', 'bckspc', 'delete'):
            if self._pending_key is not None:
                # Previous key was incorrect (user pressed backspace to correct it)
                stats = self._get_stats(self._pending_key)
                stats.incorrect += 1
                logger.debug(f"Key '{self._pending_key}' marked incorrect (accuracy: {stats.accuracy:.1f}%)")
                self._pending_key = None
            # Don't track backspace itself as a learning key
            return
        
        # Check if previous key should be marked as correct
        if self._pending_key is not None:
            # Previous key was correct (no backspace before this key)
            stats = self._get_stats(self._pending_key)
            stats.correct += 1
            logger.debug(f"Key '{self._pending_key}' marked correct (accuracy: {stats.accuracy:.1f}%)")
        
        # Set this key as pending (will be validated on next keypress)
        self._pending_key = key_lower
    
    def on_key_release(self, key: str) -> None:
        """Handle a key release event.
        
        Currently not used for learning tracking, but available for future use.
        """
        pass
    
    def is_key_learned(self, key: str) -> bool:
        """Check if a key is considered 'learned'.
        
        Args:
            key: The key label to check
            
        Returns:
            True if the key meets the learning thresholds
        """
        key_lower = key.lower()
        if key_lower not in self._stats:
            return False
        return self._stats[key_lower].is_learned()
    
    def get_learned_keys(self) -> set[str]:
        """Get the set of all learned keys.
        
        Returns:
            Set of key labels that are considered learned
        """
        return {key for key, stats in self._stats.items() if stats.is_learned()}
    
    def get_key_accuracy(self, key: str) -> float | None:
        """Get the accuracy for a specific key.
        
        Args:
            key: The key label to check
            
        Returns:
            Accuracy percentage (0-100) or None if no data
        """
        key_lower = key.lower()
        if key_lower not in self._stats:
            return None
        return self._stats[key_lower].accuracy
    
    def get_summary(self) -> str:
        """Get a human-readable summary of learning progress.
        
        Returns:
            Summary string with statistics
        """
        if not self._stats:
            return "No typing statistics recorded yet."
        
        total_keys = len(self._stats)
        learned_keys = len(self.get_learned_keys())
        
        # Calculate overall accuracy
        total_correct = sum(s.correct for s in self._stats.values())
        total_incorrect = sum(s.incorrect for s in self._stats.values())
        total_presses = total_correct + total_incorrect
        
        if total_presses > 0:
            overall_accuracy = (total_correct / total_presses) * 100
        else:
            overall_accuracy = 0.0
        
        return (
            f"Learned {learned_keys}/{total_keys} keys | "
            f"Overall accuracy: {overall_accuracy:.1f}% | "
            f"Total keypresses: {total_presses}"
        )