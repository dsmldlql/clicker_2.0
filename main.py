import time, yaml, os
from typing import Dict, List, Any
import cv2
from scripts.env_bot import VirtualBotEnv
from scripts.gpu_analyzer import GPUAnalyzer
from scripts.bot_logic import FSM
from scripts.vnc_monitor import VNCHealthMonitor
from datetime import datetime

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
  bot_configs = []  # Сохраняем конфигурации ботов для перезапуска
  bot_stop_times = {}  # Флаг что бот остановлен и ждёт перезапуска
  bot_scheduled = {}  # Флаг что бот ожидает запланированного запуска
  
  # Инициализация монитора VNC
  vnc_monitor = VNCHealthMonitor(bot_count=bots_count, check_interval=30.0)

  for i in range(bots_count):
    bot_key = f'bot_{i}'
    if bot_key not in cfg_bots:
      continue

    bot_cfg = cfg_bots[bot_key]
    bot_configs.append((i, bot_cfg))  # Сохраняем для возможного перезапуска

    # Инициализация окружения (ID и конфиг конкретного бота)
    bot = VirtualBotEnv(i, bot_cfg)

    # Проверяем, все ли вопросы уже верифицированы
    if bot.stop_event.is_set():
      print(f"[+] Бот {i} все вопросы верифицированы. Бот не запущен.")
      bots.append(None)
      logics.append(None)
      continue

    # Проверяем расписание запуска
    has_schedule = bool(bot.next_scheduled_time)
    start_immediately = bot.schedule_start_immediately

    if has_schedule and not start_immediately:
      print(f"[*] Бот {i} ожидает запланированного запуска в {bot.next_scheduled_time.strftime('%H:%M:%S')}")
      bot_scheduled[i] = True
      bots.append(bot)
      logics.append(None)  # FSM создадим при запуске
      continue

    site_name = bot_cfg['site']
    bot.start(cfg_main['sites'][site_name]['url'])
    bots.append(bot)

    # Инициализация логики (конфиг из основного файла)
    logics.append(FSM(i, cfg_main, bot_cfg))

    # Даём браузеру время на загрузку страницы
    time.sleep(3.0)

  # Запускаем монитор VNC после инициализации всех ботов
  vnc_monitor.start()
  print("[+] VNC Monitor: Активирован")

  try:
    while True:
      current_time = time.time()

      # Шаг 0.5: Проверяем падение Xvfb и перезапускаем ботов немедленно
      for bot_idx in range(bots_count):
        bot = bots[bot_idx] if bot_idx < len(bots) else None
        if bot is None:
          continue
        if vnc_monitor.is_xvfb_failed(bot_idx):
          print(f"[!] VNC Monitor: Бот {bot_idx} - Xvfb упал! Требуется немедленный перезапуск...")
          
          # Останавливаем текущего бота
          bot.stop()
          time.sleep(2)
          
          # Очищаем флаг Xvfb failure
          vnc_monitor.clear_xvfb_failed(bot_idx)
          
          # Создаём нового бота (это перезапустит Xvfb)
          bot_cfg = bot_configs[bot_idx][1]
          new_bot = VirtualBotEnv(bot_idx, bot_cfg)
          
          # Проверяем, все ли вопросы отвечены
          if new_bot.all_questions_answered():
            print(f"[+] Бот {bot_idx} все вопросы верифицированы. Перезапуск отменён.")
            new_bot.stop()
            bots[bot_idx] = None
            logics[bot_idx] = None
            continue
          
          site_name = bot_cfg['site']
          new_bot.start(cfg_main['sites'][site_name]['url'])
          bots[bot_idx] = new_bot
          
          # Создаём новую FSM
          new_fsm = FSM(bot_idx, cfg_main, bot_cfg)
          logics[bot_idx] = new_fsm
          
          # Сбрасываем флаг для сообщений
          if bot_idx in bot_stop_times:
              del bot_stop_times[bot_idx]
          
          print(f"[+] Бот {bot_idx} перезапущен после падения Xvfb")

      # Шаг 0: Проверяем запланированные запуски ботов
      for bot_idx, bot in enumerate(bots):
        if bot is None:
          continue
        if bot_idx in bot_scheduled and bot_scheduled[bot_idx]:
          # Проверяем, наступило ли время запуска
          if bot.should_start_now():
            print(f"[*] Запуск бота {bot_idx} по расписанию...")
            site_name = cfg_bots[f'bot_{bot_idx}']['site']
            bot.start(cfg_main['sites'][site_name]['url'])
            logics[bot_idx] = FSM(bot_idx, cfg_main, cfg_bots[f'bot_{bot_idx}'])
            bot_scheduled[bot_idx] = False
            print(f"[+] Бот {bot_idx} запущен по расписанию")

      # Шаг 1: Обрабатываем остановленные боты (перезапуск или завершение)
      for bot_idx, (bot, fsm) in enumerate(zip(bots, logics)):
        # Пропускаем уже удалённые боты (завершившие все вопросы)
        if bot is None:
          continue

        if bot.stop_event.is_set():
          # Бот остановлен, проверяем, нужно ли его перезапустить
          bot_cfg = bot_configs[bot_idx][1]
          restart_delay = bot_cfg.get('restart_delay', 0)

          # Проверяем, все ли вопросы верифицированы
          if bot.all_questions_answered():
            print(f"[+] Бот {bot_idx} завершил все вопросы. Перезапуск не требуется.")
            bot.stop()  # Останавливаем процессы бота
            time.sleep(1)  # Ждём освобождения ресурсов
            bots[bot_idx] = None
            logics[bot_idx] = None
            continue

          # Если restart_delay = 0, бот не перезапускается
          if restart_delay <= 0:
            continue

          # Проверяем, наступило ли время перезапуска
          if bot.next_restart_time and current_time >= bot.next_restart_time.timestamp():
            print(f"[*] Перезапуск бота {bot_idx} (прошло {restart_delay} сек с последнего запуска)...")

            # Перезапускаем бота
            bot.stop()
            time.sleep(2)  # Ждём освобождения ресурсов

            # Создаём нового бота
            new_bot = VirtualBotEnv(bot_idx, bot_cfg)

            # Проверяем, все ли вопросы отвечены у нового бота
            # stop_event может быть установлен из-за лимита max_questions, но если есть ещё вопросы — продолжаем
            if new_bot.all_questions_answered():
              print(f"[+] Бот {bot_idx} все вопросы верифицированы после перезапуска. Бот не запущен.")
              new_bot.stop()  # Останавливаем процессы
              time.sleep(1)
              bots[bot_idx] = None
              logics[bot_idx] = None
              continue

            site_name = bot_cfg['site']
            new_bot.start(cfg_main['sites'][site_name]['url'])
            bots[bot_idx] = new_bot

            # Создаём новую FSM
            new_fsm = FSM(bot_idx, cfg_main, bot_cfg)
            logics[bot_idx] = new_fsm

            # Сбрасываем флаг, чтобы сообщение о следующем перезапуске вывелось снова
            if bot_idx in bot_stop_times:
                del bot_stop_times[bot_idx]

            print(f"[+] Бот {bot_idx} перезапущен")
          elif bot.next_restart_time:
            # Показываем информацию о следующем перезапуске (только один раз)
            if bot_idx not in bot_stop_times:
              bot_stop_times[bot_idx] = True
              restart_in = int(bot.next_restart_time.timestamp() - current_time)
              print(f"[*] Бот {bot_idx} остановлен. Перезапуск через {restart_in} сек (в {bot.next_restart_time.strftime('%H:%M:%S')})")

      # Шаг 1.5: Проверяем периодический перезапуск для АКТИВНЫХ ботов
      # Если время перезапуска настало, но бот ещё работает — перезапускаем его
      for bot_idx, (bot, fsm) in enumerate(zip(bots, logics)):
        if bot is None or bot.stop_event.is_set():
          continue  # Пропускаем удалённые или остановленные боты

        bot_cfg = bot_configs[bot_idx][1]
        restart_delay_val = bot_cfg.get('restart_delay', 0)
        restart_delay = int(restart_delay_val) if restart_delay_val not in (None, 'None', '') else 0

        # Проверяем, наступило ли время перезапуска для активного бота
        if restart_delay > 0 and bot.next_restart_time and current_time >= bot.next_restart_time.timestamp():
          print(f"[*] Перезапуск бота {bot_idx} по таймеру (прошло {restart_delay} сек)...")

          # Останавливаем текущего бота
          bot.stop()
          time.sleep(2)  # Ждём освобождения ресурсов

          # Создаём нового бота
          new_bot = VirtualBotEnv(bot_idx, bot_cfg)

          # Проверяем, все ли вопросы отвечены у нового бота
          if new_bot.all_questions_answered():
            print(f"[+] Бот {bot_idx} все вопросы верифицированы. Перезапуск отменён.")
            new_bot.stop()
            time.sleep(1)
            bots[bot_idx] = None
            logics[bot_idx] = None
            continue

          site_name = bot_cfg['site']
          new_bot.start(cfg_main['sites'][site_name]['url'])
          bots[bot_idx] = new_bot

          # Создаём новую FSM
          new_fsm = FSM(bot_idx, cfg_main, bot_cfg)
          logics[bot_idx] = new_fsm

          # Сбрасываем флаг для сообщений
          if bot_idx in bot_stop_times:
              del bot_stop_times[bot_idx]

          print(f"[+] Бот {bot_idx} перезапущен (активный перезапуск)")

      # Шаг 2: Проверяем ботов, ожидающих завершения интервала между вопросами
      for bot_idx, (bot, fsm) in enumerate(zip(bots, logics)):
        if bot is None or fsm is None or bot.stop_event.is_set():
          continue
        
        # Проверяем, ожидает ли бот завершения интервала
        if hasattr(bot, 'waiting_for_interval') and bot.waiting_for_interval:
          if hasattr(bot, 'interval_resume_time') and current_time >= bot.interval_resume_time:
            # Интервал истёк, сбрасываем флаг и продолжаем работу
            print(f"[+] [Бот {bot_idx}] Интервал истёк, возобновляем работу")
            bot.waiting_for_interval = False
            bot.interval_resume_time = None
            # Выполняем reset браузера сейчас
            print(f"[*] [Бот {bot_idx}] Переход в start_question - выполняем reset браузера")
            fsm.reset_scenario(bot)
            # Ждём завершения всех действий в очереди (reset должен выполниться полностью)
            if hasattr(bot, 'action_queue'):
              bot.action_queue.join()
              print(f"[+] [Бот {bot_idx}] Reset завершён, бот готов к работе")
          # Если ещё ждём, просто продолжаем (бот будет пропущен на шаге 4)

      # Шаг 3: Фильтруем активных ботов (исключая тех, кто ждёт интервал)
      active_pairs = [(bot, fsm) for bot, fsm in zip(bots, logics)
                      if bot is not None and fsm is not None 
                      and not bot.stop_event.is_set()
                      and not (hasattr(bot, 'waiting_for_interval') and bot.waiting_for_interval)]

      # Шаг 4: Проверяем, все ли боты завершили работу
      all_bots_done = all(b is None for b in bots)
      if all_bots_done:
        print("[+] Все боты завершили все вопросы. Выход.")
        # Останавливаем все процессы (на случай если что-то осталось)
        for b in bots:
          if b:
            try:
              b.stop()
            except:
              pass
        break

      # Если нет активных ботов, но есть ожидающие перезапуска или интервала - продолжаем цикл
      if not active_pairs:
        time.sleep(1.0)
        continue

      # Шаг 5: Обрабатываем активные пары
      for bot, fsm in active_pairs:
        frame = bot.get_frame_umat()
        if frame is not None:
          fsm.execute_step(bot, analyzer, frame)

      # Минимальная пауза чтобы не нагружать CPU (теперь кадры обновляются чаще)
      time.sleep(0.1)

  except KeyboardInterrupt:
    print("\n[*] Завершение работы...")
    # Останавливаем монитор VNC
    vnc_monitor.stop()
    for b in bots:
      if b:
        b.stop()

if __name__ == "__main__":
  main()
