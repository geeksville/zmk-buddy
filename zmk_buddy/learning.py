

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

# Score threshold (0-100) above which a key is considered "learned"
LEARNED_SCORE_THRESHOLD = 80

# Score increase for a correct keystroke
CORRECT_SCORE_INCREASE = 1

# Score decrease for an incorrect keystroke
INCORRECT_SCORE_DECREASE = 5

# Maximum score a key can have
MAX_SCORE = 100

# Minimum score a key can have
MIN_SCORE = 0

# Filename for storing key statistics
STATS_FILENAME = "key_stats.json"


@dataclass
class KeyStats:
    """Statistics for a single key using a score-based system.
    
    Score ranges from 0-100:
    - Correct keystroke: +1%
    - Incorrect keystroke: -5%
    - Key is "learned" when score > 80%
    """
    
    score: float = 0.0
    total_presses: int = 0
    
    def record_correct(self) -> None:
        """Record a correct keystroke, increasing score by 1%."""
        self.score = min(MAX_SCORE, self.score + CORRECT_SCORE_INCREASE)
        self.total_presses += 1
    
    def record_incorrect(self) -> None:
        """Record an incorrect keystroke, decreasing score by 5%."""
        self.score = max(MIN_SCORE, self.score - INCORRECT_SCORE_DECREASE)
        self.total_presses += 1
    
    def is_learned(self) -> bool:
        """Check if this key is considered 'learned'.
        
        A key is learned when its score exceeds the threshold (80%).
        """
        return self.score > LEARNED_SCORE_THRESHOLD
    
    def to_dict(self) -> dict[str, float | int]:
        """Convert to dictionary for JSON serialization."""
        return {"score": self.score, "total_presses": self.total_presses}
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyStats":
        """Create from dictionary (JSON deserialization)."""
        return cls(
            score=data.get("score", 0.0),
            total_presses=data.get("total_presses", 0)
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
            logger.info(f"Loaded key statistics for {len(self._stats)} keys")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load stats file: {e}")
            self._stats = {}
    
    def save_stats(self) -> Path | None:
        """Save statistics to JSON file."""
        if self._testing_mode:
            logger.info("Testing mode: skipping save of key statistics")
            return None
        
        try:
            data = {key: stats.to_dict() for key, stats in self._stats.items()}
            with open(self._stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved key statistics to {self._stats_file}")
            return self._stats_file
        except OSError as e:
            logger.warning(f"Failed to save stats file: {e}")
            return None
    
    def _get_stats(self, key: str) -> KeyStats:
        """Get or create statistics for a key."""
        if key not in self._stats:
            if self._testing_mode:
                # In testing mode, initialize keys at 80% (at learned threshold)
                # One correct keystroke will push them to 81% (>80% = learned)
                self._stats[key] = KeyStats(score=80, total_presses=0)
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
                stats.record_incorrect()
                logger.debug(f"Key '{self._pending_key}' marked incorrect (score: {stats.score:.1f}%)")
                self._pending_key = None
            # Don't track backspace itself as a learning key
            return
        
        # Check if previous key should be marked as correct
        if self._pending_key is not None:
            # Previous key was correct (no backspace before this key)
            stats = self._get_stats(self._pending_key)
            stats.record_correct()
            logger.debug(f"Key '{self._pending_key}' marked correct (score: {stats.score:.1f}%)")
        
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
    
    def get_key_score(self, key: str) -> float | None:
        """Get the score for a specific key.
        
        Args:
            key: The key label to check
            
        Returns:
            Score percentage (0-100) or None if no data
        """
        key_lower = key.lower()
        if key_lower not in self._stats:
            return None
        return self._stats[key_lower].score
    
    def get_summary(self) -> str:
        """Get a human-readable summary of learning progress.
        
        Returns:
            Summary string with statistics
        """
        if not self._stats:
            return "No typing statistics recorded yet."
        
        total_keys = len(self._stats)
        learned_keys = len(self.get_learned_keys())
        
        # Calculate average score across all keys
        if total_keys > 0:
            avg_score = sum(s.score for s in self._stats.values()) / total_keys
        else:
            avg_score = 0.0
        
        total_presses = sum(s.total_presses for s in self._stats.values())
        
        return (
            f"Learned {learned_keys}/{total_keys} keys | "
            f"Average score: {avg_score:.1f}% | "
            f"Total keypresses: {total_presses}"
        )