import subprocess
import time
import threading
import os
from typing import Optional
from datetime import datetime


class VNCHealthMonitor:
    """
    Мониторит состояние VNC серверов и автоматически восстанавливает их при необходимости.
    Проверяет что:
    1. Xvfb процесс запущен на нужном дисплее
    2. x11vnc процесс запущен и слушает правильный порт
    3. Порт VNC доступен для подключения
    """
    
    def __init__(self, bot_count: int, check_interval: float = 30.0):
        """
        :param bot_count: Количество ботов (боты 0..bot_count-1)
        :param check_interval: Интервал проверки в секундах
        """
        self.bot_count = bot_count
        self.check_interval = check_interval
        self.stop_event = threading.Event()
        self.monitor_thread: Optional[threading.Thread] = None
        self.xvfb_failed_bots: set = set()  # Множество ботов с упавшим Xvfb
        self._lock = threading.Lock()  # Блокировка для потокобезопасности

    def check_xvfb(self, bot_id: int) -> bool:
        """Проверяет что Xvfb запущен на дисплее бота"""
        display = f":{100 + bot_id}"
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"Xvfb.*{display}"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                # Дополнительно проверяем что дисплей доступен
                result = subprocess.run(
                    ["xdpyinfo", "-display", display],
                    capture_output=True, timeout=2
                )
                return result.returncode == 0
            return False
        except Exception as e:
            print(f"[!] VNC Monitor: Ошибка проверки Xvfb для бота {bot_id}: {e}")
            return False
    
    def check_vnc_port(self, bot_id: int) -> bool:
        """Проверяет что VNC порт слушается"""
        vnc_port = 5900 + bot_id
        try:
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                return str(vnc_port) in result.stdout
            return False
        except Exception as e:
            print(f"[!] VNC Monitor: Ошибка проверки порта для бота {bot_id}: {e}")
            return False
    
    def check_vnc_process(self, bot_id: int) -> bool:
        """Проверяет что x11vnc процесс запущен"""
        display = f":{100 + bot_id}"
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"x11vnc.*{display}"],
                capture_output=True, text=True, timeout=2
            )
            # Проверяем что есть активные процессы (не defunct)
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if not pid.strip():
                        continue
                    # Проверяем что процесс не зомби
                    try:
                        ps_result = subprocess.run(
                            ["ps", "-o", "stat=", "-p", pid.strip()],
                            capture_output=True, text=True, timeout=1
                        )
                        if ps_result.returncode == 0:
                            state = ps_result.stdout.strip()
                            # 'Z' означает зомби процесс
                            if 'Z' not in state:
                                return True
                    except:
                        pass
                return False
            return False
        except Exception as e:
            print(f"[!] VNC Monitor: Ошибка проверки x11vnc для бота {bot_id}: {e}")
            return False
    
    def check_bot_health(self, bot_id: int) -> tuple:
        """
        Проверяет полное состояние VNC для бота.
        Возвращает (xvfb_ok, vnc_ok, needs_restart)
        """
        xvfb_ok = self.check_xvfb(bot_id)
        vnc_port_ok = self.check_vnc_port(bot_id)
        vnc_process_ok = self.check_vnc_process(bot_id)
        
        # VNC считается рабочим если и порт слушается и процесс активен
        vnc_ok = vnc_port_ok and vnc_process_ok
        
        # Перезапуск нужен если Xvfb жив но VNC мёртв
        needs_restart = xvfb_ok and not vnc_ok
        
        return xvfb_ok, vnc_ok, needs_restart
    
    def restart_vnc_for_bot(self, bot_id: int, display: str, vnc_port: int):
        """Перезапускает только x11vnc для бота (без перезапуска Xvfb)"""
        print(f"[*] VNC Monitor: Перезапуск x11vnc для бота {bot_id} (дисплей {display}, порт {vnc_port})")

        # Находим и убиваем старые процессы x11vnc (используем kill для надёжности)
        try:
            # Сначала пытаемся корректно остановить
            subprocess.run(
                ["pkill", "-15", "-f", f"x11vnc.*-display.*{display}"],
                capture_output=True, timeout=2
            )
            time.sleep(0.5)
            # Если ещё есть - убиваем принудительно
            subprocess.run(
                ["pkill", "-9", "-f", f"x11vnc.*-display.*{display}"],
                capture_output=True, timeout=2
            )
            time.sleep(0.5)
        except Exception as e:
            print(f"[!] VNC Monitor: Ошибка остановки x11vnc для бота {bot_id}: {e}")

        # Проверяем что порт освободился (ждём максимум 2.5 сек)
        for _ in range(5):
            if not self.check_vnc_port(bot_id):
                break
            time.sleep(0.5)

        # Запускаем новый x11vnc
        try:
            env = os.environ.copy()
            env["DISPLAY"] = display

            vnc_log = f"/tmp/bot_{bot_id}_x11vnc_monitor.log"

            # Открываем лог файл в режиме append чтобы не терять историю
            log_file = open(vnc_log, 'a')
            
            proc = subprocess.Popen([
                "x11vnc",
                "-display", display,
                "-rfbport", str(vnc_port),
                "-nopw",
                "-forever",
                "-shared",
                "-nowf",
                "-noxdamage",
                "-repeat"
            ], stdout=log_file, stderr=subprocess.STDOUT, env=env)

            # Ждём и проверяем что запустился
            time.sleep(2)
            
            # Проверяем что процесс жив
            if proc.poll() is not None:
                print(f"[!] VNC Monitor: x11vnc для бота {bot_id} умер сразу после запуска")
                log_file.close()
                return False
            
            if self.check_vnc_port(bot_id):
                print(f"[+] VNC Monitor: x11vnc для бота {bot_id} успешно перезапущен на порту {vnc_port}")
                return True
            else:
                print(f"[!] VNC Monitor: Не удалось запустить x11vnc для бота {bot_id} (порт не слушается)")
                log_file.close()
                return False

        except Exception as e:
            print(f"[!] VNC Monitor: Ошибка запуска x11vnc для бота {bot_id}: {e}")
            return False
    
    def monitor_loop(self):
        """Основной цикл мониторинга"""
        print(f"[+] VNC Monitor: Запущен (проверка {self.bot_count} ботов каждые {self.check_interval} сек)")
        
        # Статистика для логирования (чтобы не спамить если всё OK)
        last_ok_log = 0
        check_count = 0

        while not self.stop_event.is_set():
            check_count += 1
            all_ok = True
            
            for bot_id in range(self.bot_count):
                if self.stop_event.is_set():
                    break

                xvfb_ok, vnc_ok, needs_restart = self.check_bot_health(bot_id)

                if xvfb_ok and vnc_ok:
                    continue

                all_ok = False
                
                if not xvfb_ok:
                    print(f"[!] VNC Monitor: Бот {bot_id} - Xvfb не работает (дисплей :{100 + bot_id})")
                    print(f"[!] VNC Monitor: Бот {bot_id} требует перезапуска (Xvfb упал)")
                    # Добавляем бота в список требующих перезапуска
                    with self._lock:
                        self.xvfb_failed_bots.add(bot_id)
                    # Xvfb упал - это серьёзно, монитор не может восстановить
                    continue

                elif needs_restart:
                    # Xvfb работает но VNC нет - перезапускаем только VNC
                    display = f":{100 + bot_id}"
                    vnc_port = 5900 + bot_id

                    print(f"[!] VNC Monitor: Бот {bot_id} - VNC не работает (порт {vnc_port})")

                    success = self.restart_vnc_for_bot(bot_id, display, vnc_port)

                    if not success:
                        print(f"[!] VNC Monitor: Не удалось восстановить VNC для бота {bot_id}")
                        print(f"[!] VNC Monitor: Попробуйте перезапустить бота вручную")
                    else:
                        # VNC восстановлен, убираем из списка failed если там был
                        with self._lock:
                            self.xvfb_failed_bots.discard(bot_id)
            
            # Логируем статус раз в 10 проверок (5 минут)
            if all_ok and check_count % 10 == 0:
                print(f"[*] VNC Monitor: Все {self.bot_count} ботов OK (проверка #{check_count})")
            
            # Ждём до следующей проверки
            self.stop_event.wait(self.check_interval)

        print("[*] VNC Monitor: Остановлен")
    
    def start(self):
        """Запускает монитор в отдельном потоке"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            print("[!] VNC Monitor: Уже запущен")
            return
        
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop(self):
        """Останавливает монитор"""
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
            print("[*] VNC Monitor: Остановлен")
    
    def is_running(self) -> bool:
        """Проверяет запущен ли монитор"""
        return self.monitor_thread is not None and self.monitor_thread.is_alive()

    def is_xvfb_failed(self, bot_id: int) -> bool:
        """Проверяет, упал ли Xvfb для указанного бота"""
        with self._lock:
            return bot_id in self.xvfb_failed_bots

    def clear_xvfb_failed(self, bot_id: int):
        """Убирает бота из списка упавших (вызывается после успешного перезапуска)"""
        with self._lock:
            self.xvfb_failed_bots.discard(bot_id)

    def get_failed_bots(self) -> list:
        """Возвращает список ботов с упавшим Xvfb"""
        with self._lock:
            return list(self.xvfb_failed_bots)

