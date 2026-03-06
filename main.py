import time, yaml, os
from typing import Dict, List, Any
import cv2
from scripts.env_bot import VirtualBotEnv
from scripts.gpu_analyzer import GPUAnalyzer
from scripts.bot_logic import FSM

def load_config(path: str) -> Dict[str, Any]:
  if not os.path.exists(path):
    raise FileNotFoundError(f"Config file not found: {path}")
  
  with open(path, "r", encoding="utf-8") as f:
    return yaml.safe_load(f)

def main():
  base_dir = os.path.dirname(os.path.abspath(__file__))
  cfg_main_path = os.path.join(base_dir, "config_main.yaml")
  cfg_bots_path = os.path.join(base_dir, "config_bots.yaml")

  try:
    cfg_main = load_config(cfg_main_path)
    cfg_bots = load_config(cfg_bots_path)
  except Exception as e:
    print(f"Failed to load config: {e}")
    return

  bots_count = int(cfg_main.get("global", {}).get("bots_count", 0))
  
  analyzer = GPUAnalyzer()
  bots, logics = [], []
  
  for i in range(bots_count):
    bot_key = f'bot_{i}'
    if bot_key not in cfg_bots:
      continue

    bot_cfg = cfg_bots[bot_key]
      
    # Инициализация окружения (ID и конфиг конкретного бота)
    bot = VirtualBotEnv(i, bot_cfg)
    site_name = bot_cfg['site']
    bot.start(cfg_main['sites'][site_name]['url'])
    bots.append(bot)
    
    # Инициализация логики (конфиг из основного файла для Perplexity)
    logics.append(FSM(i, cfg_main, bot_cfg))
    time.sleep(1.0)

  try:
    while True:
      for bot, fsm in zip(bots, logics):
        # time.sleep(0.1)
        print(f"Global frame")
        frame = bot.get_frame_umat()
        # cv2.imwrite(f'_frame.png', frame)
        if frame is not None:
          fsm.execute_step(bot, analyzer, frame)
      # time.sleep(0.1)
  except KeyboardInterrupt:
    print("\n[*] Завершение работы...")
    for b in bots:
      b.stop()

if __name__ == "__main__":
  main()

