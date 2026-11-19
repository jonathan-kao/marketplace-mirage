#!/usr/bin/env python3
"""
analyze_scorecard_insights.py

Performs statistical analysis to compare verified vs unverified GitHub Actions
based on their OpenSSF Scorecard results. Determines if verified actions are
significantly better than unverified ones.
"""

import json
import sys
from collections import defaultdict
import re

# Fix Unicode encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def normalize_reason(reason):
    """
    Normalize reasons by removing numbers to group similar reasons together.
    Examples:
    - "4 commit(s) and 0 issue activity..." -> "X commit(s) and X issue activity found in the last 90 days"
    - "11 existing vulnerabilities detected" -> "X existing vulnerabilities detected"
    - "Found 3/10 approved changesets..." -> "Found X/X approved changesets"
    """
    if not reason:
        return reason
    
    # Replace specific number patterns
    normalized = reason
    
    # Pattern: "X commit(s) and X issue activity found in the last 90 days..."
    normalized = re.sub(r'\d+ commit\(s\) and \d+ issue activity found in the last 90 days.*', 
                       'X commit(s) and X issue activity found in the last 90 days', normalized)
    
    # Pattern: "X existing vulnerabilities detected"
    normalized = re.sub(r'\d+ existing vulnerabilities? detected', 
                       'X existing vulnerabilities detected', normalized)
    
    # Pattern: "Found X/X approved changesets..."
    normalized = re.sub(r'Found \d+/\d+ approved changesets.*', 
                       'Found X/X approved changesets (partial code review)', normalized)
    
    # Pattern: "dependency not pinned by hash detected -- score normalized to X"
    normalized = re.sub(r'dependency not pinned by hash detected -- score normalized to \d+', 
                       'dependency not pinned by hash detected', normalized)
    
    # Pattern: "X out of the last X releases have a total of X signed artifacts"
    normalized = re.sub(r'\d+ out of the last \d+ releases? have a total of \d+ signed artifacts?\.?', 
                       'X out of the last X releases have signed artifacts', normalized)
    
    # Pattern: "SAST tool is not run on all commits -- score normalized to X"
    normalized = re.sub(r'SAST tool is not run on all commits -- score normalized to \d+', 
                       'SAST tool is not run on all commits (partial)', normalized)
    
    # Pattern: "X out of X merged PRs checked by a CI test..."
    normalized = re.sub(r'\d+ out of \d+ merged PRs? checked by a CI test.*', 
                       'X out of X merged PRs checked by a CI test (partial)', normalized)
    
    # Pattern: "project has X contributing companies or organizations..."
    normalized = re.sub(r'project has \d+ contributing companies or organizations.*', 
                       'project has X contributing companies or organizations', normalized)
    
    # Pattern: "binaries present in source code"
    normalized = re.sub(r'binaries present in source code', 
                       'binaries present in source code', normalized)
    
    return normalized


def format_check_name_with_occurrence(check_name, check_occurrence_data):
    """
    Format check name with average occurrence percentages of verified and unverified < 50%.
    Returns formatted string like "CI-Tests (low sample)" or just "CI-Tests" if percentages are above threshold.
    """
    v_pct = check_occurrence_data.get("verified_occurrence_pct", 100)
    u_pct = check_occurrence_data.get("unverified_occurrence_pct", 100)
    
    # Only show percentages if either is not 100%
    if (v_pct + u_pct) / 2 < 50:
        return f"{check_name} (low sample)"
    else:
        return check_name


def calculate_correlation(data_points):
    """
    Calculate Pearson correlation coefficient between stars and scores.
    Returns: (correlation, interpretation)
    """
    if len(data_points) < 2:
        return None, "Insufficient data"
    
    n = len(data_points)
    stars = [x[0] for x in data_points]
    scores = [x[1] for x in data_points]
    
    # Calculate means
    mean_stars = sum(stars) / n
    mean_scores = sum(scores) / n
    
    # Calculate correlation coefficient
    numerator = sum((stars[i] - mean_stars) * (scores[i] - mean_scores) for i in range(n))
    denominator_stars = sum((x - mean_stars) ** 2 for x in stars)
    denominator_scores = sum((x - mean_scores) ** 2 for x in scores)
    
    if denominator_stars == 0 or denominator_scores == 0:
        return None, "No variance in data"
    
    correlation = numerator / (denominator_stars * denominator_scores) ** 0.5
    
    # Interpret correlation strength
    abs_corr = abs(correlation)
    if abs_corr >= 0.7:
        strength = "Strong"
    elif abs_corr >= 0.4:
        strength = "Moderate"
    elif abs_corr >= 0.2:
        strength = "Weak"
    else:
        strength = "Very weak"
    
    direction = "positive" if correlation > 0 else "negative"
    interpretation = f"{strength} {direction} correlation"
    
    return round(correlation, 3), interpretation


def analyze_scorecards():
    input_file = "4.openssf_scorecards_results.json"
    repos_data_file = "2.action_repos_data.json"
    output_file = "5.scorecard_insights.json"
    summary_file = "5.scorecard_insights_summary.txt"
    
    print("="*60)
    print("OpenSSF Scorecard Insight Analysis")
    print("="*60)
    
    # Load data
    print(f"\nLoading data from {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"Loading repos data from {repos_data_file}...")
    with open(repos_data_file, 'r', encoding='utf-8') as f:
        repos_data = json.load(f)
    
    # Collect scores for statistical analysis
    verified_scores = []
    unverified_scores = []
    
    verified_check_scores = defaultdict(list)
    unverified_check_scores = defaultdict(list)
    
    # For star correlation analysis
    verified_stars_scores = []  # List of (stars, score) tuples
    unverified_stars_scores = []
    
    # For reason analysis
    check_reasons = defaultdict(lambda: defaultdict(int))  # check_name -> {reason -> count}
    check_low_score_reasons = defaultdict(lambda: defaultdict(int))  # For scores < 5
    
    # For reason analysis by category (verified vs unverified)
    verified_check_reasons = defaultdict(lambda: defaultdict(int))
    unverified_check_reasons = defaultdict(lambda: defaultdict(int))
    verified_low_score_reasons = defaultdict(lambda: defaultdict(int))
    unverified_low_score_reasons = defaultdict(lambda: defaultdict(int))
    
    # Create lookup for stars from repos_data
    stars_lookup = {}
    for slug, action_data in repos_data.get("actions", {}).items():
        repo = action_data.get("repository", {})
        owner = repo.get("owner", "")
        name = repo.get("name", "")
        stars = action_data.get("stars", 0)
        if owner and name:
            repo_key = f"{owner}/{name}"
            stars_lookup[repo_key] = stars
    
    # Process verified repos
    print("\nAnalyzing verified repos...")
    for repo_name, repo_data in data.get("verified", {}).items():
        if "error" in repo_data:
            continue
        
        scorecard_data = repo_data.get("data", {})
        overall_score = scorecard_data.get("score")
        
        if overall_score is not None:
            verified_scores.append(overall_score)
            
            # Get stars for correlation
            stars = stars_lookup.get(repo_name, 0)
            verified_stars_scores.append((stars, overall_score))
        else:
            print(f"  Warning: No overall score for verified repo {repo_name}")
        
        checks = scorecard_data.get("checks", [])
        for check in checks:
            check_name = check.get("name")
            check_score = check.get("score")
            check_reason = check.get("reason", "")
            
            if check_name and check_score is not None:
                verified_check_scores[check_name].append(check_score)
                
                # Track reasons for all scores (with normalization)
                if check_reason:
                    normalized_reason = normalize_reason(check_reason)
                    check_reasons[check_name][normalized_reason] += 1
                    verified_check_reasons[check_name][normalized_reason] += 1
                    
                # Track reasons for low scores (< 5)
                if check_score < 5 and check_reason:
                    normalized_reason = normalize_reason(check_reason)
                    check_low_score_reasons[check_name][normalized_reason] += 1
                    verified_low_score_reasons[check_name][normalized_reason] += 1
    
    # Process unverified repos
    print("Analyzing unverified repos...")
    for repo_name, repo_data in data.get("unverified", {}).items():
        if "error" in repo_data:
            continue
        
        scorecard_data = repo_data.get("data", {})
        overall_score = scorecard_data.get("score")
        
        if overall_score is not None:
            unverified_scores.append(overall_score)
            
            # Get stars for correlation
            stars = stars_lookup.get(repo_name, 0)
            unverified_stars_scores.append((stars, overall_score))
        
        checks = scorecard_data.get("checks", [])
        for check in checks:
            check_name = check.get("name")
            check_score = check.get("score")
            check_reason = check.get("reason", "")
            
            if check_name and check_score is not None:
                unverified_check_scores[check_name].append(check_score)
                
                # Track reasons for all scores (with normalization)
                if check_reason:
                    normalized_reason = normalize_reason(check_reason)
                    check_reasons[check_name][normalized_reason] += 1
                    unverified_check_reasons[check_name][normalized_reason] += 1
                    
                # Track reasons for low scores (< 5)
                if check_score < 5 and check_reason:
                    normalized_reason = normalize_reason(check_reason)
                    check_low_score_reasons[check_name][normalized_reason] += 1
                    unverified_low_score_reasons[check_name][normalized_reason] += 1
    
    # Calculate statistics
    verified_avg = sum(verified_scores) / len(verified_scores) if verified_scores else 0
    unverified_avg = sum(unverified_scores) / len(unverified_scores) if unverified_scores else 0
    
    # Overall comparison
    overall_diff = verified_avg - unverified_avg
    overall_diff_pct = (overall_diff / unverified_avg * 100) if unverified_avg > 0 else 0
    
    # Check-by-check comparison
    check_comparisons = {}
    all_checks = set(list(verified_check_scores.keys()) + list(unverified_check_scores.keys()))
    
    # Count total repos for percentage calculation
    total_verified_repos = len([r for r in data.get("verified", {}).values() if "error" not in r])
    total_unverified_repos = len([r for r in data.get("unverified", {}).values() if "error" not in r])
    
    for check_name in all_checks:
        v_scores = verified_check_scores.get(check_name, [])
        u_scores = unverified_check_scores.get(check_name, [])
        
        # Calculate occurrence percentages
        v_occurrence_pct = (len(v_scores) / total_verified_repos * 100) if total_verified_repos > 0 else 0
        u_occurrence_pct = (len(u_scores) / total_unverified_repos * 100) if total_unverified_repos > 0 else 0
        
        if v_scores and u_scores:
            v_avg = sum(v_scores) / len(v_scores)
            u_avg = sum(u_scores) / len(u_scores)
            diff = v_avg - u_avg
            diff_pct = (diff / u_avg * 100) if u_avg > 0 else 0
            
            check_comparisons[check_name] = {
                "verified_avg": round(v_avg, 2),
                "unverified_avg": round(u_avg, 2),
                "difference": round(diff, 2),
                "difference_pct": round(diff_pct, 2),
                "verified_better": diff > 0,
                "verified_count": len(v_scores),
                "unverified_count": len(u_scores),
                "verified_occurrence_pct": round(v_occurrence_pct, 2),
                "unverified_occurrence_pct": round(u_occurrence_pct, 2)
            }
    
    # Find strengths and weaknesses
    strengths = {k: v for k, v in check_comparisons.items() if v["difference"] > 0.5}
    weaknesses = {k: v for k, v in check_comparisons.items() if v["difference"] < -0.5}
    similar = {k: v for k, v in check_comparisons.items() if -0.5 <= v["difference"] <= 0.5}
    
    # Sort by difference
    strengths_sorted = dict(sorted(strengths.items(), key=lambda x: x[1]["difference"], reverse=True))
    weaknesses_sorted = dict(sorted(weaknesses.items(), key=lambda x: x[1]["difference"]))
    
    # Count how many checks verified is better at
    verified_better_count = sum(1 for v in check_comparisons.values() if v["verified_better"])
    total_checks = len(check_comparisons)
    
    # Calculate score distributions
    verified_distribution = {
        "excellent (8-10)": sum(1 for s in verified_scores if s >= 8),
        "good (6-7.9)": sum(1 for s in verified_scores if 6 <= s < 8),
        "moderate (4-5.9)": sum(1 for s in verified_scores if 4 <= s < 6),
        "poor (0-3.9)": sum(1 for s in verified_scores if s < 4)
    }
    
    unverified_distribution = {
        "excellent (8-10)": sum(1 for s in unverified_scores if s >= 8),
        "good (6-7.9)": sum(1 for s in unverified_scores if 6 <= s < 8),
        "moderate (4-5.9)": sum(1 for s in unverified_scores if 4 <= s < 6),
        "poor (0-3.9)": sum(1 for s in unverified_scores if s < 4)
    }
    
    # Generate insights
    insights = []
    
    if overall_diff > 0:
        insights.append(f"✓ Verified actions have {abs(overall_diff_pct):.1f}% higher overall scores than unverified")
    else:
        insights.append(f"✗ Verified actions have {abs(overall_diff_pct):.1f}% lower overall scores than unverified")
    
    insights.append(f"✓ Verified actions score better in {verified_better_count}/{total_checks} ({verified_better_count/total_checks*100:.1f}%) security checks")
    
    if strengths_sorted:
        top_strength = list(strengths_sorted.keys())[0]
        insights.append(f"✓ Biggest verified advantage: {top_strength} (+{strengths_sorted[top_strength]['difference']:.1f} points)")
    
    if weaknesses_sorted:
        top_weakness = list(weaknesses_sorted.keys())[0]
        insights.append(f"✗ Biggest verified disadvantage: {top_weakness} ({weaknesses_sorted[top_weakness]['difference']:.1f} points)")
    
    # Star correlation analysis
    print("\nAnalyzing star-score correlations...")
    verified_corr, verified_interp = calculate_correlation(verified_stars_scores)
    unverified_corr, unverified_interp = calculate_correlation(unverified_stars_scores)
    all_stars_scores = verified_stars_scores + unverified_stars_scores
    overall_corr, overall_interp = calculate_correlation(all_stars_scores)
    
    star_correlation = {
        "verified": {
            "correlation": verified_corr,
            "interpretation": verified_interp,
            "sample_size": len(verified_stars_scores)
        },
        "unverified": {
            "correlation": unverified_corr,
            "interpretation": unverified_interp,
            "sample_size": len(unverified_stars_scores)
        },
        "overall": {
            "correlation": overall_corr,
            "interpretation": overall_interp,
            "sample_size": len(all_stars_scores)
        }
    }
    
    # Add star correlation insights
    if verified_corr is not None:
        if abs(verified_corr) < 0.2:
            insights.append(f"⭐ Star count has almost NO correlation with security scores for verified actions (r={verified_corr:.3f})")
        elif verified_corr > 0.4:
            insights.append(f"⭐ Popular verified actions tend to have BETTER security scores (r={verified_corr:.3f})")
        elif verified_corr < -0.2:
            insights.append(f"⭐ Popular verified actions tend to have WORSE security scores (r={verified_corr:.3f})")
    
    if unverified_corr is not None:
        if abs(unverified_corr) < 0.2:
            insights.append(f"⭐ Star count has almost NO correlation with security scores for unverified actions (r={unverified_corr:.3f})")
        elif unverified_corr > 0.4:
            insights.append(f"⭐ Popular unverified actions tend to have BETTER security scores (r={unverified_corr:.3f})")
        elif unverified_corr < -0.2:
            insights.append(f"⭐ Popular unverified actions tend to have WORSE security scores (r={unverified_corr:.3f})")
    
    # Analyze common failure reasons
    print("\nAnalyzing common failure reasons...")
    
    # Find most problematic checks (most low scores)
    problematic_checks = {}
    for check_name, reasons in check_low_score_reasons.items():
        total_low_scores = sum(reasons.values())
        if total_low_scores > 0:
            problematic_checks[check_name] = {
                "total_failures": total_low_scores,
                "reasons": dict(sorted(reasons.items(), key=lambda x: x[1], reverse=True))
            }
    
    problematic_checks_sorted = dict(sorted(
        problematic_checks.items(), 
        key=lambda x: x[1]["total_failures"], 
        reverse=True
    ))
    
    # Extract common issues across all checks
    common_issues = []
    for check_name, check_data in list(problematic_checks_sorted.items())[:5]:
        top_reason = list(check_data["reasons"].items())[0] if check_data["reasons"] else ("Unknown", 0)
        reason_text, count = top_reason
        common_issues.append({
            "check": check_name,
            "failure_count": check_data["total_failures"],
            "most_common_reason": reason_text,
            "reason_count": count
        })
    
    # Add insights about common issues
    if common_issues:
        top_issue = common_issues[0]
        insights.append(f"⚠️ Most problematic check: {top_issue['check']} ({top_issue['failure_count']} failures)")
        insights.append(f"⚠️ Common issue: \"{top_issue['most_common_reason']}\"")
    
    # === NEW ANALYSIS 1: FAILURE CLUSTERING ===
    print("\nAnalyzing failure clustering...")
    failure_clustering = {}
    for check_name in all_checks:
        all_check_scores = verified_check_scores.get(check_name, []) + unverified_check_scores.get(check_name, [])
        if all_check_scores:
            total = len(all_check_scores)
            failures = sum(1 for s in all_check_scores if s < 5)
            failure_rate = (failures / total * 100) if total > 0 else 0
            avg_score = sum(all_check_scores) / len(all_check_scores)
            
            # Categorize
            if failure_rate >= 75:
                tier = "critical"
                adoption = "very low"
            elif failure_rate >= 50:
                tier = "high_failure"
                adoption = "low"
            elif failure_rate >= 25:
                tier = "moderate_failure"
                adoption = "moderate"
            else:
                tier = "low_failure"
                adoption = "high"
            
            failure_clustering[check_name] = {
                "failure_rate_pct": round(failure_rate, 2),
                "failure_count": failures,
                "total_samples": total,
                "average_score": round(avg_score, 2),
                "tier": tier,
                "adoption_level": adoption
            }
    
    # Group by tier
    clustering_by_tier = defaultdict(list)
    for check_name, cluster_info in failure_clustering.items():
        clustering_by_tier[cluster_info["tier"]].append(check_name)
    
    # === NEW ANALYSIS 3: VERIFICATION IMPACT PER CHECK ===
    print("Analyzing verification impact per check...")
    verification_impact = {}
    for check_name in all_checks:
        v_scores = verified_check_scores.get(check_name, [])
        u_scores = unverified_check_scores.get(check_name, [])
        
        if v_scores and u_scores:
            v_avg = sum(v_scores) / len(v_scores)
            u_avg = sum(u_scores) / len(u_scores)
            premium = v_avg - u_avg
            premium_pct = (premium / u_avg * 100) if u_avg > 0 else 0
            
            # Calculate failure rate difference
            v_failures = sum(1 for s in v_scores if s < 5) / len(v_scores) * 100
            u_failures = sum(1 for s in u_scores if s < 5) / len(u_scores) * 100
            failure_reduction = u_failures - v_failures
            
            verification_impact[check_name] = {
                "score_premium": round(premium, 2),
                "score_premium_pct": round(premium_pct, 2),
                "failure_rate_reduction_pct": round(failure_reduction, 2),
                "verified_avg": round(v_avg, 2),
                "unverified_avg": round(u_avg, 2),
                "impact_level": "high" if abs(premium) > 2 else ("moderate" if abs(premium) > 1 else "low")
            }
    
    # Sort by premium
    high_impact_checks = {k: v for k, v in sorted(verification_impact.items(), 
                                                   key=lambda x: abs(x[1]["score_premium"]), 
                                                   reverse=True)[:5]}
    
    # === NEW ANALYSIS 4: RISK PROFILING ===
    print("Analyzing risk profiles...")
    high_risk_repos = []  # Popular but low security
    low_risk_repos = []   # High security
    
    # Define thresholds
    HIGH_POPULARITY_THRESHOLD = 1000  # stars
    LOW_SCORE_THRESHOLD = 5.0
    HIGH_SCORE_THRESHOLD = 7.0
    
    # Check verified repos
    for repo_name, repo_data in data.get("verified", {}).items():
        if "error" in repo_data:
            continue
        scorecard_data = repo_data.get("data", {})
        score = scorecard_data.get("score")
        stars = stars_lookup.get(repo_name, 0)
        
        if score is not None:
            if stars >= HIGH_POPULARITY_THRESHOLD and score < LOW_SCORE_THRESHOLD:
                high_risk_repos.append({
                    "repo": repo_name,
                    "stars": stars,
                    "score": round(score, 2),
                    "category": "verified",
                    "risk_level": "high"
                })
            elif score >= HIGH_SCORE_THRESHOLD:
                low_risk_repos.append({
                    "repo": repo_name,
                    "stars": stars,
                    "score": round(score, 2),
                    "category": "verified"
                })
    
    # Check unverified repos
    for repo_name, repo_data in data.get("unverified", {}).items():
        if "error" in repo_data:
            continue
        scorecard_data = repo_data.get("data", {})
        score = scorecard_data.get("score")
        stars = stars_lookup.get(repo_name, 0)
        
        if score is not None:
            if stars >= HIGH_POPULARITY_THRESHOLD and score < LOW_SCORE_THRESHOLD:
                high_risk_repos.append({
                    "repo": repo_name,
                    "stars": stars,
                    "score": round(score, 2),
                    "category": "unverified",
                    "risk_level": "high"
                })
            elif score >= HIGH_SCORE_THRESHOLD:
                low_risk_repos.append({
                    "repo": repo_name,
                    "stars": stars,
                    "score": round(score, 2),
                    "category": "unverified"
                })
    
    # Sort by stars
    high_risk_repos_sorted = sorted(high_risk_repos, key=lambda x: x["stars"], reverse=True)[:20]
    low_risk_repos_sorted = sorted(low_risk_repos, key=lambda x: x["score"], reverse=True)[:10]
    
    # === NEW ANALYSIS 6: ACTIONABLE RECOMMENDATIONS ===
    print("Generating actionable recommendations...")
    recommendations = []
    
    # Identify quick wins (high failure rate but easy to fix)
    quick_wins = []
    hard_improvements = []
    
    for check_name, cluster_data in failure_clustering.items():
        if cluster_data["failure_rate_pct"] > 50:
            # High failure rate
            impact = verification_impact.get(check_name, {})
            score_gain = abs(impact.get("score_premium", 0))
            
            # Estimate difficulty based on check type
            easy_checks = ["License", "Security-Policy", "Binary-Artifacts", "Dangerous-Workflow"]
            medium_checks = ["Token-Permissions", "Pinned-Dependencies", "Branch-Protection"]
            
            if check_name in easy_checks:
                difficulty = "easy"
                quick_wins.append({
                    "check": check_name,
                    "failure_rate_pct": cluster_data["failure_rate_pct"],
                    "potential_score_gain": round(score_gain, 2),
                    "difficulty": difficulty,
                    "priority": "high" if score_gain > 2 else "medium"
                })
            elif check_name in medium_checks:
                difficulty = "medium"
                quick_wins.append({
                    "check": check_name,
                    "failure_rate_pct": cluster_data["failure_rate_pct"],
                    "potential_score_gain": round(score_gain, 2),
                    "difficulty": difficulty,
                    "priority": "high" if score_gain > 2 else "medium"
                })
            else:
                difficulty = "hard"
                hard_improvements.append({
                    "check": check_name,
                    "failure_rate_pct": cluster_data["failure_rate_pct"],
                    "potential_score_gain": round(score_gain, 2),
                    "difficulty": difficulty
                })
    
    quick_wins_sorted = sorted(quick_wins, key=lambda x: (-x["failure_rate_pct"], -x["potential_score_gain"]))[:5]
    hard_improvements_sorted = sorted(hard_improvements, key=lambda x: -x["failure_rate_pct"])[:5]
    
    # === NEW ANALYSIS 7: OUTLIER DETECTION ===
    print("Detecting outliers...")
    
    all_repos_with_scores = []
    for repo_name, repo_data in data.get("verified", {}).items():
        if "error" not in repo_data:
            score = repo_data.get("data", {}).get("score")
            if score is not None:
                all_repos_with_scores.append({
                    "repo": repo_name,
                    "score": score,
                    "stars": stars_lookup.get(repo_name, 0),
                    "category": "verified"
                })
    
    for repo_name, repo_data in data.get("unverified", {}).items():
        if "error" not in repo_data:
            score = repo_data.get("data", {}).get("score")
            if score is not None:
                all_repos_with_scores.append({
                    "repo": repo_name,
                    "score": score,
                    "stars": stars_lookup.get(repo_name, 0),
                    "category": "unverified"
                })
    
    print(f"  Collected {len(all_repos_with_scores)} repos with scores")
    
    # Statistical outliers
    all_scores_list = [r["score"] for r in all_repos_with_scores]
    mean_score = sum(all_scores_list) / len(all_scores_list) if all_scores_list else 0
    variance = sum((s - mean_score) ** 2 for s in all_scores_list) / len(all_scores_list) if all_scores_list else 0
    std_dev = variance ** 0.5
    
    print(f"  Mean: {mean_score:.2f}, StdDev: {std_dev:.2f}")
    
    exceptional_high = [r for r in all_repos_with_scores if r["score"] > mean_score + 2 * std_dev]
    exceptional_low = [r for r in all_repos_with_scores if r["score"] < mean_score - 2 * std_dev]
    
    print(f"  Found {len(exceptional_high)} high outliers, {len(exceptional_low)} low outliers")
    
    exceptional_high_sorted = sorted(exceptional_high, key=lambda x: x["score"], reverse=True)[:10]
    exceptional_low_sorted = sorted(exceptional_low, key=lambda x: x["score"])[:10]
    
    # === NEW ANALYSIS 8: CHECK CORRELATION MATRIX ===
    print("Calculating check correlation matrix...")
    
    # Build matrix: for each repo, collect all check scores
    repo_check_matrix = defaultdict(dict)
    
    for repo_name, repo_data in data.get("verified", {}).items():
        if "error" not in repo_data:
            checks = repo_data.get("data", {}).get("checks", [])
            for check in checks:
                check_name = check.get("name")
                check_score = check.get("score")
                if check_name and check_score is not None:
                    repo_check_matrix[repo_name][check_name] = check_score
    
    for repo_name, repo_data in data.get("unverified", {}).items():
        if "error" not in repo_data:
            checks = repo_data.get("data", {}).get("checks", [])
            for check in checks:
                check_name = check.get("name")
                check_score = check.get("score")
                if check_name and check_score is not None:
                    repo_check_matrix[repo_name][check_name] = check_score
    
    print(f"  Built matrix with {len(repo_check_matrix)} repos")
    
    # Calculate correlations between all check pairs
    check_correlations = {}
    check_list = list(all_checks)
    
    print(f"  Analyzing correlations between {len(check_list)} checks")
    
    for i, check1 in enumerate(check_list):
        for j, check2 in enumerate(check_list):
            if i < j:  # Only upper triangle
                # Get paired scores
                paired_scores = []
                for repo_scores in repo_check_matrix.values():
                    if check1 in repo_scores and check2 in repo_scores:
                        paired_scores.append((repo_scores[check1], repo_scores[check2]))
                
                if len(paired_scores) >= 10:  # Need minimum samples
                    corr, interp = calculate_correlation(paired_scores)
                    if corr is not None and abs(corr) >= 0.3:  # Only significant correlations
                        pair_key = f"{check1}___{check2}"
                        check_correlations[pair_key] = {
                            "check1": check1,
                            "check2": check2,
                            "correlation": corr,
                            "interpretation": interp,
                            "sample_size": len(paired_scores)
                        }
    
    print(f"  Found {len(check_correlations)} significant correlations")
    
    # Calculate total repos for sample size filtering (50% threshold)
    total_repos_with_checks = len(repo_check_matrix)
    min_sample_size_threshold = total_repos_with_checks * 0.5
    
    # Filter correlations with sufficient sample size (>= 50% of total repos)
    filtered_correlations = {k: v for k, v in check_correlations.items() 
                            if v["sample_size"] >= min_sample_size_threshold}
    
    # Add sample percentage to filtered correlations
    for corr_data in filtered_correlations.values():
        corr_data["sample_percentage"] = round(corr_data["sample_size"] / total_repos_with_checks * 100, 1)
    
    print(f"  After filtering (sample size >= {min_sample_size_threshold:.0f}): {len(filtered_correlations)} correlations")
    
    # Sort by absolute correlation
    strong_correlations = dict(sorted(filtered_correlations.items(), 
                                     key=lambda x: abs(x[1]["correlation"]), 
                                     reverse=True)[:15])
    
    # Analyze reason distribution by category (verified vs unverified)
    print("Analyzing reason distribution by verification status...")
    
    # Aggregate all low-score reasons by category
    verified_reasons_total = defaultdict(int)
    unverified_reasons_total = defaultdict(int)
    
    for check_name, reasons in verified_low_score_reasons.items():
        for reason, count in reasons.items():
            verified_reasons_total[reason] += count
    
    for check_name, reasons in unverified_low_score_reasons.items():
        for reason, count in reasons.items():
            unverified_reasons_total[reason] += count
    
    # Calculate total sample counts
    verified_total_samples = sum(verified_reasons_total.values())
    unverified_total_samples = sum(unverified_reasons_total.values())
    
    # Find reasons with significant differences
    reason_comparison = {}
    all_reasons_set = set(list(verified_reasons_total.keys()) + list(unverified_reasons_total.keys()))
    
    for reason in all_reasons_set:
        v_count = verified_reasons_total.get(reason, 0)
        u_count = unverified_reasons_total.get(reason, 0)
        
        # Calculate percentages
        v_pct = (v_count / verified_total_samples * 100) if verified_total_samples > 0 else 0
        u_pct = (u_count / unverified_total_samples * 100) if unverified_total_samples > 0 else 0
        
        diff_pct = v_pct - u_pct
        
        reason_comparison[reason] = {
            "verified_count": v_count,
            "unverified_count": u_count,
            "verified_percentage": round(v_pct, 2),
            "unverified_percentage": round(u_pct, 2),
            "difference_pct": round(diff_pct, 2),
            "bias_towards": "verified" if diff_pct > 5 else "unverified" if diff_pct < -5 else "neutral"
        }
    
    # Sort by absolute difference to find biggest biases
    reason_comparison_sorted = dict(sorted(
        reason_comparison.items(),
        key=lambda x: abs(x[1]["difference_pct"]),
        reverse=True
    ))
    
    # Find reasons biased towards verified or unverified
    verified_biased_reasons = {k: v for k, v in reason_comparison_sorted.items() if v["bias_towards"] == "verified"}
    unverified_biased_reasons = {k: v for k, v in reason_comparison_sorted.items() if v["bias_towards"] == "unverified"}
    
    # Add insights about biases
    if verified_biased_reasons:
        top_verified_bias = list(verified_biased_reasons.items())[0]
        insights.append(f"🔍 Verified actions more likely to fail on: \"{top_verified_bias[0]}\" ({top_verified_bias[1]['verified_percentage']:.1f}% vs {top_verified_bias[1]['unverified_percentage']:.1f}%)")
    
    if unverified_biased_reasons:
        top_unverified_bias = list(unverified_biased_reasons.items())[0]
        insights.append(f"🔍 Unverified actions more likely to fail on: \"{top_unverified_bias[0]}\" ({top_unverified_bias[1]['unverified_percentage']:.1f}% vs {top_unverified_bias[1]['verified_percentage']:.1f}%)")
    
    # Create reason analysis output
    reason_analysis = {
        "problematic_checks": problematic_checks_sorted,
        "common_issues": common_issues,
        "all_check_reasons": {
            check: dict(sorted(reasons.items(), key=lambda x: x[1], reverse=True))
            for check, reasons in check_reasons.items()
        },
        "reason_distribution_by_category": {
            "verified_total_samples": verified_total_samples,
            "unverified_total_samples": unverified_total_samples,
            "reason_comparison": reason_comparison_sorted,
            "verified_biased_reasons": verified_biased_reasons,
            "unverified_biased_reasons": unverified_biased_reasons
        }
    }
    
    # Create check occurrence summary
    check_occurrence_summary = {}
    for check_name in all_checks:
        v_scores = verified_check_scores.get(check_name, [])
        u_scores = unverified_check_scores.get(check_name, [])
        
        v_occurrence_pct = (len(v_scores) / total_verified_repos * 100) if total_verified_repos > 0 else 0
        u_occurrence_pct = (len(u_scores) / total_unverified_repos * 100) if total_unverified_repos > 0 else 0
        
        check_occurrence_summary[check_name] = {
            "verified_count": len(v_scores),
            "verified_total": total_verified_repos,
            "verified_occurrence_pct": round(v_occurrence_pct, 2),
            "unverified_count": len(u_scores),
            "unverified_total": total_unverified_repos,
            "unverified_occurrence_pct": round(u_occurrence_pct, 2)
        }
    
    # Sort by occurrence difference
    check_occurrence_sorted = dict(sorted(
        check_occurrence_summary.items(),
        key=lambda x: abs(x[1]["verified_occurrence_pct"] - x[1]["unverified_occurrence_pct"]),
        reverse=True
    ))
    
    # Create output
    output_data = {
        "generated_at": data.get("generated_at"),
        "analysis_summary": {
            "conclusion": "Verified actions are MORE secure" if overall_diff > 0 else "Unverified actions are MORE secure",
            "overall_score_difference": round(overall_diff, 2),
            "overall_score_difference_pct": round(overall_diff_pct, 2),
            "verified_avg_score": round(verified_avg, 2),
            "unverified_avg_score": round(unverified_avg, 2),
            "checks_where_verified_better": verified_better_count,
            "total_checks_compared": total_checks,
            "verified_better_percentage": round(verified_better_count/total_checks*100, 2) if total_checks > 0 else 0,
            "total_verified_repos": total_verified_repos,
            "total_unverified_repos": total_unverified_repos
        },
        "check_occurrence_analysis": check_occurrence_sorted,
        "star_correlation_analysis": star_correlation,
        "reason_analysis": reason_analysis,
        "failure_clustering": {
            "by_check": failure_clustering,
            "by_tier": {
                "critical": clustering_by_tier.get("critical", []),
                "high_failure": clustering_by_tier.get("high_failure", []),
                "moderate_failure": clustering_by_tier.get("moderate_failure", []),
                "low_failure": clustering_by_tier.get("low_failure", [])
            },
            "summary": {
                "critical_checks_count": len(clustering_by_tier.get("critical", [])),
                "high_failure_checks_count": len(clustering_by_tier.get("high_failure", [])),
                "moderate_failure_checks_count": len(clustering_by_tier.get("moderate_failure", [])),
                "low_failure_checks_count": len(clustering_by_tier.get("low_failure", []))
            }
        },
        "verification_impact": {
            "all_checks": verification_impact,
            "high_impact_checks": high_impact_checks
        },
        "risk_profiling": {
            "high_risk_repos": high_risk_repos_sorted,
            "low_risk_repos": low_risk_repos_sorted,
            "thresholds": {
                "high_popularity_stars": HIGH_POPULARITY_THRESHOLD,
                "low_score": LOW_SCORE_THRESHOLD,
                "high_score": HIGH_SCORE_THRESHOLD
            },
            "summary": {
                "high_risk_count": len(high_risk_repos),
                "low_risk_count": len(low_risk_repos)
            }
        },
        "actionable_recommendations": {
            "quick_wins": quick_wins_sorted,
            "hard_improvements": hard_improvements_sorted
        },
        "outlier_detection": {
            "exceptional_high_performers": exceptional_high_sorted,
            "exceptional_low_performers": exceptional_low_sorted,
            "statistics": {
                "mean_score": round(mean_score, 2),
                "std_deviation": round(std_dev, 2),
                "high_outlier_threshold": round(mean_score + 2 * std_dev, 2),
                "low_outlier_threshold": round(mean_score - 2 * std_dev, 2)
            }
        },
        "check_correlation_matrix": {
            "strong_correlations": strong_correlations,
            "total_check_pairs_analyzed": len(check_correlations),
            "significant_pairs_count": len(strong_correlations),
            "total_repos_with_checks": total_repos_with_checks,
            "min_sample_size_threshold": int(min_sample_size_threshold)
        },
        "key_insights": insights,
        "score_distributions": {
            "verified": verified_distribution,
            "unverified": unverified_distribution
        },
        "verified_strengths": strengths_sorted,
        "verified_weaknesses": weaknesses_sorted,
        "similar_performance": similar,
        "detailed_check_comparison": check_comparisons
    }
    
    # Save to file
    print(f"\nSaving analysis to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    # Prepare summary text output
    summary_lines = []
    summary_lines.append("="*60)
    summary_lines.append("OpenSSF Scorecard Insight Analysis - Summary Report")
    summary_lines.append("="*60)
    summary_lines.append("")
    
    # Print summary
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE!")
    print(f"{'='*60}")
    
    print(f"\n{'='*60}")
    print("CONCLUSION")
    print(f"{'='*60}")
    print(f"{output_data['analysis_summary']['conclusion']}")
    print(f"\nOverall Score Difference: {overall_diff:+.2f} points ({overall_diff_pct:+.1f}%)")
    print(f"  Verified Average: {verified_avg:.2f} (n={total_verified_repos})")
    print(f"  Unverified Average: {unverified_avg:.2f} (n={total_unverified_repos})")
    
    summary_lines.append("="*60)
    summary_lines.append("CONCLUSION")
    summary_lines.append("="*60)
    summary_lines.append(f"{output_data['analysis_summary']['conclusion']}")
    summary_lines.append(f"\nOverall Score Difference: {overall_diff:+.2f} points ({overall_diff_pct:+.1f}%)")
    summary_lines.append(f"  Verified Average: {verified_avg:.2f} (n={total_verified_repos})")
    summary_lines.append(f"  Unverified Average: {unverified_avg:.2f} (n={total_unverified_repos})")
    summary_lines.append("")
    
    print(f"\n{'='*60}")
    print("CHECK OCCURRENCE ANALYSIS")
    print(f"{'='*60}")
    print(f"\nTotal Repos: Verified={total_verified_repos}, Unverified={total_unverified_repos}")
    print(f"\nCheck Availability by Category:")
    print(f"{'Check Name':<30} {'Verified':<25} {'Unverified':<25} {'Diff'}")
    print(f"{'-'*30} {'-'*25} {'-'*25} {'-'*10}")
    
    summary_lines.append("="*60)
    summary_lines.append("CHECK OCCURRENCE ANALYSIS")
    summary_lines.append("="*60)
    summary_lines.append(f"\nTotal Repos: Verified={total_verified_repos}, Unverified={total_unverified_repos}")
    summary_lines.append(f"\nCheck Availability by Category:")
    summary_lines.append(f"{'Check Name':<30} {'Verified':<25} {'Unverified':<25} {'Diff'}")
    summary_lines.append(f"{'-'*30} {'-'*25} {'-'*25} {'-'*10}")
    
    for check_name, occ_data in check_occurrence_sorted.items():
        v_text = f"{occ_data['verified_count']:3}/{occ_data['verified_total']:3} ({occ_data['verified_occurrence_pct']:6.2f}%)"
        u_text = f"{occ_data['unverified_count']:3}/{occ_data['unverified_total']:3} ({occ_data['unverified_occurrence_pct']:6.2f}%)"
        diff_pct = occ_data['verified_occurrence_pct'] - occ_data['unverified_occurrence_pct']
        
        print(f"{check_name:<30} {v_text:<25} {u_text:<25} {diff_pct:+6.2f}%")
        summary_lines.append(f"{check_name:<30} {v_text:<25} {u_text:<25} {diff_pct:+6.2f}%")
    
    summary_lines.append("")
    
    print(f"\n{'='*60}")
    print("KEY INSIGHTS")
    print(f"{'='*60}")
    for insight in insights:
        print(f"  {insight}")
    
    summary_lines.append("="*60)
    summary_lines.append("KEY INSIGHTS")
    summary_lines.append("="*60)
    for insight in insights:
        summary_lines.append(f"  {insight}")
    summary_lines.append("")
    
    print(f"\n{'='*60}")
    print("SCORE DISTRIBUTIONS")
    print(f"{'='*60}")
    print("\nVerified:")
    for category, count in verified_distribution.items():
        pct = (count / len(verified_scores) * 100) if verified_scores else 0
        print(f"  {category}: {count} repos ({pct:.1f}%)")
    
    print("\nUnverified:")
    for category, count in unverified_distribution.items():
        pct = (count / len(unverified_scores) * 100) if unverified_scores else 0
        print(f"  {category}: {count} repos ({pct:.1f}%)")
    
    summary_lines.append("="*60)
    summary_lines.append("SCORE DISTRIBUTIONS")
    summary_lines.append("="*60)
    summary_lines.append("\nVerified:")
    for category, count in verified_distribution.items():
        pct = (count / len(verified_scores) * 100) if verified_scores else 0
        summary_lines.append(f"  {category}: {count} repos ({pct:.1f}%)")
    summary_lines.append("\nUnverified:")
    for category, count in unverified_distribution.items():
        pct = (count / len(unverified_scores) * 100) if unverified_scores else 0
        summary_lines.append(f"  {category}: {count} repos ({pct:.1f}%)")
    summary_lines.append("")
    
    if strengths_sorted:
        print(f"\n{'='*60}")
        print("VERIFIED STRENGTHS (> 0.5 point advantage)")
        print(f"{'='*60}")
        for check, stats in list(strengths_sorted.items())[:5]:
            check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
            print(f"  {check_display}: +{stats['difference']:.2f} ({stats['verified_avg']:.1f} vs {stats['unverified_avg']:.1f})")
        
        summary_lines.append("="*60)
        summary_lines.append("VERIFIED STRENGTHS (> 0.5 point advantage)")
        summary_lines.append("="*60)
        for check, stats in list(strengths_sorted.items())[:5]:
            check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
            summary_lines.append(f"  {check_display}: +{stats['difference']:.2f} ({stats['verified_avg']:.1f} vs {stats['unverified_avg']:.1f})")
        summary_lines.append("")
    
    if weaknesses_sorted:
        print(f"\n{'='*60}")
        print("VERIFIED WEAKNESSES (< -0.5 point disadvantage)")
        print(f"{'='*60}")
        for check, stats in list(weaknesses_sorted.items())[:5]:
            check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
            print(f"  {check_display}: {stats['difference']:.2f} ({stats['verified_avg']:.1f} vs {stats['unverified_avg']:.1f})")
        
        summary_lines.append("="*60)
        summary_lines.append("VERIFIED WEAKNESSES (< -0.5 point disadvantage)")
        summary_lines.append("="*60)
        for check, stats in list(weaknesses_sorted.items())[:5]:
            check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
            summary_lines.append(f"  {check_display}: {stats['difference']:.2f} ({stats['verified_avg']:.1f} vs {stats['unverified_avg']:.1f})")
        summary_lines.append("")
    
    print(f"\n{'='*60}")
    print("STAR-SCORE CORRELATION ANALYSIS")
    print(f"{'='*60}")
    print(f"\nVerified Actions:")
    print(f"  Correlation: {verified_corr if verified_corr else 'N/A'}")
    print(f"  Interpretation: {verified_interp}")
    print(f"  Sample size: {len(verified_stars_scores)} repos")
    
    print(f"\nUnverified Actions:")
    print(f"  Correlation: {unverified_corr if unverified_corr else 'N/A'}")
    print(f"  Interpretation: {unverified_interp}")
    print(f"  Sample size: {len(unverified_stars_scores)} repos")
    
    print(f"\nOverall (All Actions):")
    print(f"  Correlation: {overall_corr if overall_corr else 'N/A'}")
    print(f"  Interpretation: {overall_interp}")
    print(f"  Sample size: {len(all_stars_scores)} repos")
    
    summary_lines.append("="*60)
    summary_lines.append("STAR-SCORE CORRELATION ANALYSIS")
    summary_lines.append("="*60)
    summary_lines.append("\nVerified Actions:")
    summary_lines.append(f"  Correlation: {verified_corr if verified_corr else 'N/A'}")
    summary_lines.append(f"  Interpretation: {verified_interp}")
    summary_lines.append(f"  Sample size: {len(verified_stars_scores)} repos")
    summary_lines.append("\nUnverified Actions:")
    summary_lines.append(f"  Correlation: {unverified_corr if unverified_corr else 'N/A'}")
    summary_lines.append(f"  Interpretation: {unverified_interp}")
    summary_lines.append(f"  Sample size: {len(unverified_stars_scores)} repos")
    summary_lines.append("\nOverall (All Actions):")
    summary_lines.append(f"  Correlation: {overall_corr if overall_corr else 'N/A'}")
    summary_lines.append(f"  Interpretation: {overall_interp}")
    summary_lines.append(f"  Sample size: {len(all_stars_scores)} repos")
    
    if overall_corr is not None:
        if abs(overall_corr) < 0.2:
            print(f"\n💡 Conclusion: Popularity (stars) does NOT predict security quality!")
            summary_lines.append("\n💡 Conclusion: Popularity (stars) does NOT predict security quality!")
        elif overall_corr > 0.4:
            print(f"\n💡 Conclusion: More popular actions tend to be more secure!")
            summary_lines.append("\n💡 Conclusion: More popular actions tend to be more secure!")
        elif overall_corr < -0.2:
            print(f"\n💡 Conclusion: More popular actions tend to be LESS secure!")
            summary_lines.append("\n💡 Conclusion: More popular actions tend to be LESS secure!")
        else:
            print(f"\n💡 Conclusion: Weak relationship between popularity and security")
            summary_lines.append("\n💡 Conclusion: Weak relationship between popularity and security")
    summary_lines.append("")
    
    print(f"\n{'='*60}")
    print("COMMON FAILURE REASONS ANALYSIS")
    print(f"{'='*60}")
    
    summary_lines.append("="*60)
    summary_lines.append("COMMON FAILURE REASONS ANALYSIS")
    summary_lines.append("="*60)
    summary_lines.append("")
    
    if common_issues:
        print("\nTop 5 Most Problematic Checks:")
        summary_lines.append("Top 5 Most Problematic Checks:")
        for i, issue in enumerate(common_issues[:5], 1):
            check_display = format_check_name_with_occurrence(issue['check'], check_occurrence_summary.get(issue['check'], {}))
            print(f"\n{i}. {check_display}")
            print(f"   Total failures (score < 5): {issue['failure_count']}")
            print(f"   Most common reason: \"{issue['most_common_reason']}\"")
            print(f"   Occurrences of this reason: {issue['reason_count']}")
            
            summary_lines.append(f"\n{i}. {check_display}")
            summary_lines.append(f"   Total failures (score < 5): {issue['failure_count']}")
            summary_lines.append(f"   Most common reason: \"{issue['most_common_reason']}\"")
            summary_lines.append(f"   Occurrences of this reason: {issue['reason_count']}")
        
        # Show top reasons across all checks
        print(f"\n{'='*60}")
        print("TOP FAILURE REASONS (Most Frequent)")
        print(f"{'='*60}")
        
        summary_lines.append("")
        summary_lines.append("="*60)
        summary_lines.append("TOP FAILURE REASONS (Most Frequent)")
        summary_lines.append("="*60)
        
        # Aggregate all reasons
        all_reasons_count = defaultdict(int)
        for check_name, reasons in check_low_score_reasons.items():
            for reason, count in reasons.items():
                all_reasons_count[reason] += count
        
        top_reasons = sorted(all_reasons_count.items(), key=lambda x: x[1], reverse=True)[:10]
        for i, (reason, count) in enumerate(top_reasons, 1):
            print(f"{i}. \"{reason}\" - {count} occurrences")
            summary_lines.append(f"{i}. \"{reason}\" - {count} occurrences")
    else:
        print("\nNo significant failure patterns detected.")
        summary_lines.append("\nNo significant failure patterns detected.")
    summary_lines.append("")
    
    print(f"\n{'='*60}")
    print("REASON BIAS ANALYSIS (Verified vs Unverified)")
    print(f"{'='*60}")
    print(f"\nTotal low-score samples:")
    print(f"  Verified: {verified_total_samples}")
    print(f"  Unverified: {unverified_total_samples}")
    
    summary_lines.append("="*60)
    summary_lines.append("REASON BIAS ANALYSIS (Verified vs Unverified)")
    summary_lines.append("="*60)
    summary_lines.append("\nTotal low-score samples:")
    summary_lines.append(f"  Verified: {verified_total_samples}")
    summary_lines.append(f"  Unverified: {unverified_total_samples}")
    
    if verified_biased_reasons:
        print(f"\nReasons MORE COMMON in VERIFIED actions (>5% difference):")
        summary_lines.append("\nReasons MORE COMMON in VERIFIED actions (>5% difference):")
        for i, (reason, reason_data) in enumerate(list(verified_biased_reasons.items())[:5], 1):
            print(f"\n{i}. \"{reason}\"")
            print(f"   Verified: {reason_data['verified_count']} occurrences ({reason_data['verified_percentage']:.1f}%)")
            print(f"   Unverified: {reason_data['unverified_count']} occurrences ({reason_data['unverified_percentage']:.1f}%)")
            print(f"   Difference: +{reason_data['difference_pct']:.1f}% towards verified")
            
            summary_lines.append(f"\n{i}. \"{reason}\"")
            summary_lines.append(f"   Verified: {reason_data['verified_count']} occurrences ({reason_data['verified_percentage']:.1f}%)")
            summary_lines.append(f"   Unverified: {reason_data['unverified_count']} occurrences ({reason_data['unverified_percentage']:.1f}%)")
            summary_lines.append(f"   Difference: +{reason_data['difference_pct']:.1f}% towards verified")
    
    if unverified_biased_reasons:
        print(f"\nReasons MORE COMMON in UNVERIFIED actions (>5% difference):")
        summary_lines.append("\nReasons MORE COMMON in UNVERIFIED actions (>5% difference):")
        for i, (reason, reason_data) in enumerate(list(unverified_biased_reasons.items())[:5], 1):
            print(f"\n{i}. \"{reason}\"")
            print(f"   Verified: {reason_data['verified_count']} occurrences ({reason_data['verified_percentage']:.1f}%)")
            print(f"   Unverified: {reason_data['unverified_count']} occurrences ({reason_data['unverified_percentage']:.1f}%)")
            print(f"   Difference: {reason_data['difference_pct']:.1f}% towards unverified")
            
            summary_lines.append(f"\n{i}. \"{reason}\"")
            summary_lines.append(f"   Verified: {reason_data['verified_count']} occurrences ({reason_data['verified_percentage']:.1f}%)")
            summary_lines.append(f"   Unverified: {reason_data['unverified_count']} occurrences ({reason_data['unverified_percentage']:.1f}%)")
            summary_lines.append(f"   Difference: {reason_data['difference_pct']:.1f}% towards unverified")
    
    if not verified_biased_reasons and not unverified_biased_reasons:
        print("\nNo significant bias detected - verified and unverified have similar failure patterns.")
        summary_lines.append("\nNo significant bias detected - verified and unverified have similar failure patterns.")
    
    # === OUTPUT FOR NEW ANALYSES ===
    
    # 1. Failure Clustering
    print(f"\n{'='*60}")
    print("FAILURE CLUSTERING ANALYSIS")
    print(f"{'='*60}")
    print(f"\nCritical Checks (>=75% failure rate): {len(clustering_by_tier.get('critical', []))}")
    for check in clustering_by_tier.get("critical", []):
        cluster_data = failure_clustering[check]
        check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
        print(f"  - {check_display}: {cluster_data['failure_rate_pct']:.1f}% fail (avg: {cluster_data['average_score']:.1f})")
    
    print(f"\nHigh Failure Checks (50-75%): {len(clustering_by_tier.get('high_failure', []))}")
    for check in clustering_by_tier.get("high_failure", []):
        cluster_data = failure_clustering[check]
        check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
        print(f"  - {check_display}: {cluster_data['failure_rate_pct']:.1f}% fail (avg: {cluster_data['average_score']:.1f})")
    
    summary_lines.append("")
    summary_lines.append("="*60)
    summary_lines.append("FAILURE CLUSTERING ANALYSIS")
    summary_lines.append("="*60)
    summary_lines.append(f"\nCritical Checks (>=75% failure rate): {len(clustering_by_tier.get('critical', []))}")
    for check in clustering_by_tier.get("critical", []):
        cluster_data = failure_clustering[check]
        check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
        summary_lines.append(f"  - {check_display}: {cluster_data['failure_rate_pct']:.1f}% fail (avg: {cluster_data['average_score']:.1f})")
    summary_lines.append(f"\nHigh Failure Checks (50-75%): {len(clustering_by_tier.get('high_failure', []))}")
    for check in clustering_by_tier.get("high_failure", []):
        cluster_data = failure_clustering[check]
        check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
        summary_lines.append(f"  - {check_display}: {cluster_data['failure_rate_pct']:.1f}% fail (avg: {cluster_data['average_score']:.1f})")
    
    # 3. Verification Impact
    print(f"\n{'='*60}")
    print("VERIFICATION IMPACT PER CHECK")
    print(f"{'='*60}")
    print("\nTop 5 Checks Where Verification Matters Most:")
    for i, (check, impact_data) in enumerate(list(high_impact_checks.items()), 1):
        check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
        print(f"\n{i}. {check_display}")
        print(f"   Score Premium: +{impact_data['score_premium']:.2f} points ({impact_data['score_premium_pct']:+.1f}%)")
        print(f"   Failure Rate Reduction: {impact_data['failure_rate_reduction_pct']:.1f}%")
        print(f"   Verified avg: {impact_data['verified_avg']:.1f}, Unverified avg: {impact_data['unverified_avg']:.1f}")
    
    summary_lines.append("")
    summary_lines.append("="*60)
    summary_lines.append("VERIFICATION IMPACT PER CHECK")
    summary_lines.append("="*60)
    summary_lines.append("\nTop 5 Checks Where Verification Matters Most:")
    for i, (check, impact_data) in enumerate(list(high_impact_checks.items()), 1):
        check_display = format_check_name_with_occurrence(check, check_occurrence_summary.get(check, {}))
        summary_lines.append(f"\n{i}. {check_display}")
        summary_lines.append(f"   Score Premium: +{impact_data['score_premium']:.2f} points ({impact_data['score_premium_pct']:+.1f}%)")
        summary_lines.append(f"   Failure Rate Reduction: {impact_data['failure_rate_reduction_pct']:.1f}%")
        summary_lines.append(f"   Verified avg: {impact_data['verified_avg']:.1f}, Unverified avg: {impact_data['unverified_avg']:.1f}")
    
    # 4. Risk Profiling
    print(f"\n{'='*60}")
    print("RISK PROFILING")
    print(f"{'='*60}")
    print(f"\n⚠️  HIGH RISK: Popular Actions with Low Security ({len(high_risk_repos)} total)")
    print(f"    (>={HIGH_POPULARITY_THRESHOLD} stars, score <{LOW_SCORE_THRESHOLD})")
    print("\nTop 10 High Risk:")
    for i, repo in enumerate(high_risk_repos_sorted[:10], 1):
        print(f"{i:2}. {repo['repo']:45} {repo['stars']:6,} ⭐ | Score: {repo['score']:.1f} | {repo['category']}")
    
    print(f"\n✅ LOW RISK: High Security Actions ({len(low_risk_repos)} total)")
    print(f"    (score >={HIGH_SCORE_THRESHOLD})")
    print("\nTop 10 Best Performers:")
    for i, repo in enumerate(low_risk_repos_sorted[:10], 1):
        print(f"{i:2}. {repo['repo']:45} {repo['stars']:6,} ⭐ | Score: {repo['score']:.1f} | {repo['category']}")
    
    summary_lines.append("")
    summary_lines.append("="*60)
    summary_lines.append("RISK PROFILING")
    summary_lines.append("="*60)
    summary_lines.append(f"\n⚠️  HIGH RISK: Popular Actions with Low Security ({len(high_risk_repos)} total)")
    summary_lines.append(f"    (>={HIGH_POPULARITY_THRESHOLD} stars, score <{LOW_SCORE_THRESHOLD})")
    summary_lines.append("\nTop 10 High Risk:")
    for i, repo in enumerate(high_risk_repos_sorted[:10], 1):
        summary_lines.append(f"{i:2}. {repo['repo']:45} {repo['stars']:6,} ⭐ | Score: {repo['score']:.1f} | {repo['category']}")
    summary_lines.append(f"\n✅ LOW RISK: High Security Actions ({len(low_risk_repos)} total)")
    summary_lines.append(f"    (score >={HIGH_SCORE_THRESHOLD})")
    summary_lines.append("\nTop 10 Best Performers:")
    for i, repo in enumerate(low_risk_repos_sorted[:10], 1):
        summary_lines.append(f"{i:2}. {repo['repo']:45} {repo['stars']:6,} ⭐ | Score: {repo['score']:.1f} | {repo['category']}")
    
    # 6. Actionable Recommendations
    print(f"\n{'='*60}")
    print("ACTIONABLE RECOMMENDATIONS")
    print(f"{'='*60}")
    print(f"\n🎯 QUICK WINS (Easy Improvements):")
    for i, rec in enumerate(quick_wins_sorted, 1):
        check_display = format_check_name_with_occurrence(rec['check'], check_occurrence_summary.get(rec['check'], {}))
        print(f"{i}. {check_display} [{rec['difficulty']}]")
        print(f"   - Failure rate: {rec['failure_rate_pct']:.1f}%")
        print(f"   - Potential gain: +{rec['potential_score_gain']:.2f} points")
        print(f"   - Priority: {rec['priority']}")
    
    print(f"\n🔧 HARD IMPROVEMENTS (Require Effort):")
    for i, rec in enumerate(hard_improvements_sorted, 1):
        check_display = format_check_name_with_occurrence(rec['check'], check_occurrence_summary.get(rec['check'], {}))
        print(f"{i}. {check_display} [{rec['difficulty']}]")
        print(f"   - Failure rate: {rec['failure_rate_pct']:.1f}%")
        print(f"   - Potential gain: +{rec['potential_score_gain']:.2f} points")
    
    summary_lines.append("")
    summary_lines.append("="*60)
    summary_lines.append("ACTIONABLE RECOMMENDATIONS")
    summary_lines.append("="*60)
    summary_lines.append("\n🎯 QUICK WINS (Easy Improvements):")
    for i, rec in enumerate(quick_wins_sorted, 1):
        check_display = format_check_name_with_occurrence(rec['check'], check_occurrence_summary.get(rec['check'], {}))
        summary_lines.append(f"{i}. {check_display} [{rec['difficulty']}]")
        summary_lines.append(f"   - Failure rate: {rec['failure_rate_pct']:.1f}%")
        summary_lines.append(f"   - Potential gain: +{rec['potential_score_gain']:.2f} points")
        summary_lines.append(f"   - Priority: {rec['priority']}")
    summary_lines.append("\n🔧 HARD IMPROVEMENTS (Require Effort):")
    for i, rec in enumerate(hard_improvements_sorted, 1):
        check_display = format_check_name_with_occurrence(rec['check'], check_occurrence_summary.get(rec['check'], {}))
        summary_lines.append(f"{i}. {check_display} [{rec['difficulty']}]")
        summary_lines.append(f"   - Failure rate: {rec['failure_rate_pct']:.1f}%")
        summary_lines.append(f"   - Potential gain: +{rec['potential_score_gain']:.2f} points")
    
    # 7. Outlier Detection
    print(f"\n{'='*60}")
    print("OUTLIER DETECTION")
    print(f"{'='*60}")
    print(f"\nStatistics: Mean={mean_score:.2f}, StdDev={std_dev:.2f}")
    print(f"High outlier threshold: >{mean_score + 2 * std_dev:.2f}")
    print(f"Low outlier threshold: <{mean_score - 2 * std_dev:.2f}")
    
    print(f"\n🌟 EXCEPTIONAL HIGH PERFORMERS ({len(exceptional_high)} total):")
    for i, repo in enumerate(exceptional_high_sorted, 1):
        print(f"{i:2}. {repo['repo']:45} Score: {repo['score']:.1f} | {repo['stars']:,} ⭐ | {repo['category']}")
    
    print(f"\n⚠️  EXCEPTIONAL LOW PERFORMERS ({len(exceptional_low)} total):")
    for i, repo in enumerate(exceptional_low_sorted, 1):
        print(f"{i:2}. {repo['repo']:45} Score: {repo['score']:.1f} | {repo['stars']:,} ⭐ | {repo['category']}")
    
    summary_lines.append("")
    summary_lines.append("="*60)
    summary_lines.append("OUTLIER DETECTION")
    summary_lines.append("="*60)
    summary_lines.append(f"\nStatistics: Mean={mean_score:.2f}, StdDev={std_dev:.2f}")
    summary_lines.append(f"High outlier threshold: >{mean_score + 2 * std_dev:.2f}")
    summary_lines.append(f"Low outlier threshold: <{mean_score - 2 * std_dev:.2f}")
    summary_lines.append(f"\n🌟 EXCEPTIONAL HIGH PERFORMERS ({len(exceptional_high)} total):")
    for i, repo in enumerate(exceptional_high_sorted, 1):
        summary_lines.append(f"{i:2}. {repo['repo']:45} Score: {repo['score']:.1f} | {repo['stars']:,} ⭐ | {repo['category']}")
    summary_lines.append(f"\n⚠️  EXCEPTIONAL LOW PERFORMERS ({len(exceptional_low)} total):")
    for i, repo in enumerate(exceptional_low_sorted, 1):
        summary_lines.append(f"{i:2}. {repo['repo']:45} Score: {repo['score']:.1f} | {repo['stars']:,} ⭐ | {repo['category']}")
    
    # 8. Check Correlation Matrix
    print(f"\n{'='*60}")
    print("CHECK CORRELATION MATRIX")
    print(f"{'='*60}")
    print(f"\nAnalyzed {len(check_correlations)} check pairs")
    print(f"Found {len(strong_correlations)} significant correlations (|r| >= 0.3)")
    print("\nTop 10 Strongest Correlations (sample% > 50%):")
    for i, (pair_key, corr_data) in enumerate(list(strong_correlations.items())[:10], 1):
        print(f"{i:2}. {corr_data['check1']:25} <-> {corr_data['check2']:25}")
        print(f"    r={corr_data['correlation']:+.3f} ({corr_data['interpretation']}) | sample% = {corr_data['sample_percentage']:.1f}%")
    
    summary_lines.append("")
    summary_lines.append("="*60)
    summary_lines.append("CHECK CORRELATION MATRIX")
    summary_lines.append("="*60)
    summary_lines.append(f"\nAnalyzed {len(check_correlations)} check pairs")
    summary_lines.append(f"Found {len(strong_correlations)} significant correlations (|r| >= 0.3)")
    summary_lines.append("\nTop 10 Strongest Correlations (sample% > 50%):")
    for i, (pair_key, corr_data) in enumerate(list(strong_correlations.items())[:10], 1):
        summary_lines.append(f"{i:2}. {corr_data['check1']:25} <-> {corr_data['check2']:25}")
        summary_lines.append(f"    r={corr_data['correlation']:+.3f} ({corr_data['interpretation']}) | sample% = {corr_data['sample_percentage']:.1f}%")
    summary_lines.append("")
    
    # Save summary to text file
    print(f"\nSaving summary to {summary_file}...")
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary_lines))
    
    print(f"\nFull analysis saved to: {output_file}")
    print(f"Summary report saved to: {summary_file}")


if __name__ == "__main__":
    analyze_scorecards()
