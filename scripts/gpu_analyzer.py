import cv2
import random
import os

class GPUAnalyzer:
  def __init__(self, base_dir=None):
    self.cache = {}
    self.counter = 0
    # Базовая директория проекта для относительных путей
    if base_dir is None:
      base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    self.base_dir = base_dir

  def find_best_match(self, frame, templates, threshold):
    print('Counter:', self.counter)
    for path in templates:
      # Преобразуем относительный путь в абсолютный
      if not os.path.isabs(path):
        abs_path = os.path.join(self.base_dir, path)
      else:
        abs_path = path
      
      if abs_path not in self.cache:
        # Загружаем шаблон в Ч/Б и сразу отправляем в VRAM (GPU)
        img = cv2.imread(abs_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
          print(f"[!] Шаблон не загружен: {abs_path}")
          continue
        img = cv2.Canny(img, 50, 150)
        self.cache[abs_path] = cv2.UMat(img)
      temp = self.cache[abs_path]
      h, w = temp.get().shape[:2]

      # cv2.imwrite(f'{self.counter}_screenshot.png', frame)
      # cv2.imwrite(f'{self.counter}_template.png', temp)

      res = cv2.matchTemplate(frame, temp, cv2.TM_CCOEFF_NORMED)
      _, max_val, _, max_loc = cv2.minMaxLoc(res)
      print(f"Search {abs_path}")
      print(f"Max_loc {max_loc}, {max_val}")
      if max_val >= threshold:
        # 3. Сохранение
        # cv2.imwrite(f'{self.counter}_screenshot.png', frame)
        # cv2.imwrite(f'{self.counter}_template.png', temp)
        self.counter += 1

        # Calculate center position with random offset
        rand_offset_x = random.randint(-int(w//5), int(w//5)) if w > 5 else 0
        rand_offset_y = random.randint(-int(h//5), int(h//5)) if h > 5 else 0
        x = max_loc[0] + w // 2 + rand_offset_x
        y = max_loc[1] + h // 2 + rand_offset_y
        print(f"Found {abs_path}")
        print(f"Max_loc {x, y}")
        return (
          max_loc[0] + w // 2 + rand_offset_x,
          max_loc[1] + h // 2 + rand_offset_y
          ), max_val
    return None, 0
