"""Test the /app4/all-events-2026 endpoint"""
import sys
import pandas as pd
from pathlib import Path

# Add Main to path
sys.path.insert(0, str(Path(__file__).parent / "Main"))

# Test the endpoint logic directly
prepared_data_path = Path(__file__).parent / "Main" / "app4" / "Data" / "final_hazard_dataset.csv"

print(f"📋 Testing All Events 2026 Endpoint")
print(f"🔍 Data file: {prepared_data_path}")
print(f"📁 Exists: {prepared_data_path.exists()}\n")

if prepared_data_path.exists():
    # Load and inspect
    df = pd.read_csv(prepared_data_path)
    print(f"📊 Total rows in dataset: {len(df)}")
    print(f"📋 Columns: {list(df.columns)}")
    print(f"📅 Years available: {sorted(df['year'].unique()) if 'year' in df.columns else 'N/A'}\n")
    
    # Filter for 2026
    if 'year' in df.columns:
        df_2026 = df[df['year'] == 2026]
        print(f"✅ Events in 2026: {len(df_2026)}")
        
        if len(df_2026) > 0:
            print(f"\n📍 Sample 2026 events:")
            print(df_2026[['Event_type', 'lat', 'lon', 'intensity', 'year']].head(10))
            
            # Check coordinates
            print(f"\n🧭 Lat range: {df_2026['lat'].min():.2f} to {df_2026['lat'].max():.2f}")
            print(f"🧭 Lon range: {df_2026['lon'].min():.2f} to {df_2026['lon'].max():.2f}")
            
            # Event type distribution
            print(f"\n📊 Event types in 2026:")
            print(df_2026['Event_type'].value_counts())
        else:
            print("❌ No 2026 events found!")
    else:
        print("❌ 'year' column not found!")
else:
    print("❌ Data file not found!")
