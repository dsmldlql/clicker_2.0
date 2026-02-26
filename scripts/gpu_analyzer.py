import cv2
import random

class GPUAnalyzer:
  def __init__(self):
    self.cache = {}

  def find_best_match(self, frame, templates, threshold):
    for path in templates:
      if path not in self.cache:
        img = cv2.imread(path)
        if img is None: continue
        self.cache[path] = cv2.UMat(img)
      temp = self.cache[path]
      res = cv2.matchTemplate(frame, temp, cv2.TM_CCOEFF_NORMED)
      _, max_val, _, max_loc = cv2.minMaxLoc(res)
      if max_val >= threshold:
        # Calculate center position with random offset
        rand_offset_x = random.randint(-int(w//2.5), int(w//2.5)) if w > 5 else 0
        rand_offset_y = random.randint(-int(h//2.5), int(h//2.5)) if h > 5 else 0
        h, w = temp.get().shape[:2]
        return (
          max_loc[0] + w // 2 + rand_offset_x, 
          max_loc[1] + h // 2 + rand_offset_y
          ), max_val
    return None, 0
