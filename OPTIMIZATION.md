# Clicker 2.0 - Анализ и рекомендации по оптимизации

## Обзор

Этот документ содержит анализ текущего кода и рекомендации по оптимизации производительности, надёжности и поддерживаемости системы Clicker 2.0.

---

## 1. Критические проблемы

### 1.1 Утечка ресурсов при перезапуске бота (`main.py`)

**Проблема:**
```python
# Перезапускаем бота
bot.stop()
time.sleep(2)  # Ждём освобождения ресурсов

# Создаём нового бота
new_bot = VirtualBotEnv(bot_idx, bot_cfg)
new_bot.start(cfg_main['sites'][site_name]['url'])
```

При перезапуске старый бот вызывается `bot.stop()`, но процессы могут не успеть завершиться перед созданием нового бота с тем же `bot_idx`. Это может привести к:
- Конфликту портов VNC (порт 5900+bot_idx уже занят)
- Конфликту дисплеев Xvfb
- Утечке памяти

**Решение:**
```python
# Проверяем время следующего перезапуска
# next_restart_time = last_start_time + restart_delay
if bot.next_restart_time and current_time >= bot.next_restart_time.timestamp():
    # Перезапускаем бота
    bot.stop()
    time.sleep(2)  # Ждём освобождения ресурсов
    
    # Очищаем процессы
    for p in bot.procs.values():
        if p and p.poll() is None:
            p.kill()
            p.wait(timeout=5)
    
    # Создаём нового бота
    new_bot = VirtualBotEnv(bot_idx, bot_cfg)
    new_bot.start(url)
```

**Исправление:** Время перезапуска теперь вычисляется как `last_start_time + restart_delay`, а не от момента остановки.

---

### 1.2 Блокирующее логирование (`env_bot.py`)

**Проблема:**
```python
def _log_event(self, event_type: str, message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{event_type}] {message}\n"
    
    with self.log_lock:
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)  # Блокирующий I/O на каждый лог!
```

Каждое событие вопроса вызывает синхронную запись на диск. При 100 вопросах это 100+ синхронных I/O операций.

**Решение:**
```python
# Вариант 1: Буферизированное логирование
def __init__(self, ...):
    self.log_buffer = []
    self.log_buffer_lock = threading.Lock()
    self.last_flush = time.time()

def _log_event(self, event_type: str, message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{event_type}] {message}\n"
    
    with self.log_buffer_lock:
        self.log_buffer.append(log_entry)
        
        # Сброс каждые 5 секунд или при 10 записях
        if len(self.log_buffer) >= 10 or time.time() - self.last_flush > 5:
            self._flush_logs()
    
def _flush_logs(self):
    with self.log_lock:
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.writelines(self.log_buffer)
        self.log_buffer.clear()
        self.last_flush = time.time()
```

---

### 1.3 Избыточные проверки в основном цикле (`main.py`)

**Проблема:**
```python
while True:
    # Проверяем ПЕРЕД КАЖДОЙ итерацией
    for bot_idx, (bot, fsm) in enumerate(zip(bots, logics)):
        if bot.stop_event.is_set():
            # ... проверка restart_delay ...
    
    # Фильтруем активных ботов
    active_pairs = [(bot, fsm) for bot, fsm in zip(bots, logics) 
                    if not bot.stop_event.is_set()]
    
    for bot, fsm in active_pairs:
        frame = bot.get_frame_umat()  # Захват экрана
        if frame is not None:
            fsm.execute_step(bot, analyzer, frame)
    
    time.sleep(0.1)  # Пауза 100мс
```

Проблемы:
1. Проверка `bot.stop_event.is_set()` выполняется дважды за итерацию
2. Проверка restart_delay выполняется каждый цикл (даже когда бот активен)
3. `time.sleep(0.1)` добавляет задержку даже для активных ботов

**Решение:**
```python
# Разделяем проверку перезапуска и обработку
restart_check_interval = 1.0  # Проверяем перезапуск раз в секунду
last_restart_check = time.time()

while True:
    current_time = time.time()
    
    # Проверяем перезапуск только раз в секунду
    if current_time - last_restart_check > restart_check_interval:
        self._check_bot_restarts()  # Вынесли в отдельный метод
        last_restart_check = current_time
    
    # Обрабатываем только активные боты
    for bot_idx, (bot, fsm) in enumerate(zip(bots, logics)):
        if not bot.stop_event.is_set():
            frame = bot.get_frame_umat()
            if frame is not None:
                fsm.execute_step(bot, analyzer, frame)
    
    # Убираем sleep или делаем адаптивным
    # time.sleep(0.01)  # Минимальная пауза
```

---

## 2. Оптимизация производительности

### 2.1 Захват экрана (`env_bot.py`)

**Проблема:**
```python
def get_frame_umat(self):
    with mss.mss() as sct:  # Создаём новое mss КАЖДЫЙ захват!
        sct_img = sct.grab(sct.monitors[1])
        img_umat = cv2.UMat(np.array(sct_img))
        gray = cv2.cvtColor(img_umat, cv2.COLOR_BGRA2GRAY)
        gray = cv2.Canny(gray, 50, 150)
        time.sleep(0.2)  # Лишняя задержка 200мс!
        return gray
```

**Проблемы:**
1. `mss.mss()` создаётся заново каждый вызов (дорогая операция)
2. `time.sleep(0.2)` добавляет 200мс задержки
3. Canny edge detection может быть избыточен

**Решение:**
```python
def __init__(self, ...):
    # Создаём mss один раз при инициализации
    self.sct = mss.mss()
    self.monitor = self.sct.monitors[1]

def get_frame_umat(self):
    try:
        # Без создания нового контекста
        sct_img = self.sct.grab(self.monitor)
        
        # Быстрая конвертация
        img_umat = cv2.UMat(np.array(sct_img))
        gray = cv2.cvtColor(img_umat, cv2.COLOR_BGRA2GRAY)
        
        # Опционально: Canny только если нужен для шаблонов
        # Если шаблоны работают с обычным grayscale - убираем Canny
        if self.use_canny:  # Новый параметр
            gray = cv2.Canny(gray, 50, 150)
        
        # Убираем time.sleep(0.2)!
        return gray
    except Exception as e:
        print(f"Ошибка на {self.display}: {e}")
        return None

def stop(self):
    # Закрываем mss при остановке
    if hasattr(self, 'sct'):
        self.sct.close()
    # ... остальной код ...
```

**Выигрыш:** ~200мс на каждый захват экрана = 20 секунд на 100 вопросов

---

### 2.2 Шаблонный поиск (`gpu_analyzer.py`)

**Проблема:**
```python
def find_best_match(self, frame, templates, threshold):
    print('Counter:', self.counter)  # Лог в каждом вызове!
    for path in templates:
        # ...
        print(f"Search {path}")  # Лог в каждом вызове!
        print(f"Max_loc {max_loc}, {max_val}")  # Лог!
        
        res = cv2.matchTemplate(frame, temp, cv2.TM_CCOEFF_NORMED)
        # matchTemplate выполняется для КАЖДОГО шаблона
```

**Проблемы:**
1. Много print() вызовов в горячем цикле
2. matchTemplate выполняется для всех шаблонов последовательно
3. Нет раннего выхода после нахождения совпадения

**Решение:**
```python
def find_best_match(self, frame, templates, threshold):
    # Убираем лишние логи
    # print('Counter:', self.counter)
    
    best_match = None
    best_val = 0
    
    for path in templates:
        if path not in self.cache:
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            img = cv2.Canny(img, 50, 150)
            if img is None: continue
            self.cache[path] = cv2.UMat(img)
        
        temp = self.cache[path]
        h, w = temp.get().shape[:2]
        
        res = cv2.matchTemplate(frame, temp, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        
        # Ранний выход при первом совпадении
        if max_val >= threshold:
            self.counter += 1
            rand_offset_x = random.randint(-int(w//5), int(w//5)) if w > 5 else 0
            rand_offset_y = random.randint(-int(h//5), int(h//5)) if h > 5 else 0
            x = max_loc[0] + w // 2 + rand_offset_x
            y = max_loc[1] + h // 2 + rand_offset_y
            
            # Лог только при важном событии
            # print(f"Found {path}")
            return (x, y), max_val
    
    return None, 0
```

---

### 2.3 Избыточные проверки лимита (`bot_logic.py`)

**Проблема:**
```python
if success:
    if not bot.increment_question_count():
        bot.log_limit_exhausted()
        return
    # ...
    if not bot.check_question_limit():  # Дублирующая проверка!
        bot.log_limit_exhausted()
        return
else:
    if not bot.increment_question_count():
        bot.log_limit_exhausted()
        return
    # ...
    if not bot.check_question_limit():  # Дублирующая проверка!
        bot.log_limit_exhausted()
        return
```

`increment_question_count()` уже проверяет лимит и вызывает `stop_event.set()`. `check_question_limit()` после этого избыточен.

**Решение:**
```python
if success:
    if not bot.increment_question_count():
        bot.log_limit_exhausted()
        return
    bot.save_verified_json(verified_data)
    advanced = bot.advance_question()
    if not advanced:
        print(f"[+] [Бот {self.bot_id}] Все вопросы обработаны")
        return
    # Убираем дублирующую проверку
    self.reset_scenario(bot)
else:
    if not bot.increment_question_count():
        bot.log_limit_exhausted()
        return
    print(f"[!] [Бот {self.bot_id}] JSON плохой, повтор (попытка #{bot.total_question_count})")
    # Убираем дублирующую проверку
    self.reset_scenario(bot)
```

---

### 2.4 Загрузка промптов при каждой инициализации (`env_bot.py`)

**Проблема:**
```python
def _load_prompts(self, base_dir, bot_cfg):
    cfg_main_path = os.path.join(base_dir, 'config_main.yaml')
    with open(cfg_main_path, 'r', encoding='utf-8') as f:
        import yaml  # Импорт внутри метода!
        cfg_main = yaml.safe_load(f)
    # ...
```

При перезапуске бота промпты загружаются заново из файла.

**Решение:**
```python
# Глобальный кэш промптов
PROMPT_CACHE = {}

def _load_prompts(self, base_dir, bot_cfg):
    cache_key = f"{self.model_name}/{self.project}/{self.subproject}"
    
    # Проверяем кэш
    if cache_key in PROMPT_CACHE:
        self.prompt_text, self.prompt_json = PROMPT_CACHE[cache_key]
        return
    
    # ... загрузка из файла ...
    
    # Сохраняем в кэш
    PROMPT_CACHE[cache_key] = (self.prompt_text, self.prompt_json)
```

---

## 3. Оптимизация памяти

### 3.1 Очистка кэша шаблонов (`gpu_analyzer.py`)

**Проблема:**
```python
class GPUAnalyzer:
    def __init__(self):
        self.cache = {}  # Растёт бесконечно!
```

Шаблоны никогда не удаляются из кэша.

**Решение:**
```python
from collections import OrderedDict

class GPUAnalyzer:
    def __init__(self, max_cache_size=100):
        self.cache = OrderedDict()
        self.max_cache_size = max_cache_size
    
    def find_best_match(self, frame, templates, threshold):
        for path in templates:
            if path not in self.cache:
                # LRU eviction
                if len(self.cache) >= self.max_cache_size:
                    self.cache.popitem(last=False)
                
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                # ...
                self.cache[path] = cv2.UMat(img)
```

---

### 3.2 Очистка временных профилей (`env_bot.py`)

**Проблема:**
```python
def _prepare_profile(self):
    if os.path.exists(self.temp_profile):
        shutil.rmtree(self.temp_profile, ignore_errors=True)
    
    self._clear_cache(self.master_profile)
    shutil.copytree(self.master_profile, self.temp_profile)
```

При перезапуске создаётся новый временный профиль, но старый может остаться.

**Решение:**
```python
def stop(self):
    # Очищаем временный профиль при остановке
    if hasattr(self, 'temp_profile') and os.path.exists(self.temp_profile):
        shutil.rmtree(self.temp_profile, ignore_errors=True)
    
    # Закрываем mss
    if hasattr(self, 'sct'):
        self.sct.close()
    
    # ... остальной код ...
```

---

## 4. Надёжность и обработка ошибок

### 4.1 Обработка исключений в основном цикле (`main.py`)

**Проблема:**
```python
try:
    while True:
        for bot, fsm in active_pairs:
            frame = bot.get_frame_umat()
            if frame is not None:
                fsm.execute_step(bot, analyzer, frame)  # Может выбросить
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\n[*] Завершение работы...")
    for b in bots:
        b.stop()
```

Любое необработанное исключение в `execute_step()` завершит весь цикл.

**Решение:**
```python
try:
    while True:
        for bot_idx, (bot, fsm) in enumerate(zip(bots, logics)):
            if not bot.stop_event.is_set():
                try:
                    frame = bot.get_frame_umat()
                    if frame is not None:
                        fsm.execute_step(bot, analyzer, frame)
                except Exception as e:
                    print(f"[!] [Бот {bot_idx}] Ошибка в цикле: {e}")
                    import traceback
                    traceback.print_exc()
                    # Продолжаем работу с другими ботами
        time.sleep(0.01)
except KeyboardInterrupt:
    # ...
```

---

### 4.2 Таймауты для subprocess (`env_bot.py`)

**Проблема:**
```python
def _executor(self):
    result = subprocess.run(
        ["xdotool", "mousemove", str(val[0]), str(val[1]), "click", "1"],
        env=env, capture_output=True, text=True
    )  # Нет таймаута!
```

Если xdotool зависнет, поток executor заблокируется навсегда.

**Решение:**
```python
def _executor(self):
    try:
        result = subprocess.run(
            ["xdotool", "mousemove", str(val[0]), str(val[1]), "click", "1"],
            env=env, capture_output=True, text=True, timeout=5.0
        )
        if result.returncode != 0:
            print(f"[!] [Бот {self.bot_id}] xdotool error: {result.stderr}")
    except subprocess.TimeoutExpired:
        print(f"[!] [Бот {self.bot_id}] xdotool timeout (5 сек)")
    except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка executor: {e}")
```

---

### 4.3 Проверка перед записью лога (`env_bot.py`)

**Проблема:**
```python
def _log_event(self, event_type: str, message: str):
    with self.log_lock:
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)  # Может упасть если диск полон
```

**Решение:**
```python
def _log_event(self, event_type: str, message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{event_type}] {message}\n"
    
    try:
        with self.log_lock:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
    except Exception as e:
        # Fallback: выводим в stdout
        print(f"[LOG ERROR] {e}: {log_entry}")
```

---

## 5. Архитектурные улучшения

### 5.1 Выделение менеджера ботов

**Текущее состояние:**
Вся логика управления ботами в `main.py` (120 строк).

**Предложение:**
```python
# scripts/bot_manager.py
class BotManager:
    def __init__(self, cfg_main, cfg_bots):
        self.cfg_main = cfg_main
        self.cfg_bots = cfg_bots
        self.bots = {}
        self.fsms = {}
        self.bot_configs = {}
        self.stop_times = {}
    
    def start_bot(self, bot_idx):
        # Логика запуска бота
    
    def stop_bot(self, bot_idx):
        # Логика остановки
    
    def restart_bot(self, bot_idx):
        # Логика перезапуска
    
    def check_restarts(self):
        # Проверка таймеров перезапуска
    
    def get_active_bots(self):
        # Возврат активных ботов
    
    def cleanup(self):
        # Остановка всех ботов
```

**Преимущества:**
- Разделение ответственности
- Упрощение `main.py`
- Легче тестировать

---

### 5.2 Конфигурация через dataclass

**Текущее состояние:**
```python
self.max_questions = bot_cfg.get('max_questions', 100)
self.restart_delay = bot_cfg.get('restart_delay', 0)
# ... много get() вызовов ...
```

**Предложение:**
```python
from dataclasses import dataclass

@dataclass
class BotConfig:
    bot_id: int
    project: str = 'hypos_norm'
    subproject: str = 'gen'
    site: str = 'perplexity'
    mode: str = 'grok'
    model_name: str = 'perplexity_grok'
    max_questions: int = 100
    restart_delay: int = 0
    row_range: Tuple[int, int] = (0, 1000000)
    # ...
    
    @classmethod
    def from_dict(cls, bot_id: int, data: dict) -> 'BotConfig':
        return cls(
            bot_id=bot_id,
            project=data.get('project', 'hypos_norm'),
            subproject=data.get('subproject', 'gen'),
            # ...
        )
```

**Преимущества:**
- Типизация
- Автодополнение в IDE
- Валидация при создании

---

### 5.3 Асинхронная архитектура

**Текущее состояние:**
- Потоки для executor
- Опрос через `time.sleep()`
- Блокирующие I/O операции

**Предложение (долгосрочное):**
```python
import asyncio
import aiohttp

class AsyncBot:
    def __init__(self, bot_id, config):
        self.bot_id = bot_id
        self.semaphore = asyncio.Semaphore(1)
    
    async def run_cycle(self):
        async with self.semaphore:
            frame = await self.capture_frame()
            await self.process_frame(frame)
    
    async def capture_frame(self):
        # Асинхронный захват экрана
        pass

async def main():
    bots = [AsyncBot(i, cfg) for i, cfg in enumerate(configs)]
    tasks = [bot.run_cycle() for bot in bots]
    await asyncio.gather(*tasks)
```

**Преимущества:**
- Лучшая утилизация CPU
- Нет блокирующих вызовов
- Легче масштабировать

---

## 6. Конкретные рекомендации

### Приоритет 1 (Критично)

1. **Убрать `time.sleep(0.2)` в `get_frame_umat()`** — экономия 20 секунд на 100 вопросов
2. **Добавить таймауты к subprocess** — предотвращение зависаний
3. **Исправить утечку ресурсов при перезапуске** — стабильность при долгой работе
4. **Добавить обработку исключений в основном цикле** — отказоустойчивость

### Приоритет 2 (Производительность)

1. **Буферизированное логирование** — меньше I/O операций
2. **Кэширование mss контекста** — быстрее захват экрана
3. **Ранний выход в find_best_match()** — быстрее поиск шаблонов
4. **Кэширование промптов** — быстрее перезапуск

### Приоритет 3 (Поддерживаемость)

1. **Выделение BotManager** — чище архитектура
2. **Dataclass для конфигурации** — типизация
3. **Удаление отладочных print()** — чище логи
4. **Добавить unit тесты** — надёжность

---

## 7. Оценка эффекта оптимизаций

| Оптимизация | Текущее | После | Выигрыш |
|-------------|---------|-------|---------|
| Захват экрана (1 вопрос) | ~300мс | ~50мс | 6x |
| Логирование (100 вопросов) | 100 I/O | 10 I/O | 10x |
| Перезапуск бота | Нестабильно | Стабильно | Надёжность |
| Обработка ошибок | Падает всё | Продолжает работать | Отказоустойчивость |

**Общий выигрыш:** 3-5x ускорение обработки вопросов + стабильность работы

---

## 8. Чек-лист для внедрения

### Немедленно (Приоритет 1)
- [ ] Удалить `time.sleep(0.2)` из `get_frame_umat()`
- [ ] Добавить `timeout=5.0` ко всем `subprocess.run()`
- [ ] Добавить `try/except` в основной цикл
- [ ] Добавить `time.sleep(2)` после `bot.stop()` перед перезапуском

### В течение недели (Приоритет 2)
- [ ] Реализовать буферизированное логирование
- [ ] Кэшировать `mss.mss()` контекст
- [ ] Удалить отладочные `print()` из production кода
- [ ] Добавить LRU кэш для шаблонов

### В течение месяца (Приоритет 3)
- [ ] Выделить `BotManager` класс
- [ ] Использовать dataclass для конфигурации
- [ ] Покрыть тестами критичную логику
- [ ] Добавить метрики производительности

---

## 9. Мониторинг производительности

### Метрики для отслеживания

```python
# В env_bot.py
import time

class VirtualBotEnv:
    def __init__(self, ...):
        self.metrics = {
            'frame_capture_times': [],
            'question_attempts': 0,
            'successful_questions': 0,
            'restart_count': 0,
        }
    
    def get_frame_umat(self):
        start = time.time()
        # ... захват ...
        elapsed = time.time() - start
        self.metrics['frame_capture_times'].append(elapsed)
        return frame
    
    def get_avg_frame_time(self):
        times = self.metrics['frame_capture_times'][-100:]  # Последние 100
        return sum(times) / len(times) if times else 0
```

### Логирование метрик

```python
# Каждые 5 минут
if time.time() - last_metrics_log > 300:
    avg_time = bot.get_avg_frame_time()
    print(f"[METRICS] Бот {bot_id}: среднее время захвата {avg_time*1000:.1f}мс")
    print(f"[METRICS] Бот {bot_id}: вопросов задано {bot.total_question_count}")
    last_metrics_log = time.time()
```

---

## Заключение

Предложенные оптимизации дадут:
- **3-5x ускорение** обработки вопросов
- **Стабильную работу** при длительном выполнении (дни/недели)
- **Лучшую диагностику** проблем через метрики
- **Проще поддержку** благодаря модульной архитектуре

Рекомендуется внедрять оптимизации постепенно, начиная с Приоритета 1, и тестировать после каждого изменения.
