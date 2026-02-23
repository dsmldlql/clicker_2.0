import time, json, subprocess

class PerplexityFSM:
  def __init__(self, bot_id, config):
    self.bot_id = bot_id
    self.config = config['scenarios']['grok']
    self.current_state = self.config['start_state']
    self.last_change = time.time()

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

  def execute_step(self, bot, analyzer, frame):
    cfg = self.config['states'][self.current_state]
    
    # Сброс по таймауту
    if time.time() - self.last_change > cfg.get('timeout', 120):
      self.current_state = self.config['start_state']
      self.last_change = time.time()
      return

    # Поиск визуального триггера
    coords, _ = analyzer.find_best_match(frame, cfg['expect']['templates'], cfg['expect']['threshold'])
    
    if coords:
      # ОЧИСТКА перед действием, если ожидаем проверку буфера
      if cfg.get('condition', {}).get('json_valid'):
        bot.clear_clipboard()
        
      self._run_action(bot, cfg['action'], coords)
      time.sleep(cfg.get('cooldown', 2.0))
      
      success = False
      cond = cfg.get('condition', {})
      
      # Проверка условий
      if 'templates' in cond:
        new_frame = bot.get_frame_umat()
        if new_frame is not None:
          hit, _ = analyzer.find_best_match(new_frame, cond['templates'], cond.get('threshold', 0.8))
          success = hit is not None
          
      elif cond.get('json_valid'):
        # Читаем буфер после паузы
        clipboard_content = self.get_clipboard(bot.display)
        success = self.is_json_valid(clipboard_content)
      else:
        success = True

      # Переход
      self.current_state = cfg['next']['success' if success else 'fail']
      self.last_change = time.time()

  def _run_action(self, bot, action, coords):
    x, y = int(coords[0]), int(coords[1])
    
    if action == "click":
      bot.action_queue.put(('click', (x, y)))
      
    elif action == "click_paste_enter":
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.5)
      bot.action_queue.put(('hotkey', ['ctrl', 'v']))
      time.sleep(0.2)
      bot.action_queue.put(('key', 'Return'))
      
    elif action == "click_copy_save_json_check":
      bot.action_queue.put(('click', (x, y)))
      time.sleep(0.5)
      bot.action_queue.put(('hotkey', ['ctrl', 'a']))
      time.sleep(0.2)
      bot.action_queue.put(('hotkey', ['ctrl', 'c']))
