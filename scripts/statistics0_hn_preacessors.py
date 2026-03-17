# statistics0_hn_preacessors.py
# Считаем статистику по статьям и пунктам, без art_part
# Загружаем JSON из папки answers/ текущего проекта

import pandas as pd
from pathlib import Path
from collections import defaultdict
from scripts.join_norms_by_count import (
    find_all_json_files,
    load_json_file,
    normalize_act_name,
    clean_micro_act,
    clean_micro_art,
    clean_micro_number,
    extract_uid,
    FOLDERS_TO_INCLUDE,
    ANSWERS_DIR
)

def main():
    """Main function to calculate statistics."""
    print(f"Starting statistics calculation from {ANSWERS_DIR}")
    print(f"Folders to include: {FOLDERS_TO_INCLUDE or 'ALL'}")
    
    # Find all JSON files
    grouped_files = find_all_json_files(ANSWERS_DIR, set(FOLDERS_TO_INCLUDE) if FOLDERS_TO_INCLUDE else None)
    print(f"Found {len(grouped_files)} unique question IDs")
    
    all_results = []
    
    # Process each question
    for question_id, file_paths in grouped_files.items():
        # Extract UID from first file path
        uid = ""
        if file_paths:
            uid = extract_uid(file_paths[0].name)
        
        counter = defaultdict(int)
        models_name_dct = {}
        
        for file_path in file_paths:
            # Extract model name from path
            parts = file_path.parts
            model = "unknown"
            for i, part in enumerate(parts):
                if part == 'answers' and i + 1 < len(parts):
                    model = parts[i + 1]
                    break
            
            # Load and process JSON
            data = load_json_file(file_path)
            if not data:
                continue
            
            # Clean norms in correct order:
            data = clean_micro_art(data)      # Remove art prefixes
            data = clean_micro_act(data)       # Normalize act names
            data = clean_micro_number(data)    # For codes, clear date/number
            
            norms = data.get('Norms', [])
            seen = set()
            unique_list = []
            
            for norm in norms:
                # Normalize act name
                act = normalize_act_name(norm.get("act", ""))
                
                comparison_tuple = (
                    act,
                    norm.get("date", ""),
                    norm.get("number", ""),
                    norm.get("art", "")
                )
                
                if comparison_tuple not in seen:
                    seen.add(comparison_tuple)
                    unique_list.append(comparison_tuple)
                
                key = str(comparison_tuple)
                if key not in models_name_dct:
                    models_name_dct[key] = [model]
                else:
                    models_name_dct[key].append(model)
            
            for t in unique_list:
                counter[t] += 1
        
        # Build results
        for combo, count in counter.items():
            all_results.append({
                "ID": question_id,
                "uid": uid,
                "act": combo[0],
                "date": combo[1],
                "number": combo[2],
                "art": combo[3],
                "count": count,
                "models": str(models_name_dct[str(combo)])
            })

    # Sort results by question ID (numeric order)
    all_results.sort(key=lambda x: int(x["ID"]) if x["ID"].isdigit() else 0)

    # Create DataFrame and save
    pdf_0 = pd.DataFrame(all_results)
    output_file = ANSWERS_DIR.parent / "statistics0_output.csv"
    pdf_0.to_csv(output_file, index=False, sep='|')
    print(f"Saved {len(pdf_0)} records to {output_file}")
    
    # Print sample
    if len(pdf_0) > 0:
        print(f"Sample output:\n{pdf_0.head(2)}")
        print(f"\nTop acts by count:")
        print(pdf_0['act'].value_counts().head(10))


if __name__ == "__main__":
    main()
