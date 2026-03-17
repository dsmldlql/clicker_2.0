#!/usr/bin/env python3
"""
Join JSON files with the same number prefix and count norm occurrences.

This script:
1. Finds all JSON files in answers/ subdirectories
2. Groups files by their numeric prefix (e.g., 0_*.json, 1_*.json)
3. Merges norms from files with the same prefix
4. Counts how many times each norm appears across files
5. Outputs CSV with: example_id, uid, norm_type, norm_number, article, point, date, count, models

Configuration:
    Set FOLDERS_TO_INCLUDE to specify which model folders to process.
    Use None to include all folders, or specify a list of folder names.
    
    Example:
        FOLDERS_TO_INCLUDE = None  # Include all folders
        FOLDERS_TO_INCLUDE = ["qwen", "gpt", "gemini"]  # Only specific folders
"""

import json
import os
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional, Set
from scripts.logger_config import setup_logging
from scripts.regex_patterns import ACT_ABBREVIATIONS, ACT_REGEX_PATTERNS
import json_repair

logger = setup_logging(__name__)

ANSWERS_DIR = Path(__file__).parent.parent / "answers"

# =============================================================================
# CONFIGURATION: Specify which folders to include for norm counting
# =============================================================================
# Set to None to include ALL folders
# Or set to a list of folder names (from answers/ directory) to include only specific models
#
# Available folder names in answers/:
#   - qwen
#   - gpt
#   - gemini
#   - perplexity_claude_sonnet
#   - perplexity_gemini
#   - perplexity_grok
#
# Examples:
#   FOLDERS_TO_INCLUDE = None  # Include ALL folders
#   FOLDERS_TO_INCLUDE = ["qwen", "gpt", "gemini"]  # Only 3 specific folders
#   FOLDERS_TO_INCLUDE = ["perplexity_claude_sonnet", "perplexity_gemini", "perplexity_grok"]  # Only Perplexity
# =============================================================================
FOLDERS_TO_INCLUDE: Optional[List[str]] = ["qwen", "gpt", "gemini", "perplexity_claude_sonnet", "perplexity_grok"]
# FOLDERS_TO_INCLUDE: Optional[List[str]] = None
# =============================================================================

# Список кодексов, у которых date и number заменяются на пустоту
SPISOK_KODEKSOV = {
    "ГК", "НК", "ТК", "СК", "УК", "ЖК", "ЗК", "ВК", "ЛК", "БК", "УИК",
    "ГПК", "АПК", "УПК", "КАС", "КоАП РФ", "КОАП", "ГрК", "ВЗК", "Конституция"
}


def extract_file_number(filename: str) -> str:
    """Extract the numeric prefix from filename like '0_abc123_qwen.json'."""
    base_name = filename.split('.')[0]
    parts = base_name.split('_')
    if parts:
        return parts[0]
    return ""


def extract_uid(filename: str) -> str:
    """Extract the UUID from filename like '0_466f428e-0e4b-4d07-b042-c1d22ff2ce88_qwen.json'."""
    base_name = filename.split('.')[0]
    parts = base_name.split('_')
    if len(parts) >= 2:
        # UUID is typically the second part (after the number)
        return parts[1]
    return ""


def extract_model_from_path(file_path: Path) -> str:
    """Extract model name from folder path like 'answers/qwen/hypos_norm/gen/'."""
    parts = file_path.parts
    # Find 'answers' in path and get the next folder (model name)
    for i, part in enumerate(parts):
        if part == 'answers' and i + 1 < len(parts):
            return parts[i + 1]
    return "unknown"


def normalize_act_name(act_name: str) -> str:
    """Normalize act name using regex patterns from regex_patterns.py.
    
    First tries ACT_REGEX_PATTERNS (more specific), then ACT_ABBREVIATIONS.
    Returns the original name if no pattern matches.
    """
    if not act_name:
        return act_name
    
    # First try regex patterns (more specific with regex)
    for pattern, abbreviation in ACT_REGEX_PATTERNS.items():
        if re.match(pattern, act_name, re.IGNORECASE):
            # Handle backreferences like \1
            if '\\' in abbreviation:
                match = re.match(pattern, act_name, re.IGNORECASE)
                if match:
                    return re.sub(pattern, abbreviation, act_name, flags=re.IGNORECASE)
            return abbreviation
    
    # Then try simple abbreviations
    for pattern, abbreviation in ACT_ABBREVIATIONS.items():
        if re.match(pattern, act_name, re.IGNORECASE):
            return abbreviation
    
    return act_name


def clean_article_field(value: str) -> str:
    """Extract only digits from article field. Remove 'ст.', 'статья', etc.
    
    Examples:
        "ст. 163" -> "163"
        "статья 421" -> "421"
        "159" -> "159"
        "" -> ""
    """
    if not value:
        return ""
    
    # Remove common prefixes
    cleaned = re.sub(r'^ст\.\s*', '', str(value), flags=re.IGNORECASE)
    cleaned = re.sub(r'^статья\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^арт\.\s*', '', cleaned, flags=re.IGNORECASE)
    
    # Extract only digits
    digits = re.findall(r'\d+', cleaned)
    return ''.join(digits) if digits else ""


def clean_point_field(value: str) -> str:
    """Extract only digits from point field. Remove 'п.', 'punkt', etc.
    
    Examples:
        "п. 1" -> "1"
        "punkt 2" -> "2"
        "3" -> "3"
        "" -> ""
    """
    if not value:
        return ""
    
    # Remove common prefixes
    cleaned = re.sub(r'^п\.\s*', '', str(value), flags=re.IGNORECASE)
    cleaned = re.sub(r'^punkt\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^point\s*', '', cleaned, flags=re.IGNORECASE)
    
    # Extract only digits
    digits = re.findall(r'\d+', cleaned)
    return ''.join(digits) if digits else ""


def find_all_json_files(answers_dir: Path, folders_to_include: Optional[Set[str]] = None) -> Dict[str, List[Path]]:
    """Find all JSON files and group them by numeric prefix.
    
    Args:
        answers_dir: Root directory to scan
        folders_to_include: Set of folder names to include, or None for all
    """
    grouped_files = defaultdict(list)
    
    for root, _, files in os.walk(answers_dir):
        # Get the model folder name (first subfolder under answers/)
        rel_path = Path(root).relative_to(answers_dir)
        model_folder = rel_path.parts[0] if rel_path.parts else None
        
        # Skip if folder filtering is enabled and this folder is not included
        if folders_to_include and model_folder not in folders_to_include:
            continue
        
        for filename in files:
            if filename.endswith('.json'):
                file_num = extract_file_number(filename)
                if file_num:
                    file_path = Path(root) / filename
                    grouped_files[file_num].append(file_path)
    
    return grouped_files


def load_json_file(file_path: Path) -> Dict[str, Any]:
    """Load and parse a JSON file. Try json_repair if standard json.loads fails."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Handle markdown code blocks
        if content.strip().startswith('```'):
            # Extract JSON from markdown block
            start = content.find('{')
            end = content.rfind('}') + 1
            if start != -1 and end != -1:
                content = content[start:end]

        # First try standard json.loads
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # If fails, try json_repair
            logger.warning(f"Standard JSON parse failed for {file_path}, trying json_repair...")
            repaired = json_repair.repair_json(content)
            data = json.loads(repaired)
            logger.info(f"JSON repaired successfully for {file_path}")

        # json_repair might return a list instead of dict
        if isinstance(data, list):
            logger.warning(f"JSON parsed as list for {file_path}, returning empty dict")
            return {}

        return data
    except Exception as e:
        logger.error(f"Failed to load {file_path}: {e}")
        return {}


def clean_micro_art(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove 'ст.', 'статья' prefixes from art fields."""
    norms = data.get("Norms", [])
    if not isinstance(norms, list):
        return data
    for item in norms:
        if isinstance(item, dict) and 'art' in item:
            item['art'] = re.sub(r'^ст. ', '', str(item['art']))
            item['art'] = re.sub(r'^статья ', '', str(item['art']))
    return data


def abbreviate_act(act_name: str) -> str:
    """Abbreviate act name using ACT_ABBREVIATIONS patterns."""
    for pattern, abbreviation in ACT_ABBREVIATIONS.items():
        if re.match(pattern, act_name, re.IGNORECASE):
            return abbreviation
    return act_name


def abbreviate_act_regex(act_name: str) -> str:
    """Abbreviate act name using ACT_REGEX_PATTERNS."""
    for pattern, abbreviation in ACT_REGEX_PATTERNS.items():
        if re.match(pattern, act_name, re.IGNORECASE):
            return abbreviation
    return act_name


def clean_micro_act(data: Dict[str, Any]) -> Dict[str, Any]:
    """Abbreviate act names using patterns."""
    norms = data.get("Norms", [])
    if not isinstance(norms, list):
        return data
    for item in norms:
        if isinstance(item, dict) and 'act' in item:
            act = str(item['act'])
            act = abbreviate_act(act)
            item['act'] = abbreviate_act_regex(act)
    return data


def clean_micro_number(data: Dict[str, Any]) -> Dict[str, Any]:
    """Clean number fields. For codes, replace date and number with empty strings.
    
    Must be called AFTER clean_micro_act so act names are already normalized.
    """
    norms = data.get("Norms", [])
    if not isinstance(norms, list):
        return data
    for item in norms:
        if isinstance(item, dict) and 'number' in item:
            val = str(item['number'])
            val = re.sub(r'null.*', '', val)
            val = re.sub(r'N/A.*', '', val)
            val = re.sub(r'б/н.*', '', val)
            
            # Check if act is a code - replace date and number with empty
            act = item.get('act', '')  # Already normalized by clean_micro_act
            
            if act in SPISOK_KODEKSOV:
                item['number'] = ''
                item['date'] = ''
            else:
                item['number'] = val
    return data


def normalize_norm(norm: Dict[str, Any]) -> Tuple:
    """Create a hashable key from norm fields for comparison.
    
    Normalizes act name and extracts only digits from art and art_punkt.
    Grouping is based on: normalized_act, date, number, art (digits only), art_punkt (digits only)
    """
    act_name = norm.get('act', '')
    normalized_act = normalize_act_name(act_name)
    
    # Clean article and point fields - extract only digits
    art_clean = clean_article_field(norm.get('art', ''))
    art_punkt_clean = clean_point_field(norm.get('art_punkt', ''))
    
    return (
        normalized_act,
        norm.get('date', ''),
        norm.get('number', ''),
        art_clean,
        art_punkt_clean,
    )


def merge_norms_with_count(file_paths: List[Path], example_id: str) -> List[Dict[str, Any]]:
    """
    Merge norms from multiple files and count occurrences.
    
    Returns a list of norm records with metadata for CSV output.
    """
    norm_counts = defaultdict(lambda: {
        'count': 0, 
        'sources': [], 
        'models': set(),
        'norm_data': None
    })
    
    for file_path in file_paths:
        model = extract_model_from_path(file_path)
        uid = extract_uid(file_path.name)
        data = load_json_file(file_path)
        
        # Process norms in correct order:
        # 1. First clean art (remove prefixes)
        data = clean_micro_art(data)
        # 2. Then normalize act names
        data = clean_micro_act(data)
        # 3. Then clean number/date (for codes, set to empty)
        data = clean_micro_number(data)
        
        norms = data.get('Norms', [])
        
        # Track norms seen in this file to avoid double-counting within same file
        seen_in_file = set()
        
        for norm in norms:
            norm_key = normalize_norm(norm)
            
            if norm_key not in seen_in_file:
                seen_in_file.add(norm_key)
                norm_counts[norm_key]['count'] += 1
                norm_counts[norm_key]['sources'].append(file_path.name)
                norm_counts[norm_key]['models'].add(model)
                
                # Store the norm data (first occurrence)
                if norm_counts[norm_key]['norm_data'] is None:
                    norm_counts[norm_key]['norm_data'] = norm.copy()
                    # Store UID from first source
                    norm_counts[norm_key]['uid'] = uid
    
    # Build result list for CSV
    merged_norms = []
    for norm_key, info in norm_counts.items():
        norm_data = info['norm_data'] if info['norm_data'] else {}

        # Normalize the act name for output
        original_act = norm_data.get('act', '')
        normalized_act = normalize_act_name(original_act)

        # Clean article and point fields - extract only digits for output
        article_clean = clean_article_field(norm_data.get('art', ''))
        point_clean = clean_point_field(norm_data.get('art_punkt', ''))

        # Determine norm type from scope field
        scope = norm_data.get('scope', '')
        norm_type = 'специальный' if scope == 'специальный' else 'общий'

        record = {
            'example_id': example_id,
            'uid': info.get('uid', ''),
            'norm_type': norm_type,
            'norm_number': norm_data.get('number', ''),
            'act': normalized_act,  # Use normalized act name
            'article': article_clean,  # Only digits
            'point': point_clean,  # Only digits
            'date': norm_data.get('date', ''),
            'occurrence_count': info['count'],
            'total_files': len(file_paths),
            'models': ';'.join(sorted(info['models']))
        }
        merged_norms.append(record)
    
    # Sort by occurrence count (descending)
    merged_norms.sort(key=lambda x: x['occurrence_count'], reverse=True)
    
    return merged_norms


def join_all_norms(output_dir: Path = None, folders_to_include: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
    """
    Process all grouped JSON files and create merged CSV outputs.
    
    Args:
        output_dir: Directory to save output files
        folders_to_include: List of folder names to include, or None for all
    
    Returns dict mapping file_number -> merged_result
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "joined_answers"
        output_dir.mkdir(exist_ok=True)
    
    # Convert list to set for faster lookup
    folders_set = set(folders_to_include) if folders_to_include else None
    
    grouped_files = find_all_json_files(ANSWERS_DIR, folders_set)
    results = {}
    
    # Log which folders are being processed
    if folders_set:
        logger.info(f"Including folders: {sorted(folders_set)}")
    else:
        logger.info("Including ALL folders")
    
    logger.info(f"Found {len(grouped_files)} groups of JSON files")
    
    for file_num, file_paths in sorted(grouped_files.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        logger.info(f"Processing group {file_num}: {len(file_paths)} files")
        
        merged = merge_norms_with_count(file_paths, file_num)
        results[file_num] = merged
        
        # Save to CSV file
        output_file = output_dir / f"{file_num}_merged_norms.csv"

        fieldnames = [
            'example_id', 'uid', 'norm_type', 'norm_number',
            'act', 'article', 'point', 'date',
            'occurrence_count', 'total_files', 'models'
        ]
        
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='|')
            writer.writeheader()
            writer.writerows(merged)
        
        logger.info(f"Saved merged result to {output_file}")
    
    return results


def main():
    """Main entry point."""
    logger.info("Starting norm joining process...")
    logger.info(f"Scanning directory: {ANSWERS_DIR}")
    
    # Use configuration from FOLDERS_TO_INCLUDE constant
    # Or override by passing a list to join_all_norms()
    results = join_all_norms(folders_to_include=FOLDERS_TO_INCLUDE)
    
    # Print summary
    total_norms = sum(len(r) for r in results.values())
    logger.info(f"Completed! Processed {len(results)} groups, total {total_norms} unique norms")
    
    # Print detailed summary for first few groups
    for file_num in list(results.keys())[:5]:
        norms = results[file_num]
        logger.info(f"Group {file_num}: {len(norms)} unique norms")
        if norms:
            logger.info(f"  Top norm: {norms[0]['act'][:50]}... (count: {norms[0]['occurrence_count']})")


if __name__ == "__main__":
    main()
