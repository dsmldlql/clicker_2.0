import cv2

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
        h, w = temp.get().shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2), max_val
    return None, 0
