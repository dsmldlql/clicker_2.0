# Изменения в логике работы с вопросами

## Дата: 2026-03-12

## Основные изменения

### 1. Логика переходов к состоянию `start_question`

Теперь при любом переходе в состояние `start_question` (не важно, success или fail) автоматически выполняется `reset_scenario()` - браузер возвращается к стартовой позиции.

**Файл:** `scripts/bot_logic.py`

```python
# Если следующее состояние - start_question, делаем reset браузера
if next_state == 'start_question':
    print(f"[*] [Бот {self.bot_id}] Переход в start_question - выполняем reset браузера")
    self.reset_scenario(bot)
    # reset_scenario уже устанавливает current_state в start_state
else:
    self.current_state = next_state
```

### 2. Логика обработки JSON ответов

#### Успешная верификация JSON:
- JSON сохраняется
- `cur_global_idx` увеличивается (переход к СЛЕДУЮЩЕМУ вопросу)
- Выполняется `reset_scenario()` для нового вопроса
- Бот начинает задавать СЛЕДУЮЩИЙ вопрос

#### Неудачная верификация JSON:
- `cur_global_idx` НЕ изменяется (вопрос остаётся тот же!)
- Увеличивается только `total_question_count` (счётчик попыток)
- Выполняется `reset_scenario()` для повторной попытки
- Бот задаёт тот же ВОПРОС заново

**Файл:** `scripts/bot_logic.py`, блок `elif cond.get('json_valid'):`

```python
if success:
    # JSON хорош - сохраняем и переходим к СЛЕДУЮЩЕМУ вопросу
    bot.save_verified_json(verified_data)
    advanced = bot.advance_question()  # cur_global_idx += 1
    self.reset_scenario(bot)
    return  # Возврат, чтобы не делать reset повторно
    
else:
    # JSON плохой - cur_global_idx НЕ изменяется, вопрос тот же
    print(f"JSON плохой, вопрос будет задан повторно (попытка #{bot.total_question_count}, индекс: {bot.cur_global_idx})")
    self.reset_scenario(bot)
    return  # Возврат, чтобы не делать reset повторно
```

## Схема работы

```
┌─────────────────────────────────────────────────────────────┐
│                    Start Question State                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │   click_paste_enter     │
              │   (задать вопрос)       │
              └─────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │   Проверка JSON из      │
              │   буфера обмена         │
              └─────────────────────────┘
                    │               │
              ┌─────┴─────┐   ┌─────┴─────┐
              │  JSON OK  │   │ JSON BAD  │
              └─────┬─────┘   └─────┬─────┘
                    │               │
                    ▼               ▼
          ┌─────────────────┐  ┌─────────────────┐
          │ save_verified_  │  │ cur_global_idx  │
          │ json()          │  │ НЕ изменяется   │
          └────────┬────────┘  └────────┬────────┘
                   │                    │
                   ▼                    ▼
          ┌─────────────────┐  ┌─────────────────┐
          │ advance_question│  │ reset_scenario  │
          │ cur_global_idx  │  │ (тот же вопрос) │
          │ += 1            │  │                 │
          └────────┬────────┘  └────────┬────────┘
                   │                    │
                   ▼                    ▼
          ┌─────────────────┐  ┌─────────────────┐
          │ reset_scenario  │  │ start_question  │
          │ (новый вопрос)  │  │ (повтор)        │
          └─────────────────┘  └─────────────────┘
```

## CSV логирование

Все события логируются в CSV файлы с разделителем `|`:

### Per-Bot CSV (logs/bot_{id}/log_{id}_{date}.csv):
```
timestamp|event_type|attempt_number|global_index|question_uid
2026-03-12 18:15:10|QUESTION_SENT||10|uid_010
2026-03-12 18:15:11|JSON_VERIFIED||10|uid_010
2026-03-12 18:15:11|JSON_SAVED||10|uid_010
2026-03-12 18:15:12|QUESTION_ADVANCE||11|uid_011
```

### Shared Scenario+Site CSV (logs/shared/{site}__{scenario}/log_{site}__{scenario}_{date}.csv):
```
timestamp|site|scenario|bot_id|event_type|attempt_number|global_index|question_uid
2026-03-12 18:15:10|perplexity|web_search|0|QUESTION_SENT||10|uid_010
```

## Ключевые отличия от предыдущей версии

| Ситуация | До изменений | После изменений |
|----------|--------------|-----------------|
| JSON плохой | cur_global_idx увеличивался | cur_global_idx НЕ изменяется |
| JSON плохой | Переход к следующему вопросу | Повтор того же вопроса |
| Переход в start_question | Без reset браузера | Автоматический reset_scenario() |
| JSON хороший | cur_global_idx увеличивался | cur_global_idx увеличивается (без изменений) |

## Тестирование

Проверьте работу бота:
1. Запустите бота
2. Дождитесь неудачной верификации JSON
3. Убедитесь, что вопрос задаётся повторно (тот же UID)
4. Проверьте CSV логи - `global_index` должен оставаться неизменным при повторных попытках
