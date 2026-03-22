import subprocess, os, time, shutil, threading, json, queue, re, sys
import numpy as np
import pandas as pd
import cv2
import mss
from queue import Queue
from datetime import datetime
from scripts.bot_logger import get_bot_logger

# Глобальный список для хранения потоков обновления VNC
vnc_refresh_threads = []

class VNCRefreshThread(threading.Thread):
  """
  Поток для периодического обновления экрана VNC.
  Решает проблему с пропаданием изображения в VNC.
  """
  def __init__(self, display, interval=2.0):
    super().__init__(daemon=True)
    self.display = display
    self.interval = interval
    self.stop_event = threading.Event()

  def run(self):
    env = os.environ.copy()
    env["DISPLAY"] = self.display
    while not self.stop_event.is_set():
      try:
        # Минимальное действие для обновления экрана
        subprocess.run(
          ["xdotool", "search", "--name", ".*"],
          env=env, capture_output=True, timeout=1
        )
      except:
        pass
      time.sleep(self.interval)

  def stop(self):
    self.stop_event.set()

class VirtualBotEnv:
  def __init__(self, bot_id, bot_cfg, width=960, height=800):
    # Параметры из конфига
    self.bot_id = bot_id
    self.project = bot_cfg.get('project', 'hypos_norm')
    self.subproject = bot_cfg.get('subproject', 'gen')
    self.site = bot_cfg.get('site', 'perplexity')
    self.mode = bot_cfg.get('mode', 'grok')
    self.model_name = bot_cfg.get('model', 'perplexity_grok')

    # Пути и системные параметры
    self.master_profile = os.path.expanduser(bot_cfg['browser_master_profile'])
    self.display = f":{100 + bot_id}"
    self.temp_profile = f"/tmp/bot_{self.project}_{self.bot_id}"

    # Область интереса (ROI) и рабочие зоны
    self.roi = bot_cfg.get('roi', [0, 0, 960, 800])
    self.cooldown = bot_cfg.get('cooldown', 1.0)
    # Интервал между вопросами (в секундах) - время от начала спрашивания предыдущего вопроса
    self.question_interval = bot_cfg.get('question_interval', 0.0)

    # Инициализация stop_event ДО загрузки вопросов (нужен для ранней установки)
    self.stop_event = threading.Event()
    self.action_queue = Queue()

    # Загрузка вопросов из CSV файла
    self.row_range = bot_cfg.get('row_range', [0, 1000000])
    # Общий лимит на количество вопросов (с учётом повторных попыток при битом JSON)
    self.max_questions = bot_cfg.get('max_questions', 100)
    # Задержка перед перезапуском бота после исчерпания лимита (в секундах)
    restart_delay_val = bot_cfg.get('restart_delay', 0)
    self.restart_delay = int(restart_delay_val) if restart_delay_val not in (None, 'None', '') else 0
    # Время последнего запуска бота
    self.last_start_time = None
    # Время планируемого перезапуска (last_start_time + restart_delay)
    self.next_restart_time = None
    # Глобальный счётчик всех попыток (включая повторные)
    self.total_question_count = 0
    # Время начала спрашивания последнего вопроса (для question_interval)
    self.last_question_start_time = None
    # Флаг ожидания завершения интервала между вопросами (неблокирующая версия)
    self.waiting_for_interval = False
    # Время, когда бот сможет возобновить работу после ожидания интервала
    self.interval_resume_time = None
    # Используем dataset_path из конфига или путь по умолчанию
    dataset_path = bot_cfg.get('dataset_path', 'datasets/sp_depers_final_with_hypnorm_used_marks.csv')
    # Преобразуем в абсолютный путь относительно проекта
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    self.dataset_path = os.path.join(base_dir, dataset_path)
    self.df_cols = bot_cfg.get('columns', ['uid', 'query', 'used'])
    self.questions, self.cur_global_idx = self._load_questions()

    # Находим последний верифицированный JSON и устанавливаем начальный индекс
    last_verified_idx = self._get_last_verified_question_index()
    if last_verified_idx is not None and self.questions is not None:
      # Начинаем со следующего вопроса после последнего верифицированного
      start_row, end_row = self.row_range
      next_idx = last_verified_idx + 1
      if next_idx <= end_row:
        self.cur_global_idx = next_idx
        print(f"[+] [Бот {self.bot_id}] Возобновление с вопроса #{self.cur_global_idx} (после верифицированного #{last_verified_idx})")
      else:
        print(f"[+] [Бот {self.bot_id}] Все вопросы в диапазоне верифицированы (последний: #{last_verified_idx})")
        # Помечаем бота как завершенный
        self.stop_event.set()
    else:
      print(f"[+] [Бот {self.bot_id}] Начальный cur_global_idx={self.cur_global_idx}")

    # Настройка логирования событий бота
    self.project = bot_cfg.get('project', 'unknown')
    self.site = bot_cfg.get('site', 'unknown')
    self.scenario = bot_cfg.get('scenario', 'unknown')
    
    # Initialize centralized logger with site and scenario for shared CSV logging
    self.logger = get_bot_logger(self.bot_id, self.project, self.site, self.scenario)

    # Расписание запуска бота
    self.schedule_start_immediately = bot_cfg.get('schedule', {}).get('start_immediately', False)
    self.schedule_times = self._parse_schedule_times(bot_cfg.get('schedule', {}).get('start_times', []))
    self.next_scheduled_time = self._get_next_scheduled_time()

    # Загрузка промптов
    self.prompt_text = None
    self.prompt_json = None
    self._load_prompts(base_dir, bot_cfg)

    # Размеры окна
    self.width = self.roi[2]
    self.height = self.roi[3]
    self.size = f"{self.width}x{self.height}x24"

    # Прокси из конфига
    self.proxy, self.proxy_auth = self._parse_proxy(bot_cfg.get('proxy'))

    # Сохраняем логин/пароль прокси
    self.proxy_login, self.proxy_password = self._extract_proxy_credentials(bot_cfg.get('proxy'))

    # Отладка: выводим информацию о прокси
    proxy_cfg = bot_cfg.get('proxy')
    # Маскируем пароль для безопасности
    proxy_display = self.proxy
    if self.proxy_login and self.proxy_password:
      proxy_display = f"http://{self.proxy_login}:***@{self.proxy.split('@')[-1] if '@' in self.proxy else self.proxy.split('://')[1]}"
    
    print(f"[+] [Бот {self.bot_id}] Конфигурация прокси:")
    print(f"    Исходный конфиг: {proxy_cfg}")
    print(f"    proxy_url: {proxy_display}")
    print(f"    proxy_login: {self.proxy_login}")
    print(f"    proxy_password: {'***' if self.proxy_password else None}")

    self.procs = {}

  def _parse_proxy(self, proxy_cfg):
    """
    Парсит конфигурацию прокси.
    Возвращает кортеж (proxy_url, auth_header) или (None, None) если прокси не используется.

    Поддерживаемые форматы:
    - [ip, port] -> ('http://ip:port', None)
    - [ip, port, login, password] -> ('http://login:password@ip:port', None)
    - 'ip:port' -> ('http://ip:port', None)
    - 'login:pass@ip:port' -> ('http://login:pass@ip:port', None)
    - 'none', 'false', False, None -> (None, None)
    """
    if proxy_cfg is None:
      return None, None

    # Проверка на отключенный прокси
    if isinstance(proxy_cfg, str):
      if proxy_cfg.lower() in ('none', 'false', ''):
        return None, None
      # Формат 'login:pass@ip:port'
      if '@' in proxy_cfg:
        return f'http://{proxy_cfg}', None
      # Формат 'ip:port'
      if ':' in proxy_cfg:
        return f'http://{proxy_cfg}', None

    # Список [ip, port] или [ip, port, login, password]
    if isinstance(proxy_cfg, list) and len(proxy_cfg) >= 2:
      ip, port = proxy_cfg[0], proxy_cfg[1]
      if len(proxy_cfg) >= 4:
        # Есть логин и пароль — встраиваем в URL
        login, password = proxy_cfg[2], proxy_cfg[3]
        return f'http://{login}:{password}@{ip}:{port}', None
      return f'http://{ip}:{port}', None

    return None, None

  def _extract_proxy_credentials(self, proxy_cfg):
    """
    Извлекает логин и пароль из конфигурации прокси.
    Возвращает кортеж (login, password) или (None, None) если нет авторизации.
    """
    if proxy_cfg is None:
      return None, None

    # Строковый формат 'login:pass@ip:port'
    if isinstance(proxy_cfg, str) and '@' in proxy_cfg:
      auth_part = proxy_cfg.rsplit('@', 1)[0]
      if ':' in auth_part:
        login, password = auth_part.split(':', 1)
        return login, password

    # Список [ip, port, login, password]
    if isinstance(proxy_cfg, list) and len(proxy_cfg) >= 4:
      return proxy_cfg[2], proxy_cfg[3]

    return None, None

  def _create_proxy_extension(self):
    """
    Создаёт временное расширение Chrome для автоматической прокси-аутентификации.
    Возвращает путь к директории расширения или None если не требуется.
    """
    if not self.proxy_login or not self.proxy_password:
      print(f"[!] [Бот {self.bot_id}] Пропускаем создание расширения: нет логина/пароля")
      return None

    print(f"[+] [Бот {self.bot_id}] Создание расширения прокси-аутентификации...")
    print(f"    Логин: '{self.proxy_login}'")
    print(f"    Пароль: '{self.proxy_password}'")

    import shutil

    # Пути
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_extension_dir = os.path.join(base_dir, 'proxy_extension')
    temp_extension_dir = os.path.join(self.temp_profile, 'proxy_extension')

    # Копируем расширение во временный профиль
    if os.path.exists(src_extension_dir):
      shutil.copytree(src_extension_dir, temp_extension_dir, dirs_exist_ok=True)

      # Заменяем логин/пароль в background.js
      background_js_path = os.path.join(temp_extension_dir, 'background.js')
      with open(background_js_path, 'r', encoding='utf-8') as f:
        content = f.read()

      content = content.replace('LOGIN_PLACEHOLDER', str(self.proxy_login))
      content = content.replace('PASSWORD_PLACEHOLDER', str(self.proxy_password))

      with open(background_js_path, 'w', encoding='utf-8') as f:
        f.write(content)

      print(f"[+] [Бот {self.bot_id}] Расширение прокси-аутентификации создано в {temp_extension_dir}")
      return temp_extension_dir

    print(f"[!] [Бот {self.bot_id}] Исходная директория расширения не найдена: {src_extension_dir}")
    return None

  def _parse_schedule_times(self, time_strings):
    """
    Парсит список времён запуска в формате 'HH:MM' или 'H:MM'.
    Пример: ['00:00', '6:00', '12:00', '18:00']
    Возвращает список кортежей (hour, minute).
    """
    parsed = []
    for time_str in time_strings:
      try:
        # Удаляем пробелы и разделяем по двоеточию
        time_str = time_str.strip()
        if ':' not in time_str:
          print(f"[!] [Бот {self.bot_id}] Неверный формат времени: '{time_str}' (ожидается HH:MM)")
          continue
        parts = time_str.split(':')
        hour = int(parts[0])
        minute = int(parts[1])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
          parsed.append((hour, minute))
        else:
          print(f"[!] [Бот {self.bot_id}] Некорректное время: '{time_str}' (часы: 0-23, минуты: 0-59)")
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка парсинга времени '{time_str}': {e}")
    return parsed

  def _setup_proxy_auth_cdp(self):
    """
    Настраивает аутентификацию прокси через Chrome DevTools Protocol.
    Отправляет заголовок Proxy-Authorization для всех запросов.
    """
    # Если нет авторизации - выходим сразу
    if not self.proxy_auth:
      return
    
    import json
    import requests
    import time

    # Находим CDP порт из процесса Chrome
    # Chrome автоматически открывает CDP на порту 9222 или случайном
    # Используем --remote-debugging-port=9222 в chrome_cmd

    cdp_url = "http://localhost:9222"
    
    # Ждём пока CDP порт станет доступен (максимум 10 секунд)
    for attempt in range(10):
      try:
        response = requests.get(f"{cdp_url}/json/list", timeout=2)
        if response.status_code == 200:
          break
      except:
        pass
      time.sleep(0.5)
    else:
      print(f"[!] [Бот {self.bot_id}] CDP порт не доступен после 10 попыток")
      return
    
    try:
      # Получаем список вкладок
      tabs = response.json()

      if tabs:
        # Берём первую вкладку
        ws_url = tabs[0].get('webSocketDebuggerUrl')

        if ws_url:
          # Отправляем команду CDP для установки заголовков
          import websocket
          ws = websocket.create_connection(ws_url, timeout=5)

          # Устанавливаем заголовки для всех запросов
          cmd = {
            "id": 1,
            "method": "Network.setExtraHTTPHeaders",
            "params": {
              "headers": {
                "Proxy-Authorization": self.proxy_auth
              }
            }
          }
          ws.send(json.dumps(cmd))
          ws.recv()  # Ждём ответ
          ws.close()

          print(f"[+] [Бот {self.bot_id}] Прокси-аутентификация настроена через CDP")
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Не удалось настроить прокси-аутентификацию CDP: {e}")

  def _get_next_scheduled_time(self):
    """
    Вычисляет следующее время запуска на основе расписания.
    Возвращает datetime следующего запуска или None, если расписание пустое.
    """
    if not self.schedule_times:
      return None

    now = datetime.now()
    next_time = None

    for hour, minute in self.schedule_times:
      scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
      # Если время сегодня уже прошло, планируем на завтра
      if scheduled <= now:
        from datetime import timedelta
        scheduled += timedelta(days=1)
      # Находим ближайшее будущее время
      if next_time is None or scheduled < next_time:
        next_time = scheduled

    return next_time

  def should_start_now(self):
    """
    Проверяет, должно ли произойти запланированное время запуска.
    Возвращает True, если:
    - Установлен флаг start_immediately
    - Или текущее время близко к запланированному (в пределах 60 секунд)
    """
    # Если установлен флаг start_immediately - запускаем сразу
    if self.schedule_start_immediately:
      print(f"[+] [Бот {self.bot_id}] Запуск по флагу start_immediately")
      self.schedule_start_immediately = False  # Сбрасываем флаг после использования
      # Обновляем следующее запланированное время для будущих запусков
      self.next_scheduled_time = self._get_next_scheduled_time()
      return True

    if not self.next_scheduled_time:
      return True  # Если расписания нет, разрешаем запуск

    now = datetime.now()
    time_diff = (self.next_scheduled_time - now).total_seconds()

    # Запускаем, если до запланированного времени осталось меньше минуты
    if 0 <= time_diff <= 60:
      print(f"[+] [Бот {self.bot_id}] Наступило время запуска (расписание)")
      # Обновляем следующее запланированное время
      self.next_scheduled_time = self._get_next_scheduled_time()
      return True

    return False

  def _load_prompts(self, base_dir, bot_cfg):
    """
    Загружает промпты из конфига для текущего бота.
    Промпты берутся из config_main.yaml -> prompts -> {model} -> {project} -> {subproject}
    """
    try:
      # Путь к основному конфигу
      cfg_main_path = os.path.join(base_dir, 'config_main.yaml')
      with open(cfg_main_path, 'r', encoding='utf-8') as f:
        import yaml
        cfg_main = yaml.safe_load(f)
      
      # Получаем пути к промптам из конфига
      prompts_config = cfg_main.get('prompts', {})
      model_prompts = prompts_config.get(self.model_name, {})
      project_prompts = model_prompts.get(self.project, {})
      subproject_prompts = project_prompts.get(self.subproject, {})
      
      if not subproject_prompts:
        print(f"[!] [Бот {self.bot_id}] Не найдены промпты для {self.model_name}/{self.project}/{self.subproject}")
        return
      
      # Загружаем текст промпта
      text_path = subproject_prompts.get('text')
      if text_path:
        full_text_path = os.path.join(base_dir, text_path)
        if os.path.exists(full_text_path):
          with open(full_text_path, 'r', encoding='utf-8') as f:
            self.prompt_text = f.read()
          print(f"[+] [Бот {self.bot_id}] Загружен текстовый промпт: {text_path}")
        else:
          print(f"[!] [Бот {self.bot_id}] Файл промпта не найден: {full_text_path}")
      
      # Загружаем JSON шаблон
      json_path = subproject_prompts.get('json')
      if json_path:
        full_json_path = os.path.join(base_dir, json_path)
        if os.path.exists(full_json_path):
          with open(full_json_path, 'r', encoding='utf-8') as f:
            self.prompt_json = f.read()
          print(f"[+] [Бот {self.bot_id}] Загружен JSON шаблон: {json_path}")
        else:
          print(f"[!] [Бот {self.bot_id}] Файл JSON шаблона не найден: {full_json_path}")
    
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка загрузки промптов: {e}")

  def get_formatted_prompt(self):
    """
    Возвращает отформатированный промпт с подставленным вопросом и JSON шаблоном.
    Заменяет {situation} на текст вопроса и {json} на JSON шаблон.
    """
    if self.prompt_text is None:
      print(f"[!] [Бот {self.bot_id}] Промпт не загружен")
      return None
    
    question_row = self.get_cur_question()
    if question_row is None:
      return None
    
    # Извлекаем текст вопроса (ситуацию)
    situation = str(question_row.get('query', question_row.iloc[1] if len(question_row) > 1 else ''))
    
    # JSON шаблон (если есть)
    json_template = self.prompt_json if self.prompt_json else '{}'
    
    # Форматируем промпт
    formatted = self.prompt_text.replace('{situation}', situation).replace('{json}', json_template)
    formatted = formatted + "\n\n" + formatted
    
    print(f"[+] [Бот {self.bot_id}] Промпт отформатирован для вопроса: {situation[:50]}...")
    return formatted

  def _get_last_verified_question_index(self):
    """
    Scans the answers directory for saved JSON files and finds the highest question index.
    Returns the index of the last verified JSON, or None if no files found.
    """
    try:
      base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
      answers_dir = os.path.join(base_dir, 'answers', self.model_name, self.project, self.subproject)
      
      if not os.path.exists(answers_dir):
        print(f"[*] [Бот {self.bot_id}] Директория ответов не найдена: {answers_dir}")
        return None
      
      # Pattern: {global_idx}_{uid}_{model_name}.json
      pattern = re.compile(r'^(\d+)_.*_' + re.escape(self.model_name) + r'\.json$')
      
      max_idx = None
      for filename in os.listdir(answers_dir):
        match = pattern.match(filename)
        if match:
          idx = int(match.group(1))
          # Check if this index is within our row_range
          start_row, end_row = self.row_range
          if start_row <= idx <= end_row:
            if max_idx is None or idx > max_idx:
              max_idx = idx
      
      if max_idx is not None:
        print(f"[+] [Бот {self.bot_id}] Найден последний верифицированный JSON для вопроса #{max_idx}")
      else:
        print(f"[*] [Бот {self.bot_id}] Верифицированные JSON не найдены в диапазоне {self.row_range}")
      
      return max_idx
    
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка поиска последнего верифицированного JSON: {e}")
      return None

  def _load_questions(self):
    """Загружает вопросы из файла в соответствии с row_range"""
    if not self.dataset_path or not os.path.exists(self.dataset_path):
      print(f"[!] [Бот {self.bot_id}] Файл с вопросами не найден: {self.dataset_path}")
      return None, None

    start_row, end_row = self.row_range
    print(f"[*] [Бот {self.bot_id}] Загрузка вопросов из {self.dataset_path}, вопросы {start_row}-{end_row}")
    try:
      # usecols принимает список имён колонок или их индексы
      # skiprows=range(1, start_row + 1) пропускает строки 1-start_row (вопросы 0-(start_row-1))
      # Начинаем чтение со строки start_row+1 (вопрос start_row)
      pdf = pd.read_csv(
        self.dataset_path,
        usecols=self.df_cols,
        skiprows=range(1, start_row + 1),
        nrows=end_row - start_row + 1
      )
      pdf.index = pdf.index + start_row
      print(f"[+] [Бот {self.bot_id}] Загружено {len(pdf)} вопросов, первый вопрос: {pdf.index[0]}")
      return pdf, start_row
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка загрузки вопросов: {e}")
      import traceback
      traceback.print_exc()
      return None, None
    
  def get_cur_question(self):
    """Returns current question as a Series with column names as keys"""
    if self.questions is None:
      print(f"[!] [Бот {self.bot_id}] Вопросы не загружены")
      return None
    
    # Проверяем, что индекс в пределах диапазона
    start_row, end_row = self.row_range
    if self.cur_global_idx < start_row or self.cur_global_idx > end_row:
      print(f"[!] [Бот {self.bot_id}] Индекс вопроса {self.cur_global_idx} вне диапазона [{start_row}-{end_row}]")
      return None
    
    return self.questions.loc[self.cur_global_idx]

  def get_cur_question_uid(self):
    """Returns the UID of the current question"""
    row = self.get_cur_question()
    if row is None:
      return None
    # Assuming 'uid' is the first column or named 'uid'
    if 'uid' in row.index:
      return row['uid']
    # Fallback: return first column value
    return row.iloc[0]

  def save_verified_json(self, json_data: dict):
    """
    Saves verified JSON to the appropriate folder using:
    - answers/{model_name}/{project}/{subproject}/ for folder structure
    - global_idx and uid for the filename
    """
    try:
      # Create directory path: answers/{model_name}/{project}/{subproject}/
      base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
      save_dir = os.path.join(base_dir, 'answers', self.model_name, self.project, self.subproject)
      os.makedirs(save_dir, exist_ok=True)

      # Get question UID and global index
      uid = self.get_cur_question_uid()
      if uid is None:
        print(f"[!] [Бот {self.bot_id}] Не удалось получить UID вопроса")
        return None

      global_idx = self.cur_global_idx
      print(f"[*] [Бот {self.bot_id}] Сохранение JSON: cur_global_idx={global_idx}, uid={uid}")

      # Create filename: {global_idx}_{uid}_{model_name}.json
      filename = f"{global_idx}_{uid}_{self.model_name}.json"
      filepath = os.path.join(save_dir, filename)

      # Save JSON
      with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

      print(f"[+] [Бот {self.bot_id}] JSON сохранён: {filepath}")
      print(f"[+] [Бот {self.bot_id}] Вопрос #{global_idx}, UID: {uid}")
      return filepath

    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка сохранения JSON: {e}")
      return None

  def is_last_question(self):
    """Проверяет, является ли текущий вопрос последним в диапазоне"""
    if self.questions is None:
      return False
    start_row, end_row = self.row_range
    return self.cur_global_idx >= end_row

  def all_questions_answered(self):
    """
    Проверяет, все ли вопросы в диапазоне имеют верифицированные JSON файлы.
    Возвращает True если все вопросы отвечены, False иначе.
    """
    start_row, end_row = self.row_range
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    answers_dir = os.path.join(base_dir, 'answers', self.model_name, self.project, self.subproject)
    
    if not os.path.exists(answers_dir):
      print(f"[*] [Бот {self.bot_id}] Директория ответов не найдена: {answers_dir}")
      return False
    
    # Pattern: {global_idx}_{uid}_{model_name}.json
    pattern = re.compile(r'^(\d+)_.*_' + re.escape(self.model_name) + r'\.json$')
    
    # Собираем все найденные индексы в диапазоне
    answered_indices = set()
    for filename in os.listdir(answers_dir):
      match = pattern.match(filename)
      if match:
        idx = int(match.group(1))
        if start_row <= idx <= end_row:
          answered_indices.add(idx)
    
    # Проверяем, все ли индексы в диапазоне покрыты
    total_questions = end_row - start_row + 1
    answered_count = len(answered_indices)
    
    if answered_count >= total_questions:
      print(f"[+] [Бот {self.bot_id}] Все вопросы в диапазоне ({total_questions}) верифицированы")
      return True
    else:
      missing = total_questions - answered_count
      print(f"[*] [Бот {self.bot_id}] Отвечено {answered_count}/{total_questions} вопросов, осталось {missing}")
      return False

  def advance_question(self):
    """Advances to the next question index"""
    if self.questions is not None:
      start_row, end_row = self.row_range
      self.cur_global_idx += 1
      # Проверка достижения последнего вопроса
      if self.cur_global_idx > end_row:
        print(f"[+] [Бот {self.bot_id}] Достигнут последний вопрос (индекс {end_row}). Остановка.")
        self.stop_event.set()  # Сигнал остановки для executor
        return False  # Возвращаем False для индикации завершения
      print(f"[+] [Бот {self.bot_id}] Вопрос изменён на индекс {self.cur_global_idx}")
      return True

  def increment_question_count(self):
    """
    Increments the global question counter.
    Returns True if limit not exceeded, False if max_questions reached.
    Called each time a question is asked (including retries).
    """
    self.total_question_count += 1
    if self.total_question_count > self.max_questions:
      print(f"[!] [Бот {self.bot_id}] Превышен общий лимит вопросов ({self.max_questions}). Всего задано: {self.total_question_count}. Остановка.")
      self.stop_event.set()
      return False
    # Получаем UID текущего вопроса для логирования
    uid = self.get_cur_question_uid()
    self.log_question_attempt(self.cur_global_idx, uid)
    print(f"[*] [Бот {self.bot_id}] Вопрос #{self.total_question_count}/{self.max_questions} (текущий индекс: {self.cur_global_idx})")
    return True

  def check_question_limit(self):
    """
    Check if question limit is reached before asking a question.
    Returns True if can continue, False if should stop.
    """
    if self.total_question_count >= self.max_questions:
      print(f"[!] [Бот {self.bot_id}] Лимит вопросов ({self.max_questions}) исчерпан. Остановка.")
      self.stop_event.set()
      return False
    return True

  def _clear_cache(self, profile_path):
    trash_dirs = [
      'Cache', 'Code Cache', 'GPUCache', 'ShaderCache',
      'GrShaderCache', 'Media Cache', 'WebSession'
    ]
    for root, dirs, files in os.walk(profile_path):
      for d in list(dirs):
        if d in trash_dirs:
          try: shutil.rmtree(os.path.join(root, d), ignore_errors=True)
          except: pass

  def log_start(self):
    """Logs bot start event with timestamp and current question index"""
    self.last_start_time = datetime.now()
    uid = self.get_cur_question_uid()
    self.logger.info("BOT_START", {
      "bot_id": self.bot_id,
      "question_idx": self.cur_global_idx,
      "total_questions": self.total_question_count,
      "uid": uid
    })
    # Log to CSV (both per-bot and shared scenario+site)
    self.logger.log_csv_operation("START", global_index=self.cur_global_idx, question_uid=uid)

  def log_question_attempt(self, question_idx: int, question_uid: str = None):
    """
    Logs each question attempt with timestamp.
    Called every time a question is asked (including retries).
    """
    self.logger.info("QUESTION_ATTEMPT", {
      "attempt": self.total_question_count,
      "max_questions": self.max_questions,
      "question_idx": question_idx,
      "uid": question_uid
    })
    # Log to CSV
    self.logger.log_csv_operation("QUESTION", global_index=question_idx, question_uid=question_uid)

  def log_question_sent(self, question_idx: int, question_uid: str = None):
    """
    Logs when a question is actually sent to the AI service.
    Called after click_paste_enter action completes.
    """
    self.logger.info("QUESTION_SENT", {
      "question_idx": question_idx,
      "uid": question_uid
    })
    # Log to CSV (also logged in bot_logic.py)

  def log_limit_exhausted(self):
    """Logs when the bot exhausts its question limit"""
    self.logger.info("LIMIT_EXHAUSTED", {
      "total_questions": self.total_question_count,
      "max_questions": self.max_questions,
      "restart_delay": self.restart_delay
    })
    # Log to CSV
    self.logger.log_csv_operation("LIMIT_EXHAUSTED")

  def log_restart(self):
    """Logs bot restart event and calculates next restart time"""
    self.last_start_time = datetime.now()
    uid = self.get_cur_question_uid()

    # Вычисляем время следующего перезапуска
    if self.restart_delay > 0:
      from datetime import timedelta
      self.next_restart_time = self.last_start_time + timedelta(seconds=self.restart_delay)
      self.logger.info("RESTART", {
        "bot_id": self.bot_id,
        "next_restart": self.next_restart_time.strftime('%H:%M:%S'),
        "restart_delay": self.restart_delay
      })
    else:
      self.logger.info("RESTART", {
        "bot_id": self.bot_id,
        "note": "first_start"
      })
    
    # Log to CSV
    self.logger.log_csv_operation("RESTART", global_index=self.cur_global_idx, question_uid=uid)

  def log_stop(self):
    """Logs bot stop event"""
    uid = self.get_cur_question_uid()
    self.logger.info("BOT_STOP", {
      "bot_id": self.bot_id,
      "total_questions": self.total_question_count
    })
    # Log to CSV
    self.logger.log_csv_operation("STOP", global_index=self.cur_global_idx, question_uid=uid)

  def _clear_cache(self, profile_path):
    trash_dirs = [
      'Cache', 'Code Cache', 'GPUCache', 'ShaderCache', 
      'GrShaderCache', 'Media Cache', 'WebSession'
    ]
    for root, dirs, files in os.walk(profile_path):
      for d in list(dirs):
        if d in trash_dirs:
          try: shutil.rmtree(os.path.join(root, d), ignore_errors=True)
          except: pass

  def _prepare_profile(self):
    if os.path.exists(self.temp_profile):
      shutil.rmtree(self.temp_profile, ignore_errors=True)
    
    self._clear_cache(self.master_profile)
    shutil.copytree(self.master_profile, self.temp_profile)
    
    for lock in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
      lock_path = os.path.join(self.temp_profile, lock)
      if os.path.exists(lock_path):
        try: os.remove(lock_path)
        except: pass

  def start(self, url):
    self._prepare_profile()
    print(f"[*] [Бот {self.bot_id}] Запуск на {self.display}...")

    # Получаем базовую директорию проекта
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Проверяем и убиваем старые процессы на этом дисплее
    try:
      # Находим PID Xvfb на этом дисплее
      result = subprocess.run(["pgrep", "-f", f"Xvfb {self.display}"], capture_output=True, text=True, timeout=1)
      if result.stdout.strip():
        old_pid = result.stdout.strip()
        print(f"[!] [Бот {self.bot_id}] Найден старый Xvfb (PID: {old_pid}), убиваем...")
        subprocess.run(["kill", old_pid], capture_output=True)
        time.sleep(0.5)
      
      # Находим PID fluxbox на этом дисплее
      env = os.environ.copy()
      env["DISPLAY"] = self.display
      result = subprocess.run(["pgrep", "-f", "fluxbox"], capture_output=True, text=True, timeout=1)
      if result.stdout.strip():
        # Проверяем, относится ли этот fluxbox к нашему дисплею
        print(f"[!] [Бот {self.bot_id}] Найден fluxbox (PID: {result.stdout.strip()}), убиваем...")
        for pid in result.stdout.strip().split():
          subprocess.run(["kill", pid], capture_output=True)
        time.sleep(0.5)
      
      # Убиваем x11vnc на нашем порту
      vnc_port = 5900 + self.bot_id
      result = subprocess.run(["fuser", "-k", f"{vnc_port}/tcp"], capture_output=True, timeout=1)
      time.sleep(0.5)
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка очистки старых процессов: {e}")

    self.procs['xvfb'] = subprocess.Popen(
      ["Xvfb", self.display, "-screen", "0", self.size, "-ac"],
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    
    # Ждём пока Xvfb полностью запустится и проверим что он работает
    xvfb_started = False
    for _ in range(10):  # Максимум 5 секунд (10 * 0.5с)
      time.sleep(0.5)
      if self.procs['xvfb'].poll() is None:
        # Проверяем, что дисплей доступен
        try:
          result = subprocess.run(
            ["xdpyinfo", "-display", self.display],
            capture_output=True, timeout=1
          )
          if result.returncode == 0:
            xvfb_started = True
            print(f"[+] [Бот {self.bot_id}] Xvfb запущен на {self.display}")
            break
        except:
          pass
      else:
        print(f"[!] [Бот {self.bot_id}] Xvfb процесс завершился unexpectedly")
        break
    
    if not xvfb_started:
      print(f"[!] [Бот {self.bot_id}] Не удалось запустить Xvfb на {self.display}")
      return

    env = os.environ.copy()
    env["DISPLAY"] = self.display

    self.procs['wm'] = subprocess.Popen(
      ["fluxbox"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    # Ждём пока fluxbox полностью запустится
    time.sleep(2)

    vnc_port = 5900 + self.bot_id
    
    # Проверяем, что порт свободен
    try:
      result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=1)
      if str(vnc_port) in result.stdout:
        print(f"[!] [Бот {self.bot_id}] Порт {vnc_port} уже занят, пытаемся освободить...")
        # Пытаемся найти и убить процесс на этом порту
        subprocess.run(["fuser", "-k", f"{vnc_port}/tcp"], capture_output=True)
        time.sleep(1)
    except:
      pass

    # Пробуем запустить x11vnc с минимальными опциями
    max_attempts = 3
    for attempt in range(max_attempts):
      # Создаём временный лог файл для отладки
      vnc_log = f"/tmp/bot_{self.bot_id}_x11vnc_attempt_{attempt}.log"
      
      # Простые опции для максимальной совместимости
      self.procs['vnc'] = subprocess.Popen([
        "x11vnc",
        "-display", self.display,
        "-rfbport", str(vnc_port),
        "-nopw",
        "-forever",
        "-shared",
        "-nowf",
        "-noxdamage"
      ], stdout=open(vnc_log, 'w'), stderr=subprocess.STDOUT)

      # Проверяем, что процесс жив
      time.sleep(2)
      if self.procs['vnc'].poll() is None:
        # Проверяем что порт слушается
        try:
          result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=1)
          if str(vnc_port) in result.stdout:
            print(f"[+] [Бот {self.bot_id}] x11vnc запущен на порту {vnc_port}")
            break
        except:
          pass
        print(f"[+] [Бот {self.bot_id}] x11vnc запущен (порт не проверен)")
        break
      else:
        # Процесс умер, читаем лог
        try:
          with open(vnc_log, 'r') as f:
            log_content = f.read()
          print(f"[!] [Бот {self.bot_id}] x11vnc не запустился (попытка {attempt + 1}/{max_attempts})")
          # Показываем последние строки лога
          lines = log_content.split('\n')
          for line in lines[-10:]:
            if line.strip():
              print(f"    {line}")
        except:
          pass
        if attempt < max_attempts - 1:
          time.sleep(2)
    else:
      print(f"[!] [Бот {self.bot_id}] Не удалось запустить x11vnc после {max_attempts} попыток")

    # Формируем команду Chrome с условным прокси
    chrome_cmd = [
      "/usr/bin/chromium",
      f"--display={self.display}",
      f"--user-data-dir={self.temp_profile}",
      f"--window-position=0,0",
      f"--window-size=960,800",
      f"--force-device-scale-factor=1",
      "--remote-debugging-port=9222",
    ]

    # Добавляем прокси если указан
    if self.proxy:
      # Извлекаем чистый IP:port без креденшалов для Chrome
      pure_proxy = self.proxy.split('://')[1].split('@')[1] if '://' in self.proxy else self.proxy.split('@')[1] if '@' in self.proxy else self.proxy
      
      # Используем прямой прокси - браузер покажет окно аутентификации
      chrome_cmd.append(f"--proxy-server={pure_proxy}")
      print(f"[*] [Бот {self.bot_id}] Используется прокси: {pure_proxy} (браузер запросит логин/пароль)")
    else:
      print(f"[*] [Бот {self.bot_id}] Прокси не используется")
    
    chrome_cmd.extend([
      "--no-sandbox",
      "--disable-gpu",
      "--disable-software-rasterizer",
      "--disable-dev-shm-usage",
      #"--blink-settings=imagesEnabled=false",
      "--disable-notifications",
      "--mute-audio",
      "--limit-fps=5",
      "--disable-blink-features=AutomationControlled",
      # Отключаем диалог прокси-аутентификации
      "--disable-prompt-on-repost",
      "--autoplay-policy=user-gesture-required",
      f"--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      url
    ])

    self.procs['browser'] = subprocess.Popen(chrome_cmd, env=env)

    # Настраиваем аутентификацию прокси через CDP если требуется
    # ОТКЛЮЧЕНО: CDP не работает надёжно для прокси-аутентификации
    # if self.proxy_auth:
    #   self._setup_proxy_auth_cdp()
    
    print(f"[+] [Бот {self.bot_id}] Готов. VNC: localhost:{vnc_port}")

    # Запускаем поток для обновления VNC (чтобы изображение не пропадало)
    self.vnc_refresh = VNCRefreshThread(self.display, interval=2.0)
    self.vnc_refresh.start()
    vnc_refresh_threads.append(self.vnc_refresh)

    # Логирование запуска бота
    self.log_restart()  # Логируем как рестарт (или первый запуск)
    
    threading.Thread(target=self._executor, daemon=True).start()
    # time.sleep(1000)

  def get_frame_umat(self):
    os.environ["DISPLAY"] = self.display
    with mss.mss() as sct:
      # print(os.environ["DISPLAY"])
      # print(sct.monitors)
      try:
        # А) Захват экрана (напрямую через Shared Memory)
        sct_img = sct.grab(sct.monitors[1])

        # Б) Перенос данных в VRAM (единственная тяжелая операция для шины)
        img_umat = cv2.UMat(np.array(sct_img))
        
        # В) Конвертация в серый НА GPU
        # Т.к. img_umat — это UMat, cvtColor вернет тоже UMat
        gray = cv2.cvtColor(img_umat, cv2.COLOR_BGRA2GRAY)
        gray = cv2.Canny(gray, 50, 150)
        time.sleep(0.2)
        return gray
      
      except Exception as e:
        print(f"Ошибка на {self.display}: {e}")
        return None


    # cmd = [
    #   "ffmpeg", "-f", "x11grab", "-video_size", self.size, 
    #   "-i", self.display, "-vframes", "1", "-f", "image2pipe", 
    #   "-vcodec", "bmp", "-"
    # ]
    # try:
    #   proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    #   raw, _ = proc.communicate(timeout=1)
    #   if raw:
    #     return cv2.UMat(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR))
    #   return None
    # except:
    #   return None

  def _executor(self):
    env = {"DISPLAY": self.display}
    action_count = 0
    last_display_check = time.time()
    
    while not self.stop_event.is_set():
      try:
        # Проверяем доступность дисплея каждые 30 секунд
        if time.time() - last_display_check > 30:
          result = subprocess.run(
            ["xdotool", "search", "--name", ".*"],
            env=env, capture_output=True, text=True, timeout=2
          )
          if result.returncode != 0 and "Failed" in result.stderr:
            print(f"[!] [Бот {self.bot_id}] Дисплей {self.display} недоступен: {result.stderr}")
          last_display_check = time.time()
        
        t_type, val = self.action_queue.get(timeout=1)
        action_count += 1
        
        # Проверка на валидность данных
        if t_type is None or val is None:
          print(f"[!] [Бот {self.bot_id}] Получены None в action_queue (action #{action_count})")
          continue
        
        # Отладочное логирование каждого 10-го действия
        if action_count % 10 == 0:
          print(f"[*] [Бот {self.bot_id}] Обработано {action_count} действий, последнее: {t_type}")
        
        if t_type == 'click':
          if not isinstance(val, (list, tuple)) or len(val) != 2:
            print(f"[!] [Бот {self.bot_id}] Неверный формат click: {val}")
            continue
          result = subprocess.run(
            ["xdotool", "mousemove", str(val[0]), str(val[1]), "click", "1"],
            env=env, capture_output=True, text=True
          )
          if result.returncode != 0:
            print(f"[!] [Бот {self.bot_id}] xdotool click error: {result.stderr}")

        elif t_type == 'mousemove':
          if not isinstance(val, (list, tuple)) or len(val) != 2:
            print(f"[!] [Бот {self.bot_id}] Неверный формат mousemove: {val}")
            continue
          result = subprocess.run(
            ["xdotool", "mousemove", str(val[0]), str(val[1])],
            env=env, capture_output=True, text=True
          )
          if result.returncode != 0:
            print(f"[!] [Бот {self.bot_id}] xdotool click error: {result.stderr}")

        elif t_type == 'key':
          # xdotool использует Return вместо enter
          key_name = 'Return' if val.lower() == 'enter' else val
          result = subprocess.run(
            ["xdotool", "key", "--clearmodifiers", key_name],
            env=env, capture_output=True, text=True
          )
          if result.returncode != 0:
            print(f"[!] [Бот {self.bot_id}] xdotool key '{key_name}' error: {result.stderr}")
          else:
            print(f"[+] [Бот {self.bot_id}] xdotool key '{key_name}' executed successfully")
            
        elif t_type == 'hotkey':
          # Формируем комбинацию клавиш в формате xdotool: ctrl+v
          key_combo = "+".join(val)
          result = subprocess.run(
            ["xdotool", "key", "--clearmodifiers", key_combo],
            env=env, capture_output=True, text=True
          )
          if result.returncode != 0:
            print(f"[!] [Бот {self.bot_id}] xdotool hotkey '{key_combo}' error: {result.stderr}")
            
        elif t_type == 'type':
          result = subprocess.run(
            ["xdotool", "type", "--clearmodifiers", val],
            env=env, capture_output=True, text=True
          )
          if result.returncode != 0:
            print(f"[!] [Бот {self.bot_id}] xdotool type error: {result.stderr}")
            
        self.action_queue.task_done()
        
      except queue.Empty:
        # Нормальное поведение - очередь пуста, продолжаем ждать
        continue
        
      except Exception as e:
        print(f"[!] [Бот {self.bot_id}] Ошибка executor: {e}")
        import traceback
        traceback.print_exc()
        continue
      
  def clear_clipboard(self):
    """Полная очистка буфера обмена на конкретном дисплее"""
    try:
      # Записываем пустоту в буфер через xclip
      subprocess.run(
        ["xclip", "-selection", "clipboard", "-display", self.display, "/dev/null"],
        stderr=subprocess.DEVNULL,
        timeout=1
      )
    except:
      pass

  def stop(self):
    print(f"[*] [Бот {self.bot_id}] Выключение...")
    # Логирование остановки
    self.log_stop()
    self.stop_event.set()

    # Останавливаем поток обновления VNC
    if hasattr(self, 'vnc_refresh'):
      self.vnc_refresh.stop()

    # Завершаем все процессы бота
    for proc_name, p in self.procs.items():
      if p:
        try:
          p.terminate()
          try:
            p.wait(timeout=3)  # Ждём до 3 секунд
          except subprocess.TimeoutExpired:
            p.kill()  # Принудительно убиваем если не завершился
            p.wait(timeout=1)
        except Exception as e:
          print(f"[!] [Бот {self.bot_id}] Остановка {proc_name}: {e}")

    # Дополнительная очистка - убиваем процессы по PID если они ещё живы
    time.sleep(1)
    try:
      # Находим и убиваем Xvfb на нашем дисплее
      result = subprocess.run(["pgrep", "-f", f"Xvfb {self.display}"], capture_output=True, text=True, timeout=1)
      if result.stdout.strip():
        for pid in result.stdout.strip().split():
          print(f"[!] [Бот {self.bot_id}] Убиваем старый Xvfb (PID: {pid})")
          subprocess.run(["kill", "-9", pid], capture_output=True)
      
      # Находим и убиваем fluxbox на нашем дисплее
      result = subprocess.run(["pgrep", "-f", "fluxbox"], capture_output=True, text=True, timeout=1)
      if result.stdout.strip():
        for pid in result.stdout.strip().split():
          print(f"[!] [Бот {self.bot_id}] Убиваем fluxbox (PID: {pid})")
          subprocess.run(["kill", "-9", pid], capture_output=True)
      
      # Освобождаем VNC порт
      vnc_port = 5900 + self.bot_id
      subprocess.run(["fuser", "-k", f"{vnc_port}/tcp"], capture_output=True, timeout=2)
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка дополнительной очистки: {e}")

    # Очищаем временный профиль
    try:
      if os.path.exists(self.temp_profile):
        shutil.rmtree(self.temp_profile, ignore_errors=True)
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка очистки профиля: {e}")
