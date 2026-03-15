"""
Расширенное логирование состояний FSM с временными метками.
Логирование в разрезе: сайт + сценарий + состояние.
"""

import time
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any


class StateTimer:
  """Таймер для замера времени выполнения состояния"""
  
  def __init__(self):
    self.start_time: Optional[float] = None
    self.end_time: Optional[float] = None
    self.condition_start: Optional[float] = None
    self.condition_end: Optional[float] = None
  
  def start(self):
    self.start_time = time.time()
    self.end_time = None
  
  def mark_condition_start(self):
    self.condition_start = time.time()
  
  def mark_condition_end(self):
    self.condition_end = time.time()
  
  def stop(self):
    self.end_time = time.time()
  
  def get_elapsed(self) -> float:
    if self.start_time is None:
      return 0.0
    end = self.end_time if self.end_time else time.time()
    return end - self.start_time
  
  def get_condition_time(self) -> float:
    if self.condition_start is None:
      return 0.0
    end = self.condition_end if self.condition_end else time.time()
    return end - self.condition_start
  
  def reset(self):
    self.__init__()


class StateLogger:
  """
  Логгер состояний FSM с детальным отслеживанием времени.
  
  Логирует:
  - Вход в состояние (с временной меткой)
  - Время ожидания триггера
  - Время проверки условий
  - Выход из состояния (с результатом)
  - Переходы между состояниями
  """
  
  def __init__(self, bot_id: int, site: str, scenario: str, log_dir: str):
    self.bot_id = bot_id
    self.site = site
    self.scenario = scenario
    self.log_dir = log_dir
    
    # Текущее состояние
    self.current_state: Optional[str] = None
    self.previous_state: Optional[str] = None
    
    # Таймеры
    self.state_timer = StateTimer()
    self.transition_time: Optional[float] = None
    
    # Статистика по состояниям
    self.state_stats: Dict[str, Dict[str, Any]] = {}
    
    # Путь к файлу логов
    os.makedirs(log_dir, exist_ok=True)
    self.state_log_path = os.path.join(log_dir, f"state_timeline_{site}_{scenario}.jsonl")
  
  def _get_timestamp(self) -> str:
    return datetime.now().isoformat()
  
  def _get_elapsed_ms(self, start: float, end: Optional[float] = None) -> float:
    if end is None:
      end = time.time()
    return round((end - start) * 1000, 2)
  
  def _log_jsonl(self, event_type: str, data: Dict[str, Any]):
    """Запись события в JSONL файл"""
    log_entry = {
      "timestamp": self._get_timestamp(),
      "bot_id": self.bot_id,
      "site": self.site,
      "scenario": self.scenario,
      "event": event_type,
      "data": data
    }
    
    try:
      with open(self.state_log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    except Exception as e:
      print(f"[!] [Бот {self.bot_id}] Ошибка записи state logger: {e}")
  
  def _update_state_stats(self, state: str, event: str, duration_ms: Optional[float] = None, 
                          success: Optional[bool] = None):
    """Обновление статистики по состоянию"""
    if state not in self.state_stats:
      self.state_stats[state] = {
        "enter_count": 0,
        "exit_count": 0,
        "success_count": 0,
        "fail_count": 0,
        "total_duration_ms": 0,
        "min_duration_ms": float('inf'),
        "max_duration_ms": 0,
        "last_enter": None,
        "last_exit": None
      }
    
    stats = self.state_stats[state]
    
    if event == "enter":
      stats["enter_count"] += 1
      stats["last_enter"] = self._get_timestamp()
    
    elif event == "exit":
      stats["exit_count"] += 1
      stats["last_exit"] = self._get_timestamp()
      
      if duration_ms is not None:
        stats["total_duration_ms"] += duration_ms
        stats["min_duration_ms"] = min(stats["min_duration_ms"], duration_ms)
        stats["max_duration_ms"] = max(stats["max_duration_ms"], duration_ms)
      
      if success is True:
        stats["success_count"] += 1
      elif success is False:
        stats["fail_count"] += 1
  
  def enter_state(self, state: str, from_state: Optional[str] = None):
    """
    Логирует вход в состояние.
    
    Args:
      state: Название текущего состояния
      from_state: Название предыдущего состояния (если есть переход)
    """
    timestamp = time.time()
    self.state_timer.start()
    
    # Обновляем статистику
    self._update_state_stats(state, "enter")
    
    # Данные события
    data = {
      "state": state,
      "from_state": from_state,
      "previous_state": self.previous_state,
      "transition_delay_ms": None
    }
    
    # Вычисляем задержку перехода
    if self.transition_time is not None:
      data["transition_delay_ms"] = self._get_elapsed_ms(self.transition_time, timestamp)
    
    # Логируем
    self._log_jsonl("STATE_ENTER", data)
    
    # Обновляем состояние
    self.previous_state = self.current_state
    self.current_state = state
    
    print(f"[STATE] [{self.site}/{self.scenario}] → ENTER '{state}' " +
          (f"(from '{from_state}')" if from_state else "") +
          (f" [+{data['transition_delay_ms']:.0f}ms]" if data['transition_delay_ms'] else ""))
  
  def mark_trigger_found(self):
    """Отмечает момент нахождения визуального триггера"""
    if self.state_timer.start_time is None:
      return
    
    elapsed = self._get_elapsed_ms(self.state_timer.start_time)
    
    self._log_jsonl("TRIGGER_FOUND", {
      "state": self.current_state,
      "time_to_trigger_ms": elapsed
    })
    
    print(f"[STATE] [{self.site}/{self.scenario}] ✓ Trigger found in '{self.current_state}' [{elapsed:.0f}ms]")
  
  def mark_condition_start(self):
    """Отмечает начало проверки условия"""
    self.state_timer.mark_condition_start()
    
    self._log_jsonl("CONDITION_CHECK_START", {
      "state": self.current_state,
      "time_from_enter_ms": self._get_elapsed_ms(self.state_timer.start_time) if self.state_timer.start_time else 0
    })
  
  def mark_condition_result(self, success: bool, condition_type: str = "unknown"):
    """
    Отмечает результат проверки условия.
    
    Args:
      success: Результат проверки (True/False)
      condition_type: Тип условия ('templates', 'json_valid', 'always')
    """
    self.state_timer.mark_condition_end()
    
    condition_time = self._get_elapsed_ms(self.state_timer.condition_start) if self.state_timer.condition_start else 0
    total_time = self._get_elapsed_ms(self.state_timer.start_time) if self.state_timer.start_time else 0
    
    self._log_jsonl("CONDITION_RESULT", {
      "state": self.current_state,
      "success": success,
      "condition_type": condition_type,
      "condition_time_ms": condition_time,
      "total_time_ms": total_time
    })
    
    result_str = "✓" if success else "✗"
    print(f"[STATE] [{self.site}/{self.scenario}] {result_str} Condition '{condition_type}' in '{self.current_state}': " +
          f"{'PASS' if success else 'FAIL'} [condition: {condition_time:.0f}ms, total: {total_time:.0f}ms]")
  
  def exit_state(self, success: bool, next_state: str, reason: str = "normal"):
    """
    Логирует выход из состояния.
    
    Args:
      success: Успешно ли выполнено условие
      next_state: Следующее состояние
      reason: Причина выхода ('normal', 'timeout', 'error')
    """
    self.state_timer.stop()
    total_duration = self._get_elapsed_ms(self.state_timer.start_time) if self.state_timer.start_time else 0
    condition_time = self.state_timer.get_condition_time() * 1000 if self.state_timer.condition_start else 0
    
    # Обновляем статистику
    self._update_state_stats(self.current_state, "exit", duration_ms=total_duration, success=success)
    
    # Данные события
    data = {
      "state": self.current_state,
      "next_state": next_state,
      "success": success,
      "reason": reason,
      "total_duration_ms": total_duration,
      "condition_check_time_ms": condition_time,
      "trigger_wait_time_ms": condition_time if condition_time > 0 else total_duration
    }
    
    # Добавляем среднее время из статистики
    stats = self.state_stats.get(self.current_state, {})
    if stats.get("exit_count", 0) > 1:
      data["avg_duration_ms"] = round(stats["total_duration_ms"] / stats["exit_count"], 2)
    
    self._log_jsonl("STATE_EXIT", data)
    
    # Запоминаем время перехода
    self.transition_time = time.time()
    
    # Вывод в консоль
    emoji = "✓" if success else "✗"
    print(f"[STATE] [{self.site}/{self.scenario}] {emoji} EXIT '{self.current_state}' → '{next_state}' " +
          f"[{reason}] [total: {total_duration:.0f}ms, condition: {condition_time:.0f}ms]" +
          (f" [avg: {data.get('avg_duration_ms', 0):.0f}ms]" if data.get('avg_duration_ms') else ""))
  
  def log_timeout(self, timeout_sec: float):
    """Логирует таймаут состояния"""
    elapsed = self._get_elapsed_ms(self.state_timer.start_time) if self.state_timer.start_time else 0
    
    self._log_jsonl("STATE_TIMEOUT", {
      "state": self.current_state,
      "timeout_sec": timeout_sec,
      "elapsed_ms": elapsed
    })
    
    self._update_state_stats(self.current_state, "exit", duration_ms=elapsed, success=False)
    
    print(f"[STATE] [{self.site}/{self.scenario}] ⏱ TIMEOUT '{self.current_state}' " +
          f"[{elapsed:.0f}ms > {timeout_sec*1000:.0f}ms]")
  
  def log_error(self, error: str, details: Optional[Dict] = None):
    """Логирует ошибку в состоянии"""
    self._log_jsonl("STATE_ERROR", {
      "state": self.current_state,
      "error": error,
      "details": details or {}
    })
    
    print(f"[STATE] [{self.site}/{self.scenario}] ✗ ERROR in '{self.current_state}': {error}")
  
  def get_stats_summary(self) -> Dict[str, Any]:
    """Возвращает сводную статистику по всем состояниям"""
    summary = {
      "bot_id": self.bot_id,
      "site": self.site,
      "scenario": self.scenario,
      "current_state": self.current_state,
      "states": {}
    }
    
    for state, stats in self.state_stats.items():
      avg_duration = 0
      if stats["exit_count"] > 0:
        avg_duration = round(stats["total_duration_ms"] / stats["exit_count"], 2)
      
      summary["states"][state] = {
        "visits": stats["enter_count"],
        "completions": stats["exit_count"],
        "success_rate": round(stats["success_count"] / stats["exit_count"] * 100, 1) if stats["exit_count"] > 0 else 0,
        "avg_duration_ms": avg_duration,
        "min_duration_ms": stats["min_duration_ms"] if stats["min_duration_ms"] != float('inf') else 0,
        "max_duration_ms": stats["max_duration_ms"]
      }
    
    return summary
  
  def print_stats(self):
    """Выводит статистику в консоль"""
    summary = self.get_stats_summary()
    
    print(f"\n{'='*60}")
    print(f"STATE STATISTICS [{self.site}/{self.scenario}]")
    print(f"{'='*60}")
    
    for state, stats in summary["states"].items():
      print(f"\n  {state}:")
      print(f"    Visits: {stats['visits']}")
      print(f"    Completions: {stats['completions']}")
      print(f"    Success rate: {stats['success_rate']}%")
      print(f"    Avg duration: {stats['avg_duration_ms']:.0f}ms")
      print(f"    Min/Max: {stats['min_duration_ms']:.0f}ms / {stats['max_duration_ms']:.0f}ms")
    
    print(f"{'='*60}\n")
