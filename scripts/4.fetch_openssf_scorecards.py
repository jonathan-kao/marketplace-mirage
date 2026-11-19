#!/usr/bin/env python3
"""
fetch_openssf_scorecards.py

Fetches OpenSSF Scorecards for top N verified and unverified GitHub Actions.
First tries the OpenSSF API for pre-calculated scorecards, falls back to CLI if needed.
"""

import json
import asyncio
import aiohttp
import subprocess
import sys
from pathlib import Path
from datetime import datetime


class ScorecardFetcher:
    def __init__(self, top_n=10, max_concurrent=20):
        self.top_n = top_n
        self.max_concurrent = max_concurrent  # Number of concurrent API requests
        self.input_file = "3.categorized_sorted_repos.json"
        self.output_file = "4.openssf_scorecards_results.json"
        
        # OpenSSF Scorecard API endpoint
        self.api_base = "https://api.securityscorecards.dev/projects/github.com"
        
        self.results = {
            "verified": {},
            "unverified": {},
            "stats": {
                "verified_total": 0,
                "verified_api_success": 0,
                "verified_cli_success": 0,
                "verified_failed": 0,
                "unverified_total": 0,
                "unverified_api_success": 0,
                "unverified_cli_success": 0,
                "unverified_failed": 0
            }
        }
        
        # Lock for thread-safe file writing
        self.save_lock = asyncio.Lock()
    
    def load_repos(self):
        """Load repository list from JSON"""
        print(f"Loading repositories from {self.input_file}...")
        with open(self.input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        verified = data.get("verified", [])[:self.top_n]
        unverified = data.get("unverified", [])[:self.top_n]
        
        print(f"Selected top {self.top_n} verified repos")
        print(f"Selected top {self.top_n} unverified repos")
        
        return verified, unverified
    
    async def fetch_scorecard_api(self, session, owner, repo):
        """Try to fetch pre-calculated scorecard from OpenSSF API"""
        url = f"{self.api_base}/{owner}/{repo}"
        
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data, "api"
                elif response.status == 404:
                    return None, "not_found"
                else:
                    return None, f"api_error_{response.status}"
        except asyncio.TimeoutError:
            return None, "timeout"
        except Exception as e:
            return None, f"error: {str(e)}"
    
    def fetch_scorecard_cli(self, owner, repo):
        """Fetch fresh scorecard using CLI"""
        repo_url = f"https://github.com/{owner}/{repo}"
        
        try:
            print(f"    Running CLI for {owner}/{repo}...")
            
            # Run scorecard CLI
            result = subprocess.run(
                ["scorecard", "--repo", repo_url, "--format", "json"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data, "cli"
            else:
                return None, f"cli_error: {result.stderr[:100]}"
        
        except FileNotFoundError:
            return None, "cli_not_installed"
        except subprocess.TimeoutExpired:
            return None, "cli_timeout"
        except json.JSONDecodeError:
            return None, "cli_invalid_json"
        except Exception as e:
            return None, f"cli_error: {str(e)}"
    
    async def fetch_scorecard(self, session, repo_full_name, category):
        """Fetch scorecard for a repo (try API first, then CLI)"""
        owner, repo = repo_full_name.split('/', 1)
        
        print(f"\n[{category.upper()}] Processing {owner}/{repo}")
        
        # Try API first
        print(f"  Trying API...")
        data, method = await self.fetch_scorecard_api(session, owner, repo)
        
        # If API fails or returns not found, try CLI (but skip if CLI not installed)
        if data is None and method in ["not_found", "timeout", "api_error_500"]:
            if not hasattr(self, '_cli_unavailable'):
                print(f"  API failed ({method}), trying CLI...")
                data, method = self.fetch_scorecard_cli(owner, repo)
                
                # Mark CLI as unavailable to skip future attempts
                if method == "cli_not_installed":
                    self._cli_unavailable = True
                    print(f"  ℹ CLI not installed - will skip CLI for remaining repos")
            else:
                print(f"  API failed ({method}), CLI unavailable")
        
        # Store result
        if data:
            print(f"  ✓ Success via {method.upper()}")
            self.results[category][repo_full_name] = {
                "data": data,
                "method": method,
                "fetched_at": datetime.now().isoformat()
            }
            
            # Update stats
            if method == "api":
                self.results["stats"][f"{category}_api_success"] += 1
            elif method == "cli":
                self.results["stats"][f"{category}_cli_success"] += 1
        else:
            print(f"  ✗ Failed: {method}")
            self.results[category][repo_full_name] = {
                "error": method,
                "fetched_at": datetime.now().isoformat()
            }
            self.results["stats"][f"{category}_failed"] += 1
        
        self.results["stats"][f"{category}_total"] += 1
    
    async def fetch_all_scorecards(self, verified_repos, unverified_repos):
        """Fetch scorecards for all repos concurrently"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        
        # Create a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def fetch_with_semaphore(session, repo, category):
            async with semaphore:
                await self.fetch_scorecard(session, repo, category)
        
        async with aiohttp.ClientSession(headers=headers) as session:
            # Process verified repos
            print("\n" + "="*60)
            print(f"PROCESSING {len(verified_repos)} VERIFIED REPOS")
            print(f"Max concurrent requests: {self.max_concurrent}")
            print("="*60)
            
            tasks = [fetch_with_semaphore(session, repo, "verified") for repo in verified_repos]
            await asyncio.gather(*tasks)
            
            # Save after verified batch
            print(f"\nSaving results after verified batch...")
            self.save_results()
            
            # Process unverified repos
            print("\n" + "="*60)
            print(f"PROCESSING {len(unverified_repos)} UNVERIFIED REPOS")
            print(f"Max concurrent requests: {self.max_concurrent}")
            print("="*60)
            
            tasks = [fetch_with_semaphore(session, repo, "unverified") for repo in unverified_repos]
            await asyncio.gather(*tasks)
            
            # Save after unverified batch
            print(f"\nSaving results after unverified batch...")
            self.save_results()
    
    def save_results(self, show_summary=False):
        """Save results to JSON file"""
        output_data = {
            "generated_at": datetime.now().isoformat(),
            "top_n": self.top_n,
            "stats": self.results["stats"],
            "verified": self.results["verified"],
            "unverified": self.results["unverified"]
        }
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        if show_summary:
            print(f"\n{'='*60}")
            print("SCORECARD FETCHING COMPLETE!")
            print(f"{'='*60}")
            print(f"\nVERIFIED REPOS ({self.top_n} total):")
            print(f"  - API Success: {self.results['stats']['verified_api_success']}")
            print(f"  - CLI Success: {self.results['stats']['verified_cli_success']}")
            print(f"  - Failed: {self.results['stats']['verified_failed']}")
            
            print(f"\nUNVERIFIED REPOS ({self.top_n} total):")
            print(f"  - API Success: {self.results['stats']['unverified_api_success']}")
            print(f"  - CLI Success: {self.results['stats']['unverified_cli_success']}")
            print(f"  - Failed: {self.results['stats']['unverified_failed']}")
            
            print(f"\nResults saved to: {self.output_file}")
    
    async def run(self):
        """Main execution"""
        verified_repos, unverified_repos = self.load_repos()
        await self.fetch_all_scorecards(verified_repos, unverified_repos)
        self.save_results(show_summary=True)


async def main():
    # Configuration
    TOP_N = 500  # Number of repos to fetch from each category
    
    print("="*60)
    print("OpenSSF Scorecard Fetcher")
    print("="*60)
    print(f"Fetching scorecards for top {TOP_N} verified and unverified repos")
    print("Strategy: Try API first, fall back to CLI if needed")
    print("="*60)
    
    fetcher = ScorecardFetcher(top_n=TOP_N)
    await fetcher.run()


if __name__ == "__main__":
    asyncio.run(main())
