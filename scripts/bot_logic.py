import time, json, subprocess, re, os
from typing import Tuple, Any, Dict

# Import verification logic
try:
  from scripts.verification_saved_json import verify_saved_json, load_messy_json, check_valid_json
except ImportError:
  # Fallback if module not available
  verify_saved_json = None
  check_valid_json = None


class FSM:
  def __init__(self, bot_id, cfg_main, bot_config):
    self.bot_id = bot_id
    self.cfg_main = cfg_main
    self.bot_config = bot_config

    site = bot_config['site']
    scenario = bot_config['scenario']
    self.scenario = cfg_main['sites'][site]['scenarios'][scenario]
    self.site_config = cfg_main['sites'][site]
    self.current_state = self.scenario['start_state']
    self.expected_complete = False

    self.last_change = time.time()
    self.json_path = f"/tmp/bot_{bot_id}_response.json"


  def get_clipboard(self, display):
    try:
      cmd = ["xclip", "-selection", "clipboard", "-o", "-display", display]
      return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
    except:
      return ""

  def is_json_valid(self, text):
    if not text: return False
    try:
      # Поиск границ JSON в тексте
      start = text.find('{')
      end = text.rfind('}') + 1
      if start != -1 and end != 0:
        json.loads(text[start:end])
        return True
      return False
    except:
      return False

  def verify_json_from_clipboard(self, display) -> Tuple[bool, Any]:
    """
    Читает JSON из буфера обмена и верифицирует его с помощью verification_saved_json.
    Возвращает (success, data).
    Если JSON плохой - вопрос НЕ переключается.
    """
    try:
      # Читаем из буфера
      cmd = ["xclip", "-selection", "clipboard", "-o", "-display", display]
      clipboard_content = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()

      if not clipboard_content:
        print(f"[!] [Бот {self.bot_id}] Буфер обмена пуст")
        return False, None

      # Логируем первые 200 символов содержимого буфера
      preview = clipboard_content[:200].replace('\n', ' ')
      print(f"[*] [Бот {self.bot_id}] Буфер: {preview}...")

      # Сохраняем во временный файл для верификации
      with open(self.json_path, 'w', encoding='utf-8') as f:
        f.write(clipboard_content)

      # Верифицируем с использованием полного функционала
      if check_valid_json:
        success, data = check_valid_json(clipboard_content, self.bot_id)
        if success:
          print(f"[+] [Бот {self.bot_id}] JSON верифицирован успешно")
          norms_count = len(data.get("Norms", [])) if isinstance(data, dict) else 0
          print(f"[+] [Бот {self.bot_id}] Найдено норм: {norms_count}")
          return True, data
        else:
          print(f"[!] [Бот {self.bot_id}] JSON не прошёл верификацию")
          return False, None
      else:
        # Fallback: простая проверка
        success = self.is_json_valid(clipboard_content)
        if success:
          print(f"[+] [Бот {self.bot_id}] JSON валиден (fallback проверка)")
          return True, clipboard_content
        else:
          print(f"[!] [Бот {self.bot_id}] JSON невалиден (fallback проверка)")
          return False, None

    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка верификации JSON: {e}")
      return False, None


  def reset_scenario(self, bot):
    """
    Выполняет reset последовательность из конфига сайта.
    Пример: Ctrl+L → ввод URL → Enter → ожидание
    """
    print(f"[!] [Бот {self.bot_id}] Выполнение reset последовательности...")

    reset_config = self.site_config.get('home', {}).get('reset', {})
    sequence = reset_config.get('sequence', [])

    for step in sequence:
      step_type = step.get('type')

      if step_type == 'hotkey':
        keys = step.get('keys', [])
        key_combo = "+".join(keys)
        bot.action_queue.put(('hotkey', keys))
        print(f"  → Hotkey: {key_combo}")
        time.sleep(0.3)

      elif step_type == 'text':
        text = step.get('value', '')
        # Вводим текст целиком, но с задержкой для надёжности
        bot.action_queue.put(('type', text))
        # Ждём пока текст введётся (из расчёта ~10мс на символ + запас)
        wait_time = max(0.5, len(text) * 0.02)
        time.sleep(wait_time)
        print(f"  → Type: {text[:50]}...")

      elif step_type == 'key':
        key = step.get('key', '')
        bot.action_queue.put(('key', key))
        print(f"  → Key: {key}")
        time.sleep(0.5)  # Увеличенная пауза после нажатия клавиши

      elif step_type == 'wait':
        seconds = step.get('seconds', 1.0)
        print(f"  → Wait: {seconds}с")
        time.sleep(seconds)

    # Сброс состояния и таймера
    self.current_state = self.scenario['start_state']
    self.last_change = time.time()
    print(f"[+] [Бот {self.bot_id}] Reset завершён, возврат к '{self.current_state}'")

  def execute_step(self, bot, analyzer, frame):
    cur_state_config = self.scenario['states'][self.current_state]
    timeout = cur_state_config.get('timeout', 120)
    elapsed = time.time() - self.last_change

    # Проверка таймаута состояния
    if elapsed > timeout:
      print(f"[!] [Бот {self.bot_id}] Таймаут состояния '{self.current_state}' ({elapsed:.1f}с > {timeout}с)")
      # Выполняем reset последовательность в браузере
      self.reset_scenario(bot)
      return

    if not self.expected_complete:
      # Поиск визуального триггера
      print(f'Expect [{self.current_state}]')
      coords, _ = analyzer.find_best_match(
        frame,
        cur_state_config['expect']['templates'],
        cur_state_config['expect']['threshold']
      )

      if coords and not self.expected_complete:
        print(f'coords and not self.expected_complete: {coords}, {self.expected_complete:}')
        self.expected_complete = True
        # Сброс таймера при успешном нахождении триггера
        self.last_change = time.time()
        
        # ОЧИСТКА перед действием, если ожидаем проверку буфера
        if cur_state_config.get('condition', {}).get('json_valid'):
          bot.clear_clipboard()

        self._run_action(bot, cur_state_config['action'], coords)
        # time.sleep(cur_state_config.get('cooldown', 2.0))
    
    if self.expected_complete:
      print(f'self.expected_complete {self.expected_complete}')
      # time.sleep(2.0)

      success = False
      cond = cur_state_config.get('condition', {})

      # Проверка условий
      if 'templates' in cond:
        print('Condition')
        new_frame = bot.get_frame_umat()
        if new_frame is not None:
          hit, _ = analyzer.find_best_match(
            new_frame,
            cur_state_config['condition']['templates'],
            cur_state_config['condition'].get('threshold', 0.8)
          )
          success = hit is not None
          if hit is None:
            print('Condition not found')
            time.sleep(0.1)

      elif cond.get('json_valid'):
        # Полная верификация JSON из буфера
        success, verified_data = self.verify_json_from_clipboard(bot.display)
        if success:
          # JSON хорош - сохраняем ТЕКУЩИЙ вопрос
          bot.save_verified_json(verified_data)
          # Затем переходим к следующему вопросу
          advanced = bot.advance_question()
          if not advanced:
            # Достигнут последний вопрос - бот будет остановлен
            print(f"[+] [Бот {self.bot_id}] Все вопросы обработаны, бот будет остановлен")
            return
          # Выполняем reset последовательность браузера для нового вопроса
          self.reset_scenario(bot)
        else:
          # JSON плох - остаёмся на том же вопросе
          print(f"[!] [Бот {self.bot_id}] JSON плохой, вопрос будет задан повторно")
      else:
        success = True

      # Переход
      if time.time() - self.last_change > 2.0:
        print(time.time() - self.last_change)
        print('PEREHOD\n')
        next_state_key = 'success' if success else 'fail'
        self.current_state = cur_state_config['next'].get(next_state_key, self.scenario['start_state'])
        self.last_change = time.time()
        self.expected_complete = False

  def _run_action(self, bot, action, coords):
    x, y = int(coords[0]), int(coords[1])
    
    if action == "click":
      bot.action_queue.put(('click', (x, y)))
      
    elif action == "click_paste_enter":
      # Получаем отформатированный промпт (вопрос + JSON шаблон)
      prompt_text = bot.get_formatted_prompt()
      if prompt_text is None:
        print(f"[!] [Бот {self.bot_id}] Промпт не загружен, пропускаем действие")
        return
      
      print(f"[*] [Бот {self.bot_id}] Отправляем промпт (длина: {len(prompt_text)} символов)...")
      
      # Копируем промпт в буфер обмена конкретного бота
      try:
        cmd = ["xclip", "-selection", "clipboard", "-display", bot.display]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc.communicate(input=prompt_text.encode('utf-8'))
        proc.wait(timeout=2)
        print(f"[+] [Бот {self.bot_id}] Промпт скопирован в буфер")
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка копирования в буфер: {e}")
        return

      # Клик по полю ввода
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.5)
      
      # Вставка из буфера
      bot.action_queue.put(('hotkey', ['ctrl', 'v']))
      time.sleep(0.3)
      
      # Нажатие Enter
      bot.action_queue.put(('key', 'Return'))
      
    elif action == "click_copy_save_json_check":
      # Первый клик по кнопке копирования
      bot.action_queue.put(('click', (x, y)))
      time.sleep(1.0)  # Пауза 1 секунда между кликами
      # Второй клик по кнопке копирования
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.5)  # Ждём пока контент скопируется в буфер
      # Контент из кнопки копирования уже в буфере - не делаем Ctrl+A/Ctrl+C

    elif action == "click_ctrl_end":
      # Клик + переход в конец страницы (Ctrl+End)
      bot.action_queue.put(('click', (x, y - 30)))
      time.sleep(0.3)
      bot.action_queue.put(('hotkey', ['ctrl', 'End']))
      time.sleep(0.3)

    elif action == "click_scroll_down":
      # Клик + прокрутка вниз (Page Down)
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.3)
      bot.action_queue.put(('key', 'pagedown'))
      time.sleep(0.3)

    elif action == "scroll_up":
      # Прокрутка вверх (Page Up)
      bot.action_queue.put(('key', 'pageup'))
      time.sleep(0.3)
