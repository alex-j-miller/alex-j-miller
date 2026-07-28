import os
import subprocess
import shutil
from pathlib import Path
import json

class RepoAnalyzer:
    def __init__(self, repos_dir="./cloned_repos"):
        self.repos_dir = repos_dir
        Path(self.repos_dir).mkdir(exist_ok=True)

    def clone_repo(self, repo_url):
        """Clone a repo via SSH"""
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        repo_path = os.path.join(self.repos_dir, repo_name)

        if os.path.exists(repo_path):
            print(f"  Repo already exists, skipping clone: {repo_name}")
            return repo_path

        print(f"  Cloning {repo_name}...")
        try:
            subprocess.run(['git', 'clone', repo_url, repo_path],
                         check=True, capture_output=True)
            return repo_path
        except subprocess.CalledProcessError as e:
            print(f"  Error cloning {repo_name}: {e}")
            return None

    def get_commit_count(self, repo_path):
        """Get total commit count"""
        try:
            result = subprocess.run(['git', 'log', '--oneline'],
                                  cwd=repo_path,
                                  capture_output=True,
                                  text=True,
                                  check=True)
            return len(result.stdout.strip().split('\n'))
        except subprocess.CalledProcessError:
            return 0

    def get_loc_stats(self, repo_path):
        """Get lines added and deleted"""
        try:
            result = subprocess.run(['git', 'log', '--pretty=format:', '--numstat'],
                                  cwd=repo_path,
                                  capture_output=True,
                                  text=True,
                                  check=True)

            additions = 0
            deletions = 0

            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        try:
                            additions += int(parts[0]) if parts[0].isdigit() else 0
                            deletions += int(parts[1]) if parts[1].isdigit() else 0
                        except (ValueError, IndexError):
                            pass

            return additions, deletions
        except subprocess.CalledProcessError:
            return 0, 0

    def get_current_loc(self, repo_path):
        """Get current lines of code in repo"""
        try:
            result = subprocess.run(
                ['git', 'ls-files'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )

            files = result.stdout.strip().split('\n')
            code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.cs', '.go', '.rb', '.php'}

            total_lines = 0
            for file in files:
                if any(file.endswith(ext) for ext in code_extensions):
                    file_path = os.path.join(repo_path, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            total_lines += len(f.readlines())
                    except:
                        pass

            return total_lines
        except subprocess.CalledProcessError:
            return 0

    def analyze_repo(self, repo_url):
        """Analyze a single repo"""
        repo_path = self.clone_repo(repo_url)
        if not repo_path:
            return None

        repo_name = repo_url.split('/')[-1].replace('.git', '')
        commits = self.get_commit_count(repo_path)
        additions, deletions = self.get_loc_stats(repo_path)
        current_loc = self.get_current_loc(repo_path)

        return {
            'name': repo_name,
            'url': repo_url,
            'commits': commits,
            'additions': additions,
            'deletions': deletions,
            'net_loc': additions - deletions,
            'current_loc': current_loc
        }

    def analyze_multiple_repos(self, repo_urls):
        """Analyze multiple repos"""
        results = []
        for url in repo_urls:
            print(f"\nAnalyzing {url.split('/')[-1]}...")
            result = self.analyze_repo(url)
            if result:
                results.append(result)

        return results

    def save_cache(self, results, filename='cache/ssh_stats_cache.json'):
        """Save stats to cache file"""
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        cache = {
            'repos': results,
            'totals': {
                'commits': sum(r['commits'] for r in results),
                'additions': sum(r['additions'] for r in results),
                'deletions': sum(r['deletions'] for r in results),
                'net_loc': sum(r['net_loc'] for r in results),
                'current_loc': sum(r['current_loc'] for r in results),
            }
        }
        with open(filename, 'w') as f:
            json.dump(cache, f, indent=2)
        print(f"\nStats cached to {filename}")

    def print_results(self, results):
        """Print results in a nice format"""
        if not results:
            print("No repos analyzed")
            return

        print("\n" + "="*80)
        print("Repository Statistics (SSH)")
        print("="*80)

        total_commits = 0
        total_additions = 0
        total_deletions = 0
        total_current_loc = 0

        for repo in results:
            print(f"\n{repo['name']}:")
            print(f"  Commits:     {repo['commits']:,}")
            print(f"  Additions:   {repo['additions']:,}")
            print(f"  Deletions:   {repo['deletions']:,}")
            print(f"  Net LOC:     {repo['net_loc']:,}")
            print(f"  Current LOC: {repo['current_loc']:,}")

            total_commits += repo['commits']
            total_additions += repo['additions']
            total_deletions += repo['deletions']
            total_current_loc += repo['current_loc']

        print("\n" + "="*80)
        print("Totals:")
        print(f"  Total Commits:     {total_commits:,}")
        print(f"  Total Additions:   {total_additions:,}")
        print(f"  Total Deletions:   {total_deletions:,}")
        print(f"  Total Net LOC:     {total_additions - total_deletions:,}")
        print(f"  Total Current LOC: {total_current_loc:,}")
        print("="*80)

        return results


if __name__ == '__main__':
    # Example usage
    analyzer = RepoAnalyzer()

    # Add your repo URLs here
    repos = [
        'git@github.com:MiCHDevelopment/MICIP.git',
    ]

    results = analyzer.analyze_multiple_repos(repos)
    analyzer.print_results(results)
    analyzer.save_cache(results, 'cache/ssh_stats_cache.json')
