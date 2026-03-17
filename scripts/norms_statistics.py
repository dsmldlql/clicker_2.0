#!/usr/bin/env python3
"""
Calculate and display statistics for merged norms data.

Shows:
- Total norms count
- Most frequently cited acts (НПА)
- Distribution by occurrence count
- Model coverage statistics
"""

import csv
import os
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Any
from scripts.logger_config import setup_logging

logger = setup_logging(__name__)

JOINED_ANSWERS_DIR = Path(__file__).parent.parent / "joined_answers"


def load_all_merged_csvs(joined_dir: Path) -> List[Dict[str, Any]]:
    """Load all merged CSV files and combine into single list."""
    all_norms = []
    
    for filename in sorted(joined_dir.glob("*_merged_norms.csv")):
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['source_file'] = filename.name
                all_norms.append(row)
    
    return all_norms


def calculate_statistics(norms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate comprehensive statistics from norms data."""
    
    # Act name statistics
    act_counter = Counter()
    act_with_articles = defaultdict(set)
    
    # Occurrence distribution
    occurrence_distribution = Counter()
    
    # Model statistics
    model_norm_count = defaultdict(int)
    model_examples = defaultdict(set)
    
    # Norm type distribution
    norm_type_counter = Counter()
    
    for norm in norms:
        act = norm.get('act', 'Unknown')
        article = norm.get('article', '')
        occurrence = int(norm.get('occurrence_count', 0))
        models = norm.get('models', '').split(';')
        norm_type = norm.get('norm_type', 'unknown')
        example_id = norm.get('example_id', '')
        
        # Count acts
        act_counter[act] += 1
        if article:
            act_with_articles[act].add(article)
        
        # Occurrence distribution
        occurrence_distribution[occurrence] += 1
        
        # Model statistics
        for model in models:
            if model:
                model_norm_count[model] += 1
                model_examples[model].add(example_id)
        
        # Norm type
        norm_type_counter[norm_type] += 1
    
    return {
        'total_norms': len(norms),
        'unique_acts': len(act_counter),
        'act_counter': act_counter.most_common(20),
        'act_with_articles': {k: len(v) for k, v in act_with_articles.items()},
        'occurrence_distribution': dict(sorted(occurrence_distribution.items())),
        'model_stats': {
            model: {
                'norm_count': count,
                'examples': len(model_examples[model])
            }
            for model, count in model_norm_count.items()
        },
        'norm_type_distribution': dict(norm_type_counter)
    }


def print_statistics(stats: Dict[str, Any]):
    """Print formatted statistics report."""
    
    print("\n" + "=" * 80)
    print("СТАТИСТИКА НОРМАТИВНО-ПРАВОВЫХ АКТОВ")
    print("=" * 80)
    
    print(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
    print(f"   Всего норм: {stats['total_norms']:,}")
    print(f"   Уникальных актов (НПА): {stats['unique_acts']}")
    
    print(f"\n📚 ТОП-20 НАИБОЛЕЕ ЧАСТЫХ АКТОВ:")
    print("-" * 80)
    print(f"{'№':<3} {'Название акта':<50} {'Кол-во норм':<12}")
    print("-" * 80)
    for i, (act, count) in enumerate(stats['act_counter'], 1):
        act_display = act[:47] + "..." if len(act) > 50 else act
        print(f"{i:<3} {act_display:<50} {count:<12}")
    
    print(f"\n📈 РАСПРЕДЕЛЕНИЕ ПО ВСТРЕЧАЕМОСТИ (occurrence_count):")
    print("-" * 60)
    print(f"{'Вхождений':<15} {'Кол-во норм':<15}")
    print("-" * 60)
    for occurrence, count in stats['occurrence_distribution'].items():
        print(f"{occurrence:<15} {count:<15}")
    
    print(f"\n🤖 СТАТИСТИКА ПО МОДЕЛЯМ:")
    print("-" * 80)
    print(f"{'Модель':<35} {'Норм':<10} {'Примеров':<10}")
    print("-" * 80)
    for model, data in sorted(stats['model_stats'].items(), key=lambda x: x[1]['norm_count'], reverse=True):
        print(f"{model:<35} {data['norm_count']:<10} {data['examples']:<10}")
    
    print(f"\n📋 ТИПЫ НОРМ:")
    print("-" * 40)
    for norm_type, count in stats['norm_type_distribution'].items():
        print(f"   {norm_type}: {count:,}")
    
    print("\n" + "=" * 80)


def main():
    """Main entry point."""
    logger.info(f"Loading merged CSV files from {JOINED_ANSWERS_DIR}")
    
    if not JOINED_ANSWERS_DIR.exists():
        logger.error(f"Directory {JOINED_ANSWERS_DIR} does not exist")
        return
    
    norms = load_all_merged_csvs(JOINED_ANSWERS_DIR)
    logger.info(f"Loaded {len(norms):,} norms from CSV files")
    
    stats = calculate_statistics(norms)
    print_statistics(stats)
    
    # Save summary to file
    summary_file = JOINED_ANSWERS_DIR / "statistics_summary.txt"
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("СТАТИСТИКА НОРМАТИВНО-ПРАВОВЫХ АКТОВ\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Всего норм: {stats['total_norms']:,}\n")
        f.write(f"Уникальных актов: {stats['unique_acts']}\n\n")
        
        f.write("ТОП-20 АКТОВ:\n")
        f.write("-" * 80 + "\n")
        for i, (act, count) in enumerate(stats['act_counter'], 1):
            f.write(f"{i}. {act}: {count} норм\n")
    
    logger.info(f"Summary saved to {summary_file}")


if __name__ == "__main__":
    main()
