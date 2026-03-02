"""
Advanced Bot Logging System

Provides structured logging for each bot with:
- Per-bot log files with rotation
- Success/failure tracking for all operations
- JSON structured logging for analysis
- Different log levels (INFO, SUCCESS, WARNING, ERROR, DEBUG)
"""

import logging
import os
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import logging.handlers


class BotLogger:
    """
    Dedicated logger for a single bot instance.
    Creates separate log files for each bot with structured logging.
    """
    
    # Custom log levels
    SUCCESS = 25  # Between INFO and WARNING
    ACTION = 22   # Between INFO and SUCCESS
    
    def __init__(self, bot_id: int, project: str = "unknown", log_dir: str = "logs"):
        self.bot_id = bot_id
        self.project = project
        self.logger_name = f"bot_{bot_id}"
        
        # Setup base directory
        base_dir = Path(__file__).parent.parent
        self.log_dir = base_dir / log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create bot-specific log directory
        self.bot_log_dir = self.log_dir / f"bot_{bot_id}"
        self.bot_log_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize logger
        self.logger = self._setup_logger()
        
        # Statistics tracking
        self.stats = {
            "actions_total": 0,
            "actions_success": 0,
            "actions_failed": 0,
            "states_visited": {},
            "start_time": datetime.now().isoformat(),
            "last_activity": None
        }
        
        self._log_startup()
    
    def _setup_logger(self) -> logging.Logger:
        """Setup logger with multiple handlers for different outputs"""
        logger = logging.getLogger(self.logger_name)
        logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # Register custom levels
        logging.addLevelName(self.SUCCESS, "SUCCESS")
        logging.addLevelName(self.ACTION, "ACTION")
        
        # 1. File handler - All logs with rotation
        log_file = self.bot_log_dir / f"bot_{self.bot_id}_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # 2. JSON log file - Structured events for analysis
        json_log_file = self.bot_log_dir / f"events_{self.bot_id}_{datetime.now().strftime('%Y%m%d')}.jsonl"
        self.json_log_path = json_log_file
        # Note: JSON logging handled separately
        
        # 3. Console handler - Only important messages
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s | Bot %(bot_id)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # Add bot_id to log records
        old_factory = logging.getLogRecordFactory()
        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.bot_id = self.bot_id
            return record
        logging.setLogRecordFactory(record_factory)
        
        return logger
    
    def _log_startup(self):
        """Log bot startup information"""
        self.info("BOT_START", {
            "bot_id": self.bot_id,
            "project": self.project,
            "timestamp": datetime.now().isoformat(),
            "log_dir": str(self.bot_log_dir)
        })
    
    def _log_json(self, event_type: str, data: Dict[str, Any]):
        """Write structured JSON log entry"""
        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "bot_id": self.bot_id,
                "event_type": event_type,
                "data": data
            }
            with open(self.json_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as e:
            self.logger.error(f"Failed to write JSON log: {e}")
    
    def _log_action(self, action_name: str, success: bool, details: Optional[Dict] = None):
        """Internal method to log actions with statistics"""
        self.stats["actions_total"] += 1
        self.stats["last_activity"] = datetime.now().isoformat()
        
        if success:
            self.stats["actions_success"] += 1
            level = self.ACTION
            level_name = "ACTION"
        else:
            self.stats["actions_failed"] += 1
            level = logging.WARNING
            level_name = "ACTION_FAIL"
        
        message = f"{action_name} - {'✓' if success else '✗'}"
        if details:
            message += f" | {details}"
        
        self.logger.log(level, message)
        
        # Also log to JSON
        self._log_json("action", {
            "action": action_name,
            "success": success,
            "details": details or {}
        })
    
    # === Public logging methods ===
    
    def info(self, event: str, data: Optional[Dict] = None):
        """Log informational message"""
        message = f"[{event}]"
        if data:
            message += f" {json.dumps(data, ensure_ascii=False)}"
        self.logger.info(message)
        self._log_json(event, data or {})
    
    def success(self, event: str, data: Optional[Dict] = None):
        """Log successful operation"""
        message = f"✓ [{event}]"
        if data:
            message += f" {json.dumps(data, ensure_ascii=False)}"
        self.logger.log(self.SUCCESS, message)
        self._log_json(f"SUCCESS_{event}", data or {})
    
    def action(self, action_name: str, details: Optional[Dict] = None):
        """Log action execution"""
        self._log_action(action_name, True, details)
    
    def action_failed(self, action_name: str, error: str, details: Optional[Dict] = None):
        """Log action failure"""
        data = details or {}
        data["error"] = error
        self._log_action(action_name, False, data)
        self.logger.error(f"✗ [{action_name}] {error}")
    
    def error(self, event: str, error: str, data: Optional[Dict] = None):
        """Log error with context"""
        message = f"✗ [{event}] {error}"
        self.logger.error(message)
        self._log_json(f"ERROR_{event}", {
            "error": error,
            "data": data or {}
        })
    
    def warning(self, event: str, message: str, data: Optional[Dict] = None):
        """Log warning"""
        full_message = f"⚠ [{event}] {message}"
        self.logger.warning(full_message)
        self._log_json(f"WARNING_{event}", {
            "message": message,
            "data": data or {}
        })
    
    def debug(self, event: str, data: Optional[Dict] = None):
        """Log debug information"""
        message = f"[{event}]"
        if data:
            message += f" {json.dumps(data, ensure_ascii=False)}"
        self.logger.debug(message)
    
    # === State tracking ===
    
    def state_enter(self, state_name: str, details: Optional[Dict] = None):
        """Log entering a new state"""
        self.stats["states_visited"][state_name] = self.stats["states_visited"].get(state_name, 0) + 1
        self.info(f"STATE_ENTER_{state_name}", details)
        self._log_json("state_enter", {
            "state": state_name,
            "visit_count": self.stats["states_visited"][state_name],
            "details": details or {}
        })
    
    def state_exit(self, state_name: str, success: bool, details: Optional[Dict] = None):
        """Log exiting a state"""
        data = details or {}
        data["success"] = success
        self.info(f"STATE_EXIT_{state_name}", data)
        self._log_json("state_exit", {
            "state": state_name,
            "success": success,
            "details": data
        })
    
    # === Operation-specific logging ===
    
    def log_operation(self, operation: str, success: bool, duration_ms: Optional[float] = None, 
                     details: Optional[Dict] = None):
        """Log any operation with timing"""
        data = details or {}
        if duration_ms is not None:
            data["duration_ms"] = duration_ms
        data["success"] = success
        
        if success:
            self.success(f"OP_{operation}", data)
        else:
            self.error(f"OP_{operation}", "Operation failed", data)
    
    def log_click(self, coords: tuple, success: bool, element: str = "unknown"):
        """Log click action"""
        self.log_operation(
            "click",
            success,
            details={"coords": coords, "element": element}
        )
    
    def log_json_saved(self, filepath: str, uid: str, global_idx: int):
        """Log JSON save operation"""
        self.success("JSON_SAVED", {
            "filepath": filepath,
            "uid": uid,
            "global_idx": global_idx
        })
    
    def log_json_failed(self, reason: str, uid: Optional[str] = None):
        """Log JSON save/verification failure"""
        self.error("JSON_FAILED", reason, {"uid": uid})
    
    def log_question_advance(self, old_idx: int, new_idx: int, uid: str):
        """Log question advancement"""
        self.info("QUESTION_ADVANCE", {
            "old_idx": old_idx,
            "new_idx": new_idx,
            "uid": uid
        })
    
    def log_clipboard(self, operation: str, success: bool, content_preview: Optional[str] = None):
        """Log clipboard operations"""
        data = {}
        if content_preview:
            data["preview"] = content_preview[:100] + "..." if len(content_preview) > 100 else content_preview
        
        if success:
            self.action(f"CLIPBOARD_{operation}", data)
        else:
            self.action_failed(f"CLIPBOARD_{operation}", "Operation failed", data)
    
    def log_browser_action(self, action: str, success: bool, details: Optional[Dict] = None):
        """Log browser-related actions"""
        if success:
            self.action(f"BROWSER_{action}", details)
        else:
            self.action_failed(f"BROWSER_{action}", "Browser action failed", details)
    
    def log_verification(self, verification_type: str, success: bool, details: Optional[Dict] = None):
        """Log verification operations (JSON, templates, etc.)"""
        data = details or {}
        if success:
            self.success(f"VERIFY_{verification_type}", data)
        else:
            self.warning(f"VERIFY_{verification_type}_FAILED", "Verification failed", data)
    
    def log_timeout(self, state: str, elapsed: float, timeout: float):
        """Log state timeout"""
        self.warning("STATE_TIMEOUT", f"State '{state}' timed out", {
            "state": state,
            "elapsed": elapsed,
            "timeout": timeout
        })
    
    def log_reset(self, reason: str):
        """Log scenario reset"""
        self.info("SCENARIO_RESET", {"reason": reason})
    
    # === Statistics ===
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        return {
            **self.stats,
            "success_rate": (
                self.stats["actions_success"] / self.stats["actions_total"] * 100
                if self.stats["actions_total"] > 0 else 0
            )
        }
    
    def log_stats(self):
        """Log current statistics"""
        stats = self.get_stats()
        self.info("STATS", stats)
        return stats
    
    def log_shutdown(self):
        """Log bot shutdown"""
        self.log_stats()
        self.info("BOT_STOP", {
            "bot_id": self.bot_id,
            "runtime_stats": self.get_stats()
        })


class LogManager:
    """
    Centralized logger manager for all bots.
    Provides unified access to bot-specific loggers.
    """
    
    _instance = None
    _loggers: Dict[int, BotLogger] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_logger(self, bot_id: int, project: str = "unknown") -> BotLogger:
        """Get or create logger for specific bot"""
        if bot_id not in self._loggers:
            self._loggers[bot_id] = BotLogger(bot_id, project)
        return self._loggers[bot_id]
    
    def get_all_stats(self) -> Dict[int, Dict]:
        """Get statistics from all bot loggers"""
        return {
            bot_id: logger.get_stats()
            for bot_id, logger in self._loggers.items()
        }
    
    def log_global_stats(self):
        """Log statistics for all bots"""
        stats = self.get_all_stats()
        global_logger = logging.getLogger("bot_manager")
        global_logger.info("=" * 60)
        global_logger.info("GLOBAL BOT STATISTICS")
        global_logger.info("=" * 60)
        for bot_id, bot_stats in stats.items():
            success_rate = bot_stats.get("success_rate", 0)
            total = bot_stats.get("actions_total", 0)
            global_logger.info(f"Bot {bot_id}: {total} actions, {success_rate:.1f}% success")
        global_logger.info("=" * 60)


# Convenience functions for quick access
def get_bot_logger(bot_id: int, project: str = "unknown") -> BotLogger:
    """Get logger for a specific bot"""
    manager = LogManager()
    return manager.get_logger(bot_id, project)


def log_global_stats():
    """Log statistics for all active bots"""
    manager = LogManager()
    manager.log_global_stats()
