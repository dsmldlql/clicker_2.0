import subprocess
import os
import time
import shutil

class VirtualBotEnv:
    def __init__(self, bot_id, master_profile, width=600, height=800):
        self.bot_id = bot_id
        self.master_profile = os.path.abspath(master_profile)
        self.display = f":{100 + bot_id}"
        self.size = f"{width}x{height}x24"
        self.temp_profile = f"/tmp/perplexity_bot_{self.bot_id}"
        self.procs = {}

    def _clear_cache(self, profile_path):
        """Удаляет только тяжелый мусор, сохраняя сессию Perplexity"""
        # Эти папки НЕЛЬЗЯ удалять (там лежит логин): Local Storage, IndexedDB, Sessions
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
        """Подготовка изолированного профиля"""
        if os.path.exists(self.temp_profile):
            shutil.rmtree(self.temp_profile, ignore_errors=True)
        
        # Чистим кэш в мастере перед копированием для скорости
        self._clear_cache(self.master_profile)
        shutil.copytree(self.master_profile, self.temp_profile)
        
        # Снятие блокировки Chromium
        for lock in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_path = os.path.join(self.temp_profile, lock)
            if os.path.exists(lock_path):
                try: os.remove(lock_path)
                except: pass

    def start(self, url):
        self._prepare_profile()
        print(f"[*] [Бот {self.bot_id}] Запуск на {self.display}...")

        # 1. Xvfb
        self.procs['xvfb'] = subprocess.Popen(
            ["Xvfb", self.display, "-screen", "0", self.size, "-ac"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(1)

        env = os.environ.copy()
        env["DISPLAY"] = self.display

        # 2. Fluxbox (легкий оконный менеджер)
        self.procs['wm'] = subprocess.Popen(
            ["fluxbox"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # 3. VNC (localhost:5901, 5902...)
        vnc_port = 5900 + self.bot_id
        self.procs['vnc'] = subprocess.Popen([
            "x11vnc", "-display", self.display, "-rfbport", str(vnc_port), 
            "-nopw", "-forever", "-shared"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 4. Chromium с экстремальным сбережением ресурсов для Perplexity
        chrome_cmd = [
            "/usr/bin/chromium", # или "chromium-browser"
            f"--display={self.display}",
            f"--user-data-dir={self.temp_profile}",
            "--no-sandbox",
            
            "--disable-frame-rate-limit",      # Позволяет управлять лимитами программно
            "--disable-rendering-loop",       # Отключает постоянное обновление кадров

            "--disable-javascript",           # ПОЛНОЕ ОТКЛЮЧЕНИЕ JS
            "--disable-gpu",                  # Отключаем аппаратное ускорение
            "--disable-software-rasterizer",  # Не нагружаем CPU программным рендером
            "--disable-dev-shm-usage",        # Используем диск вместо /dev/shm (если памяти мало)
            
            # ЭКСТРЕМАЛЬНАЯ ЭКОНОМИЯ ГРАФИКИ:
            "--blink-settings=imagesEnabled=false", # Без картинок
            "--disable-2d-canvas-clip",             # Отключаем отрисовку холстов
            "--disable-reading-from-canvas",        # Запрещаем чтение холстов
            "--disable-accelerated-2d-canvas",      # Без ускорения 2D
            "--disable-threaded-scrolling",         # Отключаем потоковый скроллинг
            "--disable-notifications",              # Без уведомлений
            "--disable-background-networking",      # Без фонового обмена данными
            "--mute-audio",                         # Без звука
            
            # ОГРАНИЧЕНИЕ ЧАСТОТЫ КАДРОВ (FPS):
            "--limit-fps=1",                        # Ограничиваем отрисовку 1 кадром в секунду

            # ОТКЛЮЧЕНИЕ ТЯЖЕЛОГО РЕНДЕРИНГА:
            "--disable-remote-fonts",                # Без кастомных шрифтов
            "--disable-canvas-aa",                   # Без сглаживания
            "--animation-duration-scale=0",          # Без анимаций
            # МАСКИРОВКА И СТАБИЛЬНОСТЬ:
            "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--lang=ru-RU",
            # "--js-flags='--max-old-space-size=300'", # Ограничение памяти на вкладку
            url
        ]
        
        self.procs['browser'] = subprocess.Popen(chrome_cmd, env=env)
        print(f"[+] [Бот {self.bot_id}] Готов. VNC: localhost:{vnc_port}")

    def stop(self):
        print(f"[*] [Бот {self.bot_id}] Выключение...")
        for p in self.procs.values():
            if p:
                try: p.terminate()
                except: pass

if __name__ == "__main__":
    # ПУТЬ К ТВОЕМУ МАСТЕР-ПРОФИЛЮ
    MASTER_PATH = os.path.expanduser("~/bot_master_profile")
    PERPLEXITY_URL = "https://www.perplexity.ai"
    BOT_COUNT = 3 
    
    if not os.path.exists(MASTER_PATH):
        print(f"Сначала создай мастер-профиль: chromium --user-data-dir={MASTER_PATH}")
        exit(1)

    active_bots = []
    try:
        for i in range(1, BOT_COUNT + 1):
            bot = VirtualBotEnv(bot_id=i, master_profile=MASTER_PATH)
            bot.start(PERPLEXITY_URL)
            active_bots.append(bot)
            time.sleep(8) # Пауза важна для Cloudflare и CPU
        
        print("\n[OK] Все боты запущены. Нажми Ctrl+C для остановки.")
        while True: time.sleep(1)
            
    except KeyboardInterrupt:
        for b in active_bots: b.stop()
        print("\n[!] Работа завершена.")
