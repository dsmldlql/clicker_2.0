# Bot Schedule Feature

## Overview

Bots can now be configured to start at specific times of day instead of starting immediately.

## Configuration

Add a `schedule` section to your bot configuration in `config_bots.yaml`:

```yaml
bot_0:
  project: hypos_norm
  site: gemini
  # ... other config ...
  schedule:
    start_immediately: false  # Запустить сразу при старте программы
    start_times:
      - "00:00"
      - "06:00"
      - "12:00"
      - "18:00"
```

## Parameters

### `start_immediately` (optional)

- **Type**: boolean
- **Default**: `false`
- **Description**: If `true`, bot starts immediately when program launches, then follows the schedule for subsequent runs

**Behavior:**
- `true`: Bot starts right away, then waits for next scheduled time
- `false` or omitted: Bot waits until the next scheduled time

### `start_times`

- **Type**: list of strings
- **Format**: `HH:MM` or `H:MM` (24-hour format)
- **Description**: List of times when the bot should start

- **Time format**: `HH:MM` or `H:MM` (24-hour format)
- **Valid hours**: 0-23
- **Valid minutes**: 0-59
- **Multiple times**: Specify as many start times as needed

## Examples

### Start every 6 hours (wait for scheduled time)
```yaml
schedule:
  start_times:
    - "00:00"
    - "06:00"
    - "12:00"
    - "18:00"
```

### Start immediately, then every 6 hours
```yaml
schedule:
  start_immediately: true
  start_times:
    - "00:00"
    - "06:00"
    - "12:00"
    - "18:00"
```

### Start only at night
```yaml
schedule:
  start_times:
    - "23:00"
    - "02:00"
    - "04:00"
```

### Start at custom times
```yaml
schedule:
  start_times:
    - "9:00"
    - "14:30"
    - "20:15"
```

### No schedule (immediate start)
```yaml
# Option 1: Omit the schedule section entirely
# Bot will start immediately

# Option 2: Empty schedule
schedule:
  start_times: []
```

## How It Works

1. **On program startup**: 
   - If `start_immediately: true` → bot starts right away
   - If `start_immediately: false` → bot waits until next scheduled time
2. **Waiting**: The main loop checks every second if it's time to start any scheduled bots
3. **Start**: When the scheduled time arrives (within 60 seconds), the bot automatically starts
4. **Next run**: After starting, the next scheduled time is calculated (next occurrence of any specified time)

## Behavior

| `start_immediately` | Schedule | Time at launch | Bot behavior |
|---------------------|----------|----------------|--------------|
| `true` | Any | Any | **Starts immediately**, then waits for next scheduled time |
| `false` | Has times | Before scheduled | **Waits** until scheduled time |
| `false` | Has times | After scheduled | **Waits** until tomorrow's scheduled time |
| omitted/`false` | Empty/none | Any | **Starts immediately** (default behavior) |

## Examples

**Program launched at 10:00:**

```yaml
# Bot waits until 12:00
schedule:
  start_times:
    - "00:00"
    - "06:00"
    - "12:00"
    - "18:00"
```

```yaml
# Bot starts immediately at 10:00, then waits until 12:00
schedule:
  start_immediately: true
  start_times:
    - "00:00"
    - "06:00"
    - "12:00"
    - "18:00"
```

## Logs

You'll see messages like:
```
[*] Бот 0 ожидает запланированного запуска в 18:00:00
[+] Бот 0 Наступило время запуска (расписание)
[*] Запуск бота 0 по расписанию...
[+] Бот 0 запущен по расписанию
```

## Notes

- Bots without a schedule start immediately (default behavior)
- Schedule works independently for each bot
- You can combine schedule with `restart_delay` for complex timing patterns
