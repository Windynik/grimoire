#!/usr/bin/env python3
"""
Update ManaBox collection CSV with mana value and oracle text from Scryfall API.
"""

import csv
import time
import requests
from typing import Dict, Optional
import sys


def fetch_card_data(scryfall_id: str) -> Optional[Dict]:
    """
    Fetch card data from Scryfall API using the Scryfall ID.
    
    Args:
        scryfall_id: The Scryfall UUID for the card
        
    Returns:
        Dictionary with mana_cost, oracle_text, and type_line, or None if request fails
    """
    url = f"https://api.scryfall.com/cards/{scryfall_id}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        return {
            'mana_cost': data.get('mana_cost', ''),  # e.g., {2}{U}{B}
            'oracle_text': data.get('oracle_text', ''),
            'type_line': data.get('type_line', '')
        }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching card {scryfall_id}: {e}")
        return None


def update_collection_csv(input_file: str, output_file: str):
    """
    Read ManaBox CSV, fetch card data from Scryfall, and write updated CSV.
    
    Args:
        input_file: Path to input CSV file
        output_file: Path to output CSV file
    """
    rows = []
    
    # Read the CSV file
    print(f"Reading {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        
        # Add new columns if they don't exist
        new_headers = list(headers)
        if 'Mana Cost' not in new_headers:
            new_headers.append('Mana Cost')
        if 'Oracle Text' not in new_headers:
            new_headers.append('Oracle Text')
        if 'Type Line' not in new_headers:
            new_headers.append('Type Line')
        
        for row in reader:
            rows.append(row)
    
    total_cards = len(rows)
    print(f"Found {total_cards} cards in collection")
    print("Fetching card data from Scryfall API...")
    print("Note: This will take some time due to API rate limiting (10 requests per second)")
    
    # Update each row with Scryfall data
    for i, row in enumerate(rows, 1):
        scryfall_id = row.get('Scryfall ID', '')
        card_name = row.get('Name', 'Unknown')
        
        if not scryfall_id:
            print(f"[{i}/{total_cards}] Skipping {card_name} - no Scryfall ID")
            row['Mana Cost'] = ''
            row['Oracle Text'] = ''
            row['Type Line'] = ''
            continue
        
        print(f"[{i}/{total_cards}] Fetching {card_name}...", end=' ')
        
        card_data = fetch_card_data(scryfall_id)
        
        if card_data:
            row['Mana Cost'] = card_data['mana_cost']
            row['Oracle Text'] = card_data['oracle_text']
            row['Type Line'] = card_data['type_line']
            print("✓")
        else:
            row['Mana Cost'] = ''
            row['Oracle Text'] = ''
            row['Type Line'] = ''
            print("✗")
        
        # Respect Scryfall's rate limit (100ms between requests = 10 req/sec)
        # Being extra conservative with 150ms delay
        if i < total_cards:
            time.sleep(0.11)
    
    # Write the updated CSV
    print(f"\nWriting updated data to {output_file}...")
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_headers)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"✓ Successfully updated {total_cards} cards!")
    print(f"Output saved to: {output_file}")


def main():
    """Main entry point."""
    input_file = 'ManaBox_Collection.csv'
    output_file = 'ManaBox_Collection_Updated.csv'
    
    print("=" * 60)
    print("MTG Collection Updater - Scryfall API")
    print("=" * 60)
    
    try:
        update_collection_csv(input_file, output_file)
    except FileNotFoundError:
        print(f"Error: Could not find input file: {input_file}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
