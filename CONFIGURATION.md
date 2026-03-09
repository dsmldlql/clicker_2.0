# Конфигурация приложения Clicker 2.0

## Обзор

Приложение Clicker 2.0 использует два основных файла конфигурации:

- `config.yaml` - основной файл конфигурации с глобальными настройками и сценариями
- `bots_home.yaml` - файл с определениями отдельных ботов

## Структура config.yaml

### Глобальные параметры

```yaml
global:
  screen_max_width: 4000      # Максимальная ширина экрана
  screen_max_height: 2200     # Максимальная высота экрана
  screen_fps: 5               # Частота кадров
  dataset_path: datasets/sp_depers_final_with_hypnorm_used_marks.csv  # Путь к датасету
  columns:                    # Колонки в датасете
    - uid
    - query
    - used
  bots_count: 6               # Количество ботов
```

### Подсказки для моделей ИИ

Секция `prompts` определяет пути к подсказкам для различных моделей:

```yaml
prompts:
  gpt:
    hypos_norm:
      gen: 
        text: prompts/gpt/hypos_norm/gen/hn_gen_gpt_text_latest
        json: prompts/gpt/hypos_norm/gen/hn_gen_gpt_json_latest
      filter:
        text: prompts/gpt/hypos_norm/filter/hn_filter_gpt_text_latest
        json: prompts/gpt/hypos_norm/filter/hn_filter_gpt_json_latest
  # и другие модели: grok, claude_sonnet, gemini, qwen
```

### Конфигурация ботов

Каждый бот имеет уникальную конфигурацию:

```yaml
bots:
  bot_0:
    project: hypos_norm       # Проект (генерация гипотез)
    subproject: gen          # Подпроект (генерация)
    site: perplexity         # Целевой сайт
    mode: grok               # Режим работы
    model: perplexity_grok   # Используемая модель
    roi: [0, 0, 500, 620]    # Область интереса [x, y, ширина, высота]
    cooldown: 1.0            # Время задержки между действиями
    row_range: [83, 107]     # Диапазон строк для обработки
    max_questions: 100       # Общий лимит на количество вопросов
    restart_delay: 3600      # Задержка перед перезапуском (секунды)
```

Параметр `max_questions` определяет общий лимит на количество вопросов (включая повторные попытки). 
Каждый успешно заданный вопрос и каждая повторная попытка (при битом JSON) увеличивают общий счётчик. 
При исчерпании лимита бот останавливается.

Параметр `restart_delay` определяет задержку в секундах перед автоматическим перезапуском бота после исчерпания лимита вопросов.
Если `restart_delay: 3600`, бот перезапустится через 1 час (3600 секунд) после остановки.
Если `restart_delay: 0`, бот не будет перезапущен автоматически.

### Сценарии для сайтов

Самая сложная часть конфигурации - сценарии для каждого сайта. Они определяют FSM для автоматизации.

Пример сценария для Perplexity с Grok:

```yaml
perplexity:
  url: https://www.perplexity.ai/
  scenarios:
    grok:
      start_state: start_question
      states:
        start_question:
          expect:
            templates:
              - templates/brave/perplexity/ask_anything.png
            threshold: 0.8
          action: click
          condition:
            templates:
              - templates/brave/perplexity/model.png
            threshold: 0.8
          next:
            success: open_model_menu
            fail: model_selected
          timeout: 120.0
```

Каждое состояние включает:

- `expect`: Шаблоны для поиска на экране
- `action`: Действие для выполнения (click, click_paste_enter и др.)
- `condition`: Условие для перехода к следующему состоянию
- `next`: Переходы при успехе/неудаче
- `timeout`: Время ожидания перед сбросом

## Доступные действия

- `click`: Простой клик по элементу
- `click_paste_enter`: Клик, вставка текста из буфера и Enter
- `click_copy_save_json_check`: Клик, выделение всего, копирование и проверка JSON
- `click_scroll_down`: Клик с последующей прокруткой вниз
- `scroll_up`: Прокрутка вверх

## Структура bots_home.yaml

Файл `bots_home.yaml` содержит только определения ботов:

```yaml
bots:
  bot_0:
    project: hypos_norm
    subproject: gen
    site: perplexity
    mode: grok
    model: perplexity_grok
    roi: [0, 0, 500, 620]
    cooldown: 1.0
    row_range: [67, 107]
    max_questions: 100  # Общий лимит на все вопросы (включая повторные попытки)
    restart_delay: 3600  # Задержка перед перезапуском в секундах (1 час)
  # и другие боты...
```

## Шаблоны для сопоставления

Приложение использует файлы шаблонов в директории `templates/` для сопоставления с элементами интерфейса:

- `templates/brave/perplexity/` - шаблоны для Perplexity
- `templates/firefox/gpt/` - шаблоны для ChatGPT
- `templates/firefox/gemini/` - шаблоны для Gemini
- `templates/firefox/qwen/` - шаблоны для Qwen

Каждый шаблон - это изображение элемента интерфейса, которое используется для определения его наличия на экране.

## Режимы работы

Приложение поддерживает различные режимы работы:

- `grok` - для взаимодействия с моделью Grok
- `study_learn` - режим обучения для ChatGPT
- `web_search_no_think` - веб-поиск без размышлений для Qwen
- `claude_sonnet` - для взаимодействия с Claude Sonnet
- `gemini` - для взаимодействия с Gemini

Каждый режим имеет свои специфические сценарии автоматизации.

## Настройка ROI (область интереса)

ROI (Region of Interest) определяет прямоугольную область экрана, в которой будут искаться шаблоны:

```yaml
roi: [x_offset, y_offset, width, height]
```

Это позволяет оптимизировать поиск, ограничивая область поиска только необходимой частью экрана.

## Управление нагрузкой

Параметр `cooldown` в конфигурации ботов управляет задержкой между действиями, что помогает:

- Избежать детектирования автоматизации
- Уменьшить нагрузку на сервера
- Обеспечить стабильность работы