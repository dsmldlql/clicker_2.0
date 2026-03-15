# State Logging Documentation

## Overview

Расширенное логирование состояний FSM с детальным отслеживанием времени выполнения.

## Features

Логгер состояний (`scripts/state_logger.py`) предоставляет:

- **Временные метки** для каждого события
- **Замер времени** выполнения состояний
- **Отслеживание переходов** между состояниями
- **Статистику** по каждому состоянию
- **JSONL формат** для удобного парсинга

## Log Events

### STATE_ENTER
Вход в состояние:
- `state`: название состояния
- `from_state`: предыдущее состояние
- `transition_delay_ms`: время между выходами из предыдущего состояния

### TRIGGER_FOUND
Визуальный триггер найден:
- `time_to_trigger_ms`: время от входа в состояние до нахождения триггера

### CONDITION_CHECK_START
Начало проверки условия:
- `time_from_enter_ms`: время от входа в состояние

### CONDITION_RESULT
Результат проверки условия:
- `success`: True/False
- `condition_type`: 'templates', 'json_valid', 'always'
- `condition_time_ms`: время проверки условия
- `total_time_ms`: общее время в состоянии

### STATE_EXIT
Выход из состояния:
- `next_state`: следующее состояние
- `success`: результат условия
- `reason`: 'normal', 'timeout', 'error'
- `total_duration_ms`: общее время в состоянии
- `condition_check_time_ms`: время проверки условия
- `avg_duration_ms`: среднее время для этого состояния

### STATE_TIMEOUT
Таймаут состояния:
- `timeout_sec`: установленный таймаут
- `elapsed_ms`: фактическое время

## Output Files

Логи сохраняются в:
```
logs/bot_<ID>/state_timeline_<site>_<scenario>.jsonl
```

## Console Output

Пример вывода в консоль:

```
[STATE] [gemini/thinking] → ENTER 'start_question'
[STATE] [gemini/thinking] ✓ Trigger found in 'start_question' [1250ms]
[STATE] [gemini/thinking] ✓ Condition 'templates': PASS [condition: 45ms, total: 1295ms]
[STATE] [gemini/thinking] ✓ EXIT 'start_question' → 'paste_question' [normal] [total: 1295ms, condition: 45ms]
```

## Usage

### В коде (автоматически)

StateLogger автоматически инициализируется в `FSM.__init__()`:

```python
self.state_logger = StateLogger(bot_id, site, scenario_name, log_dir)
```

### Методы для ручного вызова

```python
# Вывод статистики в консоль
bot.fsm.print_state_stats()

# Получение статистики как dict
stats = bot.fsm.get_state_stats()
```

## Log File Format

Каждая строка - JSON объект:

```json
{
  "timestamp": "2026-03-15T10:30:45.123456",
  "bot_id": 0,
  "site": "gemini",
  "scenario": "thinking",
  "event": "STATE_ENTER",
  "data": {
    "state": "start_question",
    "from_state": null,
    "transition_delay_ms": null
  }
}
```

## Analysis Example

Анализ логов с помощью Python:

```python
import json

events = []
with open('logs/bot_0/state_timeline_gemini_thinking.jsonl') as f:
    for line in f:
        events.append(json.loads(line))

# Посчитать среднее время состояния
state_times = []
for e in events:
    if e['event'] == 'STATE_EXIT':
        state_times.append(e['data']['total_duration_ms'])

avg_time = sum(state_times) / len(state_times)
print(f"Average state duration: {avg_time:.0f}ms")
```

## Integration Points

Логгер интегрирован в следующие места `bot_logic.py`:

1. **FSM.__init__()** - инициализация и логирование начального состояния
2. **execute_step()** - логирование:
   - Таймаутов
   - Нахождения триггеров
   - Проверки условий
   - Переходов между состояниями
3. **reset_scenario()** - логирование возврата в start_state
