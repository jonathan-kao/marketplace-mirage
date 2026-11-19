#!/usr/bin/env python3
"""
simple_crawler.py

A simplified version of the GitHub Actions Marketplace crawler that only collects
action slugs as a set without any metadata tracking.

Features:
- Collects only action slugs (no isVerifiedOwner, discovered_at, category_pages)
- Stores slugs as a simple set in JSON
- Async processing for better performance
- Minimal file structure: {"action_slugs": [...], "total_action_slugs": count}
- Much faster and uses less memory than the full crawler
"""

import requests
from lxml import html
import json
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime

class SimpleActionCrawler:
    def __init__(self, max_categories=None, max_pages=None, max_workers=6):
        self.base_url = "https://github.com"
        self.marketplace_url = "https://github.com/marketplace?type=actions"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Simple data structures
        self.action_slugs = set()  # Just a set of slugs
        self.categories = {}  # category_slug -> total_pages
        self.categories_list = []  # Ordered list of categories for sequential processing
        
        # Progress tracking
        self.current_progress = [0, 0]  # [category_index, page_number]
        
        # Configuration
        self.max_categories = max_categories
        self.max_pages = max_pages
        self.max_workers = max_workers
        
        # Output file
        self.output_file = "1.marketplace_slugs.json"
        
        # Load existing slugs if file exists
        self.load_existing_slugs()
    
    def load_existing_slugs(self):
        """Load existing action slugs from file if it exists"""
        try:
            with open(self.output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            existing_slugs = data.get("action_slugs", [])
            self.action_slugs = set(existing_slugs)
            
            # Load progress tracking
            self.current_progress = data.get("current_progress", [0, 0])
            
            print(f"Loaded {len(self.action_slugs)} existing action slugs from {self.output_file}")
            print(f"Progress: Category {self.current_progress[0]}, Page {self.current_progress[1]}")
            
        except FileNotFoundError:
            print(f"No existing file found. Starting fresh.")
            self.action_slugs = set()
            self.current_progress = [0, 0]
        except Exception as e:
            print(f"Error loading existing slugs: {e}. Starting fresh.")
            self.action_slugs = set()
            self.current_progress = [0, 0]
    
    def save_slugs(self, save_reason="periodic"):
        """Save action slugs to JSON file with progress tracking"""
        data = {
            "crawl_started": datetime.datetime.now().isoformat(),
            "action_slugs": sorted(list(self.action_slugs)),  # Convert set to sorted list for JSON
            "total_action_slugs": len(self.action_slugs),
            "current_progress": self.current_progress,  # [category_index, page_number]
            "last_updated": datetime.datetime.now().isoformat(),
            "save_reason": save_reason
        }
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"Saved {len(self.action_slugs)} action slugs to {self.output_file} (reason: {save_reason})")
        print(f"Progress: Category {self.current_progress[0]}, Page {self.current_progress[1]}")
    
    def safe_request(self, url, max_retries=3, base_delay=1):
        """Make a safe HTTP request with retry logic and rate limiting"""
        for attempt in range(max_retries):
            try:
                # Add random delay to avoid rate limiting
                if attempt > 0:
                    delay = base_delay * (2 ** attempt) + random.uniform(1, 3)
                    print(f"    Waiting {delay:.1f}s before retry {attempt + 1}...")
                    time.sleep(delay)
                else:
                    # Initial delay to be respectful
                    time.sleep(random.uniform(0.5, 2.0))
                
                response = self.session.get(url, timeout=15)
                
                if response.status_code == 429:
                    # Rate limited - save progress immediately
                    print(f"    Rate limited (429). Saving progress...")
                    self.save_slugs("rate_limit_429")
                    
                    wait_time = random.uniform(30, 60)  # Longer wait for rate limits
                    print(f"    Waiting {wait_time:.1f}s for rate limit...")
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                print(f"    Request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    # Save progress before giving up
                    print(f"    Saving progress before failing...")
                    self.save_slugs("request_failed")
                    raise
                    
        return None
    
    def get_total_pages_for_category(self, category_slug):
        """Get total pages for a given category"""
        url = f"{self.marketplace_url}&category={category_slug}"
        print(f"  Fetching page count for category: {category_slug}")
        response = self.safe_request(url)
        if not response:
            return 0
        
        tree = html.fromstring(response.content)
        script_elements = tree.xpath(
            '//script[@type="application/json"][@data-target="react-app.embeddedData"]'
        )

        if not script_elements:
            print("Error: Could not find the embedded data")
            return 0
        
        json_str = script_elements[0].text_content()
        embedded_data = json.loads(json_str)
        payload = embedded_data.get('payload', {})
        search_results = payload.get('searchResults', {})
        total_pages = search_results.get('totalPages', 0)
        
        return total_pages
    
    def get_categories(self):
        """Get all action categories from the marketplace page"""
        print("Fetching categories...")
        response = self.safe_request(self.marketplace_url)
        if not response:
            print("Failed to fetch categories after retries")
            return
        
        tree = html.fromstring(response.content)
        script_elements = tree.xpath(
            '//script[@type="application/json"][@data-target="react-app.embeddedData"]'
        )

        if not script_elements:
            print("Error: Could not find the embedded data")
            return
        
        json_str = script_elements[0].text_content()
        embedded_data = json.loads(json_str)
        payload = embedded_data.get('payload', {})
        actions_categories = payload.get('categories', {}).get('actions', [])
        
        # Apply max_categories limit if specified
        if self.max_categories:
            actions_categories = actions_categories[:self.max_categories]
            print(f"Limited to first {self.max_categories} categories")
        
        # Prepare category data for sequential processing
        category_data = [(item.get('slug'), item.get('description_html', 'N/A').strip()) 
                        for item in actions_categories]
        
        # Store categories in order for progress tracking
        self.categories_list = [slug for slug, desc in category_data]
        
        print(f"Processing {len(category_data)} categories with {self.max_workers} workers...")
        
        # Use ThreadPoolExecutor to fetch page counts concurrently
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_category = {
                executor.submit(self.get_total_pages_for_category, slug): (slug, desc)
                for slug, desc in category_data
            }
            
            for future in as_completed(future_to_category):
                slug, desc = future_to_category[future]
                try:
                    total_pages = future.result()
                    self.categories[slug] = total_pages
                    print(f"  Completed category: {slug} ({total_pages} pages)")
                except Exception as e:
                    print(f"  Error processing category {slug}: {e}")
                    self.categories[slug] = 0
    
    def _fetch_page_data(self, category_slug, page):
        """Helper method to fetch and parse data from a single page"""
        url = f"{self.marketplace_url}&category={category_slug}&page={page}"
        response = self.safe_request(url)
        if not response:
            return []
            
        tree = html.fromstring(response.content)
        script_elements = tree.xpath(
            '//script[@type="application/json"][@data-target="react-app.embeddedData"]'
        )
        
        if not script_elements:
            return []
        
        json_str = script_elements[0].text_content()
        embedded_data = json.loads(json_str)
        payload = embedded_data.get('payload', {})
        search_results = payload.get('searchResults', {})
        results = search_results.get('results', [])
        
        # Extract only the slugs
        slugs = []
        for item in results:
            slug = item.get('slug')
            if slug:
                slugs.append(slug)
        
        return slugs
    
    def crawl_category_hybrid(self, category_slug, total_pages, category_index):
        """Crawl category with async pages but sequential progress tracking"""
        pages_to_crawl = total_pages
        if self.max_pages:
            pages_to_crawl = min(total_pages, self.max_pages)
        
        print(f"  Crawling category {category_slug}: {pages_to_crawl} pages with {self.max_workers} async workers")
        
        # Determine starting page based on progress
        start_page = 1
        if category_index == self.current_progress[0]:
            start_page = max(1, self.current_progress[1])  # Resume from saved page
            if start_page > 1:
                print(f"    Resuming from page {start_page}")
        
        # Create page list for async processing
        pages_to_process = list(range(start_page, pages_to_crawl + 1))
        
        if not pages_to_process:
            print(f"    No pages to process for category {category_slug}")
            return 0
        
        new_slugs_count = 0
        completed_pages = []
        
        # Use ThreadPoolExecutor for async page processing
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all page tasks
            future_to_page = {
                executor.submit(self._fetch_page_data_with_progress, category_slug, page, category_index): page
                for page in pages_to_process
            }
            
            # Process results as they complete (async)
            for future in as_completed(future_to_page):
                page = future_to_page[future]
                try:
                    page_slugs, page_new_slugs = future.result()
                    
                    if page_slugs is not None:
                        new_slugs_count += page_new_slugs
                        completed_pages.append(page)
                        print(f"      Page {page}: {len(page_slugs)} total, {page_new_slugs} new slugs")
                        
                        # Update progress to highest completed page
                        max_completed = max(completed_pages)
                        self.current_progress = [category_index, max_completed]
                        
                        # Save progress periodically (every 10 completed pages)
                        if len(completed_pages) % 10 == 0:
                            self.save_slugs("async_progress_save")
                    else:
                        print(f"      Page {page}: Failed to fetch")
                        
                except Exception as e:
                    print(f"    Error processing page {page}: {e}")
                    # Save progress on error
                    if completed_pages:
                        max_completed = max(completed_pages)
                        self.current_progress = [category_index, max_completed]
                        self.save_slugs("async_page_error")
        
        # Mark category as completed
        self.current_progress = [category_index + 1, 0]
        
        print(f"  Category {category_slug} completed: {new_slugs_count} new slugs found")
        return new_slugs_count
    
    def _fetch_page_data_with_progress(self, category_slug, page, category_index):
        """Fetch page data and update slugs atomically"""
        try:
            page_slugs = self._fetch_page_data(category_slug, page)
            
            if not page_slugs:
                return None, 0
            
            # Process slugs and count new ones
            page_new_slugs = 0
            for slug in page_slugs:
                if slug not in self.action_slugs:
                    self.action_slugs.add(slug)
                    page_new_slugs += 1
            
            return page_slugs, page_new_slugs
            
        except Exception as e:
            # Re-raise to be handled by caller
            raise e
    
    def crawl(self):
        """Main crawl method"""
        print("=== Simple Action Crawler Started ===")
        
        # Get all categories
        self.get_categories()
        
        print(f"\n=== Categories Found ===")
        for idx, (slug, total_pages) in enumerate(self.categories.items(), 1):
            print(f"{idx}. {slug} (Total Pages: {total_pages})")
        print(f"=== Total: {len(self.categories)} categories ===")
        
        # Crawl each category sequentially with progress tracking
        total_new_slugs = 0
        initial_count = len(self.action_slugs)
        
        # Determine starting category based on progress
        start_category_index = self.current_progress[0]
        if start_category_index > 0:
            print(f"Resuming from category index {start_category_index}")
        
        for idx in range(start_category_index, len(self.categories_list)):
            category_slug = self.categories_list[idx]
            total_pages = self.categories.get(category_slug, 0)
            
            print(f"\n[{idx + 1}/{len(self.categories_list)}] Crawling category: {category_slug}")
            
            try:
                new_slugs_count = self.crawl_category_hybrid(category_slug, total_pages, idx)
                total_new_slugs += new_slugs_count
                
                print(f"  Progress: {len(self.action_slugs)} total slugs (+{new_slugs_count} from this category)")
                
                # Save progress after each category
                self.save_slugs("category_completed")
                
            except Exception as e:
                print(f"  Error crawling category {category_slug}: {e}")
                # Save progress even on error
                self.save_slugs("category_error")
        
        # Final save
        self.save_slugs("crawl_completed")
        
        print(f"\n=== Crawl Completed ===")
        print(f"Initial slugs: {initial_count}")
        print(f"Final slugs: {len(self.action_slugs)}")
        print(f"New slugs found: {total_new_slugs}")
        print(f"Results saved to: {self.output_file}")


if __name__ == "__main__":
    # Configuration
    MAX_CATEGORIES = None  # Set to a number to limit categories for testing
    MAX_PAGES = None       # Set to a number to limit pages per category for testing
    MAX_WORKERS = 6        # Number of concurrent workers
    
    print("=== Simple GitHub Actions Marketplace Crawler ===")
    print("This crawler only collects action slugs without metadata")
    print(f"Configuration: max_categories={MAX_CATEGORIES}, max_pages={MAX_PAGES}, max_workers={MAX_WORKERS}")
    
    # Create and run crawler
    crawler = SimpleActionCrawler(
        max_categories=MAX_CATEGORIES,
        max_pages=MAX_PAGES,
        max_workers=MAX_WORKERS
    )
    
    start_time = time.time()
    crawler.crawl()
    end_time = time.time()
    
    print(f"\nTotal execution time: {end_time - start_time:.2f} seconds")