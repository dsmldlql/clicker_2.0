import time, json, subprocess, re, os
from typing import Tuple, Any, Dict
from scripts.bot_logger import get_bot_logger
from scripts.state_logger import StateLogger

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
    scenario_name = bot_config['scenario']
    self.scenario = cfg_main['sites'][site]['scenarios'][scenario_name]
    self.site_config = cfg_main['sites'][site]
    self.current_state = self.scenario['start_state']
    self.expected_complete = False

    self.last_change = time.time()
    self.json_path = f"/tmp/bot_{bot_id}_response.json"

    # Интервал между вопросами (в секундах)
    self.question_interval = bot_config.get('question_interval', 0.0)

    # Initialize logger with site and scenario for shared CSV logging
    self.project = bot_config.get('project', 'unknown')
    self.site = site
    self.scenario_name = scenario_name
    self.logger = get_bot_logger(bot_id, self.project, self.site, self.scenario_name)
    
    # Initialize state logger for detailed timing
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', f'bot_{bot_id}')
    self.state_logger = StateLogger(bot_id, site, scenario_name, log_dir)

    self.logger.info("FSM_INITIALIZED", {
      "site": self.site,
      "scenario": self.scenario_name,
      "start_state": self.current_state
    })
    
    # Log initial state
    self.state_logger.enter_state(self.current_state)


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
    
    Args:
      bot: Экземпляр бота
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
    previous_state = self.current_state
    self.current_state = self.scenario['start_state']
    self.last_change = time.time()
    
    # Логируем переход в start_state после reset
    self.state_logger.enter_state(self.current_state, from_state=previous_state)

    # Дополнительная задержка на загрузку страницы после reset
    time.sleep(2.0)

    print(f"[+] [Бот {self.bot_id}] Reset завершён, возврат к '{self.current_state}'")

  def execute_step(self, bot, analyzer, frame):
    cur_state_config = self.scenario['states'][self.current_state]
    timeout = cur_state_config.get('timeout', 120)
    elapsed = time.time() - self.last_change

    # Проверка таймаута состояния
    if elapsed > timeout:
      print(f"[!] [Бот {self.bot_id}] Таймаут состояния '{self.current_state}' ({elapsed:.1f}с > {timeout}с)")
      # Логируем таймаут
      self.state_logger.log_timeout(timeout)
      
      # Переход на fail state
      fail_state = cur_state_config['next'].get('fail', self.scenario['start_state'])
      next_state = fail_state
      self.state_logger.exit_state(success=False, next_state=next_state, reason='timeout')
      
      self.current_state = fail_state
      self.last_change = time.time()
      self.expected_complete = False
      # Сбрасываем флаг защиты от повторного выполнения
      if hasattr(self, '_paste_enter_executed'):
          del self._paste_enter_executed
      return

    # Проверка интервала между вопросами - ждём если интервал ещё не прошёл
    if self.question_interval > 0 and bot.last_question_start_time is not None:
      time_since_last_question = time.time() - bot.last_question_start_time
      if time_since_last_question < self.question_interval:
        remaining = self.question_interval - time_since_last_question
        # Показываем сообщение только один раз при первом входе в это состояние
        if not hasattr(self, '_waiting_interval_shown'):
          self._waiting_interval_shown = True
          print(f"[*] [Бот {self.bot_id}] Ожидание интервала между вопросами: {remaining:.1f}с (интервал: {self.question_interval}с)")
        return
      else:
        # Интервал прошёл - сбрасываем флаг
        self._waiting_interval_shown = False

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
        # Логируем нахождение триггера
        self.state_logger.mark_trigger_found()
        
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
      time.sleep(1.0)  # Даём время на обновление экрана перед проверкой условия

      success = False
      cond = cur_state_config.get('condition', {})

      # Проверка условий
      if 'templates' in cond:
        print(f'Condition: checking templates {cond["templates"]}')
        # Отмечаем начало проверки условия
        self.state_logger.mark_condition_start()
        
        new_frame = bot.get_frame_umat()
        if new_frame is not None:
          hit, score = analyzer.find_best_match(
            new_frame,
            cur_state_config['condition']['templates'],
            cur_state_config['condition'].get('threshold', 0.8)
          )
          success = hit is not None
          if hit is None:
            print(f'Condition not found (best score: {score})')
          else:
            print(f'Condition found with score: {score}')
        else:
          print('Condition: frame is None')
        
        # Логируем результат проверки
        self.state_logger.mark_condition_result(success, condition_type='templates')

      elif cond.get('json_valid'):
        # ОДНА попытка верификации JSON из буфера
        success = False
        verified_data = None
        
        # Отмечаем начало проверки условия
        self.state_logger.mark_condition_start()

        print(f"[+] [Бот {self.bot_id}] Верификация JSON...")
        
        # Читаем из буфера
        try:
          cmd = ["xclip", "-selection", "clipboard", "-o", "-display", bot.display]
          clipboard_content = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
        except Exception as e:
          clipboard_content = ""
          print(f"[!] [Бот {self.bot_id}] Ошибка чтения буфера: {e}")
        
        if not clipboard_content:
          print(f"[!] [Бот {self.bot_id}] Буфер пуст")
        else:
          print(f"[+] [Бот {self.bot_id}] Буфер содержит {len(clipboard_content)} символов, верифицируем...")
          
          # Верифицируем с использованием полного функционала
          if check_valid_json:
            success, verified_data = check_valid_json(clipboard_content, self.bot_id)
            if success:
              print(f"[+] [Бот {self.bot_id}] JSON верифицирован успешно")
              norms_count = len(verified_data.get("Norms", [])) if isinstance(verified_data, dict) else 0
              print(f"[+] [Бот {self.bot_id}] Найдено норм: {norms_count}")
            else:
              print(f"[!] [Бот {self.bot_id}] JSON не прошёл верификацию")
              
              # Пробуем восстановить JSON через json_repair
              try:
                import sys
                sys.path.insert(0, '/home/dmitrii/Documents/projects/clicker_2.0/venv/lib/python3.10/site-packages')
                import json_repair
                repaired = json_repair.repair_json(clipboard_content)
                if repaired:
                  print(f"[+] [Бот {self.bot_id}] JSON восстановлен через json_repair, проверяем...")
                  success, verified_data = check_valid_json(repaired, self.bot_id)
                  if success:
                    print(f"[+] [Бот {self.bot_id}] Восстановленный JSON верифицирован!")
                  else:
                    print(f"[!] [Бот {self.bot_id}] Восстановленный JSON всё ещё невалиден")
                else:
                  print(f"[!] [Бот {self.bot_id}] json_repair не помог")
              except ImportError:
                print(f"[!] [Бот {self.bot_id}] json_repair не найден")
              except Exception as e:
                print(f"[!] [Бот {self.bot_id}] Ошибка json_repair: {e}")
          else:
            # Fallback: простая проверка
            success = self.is_json_valid(clipboard_content)
            verified_data = clipboard_content if success else None

        # Get question info for CSV logging
        uid = bot.get_cur_question_uid()
        global_idx = bot.cur_global_idx

        if success and verified_data:
          # Сбрасываем флаг ожидания ПЕРЕД всеми операциями
          self.expected_complete = False
          
          # Log to CSV: JSON verified successfully
          self.logger.log_csv_operation("JSON_VERIFIED", global_index=global_idx, question_uid=uid)

          # Увеличиваем глобальный счётчик вопросов (и логируем попытку)
          if not bot.increment_question_count():
            # Лимит исчерпан - логируем и останавливаем бота
            bot.log_limit_exhausted()
            return
          # JSON хорош - сохраняем ТЕКУЩИЙ вопрос
          bot.save_verified_json(verified_data)

          # Log to CSV: JSON saved
          self.logger.log_csv_operation("JSON_SAVED", global_index=global_idx, question_uid=uid)

          # Очищаем буфер после сохранения
          bot.clear_clipboard()
          print(f"[+] [Бот {self.bot_id}] Буфер очищен после сохранения JSON")

          # Переходим к СЛЕДУЮЩЕМУ вопросу (увеличиваем индекс)
          advanced = bot.advance_question()
          if not advanced:
            # Достигнут последний вопрос - бот будет остановлен
            print(f"[+] [Бот {self.bot_id}] Все вопросы обработаны, бот будет остановлен")
            return

          # Log to CSV: question advanced
          new_uid = bot.get_cur_question_uid()
          new_global_idx = bot.cur_global_idx
          self.logger.log_csv_operation("QUESTION_ADVANCE", global_index=new_global_idx, question_uid=new_uid)

          # Проверяем, не достигнут ли лимит вопросов перед продолжением
          if not bot.check_question_limit():
            bot.log_limit_exhausted()
            return

          # Выполняем reset последовательность браузера для НОВОГО вопроса
          # reset_scenario сам устанавливает current_state в start_state и логирует переход
          self.reset_scenario(bot)
          # Возвращаем, чтобы не переходить в другое состояние
          return

        else:
          # Log to CSV: JSON verification failed
          self.logger.log_csv_operation("JSON_VERIFY_FAILED", global_index=global_idx, question_uid=uid)

          # JSON плохой - НЕ увеличиваем cur_global_idx, вопрос остаётся тот же!
          # Увеличиваем только счётчик попыток (total_question_count)
          if not bot.increment_question_count():
            # Лимит исчерпан при повторной попытке - логируем и останавливаем
            bot.log_limit_exhausted()
            return

          # Вопрос будет задан ПОВТОРНО (cur_global_idx не изменился!)
          print(f"[!] [Бот {self.bot_id}] JSON плохой, вопрос будет задан повторно (попытка #{bot.total_question_count}, индекс: {bot.cur_global_idx})")

          # Сбрасываем флаг ожидания
          self.expected_complete = False

          # Очищаем буфер после неудачной верификации
          bot.clear_clipboard()
          print(f"[+] [Бот {self.bot_id}] Буфер очищен после неудачной верификации")

          # Проверяем, не достигнут ли лимит перед повторной попыткой
          if not bot.check_question_limit():
            bot.log_limit_exhausted()
            return

          # НЕ делаем reset_scenario здесь - пусть FSM перейдёт в состояние try_again
          # как указано в конфиге (fail: try_again)
          # reset_scenario будет вызван только при переходе в start_question
          success = False  # Устанавливаем fail для перехода в try_again
      else:
        success = True
        # Для условий без явной проверки (always success)
        if not hasattr(self, '_condition_logged'):
          self.state_logger.mark_condition_start()
          self.state_logger.mark_condition_result(True, condition_type='always')
          self._condition_logged = True

      # Переход
      if time.time() - self.last_change > 2.0:
        print(time.time() - self.last_change)
        print('PEREHOD\n')
        next_state_key = 'success' if success else 'fail'
        next_state = cur_state_config['next'].get(next_state_key, self.scenario['start_state'])
        
        # Логируем выход из состояния и переход
        self.state_logger.exit_state(success=success, next_state=next_state, reason='normal')

        # Если следующее состояние - start_question, делаем reset браузера
        if next_state == 'start_question':
          print(f"[*] [Бот {self.bot_id}] Переход в start_question - выполняем reset браузера")
          # reset_scenario сам логирует переход в start_state
          self.reset_scenario(bot)
        else:
          prev_state = self.current_state
          self.current_state = next_state
          # Логируем вход в новое состояние
          self.state_logger.enter_state(self.current_state, from_state=prev_state)

        self.last_change = time.time()
        self.expected_complete = False
        # Сбрасываем флаг защиты от повторного выполнения
        if hasattr(self, '_paste_enter_executed'):
            del self._paste_enter_executed
        # Сбрасываем флаг логирования условия
        if hasattr(self, '_condition_logged'):
            del self._condition_logged

  def _run_action(self, bot, action, coords):
    x, y = int(coords[0]), int(coords[1])
    
    if action == "click":
      bot.action_queue.put(('click', (x, y)))
    
    elif action == "mousemove":
      bot.action_queue.put(('mousemove', (x, y)))
      
    elif action == "click_paste_enter":
      # Защита от повторного выполнения
      if hasattr(self, '_paste_enter_executed'):
        print(f"[+] [Бот {self.bot_id}] click_paste_enter уже выполнен, пропускаем")
        return

      # Получаем отформатированный промпт (вопрос + JSON шаблон)
      prompt_text = bot.get_formatted_prompt()
      if prompt_text is None:
        print(f"[!] [Бот {self.bot_id}] Промпт не загружен, пропускаем действие")
        return

      # Get question info for CSV logging
      uid = bot.get_cur_question_uid()
      global_idx = bot.cur_global_idx

      print(f"[*] [Бот {self.bot_id}] Отправляем промпт (длина: {len(prompt_text)} символов)...")

      # Log to CSV: question being sent
      self.logger.log_csv_operation("QUESTION_SENT", global_index=global_idx, question_uid=uid)

      # Запоминаем время начала спрашивания вопроса
      bot.last_question_start_time = time.time()

      # Очищаем буфер обмена перед копированием нового промпта
      bot.clear_clipboard()
      time.sleep(0.2)

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
      time.sleep(1.0)  # Увеличенная пауза после клика

      # Вставка из буфера
      try:
        # Вставляем текст через ctrl+v
        bot.action_queue.put(('hotkey', ['ctrl', 'v']))
        time.sleep(1.0)  # Увеличенная пауза для вставки

        print(f"[+] [Бот {self.bot_id}] Текст вставлен")
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка вставки: {e}")

      # Нажатие Enter
      bot.action_queue.put(('key', 'Return'))
      time.sleep(0.5)  # Пауза после Enter

      # Логируем факт задавания вопроса
      bot.log_question_sent(bot.cur_global_idx, uid)
      
      # Очищаем буфер после вставки
      bot.clear_clipboard()
      print(f"[+] [Бот {self.bot_id}] Буфер очищен после вставки")
      
      # Устанавливаем флаг, что действие выполнено
      self._paste_enter_executed = True

    elif action == "click_paste_file_enter":
      # Защита от повторного выполнения
      if hasattr(self, '_paste_enter_executed'):
        print(f"[+] [Бот {self.bot_id}] click_paste_file_enter уже выполнен, пропускаем")
        return

      # Получаем путь к файлу из конфигурации состояния
      current_state_config = self.scenario['states'].get(self.current_state, {})
      file_path = current_state_config.get('file')

      if not file_path:
        print(f"[!] [Бот {self.bot_id}] Не указан параметр 'file' для click_paste_file_enter")
        return

      # Читаем текст из файла
      try:
        with open(file_path, 'r', encoding='utf-8') as f:
          file_content = f.read()
        print(f"[+] [Бот {self.bot_id}] Текст прочитан из файла {file_path} ({len(file_content)} символов)")
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка чтения файла {file_path}: {e}")
        return

      # Get question info for CSV logging
      uid = bot.get_cur_question_uid()
      global_idx = bot.cur_global_idx

      print(f"[*] [Бот {self.bot_id}] Отправляем текст из файла (длина: {len(file_content)} символов)...")

      # Log to CSV: question being sent
      self.logger.log_csv_operation("QUESTION_SENT", global_index=global_idx, question_uid=uid)

      # Запоминаем время начала спрашивания вопроса
      bot.last_question_start_time = time.time()

      # Очищаем буфер обмена перед копированием
      bot.clear_clipboard()
      time.sleep(0.2)

      # Копируем содержимое файла в буфер обмена конкретного бота
      try:
        cmd = ["xclip", "-selection", "clipboard", "-display", bot.display]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc.communicate(input=file_content.encode('utf-8'))
        proc.wait(timeout=2)
        print(f"[+] [Бот {self.bot_id}] Текст из файла скопирован в буфер")
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка копирования в буфер: {e}")
        return

      # Клик по полю ввода
      bot.action_queue.put(('click', (x, y)))
      time.sleep(1.0)  # Увеличенная пауза после клика

      # Вставка из буфера
      try:
        # Вставляем текст через ctrl+v
        bot.action_queue.put(('hotkey', ['ctrl', 'v']))
        time.sleep(1.0)  # Увеличенная пауза для вставки

        print(f"[+] [Бот {self.bot_id}] Текст вставлен")
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка вставки: {e}")

      # Нажатие Enter
      bot.action_queue.put(('key', 'Return'))
      time.sleep(0.5)  # Пауза после Enter

      # Логируем факт задавания вопроса
      bot.log_question_sent(bot.cur_global_idx, uid)

      # Очищаем буфер после вставки
      bot.clear_clipboard()
      print(f"[+] [Бот {self.bot_id}] Буфер очищен после вставки")

      # Устанавливаем флаг, что действие выполнено
      self._paste_enter_executed = True

    elif action == "click_copy_save_json_check":
      # Сохраняем координаты кнопки копирования
      self.copy_button_coords = (x, y)
      
      # ОДНА попытка копирования
      print(f"[+] [Бот {self.bot_id}] Копирование ответа...")
      
      # Первый клик по кнопке копирования
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.5)
      # Второй клик по кнопке копирования (для надёжности)
      bot.action_queue.put(('click', (x, y)))
      time.sleep(1.0)  # Ждём пока контент скопируется в буфер
      
      # Проверяем, что в буфере что-то есть
      try:
        cmd = ["xclip", "-selection", "clipboard", "-o", "-display", bot.display]
        clipboard_content = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
        
        if clipboard_content:
          print(f"[+] [Бот {self.bot_id}] Буфер содержит данные ({len(clipboard_content)} символов)")
        else:
          print(f"[!] [Бот {self.bot_id}] Буфер пуст после копирования")
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка чтения буфера: {e}")

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

  def print_state_stats(self):
    """Выводит статистику состояний в консоль"""
    if hasattr(self, 'state_logger'):
      self.state_logger.print_stats()

  def get_state_stats(self) -> Dict[str, Any]:
    """Возвращает статистику состояний"""
    if hasattr(self, 'state_logger'):
      return self.state_logger.get_stats_summary()
    return {}
