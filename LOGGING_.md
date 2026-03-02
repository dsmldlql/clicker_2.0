# Bot Logging System

## Overview

The Clicker 2.0 application now includes a comprehensive logging system that tracks all bot activities with timestamps, success/failure status, and detailed context.

## Features

### 1. Per-Bot Log Files
Each bot has its own dedicated log directory:
```
logs/
├── bot_0/
│   ├── bot_0_20260302.log          # Human-readable log file
│   └── events_0_20260302.jsonl     # Structured JSON events for analysis
├── bot_1/
│   ├── bot_1_20260302.log
│   └── events_1_20260302.jsonl
...
```

### 2. Log Levels

| Level | Value | Description |
|-------|-------|-------------|
| DEBUG | 10 | Detailed debugging information |
| INFO | 20 | General informational messages |
| ACTION | 22 | Action execution (custom level) |
| SUCCESS | 25 | Successful operations (custom level) |
| WARNING | 30 | Warning messages |
| ERROR | 40 | Error messages |

### 3. Logged Events

#### Bot Lifecycle
- `BOT_START` - Bot initialization
- `BOT_STARTING` - Browser starting
- `BOT_STOPPING` - Bot shutdown initiated
- `BOT_STOP` - Bot fully stopped

#### State Machine
- `STATE_ENTER_{state}` - Entering a new state
- `STATE_EXIT_{state}` - Exiting a state with success/failure
- `STATE_TIMEOUT` - State timeout occurred
- `SCENARIO_RESET` - Scenario reset executed

#### Actions
- `CLICK` - Click actions with coordinates
- `KEY_*` - Keyboard actions
- `HOTKEY_*` - Hotkey combinations
- `TYPE_*` - Text input actions
- `CLICK_PASTE_ENTER` - Prompt submission
- `CLICK_COPY_SAVE_JSON_CHECK` - Copy operations

#### JSON Operations
- `JSON_SAVED` - JSON successfully saved
- `JSON_FAILED` - JSON save/verification failed
- `VERIFY_JSON` - JSON verification result

#### Clipboard Operations
- `CLIPBOARD_READ` - Reading from clipboard
- `CLIPBOARD_WRITE` - Writing to clipboard
- `CLIPBOARD_CLEAR` - Clearing clipboard

#### Verification
- `VERIFY_TEMPLATE_MATCH` - Template matching result
- `VERIFY_CONDITION_TEMPLATE` - Condition check result
- `VERIFY_JSON` - JSON validation result

## Log File Format

### Human-Readable Log (.log)
```
2026-03-02 14:30:15 | INFO     | [FSM_INITIALIZED] {"site": "qwen", "scenario": "web_search_no_think", "start_state": "initial"}
2026-03-02 14:30:16 | ACTION   | ✓ [CLICK] {"coords": [150, 300]}
2026-03-02 14:30:17 | SUCCESS  | ✓ [JSON_SAVED] {"filepath": "/path/to/file.json", "uid": "12345", "global_idx": 168}
2026-03-02 14:30:18 | WARNING  | ⚠ [STATE_TIMEOUT] State 'waiting' timed out
2026-03-02 14:30:19 | ERROR    | ✗ [JSON_VERIFICATION_ERROR] Invalid JSON format
```

### Structured JSON Log (.jsonl)
Each line is a JSON object:
```json
{"timestamp": "2026-03-02T14:30:15.123456", "bot_id": 0, "event_type": "FSM_INITIALIZED", "data": {"site": "qwen", "scenario": "web_search_no_think"}}
{"timestamp": "2026-03-02T14:30:16.234567", "bot_id": 0, "event_type": "action", "data": {"action": "CLICK", "success": true, "details": {"coords": [150, 300]}}}
```

## Statistics Tracking

Each bot tracks:
- Total actions executed
- Successful actions
- Failed actions
- Success rate percentage
- States visited (count per state)
- Runtime duration
- Last activity timestamp

### Viewing Statistics

Statistics are automatically logged:
1. On bot shutdown
2. When calling `log_global_stats()` in main.py

Example output:
```
============================================================
GLOBAL BOT STATISTICS
============================================================
Bot 0: 1250 actions, 98.4% success
Bot 1: 1180 actions, 97.2% success
Bot 2: 1305 actions, 99.1% success
============================================================
```

## Usage

### Getting a Bot Logger

```python
from scripts.bot_logger import get_bot_logger

# In bot initialization
logger = get_bot_logger(bot_id, project_name)

# Log events
logger.info("EVENT_NAME", {"key": "value"})
logger.success("OPERATION_SUCCESS", {"details": "here"})
logger.error("OPERATION_FAILED", "Error message", {"context": "data"})
logger.action("ACTION_NAME", {"coords": [x, y]})
logger.action_failed("ACTION_NAME", "Error reason")
```

### Logging Specific Operations

```python
# State transitions
logger.state_enter("state_name", {"context": "data"})
logger.state_exit("state_name", success=True, {"next": "state"})

# Click operations
logger.log_click((x, y), success=True, element="button_name")

# JSON operations
logger.log_json_saved(filepath, uid, global_idx)
logger.log_json_failed("reason", uid)

# Question advancement
logger.log_question_advance(old_idx, new_idx, uid)

# Verification
logger.log_verification("JSON", success=True, {"norms_count": 5})

# Timing
logger.log_operation("operation_name", success=True, duration_ms=150.5)
```

## Analyzing Logs

### Using grep for quick searches
```bash
# Find all errors for bot 0
grep "ERROR" logs/bot_0/*.log

# Find all successful JSON saves
grep "JSON_SAVED" logs/bot_*/events_*.jsonl

# Find timeouts
grep "STATE_TIMEOUT" logs/bot_*/bot_*.log
```

### Using Python for JSON analysis
```python
import json
from pathlib import Path

# Read all events for bot 0
events = []
with open('logs/bot_0/events_0_20260302.jsonl') as f:
    for line in f:
        events.append(json.loads(line))

# Filter for errors
errors = [e for e in events if 'ERROR' in e['event_type']]

# Calculate success rate
actions = [e for e in events if e['event_type'] == 'action']
success_rate = sum(1 for a in actions if a['data']['success']) / len(actions) * 100
```

## Log Rotation

Log files automatically rotate when they reach 10MB:
- Current log: `bot_0_20260302.log`
- Rotated logs: `bot_0_20260302.log.1`, `.2`, etc. (up to 5 backups)

## Best Practices

1. **Always log with context**: Include relevant data in every log entry
2. **Use appropriate log levels**: 
   - INFO for normal operations
   - SUCCESS for important successful completions
   - WARNING for recoverable issues
   - ERROR for failures
3. **Log state transitions**: Always log when entering/exiting states
4. **Track timing**: Use `log_operation()` with duration for performance tracking
5. **Review statistics**: Check `log_global_stats()` output regularly

## Troubleshooting

### No logs appearing
1. Check that `logs/` directory exists
2. Verify bot has write permissions
3. Check console output for logger initialization errors

### Missing events
1. Ensure logger is initialized in bot's `__init__`
2. Check log level configuration
3. Verify JSON log file isn't locked by another process

### Performance issues
1. JSON logging is asynchronous and shouldn't impact performance
2. If disk space is concern, reduce log rotation backup count
3. Consider increasing rotation size limit
