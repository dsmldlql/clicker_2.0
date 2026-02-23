# verification_saved_json.py
import re
import json
import logging
from typing import Optional, Dict, Any, Tuple

from json_repair import repair_json

from scripts.regex_patterns import ACT_ABBREVIATIONS, ACT_REGEX_PATTERNS
from scripts.logger_config import setup_logging

# Initialize logger
logger = setup_logging(__name__)


def clean_macro(data: str) -> str:
  """Cleans markdown artifacts and noise from the raw string."""
  # Remove numbers in square brackets like [1], [2]
  data = re.sub(r'\[\d+\]', '', data)
  # Strip whitespace
  # print(data.strip())
  return data.strip()


def load_messy_json(full_path: str, bot_id) -> str:
  """Attempts to read a file and extract the JSON part."""
  try:
    with open(full_path, 'r', encoding='utf-8') as file:
      content = file.read()
  except Exception as e:
    logger.error(f"Bot_{bot_id} Failed to read file {full_path}: {e}")
    return ""

  try:
    # Try finding the first '{' and last '}'
    first_brace = content.find('{')
    last_brace = content.rfind('}')
    
    if first_brace != -1 and last_brace != -1:
      json_str = content[first_brace : last_brace + 1]
      return clean_macro(json_str)
    else:
      logger.warning(f"Bot_{bot_id} No JSON braces found in file.")
      return clean_macro(content)
      
  except Exception as e:
    logger.error(f"Bot_{bot_id} Error extracting JSON from string: {e}")
    return ""


def clean_micro_art(data: Dict[str, Any]) -> Dict[str, Any]:
  norms = data.get("Norms", [])
  if not isinstance(norms, list):
    return data # Or log warning
    
  for item in norms:
    if isinstance(item, dict) and 'art' in item:
      item['art'] = re.sub(r'^ст. ', '', str(item['art']))
      item['art'] = re.sub(r'^статья ', '', str(item['art']))
  return data


def clean_micro_act(data: Dict[str, Any]) -> Dict[str, Any]:
  norms = data.get("Norms", [])
  if not isinstance(norms, list):
    return data

  for item in norms:
    if isinstance(item, dict) and 'act' in item:
      act = str(item['act'])
      act = abbreviate_act(act)
      item['act'] = abbreviate_act_regex(act)
  return data


def abbreviate_act(act_name: str) -> str:
  for pattern, abbreviation in ACT_ABBREVIATIONS.items():
    if re.match(pattern, act_name, re.IGNORECASE):
      return abbreviation
  return act_name 


def abbreviate_act_regex(act_name: str) -> str:
  for pattern, abbreviation in ACT_REGEX_PATTERNS.items():
    if re.match(pattern, act_name, re.IGNORECASE):
      return abbreviation
  return act_name 


def clean_micro_number(data: Dict[str, Any]) -> Dict[str, Any]:
  norms = data.get("Norms", [])
  if not isinstance(norms, list):
    return data

  for item in norms:
    if isinstance(item, dict) and 'number' in item:
      val = str(item['number'])
      val = re.sub(r'null.*', '', val)
      val = re.sub(r'N/A.*', '', val)
      val = re.sub(r'б/н.*', '', val)
      item['number'] = val
  return data


def check_valid_json(raw_data: Any, bot_id) -> Tuple[bool, Any]:
  try:
    data = raw_data
    # If string, try to parse
    if isinstance(data, str):
      try:
        data = json.loads(data)
      except json.JSONDecodeError as e:
        logger.warning(f"Bot_{bot_id} Initial JSON parse failed: {e}")
        try:
          data = repair_json(data)
          data = json.loads(data)
          norms_count = len(data.get("Norms", []))
          if norms_count <= 1:
            return False, raw_data
        except json.JSONDecodeError as e:
          logger.warning(f"Bot_{bot_id} Initial JSON second parse failed: {e}")
        # Optional: try simple repair or just fail. 
        # The original code wrote to spam.json and re-read it, which is weird.
        # We will log and fail for now unless strict repair is needed.
          return False, raw_data

    if not isinstance(data, dict):
       logger.warning(f"Bot_{bot_id} Parsed data is not a dict: {type(data)}")
       return False, data

    if "Norms" not in data:
      logger.warning(f"Bot_{bot_id} Missing 'Norms' key in JSON")
      return False, data

    # Cleaning steps
    data = clean_micro_art(data)
    data = clean_micro_number(data)
    data = clean_micro_act(data)
    
    logger.info(f"Bot_{bot_id} JSON verified and cleaned successfully")
    return True, data

  except Exception as e:
    logger.exception(f"Bot_{bot_id} Validation failed: {e}")
    return False, raw_data


def verify_saved_json(path_to_json: str, bot_id) -> bool:
  try:
    raw_string = load_messy_json(path_to_json, bot_id)
    if not raw_string:
      return False
      
    success, _ = check_valid_json(raw_string, bot_id)
    return success
  except Exception as e:
    logger.exception(f"verify_saved_json crashed: {e}")
    return False
