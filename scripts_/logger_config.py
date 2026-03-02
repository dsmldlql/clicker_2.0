import logging
import sys

def setup_logging(name: str) -> logging.Logger:
  """Simple logger setup for bot scripts"""
  logger = logging.getLogger(name)
  logger.setLevel(logging.INFO)
  
  if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
      '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
  
  return logger
