#!/usr/bin/env python3
"""
sort_actions_by_verification.py

Separates GitHub Actions from 2.action_repos_data.json into verified and unverified,
sorted by stars (most to least), and outputs in format: owner/name
"""

import json


def sort_actions_by_verification():
    input_file = "2.action_repos_data.json"
    output_file = "3.categorized_sorted_repos.json"
    
    # Load data
    print(f"Loading data from {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    actions = data.get("actions", {})
    print(f"Found {len(actions)} actions")
    
    # Separate into verified and unverified
    # Use dictionaries to track unique repos and keep highest star count
    verified_dict = {}  # owner/name -> stars
    unverified_dict = {}  # owner/name -> stars
    
    for slug, action_data in actions.items():
        repository = action_data.get("repository", {})
        owner = repository.get("owner", "")
        name = repository.get("name", "")
        stars = action_data.get("stars", 0)
        is_verified = action_data.get("isVerifiedOwner", False)
        
        # Create owner/name format
        if owner and name:
            owner_name = f"{owner}/{name}"
            
            if is_verified:
                # Keep the entry with higher stars if duplicate exists
                if owner_name not in verified_dict or stars > verified_dict[owner_name]:
                    verified_dict[owner_name] = stars
            else:
                # Keep the entry with higher stars if duplicate exists
                if owner_name not in unverified_dict or stars > unverified_dict[owner_name]:
                    unverified_dict[owner_name] = stars
    
    # Convert to list of entries
    verified = [{"name": name, "stars": stars} for name, stars in verified_dict.items()]
    unverified = [{"name": name, "stars": stars} for name, stars in unverified_dict.items()]
    
    print(f"After deduplication: {len(verified)} verified, {len(unverified)} unverified")
    
    # Sort by stars (descending)
    verified.sort(key=lambda x: x["stars"], reverse=True)
    unverified.sort(key=lambda x: x["stars"], reverse=True)
    
    # Extract just the names
    verified_names = [entry["name"] for entry in verified]
    unverified_names = [entry["name"] for entry in unverified]
    
    # Create output structure
    output_data = {
        "verified": verified_names,
        "unverified": unverified_names,
        "stats": {
            "total_verified": len(verified_names),
            "total_unverified": len(unverified_names),
            "total_actions": len(verified_names) + len(unverified_names)
        }
    }
    
    # Save to file
    print(f"\nSaving to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print("SORTING COMPLETE!")
    print(f"{'='*60}")
    print(f"Verified actions: {len(verified_names)}")
    print(f"Unverified actions: {len(unverified_names)}")
    print(f"Total: {len(verified_names) + len(unverified_names)}")
    print(f"\nOutput saved to: {output_file}")
    
    # Show top 5 from each category
    print(f"\nTop 5 Verified (by stars):")
    for i, entry in enumerate(verified[:5], 1):
        print(f"  {i}. {entry['name']} - {entry['stars']} stars")
    
    print(f"\nTop 5 Unverified (by stars):")
    for i, entry in enumerate(unverified[:5], 1):
        print(f"  {i}. {entry['name']} - {entry['stars']} stars")


if __name__ == "__main__":
    print("="*60)
    print("GitHub Actions Verification Sorter")
    print("="*60)
    sort_actions_by_verification()
