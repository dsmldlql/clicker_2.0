# VNC Fix - Пропадание изображения

## Проблема

VNC переставал показывать изображение через некоторое время, а также x11vnc не запускался с ошибкой:
```
[!] [Бот 3] x11vnc не запустился (попытка 1/3)
XOpenDisplay(":103") failed.
```

## Причины проблем

1. **x11vnc запускался слишком рано** - Xvfb ещё не успевал инициализироваться
2. **Отсутствовала проверка** что Xvfb действительно готов
3. **VNC не обновлял экран** когда не было изменений

## Решение

### 1. Проверка запуска Xvfb

Добавлена проверка с помощью `xdpyinfo`:

```python
# Ждём пока Xvfb запустится и проверим что он работает
for _ in range(10):  # Максимум 5 секунд
  time.sleep(0.5)
  result = subprocess.run(["xdpyinfo", "-display", self.display])
  if result.returncode == 0:
    print(f"[+] Xvfb запущен на {self.display}")
    break
```

### 2. Улучшенные опции x11vnc

```bash
x11vnc \
  -display :100 \
  -rfbport 5900 \
  -nopw -forever -shared \
  -repeat      # Повторять события
  -nowf        # Не ждать WaitForEvent
  -noncache    # Без кэширования
  -copyrect    # Эффективные обновления
```

### 3. VNC Refresh Thread

Фоновый поток обновляет экран каждые 2 секунды:

```python
class VNCRefreshThread(threading.Thread):
  def run(self):
    while not stop_event:
      subprocess.run(["xdotool", "search", "--name", ".*"])
      time.sleep(2.0)
```

### 4. Проверка запуска x11vnc

Дополнительная проверка что порт слушается:

```python
if self.procs['vnc'].poll() is None:
  result = subprocess.run(["ss", "-tlnp"])
  if str(vnc_port) in result.stdout:
    print(f"[+] x11vnc запущен на порту {vnc_port}")
```

## Проверка работы

После запуска ботов проверьте:

```bash
# Все ли Xvfb процессы активны
ps aux | grep "Xvfb.*:10" | grep -v grep

# Все ли x11vnc процессы активны (не должны быть <defunct>)
ps aux | grep x11vnc | grep -v grep

# Все ли порты слушаются
netstat -tlnp | grep -E "5900|5901|5902|5903"
```

## Зависимости

Убедитесь, что установлены все необходимые утилиты:

```bash
sudo apt install xdotool xdpyinfo x11vnc xvfb fluxbox
```

## Подключение к VNC

```
Бот 0: localhost:5900 (дисплей :100)
Бот 1: localhost:5901 (дисплей :101)
Бот 2: localhost:5902 (дисплей :102)
Бот 3: localhost:5903 (дисплей :103)
```

## Рекомендации по VNC клиенту

- **TigerVNC Viewer** - стабильный, быстро обновляется
- **RealVNC Viewer** - хорошая совместимость
- **Remmina** (Linux) - удобный интерфейс

Избегайте старых версий VNC клиентов - они могут плохо обновлять изображение.
