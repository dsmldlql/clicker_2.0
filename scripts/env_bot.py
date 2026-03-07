import subprocess, os, time, shutil, threading, json, queue
import numpy as np
import pandas as pd
import cv2
import mss
from queue import Queue

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

    # Загрузка вопросов из CSV файла
    self.row_range = bot_cfg.get('row_range', [0, 1000000])
    # Используем dataset_path из конфига или путь по умолчанию
    dataset_path = bot_cfg.get('dataset_path', 'datasets/sp_depers_final_with_hypnorm_used_marks.csv')
    # Преобразуем в абсолютный путь относительно проекта
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    self.dataset_path = os.path.join(base_dir, dataset_path)
    self.df_cols = bot_cfg.get('columns', ['uid', 'query', 'used'])
    self.questions, self.cur_global_idx = self._load_questions()
    print(f"[+] [Бот {self.bot_id}] Начальный cur_global_idx={self.cur_global_idx}")

    # Загрузка промптов
    self.prompt_text = None
    self.prompt_json = None
    self._load_prompts(base_dir, bot_cfg)
    
    # Размеры окна
    self.width = self.roi[2]
    self.height = self.roi[3]
    self.size = f"{self.width}x{self.height}x24"
    
    self.procs = {}
    self.action_queue = Queue()
    self.stop_event = threading.Event()

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

    self.procs['xvfb'] = subprocess.Popen(
      ["Xvfb", self.display, "-screen", "0", self.size, "-ac"],
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1)

    env = os.environ.copy()
    env["DISPLAY"] = self.display

    self.procs['wm'] = subprocess.Popen(
      ["fluxbox"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    vnc_port = 5900 + self.bot_id
    self.procs['vnc'] = subprocess.Popen([
      "x11vnc", "-display", self.display, "-rfbport", str(vnc_port), 
      "-nopw", "-forever", "-shared"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    chrome_cmd = [
      "/usr/bin/chromium",
      f"--display={self.display}",
      f"--user-data-dir={self.temp_profile}",

      f"--window-position=0,0",
      f"--window-size=960,800",
      f"--force-device-scale-factor=1",
      # f"--high-dpi-support=1",e

      "--no-sandbox",
      "--disable-gpu",
      "--disable-software-rasterizer",
      "--disable-dev-shm-usage",
      "--blink-settings=imagesEnabled=false",
      "--disable-notifications",
      "--mute-audio",
      "--limit-fps=5", # Увеличено до 5 для стабильности интерфейса
      "--disable-blink-features=AutomationControlled",
      f"--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      url
    ]
    
    self.procs['browser'] = subprocess.Popen(chrome_cmd, env=env)
    print(f"[+] [Бот {self.bot_id}] Готов. VNC: localhost:{vnc_port}")
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
    self.stop_event.set()
    for p in self.procs.values():
      if p:
        try: p.terminate()
        except: pass
