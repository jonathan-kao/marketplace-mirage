#!/usr/bin/env python3
"""
batch_repo_crawler.py

Fetches action data for slugs from 1.marketplace_slugs.json in batches.
Saves progress after each batch and skips already processed slugs.
"""

import asyncio
import json
import aiohttp
from selectolax.parser import HTMLParser
import datetime
import time
from pathlib import Path


class BatchRepoCrawler:
    def __init__(self, batch_size=50, max_concurrent=10, output_file="2.action_repos_data.json"):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.output_file = output_file
        self.slugs_file = "1.marketplace_slugs.json"
        
        # Data structures
        self.all_slugs = []
        self.processed_data = {}  # slug -> action_data
        self.failed_slugs = []
        
        # Load existing data
        self.load_existing_data()
        self.load_slugs()
    
    def load_slugs(self):
        """Load slugs from 1.marketplace_slugs.json"""
        try:
            with open(self.slugs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.all_slugs = data.get("action_slugs", [])
            print(f"Loaded {len(self.all_slugs)} slugs from {self.slugs_file}")
        except FileNotFoundError:
            print(f"Error: {self.slugs_file} not found!")
            self.all_slugs = []
        except Exception as e:
            print(f"Error loading slugs: {e}")
            self.all_slugs = []
    
    def load_existing_data(self):
        """Load existing processed data from output file"""
        if Path(self.output_file).exists():
            try:
                with open(self.output_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.processed_data = data.get("actions", {})
                self.failed_slugs = data.get("failed_slugs", [])
                
                print(f"Loaded {len(self.processed_data)} existing processed actions")
                print(f"Loaded {len(self.failed_slugs)} failed slugs")
            except Exception as e:
                print(f"Error loading existing data: {e}. Starting fresh.")
                self.processed_data = {}
                self.failed_slugs = []
        else:
            print(f"No existing {self.output_file} found. Starting fresh.")
            self.processed_data = {}
            self.failed_slugs = []
    
    def save_data(self, batch_num=None):
        """Save processed data to JSON file"""
        data = {
            "last_updated": datetime.datetime.now().isoformat(),
            "total_slugs": len(self.all_slugs),
            "processed_count": len(self.processed_data),
            "failed_count": len(self.failed_slugs),
            "remaining_count": len(self.all_slugs) - len(self.processed_data),
            "batch_number": batch_num,
            "actions": self.processed_data,
            "failed_slugs": self.failed_slugs
        }
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*60}")
        print(f"Saved batch {batch_num} to {self.output_file}")
        print(f"Total processed: {len(self.processed_data)}/{len(self.all_slugs)}")
        print(f"Failed: {len(self.failed_slugs)}")
        print(f"Remaining: {data['remaining_count']}")
        print(f"{'='*60}\n")
    
    async def fetch_action_data(self, session, slug, semaphore):
        """Fetch data for a single action slug"""
        async with semaphore:
            url = f"https://github.com/marketplace/actions/{slug}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        text = await response.text()
                        tree = HTMLParser(text)
                        node = tree.css_first('script[type="application/json"][data-target="react-app.embeddedData"]')
                        
                        if node:
                            action = json.loads(node.text())
                            payload = action.get('payload', {})
                            action_data = payload.get('action', {})
                            repo_data = payload.get('repository', {})
                            
                            cleaned_data = {
                                "slug": slug,
                                "id": action_data.get('id'),
                                "name": action_data.get('name'),
                                "ownerLogin": action_data.get('ownerLogin'),
                                "description": action_data.get('description'),
                                "categories": action_data.get('categories', []),
                                "stars": action_data.get('stars', 0),
                                "isVerifiedOwner": action_data.get('isVerifiedOwner', False),
                                "repository": {
                                    "name": repo_data.get('name'),
                                    "owner": repo_data.get('owner', action_data.get('ownerLogin')),
                                    "isOrganization": repo_data.get('isOrganization', False),
                                    "isThirdParty": repo_data.get('isThirdParty', True)
                                },
                                "fetched_at": datetime.datetime.now().isoformat()
                            }
                            
                            return slug, cleaned_data, None
                        else:
                            return slug, None, "No data node found"
                    else:
                        return slug, None, f"HTTP {response.status}"
            
            except asyncio.TimeoutError:
                return slug, None, "Timeout"
            except Exception as e:
                return slug, None, str(e)
    
    async def process_batch(self, batch_slugs, batch_num):
        """Process a batch of slugs"""
        print(f"\nProcessing batch {batch_num} ({len(batch_slugs)} slugs)...")
        
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async with aiohttp.ClientSession(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }
        ) as session:
            tasks = [self.fetch_action_data(session, slug, semaphore) for slug in batch_slugs]
            results = await asyncio.gather(*tasks)
        
        # Process results
        success_count = 0
        fail_count = 0
        
        for slug, data, error in results:
            if data:
                self.processed_data[slug] = data
                success_count += 1
                # Remove from failed list if it was previously failed but now succeeded
                if slug in self.failed_slugs:
                    self.failed_slugs.remove(slug)
                    print(f"  Recovered: {slug} (was previously failed)")
            else:
                if slug not in self.failed_slugs:
                    self.failed_slugs.append(slug)
                fail_count += 1
                print(f"  Failed: {slug} - {error}")
        
        print(f"Batch {batch_num} complete: {success_count} success, {fail_count} failed")
        
        # Save after each batch
        self.save_data(batch_num)
    
    async def crawl_all(self):
        """Crawl all slugs in batches"""
        # Filter out already processed slugs (but include failed ones for retry)
        unprocessed_slugs = [
            slug for slug in self.all_slugs 
            if slug not in self.processed_data
        ]
        
        # Count how many are retries
        retry_count = sum(1 for slug in unprocessed_slugs if slug in self.failed_slugs)
        
        print(f"\nTotal slugs: {len(self.all_slugs)}")
        print(f"Already processed: {len(self.processed_data)}")
        print(f"To process: {len(unprocessed_slugs)}")
        print(f"  - New slugs: {len(unprocessed_slugs) - retry_count}")
        print(f"  - Retrying failed: {retry_count}")
        print(f"Batch size: {self.batch_size}")
        print(f"Max concurrent requests: {self.max_concurrent}\n")
        
        if not unprocessed_slugs:
            if self.failed_slugs:
                print(f"All new slugs processed! {len(self.failed_slugs)} slugs remain failed.")
            else:
                print("All slugs have been processed!")
            return
        
        # Process in batches
        total_batches = (len(unprocessed_slugs) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(unprocessed_slugs), self.batch_size):
            batch_slugs = unprocessed_slugs[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            
            print(f"\n{'='*60}")
            print(f"Starting batch {batch_num}/{total_batches}")
            print(f"{'='*60}")
            
            await self.process_batch(batch_slugs, batch_num)
            
            # Small delay between batches to be polite
            if i + self.batch_size < len(unprocessed_slugs):
                await asyncio.sleep(2)
        
        print("\n" + "="*60)
        print("CRAWLING COMPLETE!")
        print("="*60)
        print(f"Total processed: {len(self.processed_data)}")
        print(f"Total failed: {len(self.failed_slugs)}")
        print(f"Success rate: {len(self.processed_data) / len(self.all_slugs) * 100:.2f}%")


async def main():
    # Configuration
    BATCH_SIZE = 50  # Process 50 slugs per batch
    MAX_CONCURRENT = 10  # Max 10 concurrent requests
    OUTPUT_FILE = "2.action_repos_data.json"
    
    crawler = BatchRepoCrawler(
        batch_size=BATCH_SIZE,
        max_concurrent=MAX_CONCURRENT,
        output_file=OUTPUT_FILE
    )
    
    await crawler.crawl_all()


if __name__ == "__main__":
    print("="*60)
    print("GitHub Actions Batch Repository Crawler")
    print("="*60)
    
    asyncio.run(main())
