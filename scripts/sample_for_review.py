# scripts/sample_for_review.py
import pandas as pd
import os

def create_sample_batch(source_path, target_path, n=50):
    if not os.path.exists(source_path):
        print(f"Source {source_path} not found!")
        return

    # Read the raw JSONL
    df = pd.read_json(source_path, lines=True)
    
    # Take a random sample
    sample = df.sample(n=min(n, len(df)))
    
    # Ensure directory exists and save
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    sample.to_json(target_path, orient='records', lines=True)
    print(f"✅ Created sample batch with {len(sample)} records at {target_path}")

if __name__ == "__main__":
    # Example: Sampling from your 'pass' file
    create_sample_batch("data/raw/pass.jsonl", "data/staging/review_batch.jsonl")