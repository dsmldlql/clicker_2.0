import subprocess, os, time, shutil, threading, numpy as np, cv2
from queue import Queue

class VirtualBotEnv:
  def __init__(self, bot_id, bot_cfg, width=600, height=800):
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
    self.roi = bot_cfg.get('roi', [0, 0, 500, 620])
    self.row_range = bot_cfg.get('row_range', [0, 1000000])
    self.cooldown = bot_cfg.get('cooldown', 1.0)
    
    # Размеры окна
    self.width = self.roi[2]
    self.height = self.roi[3]
    self.size = f"{self.width}x{self.height}x24"
    
    self.procs = {}
    self.action_queue = Queue()
    self.stop_event = threading.Event()

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

  def get_frame_umat(self):
    cmd = [
      "ffmpeg", "-f", "x11grab", "-video_size", self.size, 
      "-i", self.display, "-vframes", "1", "-f", "image2pipe", 
      "-vcodec", "bmp", "-"
    ]
    try:
      proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
      raw, _ = proc.communicate(timeout=1)
      if raw:
        return cv2.UMat(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR))
      return None
    except:
      return None

  def _executor(self):
    env = {"DISPLAY": self.display}
    while not self.stop_event.is_set():
      try:
        t_type, val = self.action_queue.get(timeout=1)
        if t_type == 'click':
          subprocess.run(["xdotool", "mousemove", str(val[0]), str(val[1]), "click", "1"], env=env)
        elif t_type == 'key':
          subprocess.run(["xdotool", "key", val], env=env)
        elif t_type == 'hotkey':
          subprocess.run(["xdotool", "key", "--clearmodifiers"] + val, env=env)
        elif t_type == 'type':
          subprocess.run(["xdotool", "type", val], env=env)
        self.action_queue.task_done()
      except:
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
