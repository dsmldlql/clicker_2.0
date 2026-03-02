import time, json, subprocess, re, os
from typing import Tuple, Any, Dict
from scripts.bot_logger import get_bot_logger

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
    
    # Initialize logger
    self.project = bot_config.get('project', 'unknown')
    self.logger = get_bot_logger(bot_id, self.project)

    site = bot_config['site']
    scenario = bot_config['scenario']
    self.scenario = cfg_main['sites'][site]['scenarios'][scenario]
    self.site_config = cfg_main['sites'][site]
    self.current_state = self.scenario['start_state']

    self.last_change = time.time()
    self.json_path = f"/tmp/bot_{bot_id}_response.json"
    
    self.logger.info("FSM_INITIALIZED", {
      "site": site,
      "scenario": scenario,
      "start_state": self.current_state
    })


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
        self.logger.log_clipboard("READ", False, "")
        return False, None

      # Логируем первые 200 символов содержимого буфера
      preview = clipboard_content[:200].replace('\n', ' ')
      self.logger.log_clipboard("READ", True, preview)

      # Сохраняем во временный файл для верификации
      with open(self.json_path, 'w', encoding='utf-8') as f:
        f.write(clipboard_content)

      # Верифицируем с использованием полного функционала
      if check_valid_json:
        success, data = check_valid_json(clipboard_content, self.bot_id)
        if success:
          norms_count = len(data.get("Norms", [])) if isinstance(data, dict) else 0
          self.logger.log_verification("JSON", True, {
            "norms_count": norms_count,
            "clipboard_preview": preview
          })
          return True, data
        else:
          self.logger.log_verification("JSON", False, {"clipboard_preview": preview})
          return False, None
      else:
        # Fallback: простая проверка
        success = self.is_json_valid(clipboard_content)
        if success:
          self.logger.log_verification("JSON_FALLBACK", True, {"clipboard_preview": preview})
          return True, clipboard_content
        else:
          self.logger.log_verification("JSON_FALLBACK", False, {"clipboard_preview": preview})
          return False, None

    except Exception as e:
      self.logger.error("JSON_VERIFICATION_ERROR", str(e))
      return False, None


  def reset_scenario(self, bot):
    """
    Выполняет reset последовательность из конфига сайта.
    Пример: Ctrl+L → ввод URL → Enter → ожидание
    """
    self.logger.log_reset("State timeout or manual reset")
    self.logger.info("RESET_SEQUENCE_START", {"current_state": self.current_state})

    reset_config = self.site_config.get('home', {}).get('reset', {})
    sequence = reset_config.get('sequence', [])
    steps_executed = []

    for step in sequence:
      step_type = step.get('type')

      if step_type == 'hotkey':
        keys = step.get('keys', [])
        key_combo = "+".join(keys)
        bot.action_queue.put(('hotkey', keys))
        steps_executed.append(f"hotkey:{key_combo}")
        time.sleep(0.3)

      elif step_type == 'text':
        text = step.get('value', '')
        # Вводим текст целиком, но с задержкой для надёжности
        bot.action_queue.put(('type', text))
        # Ждём пока текст введётся (из расчёта ~10мс на символ + запас)
        wait_time = max(0.5, len(text) * 0.02)
        time.sleep(wait_time)
        steps_executed.append(f"type:{text[:30]}...")

      elif step_type == 'key':
        key = step.get('key', '')
        bot.action_queue.put(('key', key))
        steps_executed.append(f"key:{key}")
        time.sleep(0.5)  # Увеличенная пауза после нажатия клавиши

      elif step_type == 'wait':
        seconds = step.get('seconds', 1.0)
        steps_executed.append(f"wait:{seconds}s")
        time.sleep(seconds)

    # Сброс состояния и таймера
    old_state = self.current_state
    self.current_state = self.scenario['start_state']
    self.last_change = time.time()
    self.logger.log_reset("Reset sequence completed")
    self.logger.info("RESET_SEQUENCE_COMPLETE", {
      "old_state": old_state,
      "new_state": self.current_state,
      "steps": steps_executed
    })

  def execute_step(self, bot, analyzer, frame):
    start_time = time.time()
    cur_state_config = self.scenario['states'][self.current_state]
    timeout = cur_state_config.get('timeout', 120)
    elapsed = time.time() - self.last_change
    
    # Log state entry
    self.logger.state_enter(self.current_state, {
      "elapsed": round(elapsed, 1),
      "timeout": timeout
    })

    # Проверка таймаута состояния
    if elapsed > timeout:
      self.logger.log_timeout(self.current_state, elapsed, timeout)
      # Выполняем reset последовательность в браузере
      self.reset_scenario(bot)
      return

    # Поиск визуального триггера
    self.logger.debug("STATE_EXPECT", {"state": self.current_state})
    coords, match_score = analyzer.find_best_match(
      frame,
      cur_state_config['expect']['templates'],
      cur_state_config['expect']['threshold']
    )

    if coords:
      # Сброс таймера при успешном нахождении триггера
      self.last_change = time.time()
      self.logger.log_verification("TEMPLATE_MATCH", True, {
        "state": self.current_state,
        "coords": coords,
        "score": match_score
      })

      # ОЧИСТКА перед действием, если ожидаем проверку буфера
      if cur_state_config.get('condition', {}).get('json_valid'):
        bot.clear_clipboard()
        self.logger.log_clipboard("CLEAR", True)

      self._run_action(bot, cur_state_config['action'], coords)
      # time.sleep(cur_state_config.get('cooldown', 2.0))

      time.sleep(2.0)

      success = False
      cond = cur_state_config.get('condition', {})

      # Проверка условий
      if 'templates' in cond:
        new_frame = bot.get_frame_umat()
        if new_frame is not None:
          hit, _ = analyzer.find_best_match(
            new_frame,
            cur_state_config['condition']['templates'],
            cur_state_config['condition'].get('threshold', 0.8)
          )
          success = hit is not None
          self.logger.log_verification("CONDITION_TEMPLATE", success, {
            "state": self.current_state
          })
          if not success:
            self.logger.warning("CONDITION_NOT_MET", "Template condition not found", {
              "state": self.current_state
            })
            time.sleep(10.0)

      elif cond.get('json_valid'):
        # Полная верификация JSON из буфера
        success, verified_data = self.verify_json_from_clipboard(bot.display)
        if success:
          # JSON хорош - сохраняем ТЕКУЩИЙ вопрос
          bot.save_verified_json(verified_data)
          # Затем переходим к следующему вопросу
          bot.advance_question()
          # Выполняем reset последовательность браузера для нового вопроса
          self.reset_scenario(bot)
        else:
          # JSON плох - остаёмся на том же вопросе
          self.logger.warning("JSON_INVALID", "JSON плохой, вопрос будет задан повторно")
      else:
        success = True

      # Переход
      old_state = self.current_state
      next_state_key = 'success' if success else 'fail'
      self.current_state = cur_state_config['next'].get(next_state_key, self.scenario['start_state'])
      self.last_change = time.time()
      
      # Log state transition
      self.logger.state_exit(old_state, success, {
        "next_state": self.current_state,
        "transition": next_state_key,
        "duration_ms": round((time.time() - start_time) * 1000, 2)
      })

  def _run_action(self, bot, action, coords):
    x, y = int(coords[0]), int(coords[1])
    action_start = time.time()

    if action == "click":
      bot.action_queue.put(('click', (x, y)))
      self.logger.action("CLICK", {"coords": (x, y)})

    elif action == "click_paste_enter":
      # Получаем отформатированный промпт (вопрос + JSON шаблон)
      prompt_text = bot.get_formatted_prompt()
      if prompt_text is None:
        self.logger.action_failed("CLICK_PASTE_ENTER", "Промпт не загружен")
        return

      self.logger.info("PROMPT_SEND_START", {
        "length": len(prompt_text),
        "coords": (x, y)
      })

      # Копируем промпт в буфер обмена конкретного бота
      try:
        cmd = ["xclip", "-selection", "clipboard", "-display", bot.display]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc.communicate(input=prompt_text.encode('utf-8'))
        proc.wait(timeout=2)
        self.logger.log_clipboard("WRITE_PROMPT", True, f"Prompt: {len(prompt_text)} chars")
      except Exception as e:
        self.logger.log_clipboard("WRITE_PROMPT", False, str(e))
        return

      # Клик по полю ввода
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.5)

      # Вставка из буфера
      bot.action_queue.put(('hotkey', ['ctrl', 'v']))
      time.sleep(0.3)

      # Нажатие Enter
      bot.action_queue.put(('key', 'Return'))
      self.logger.action("CLICK_PASTE_ENTER", {
        "coords": (x, y),
        "prompt_length": len(prompt_text)
      })

    elif action == "click_copy_save_json_check":
      # Первый клик по кнопке копирования
      bot.action_queue.put(('click', (x, y)))
      time.sleep(1.0)  # Пауза 1 секунда между кликами
      # Второй клик по кнопке копирования
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.5)  # Ждём пока контент скопируется в буфер
      self.logger.action("CLICK_COPY_SAVE_JSON_CHECK", {"coords": (x, y)})

    elif action == "click_ctrl_end":
      # Клик + переход в конец страницы (Ctrl+End)
      bot.action_queue.put(('click', (x, y - 30)))
      time.sleep(0.3)
      bot.action_queue.put(('hotkey', ['ctrl', 'End']))
      time.sleep(0.3)
      self.logger.action("CLICK_CTRL_END", {"coords": (x, y - 30)})

    elif action == "click_scroll_down":
      # Клик + прокрутка вниз (Page Down)
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.3)
      bot.action_queue.put(('key', 'pagedown'))
      time.sleep(0.3)
      self.logger.action("CLICK_SCROLL_DOWN", {"coords": (x, y)})

    elif action == "scroll_up":
      # Прокрутка вверх (Page Up)
      bot.action_queue.put(('key', 'pageup'))
      time.sleep(0.3)
      self.logger.action("SCROLL_UP", {})
    
    # Log action duration
    duration_ms = (time.time() - action_start) * 1000
    self.logger.debug("ACTION_COMPLETED", {"action": action, "duration_ms": round(duration_ms, 2)})
