#!/usr/bin/env python3
"""Publish a GitHub API snapshot directly into a marked README Markdown section.

Python standard library only. No network or writes occur on import.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"
START = "<!-- observatory:start -->"
END = "<!-- observatory:end -->"


class DataError(RuntimeError):
    """A complete, trustworthy snapshot could not be obtained."""


def count(value, label):
    if type(value) is not int or value < 0:
        raise DataError(f"Invalid or missing count: {label}")
    return value


def detect_username(explicit=None):
    username = explicit or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not username:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        username = repository.split("/")[0] if repository else None
    if not username:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True
        ).strip()
        match = re.search(r"github\.com[:/]([^/]+)/[^/]+(?:\.git)?$", remote)
        username = match.group(1) if match else None
    if not username or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", username):
        raise DataError("Cannot detect a GitHub username; pass --username.")
    return username


class GitHub:
    def __init__(self, token=None):
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "GitHub-Observatory/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, params=None):
        url = API + path if path.startswith("/") else path
        # Never forward credentials to a foreign pagination URL.
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise DataError("Refusing a non-GitHub API URL.")
        if params:
            url += "?" + urlencode(params)
        for attempt in range(4):
            try:
                with urlopen(Request(url, headers=self.headers), timeout=30) as response:
                    return json.load(response), response.headers
            except HTTPError as exc:
                retryable = exc.code in (403, 429, 500, 502, 503, 504)
                if not retryable or attempt == 3:
                    raise DataError(f"GitHub API returned HTTP {exc.code}; snapshot preserved.") from None
                delay = 2 ** (attempt + 1)
                retry_after = exc.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = parsedate_to_datetime(retry_after).timestamp() - time.time()
                elif exc.headers.get("X-RateLimit-Remaining") == "0":
                    delay = float(exc.headers.get("X-RateLimit-Reset", 0)) - time.time() + 1
                elif exc.code in (403, 429):
                    delay = 60  # GitHub secondary-rate-limit guidance.
                if delay > 60:
                    raise DataError("GitHub rate limit exhausted; retry after reset. Snapshot preserved.") from None
                print(f"GitHub HTTP {exc.code}; retrying in {max(1, delay):.0f}s.", file=sys.stderr)
                time.sleep(max(1, delay))
            except (URLError, TimeoutError, ConnectionError) as exc:
                if attempt == 3:
                    raise DataError(f"GitHub connection failed ({type(exc).__name__}); snapshot preserved.") from None
                time.sleep(2 ** (attempt + 1))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise DataError("GitHub returned invalid JSON; snapshot preserved.") from None

    def repositories(self, username):
        path = f"/users/{quote(username)}/repos"
        params = {"type": "owner", "sort": "full_name", "per_page": 100}
        seen_urls = set()
        repos = {}
        while path:
            if path in seen_urls:
                raise DataError("Repeated GitHub pagination link.")
            seen_urls.add(path)
            data, headers = self.get(path, params)
            if not isinstance(data, list):
                raise DataError("Invalid repository response.")
            for repo in data:
                if repo["owner"]["login"].casefold() == username.casefold() and not repo["private"]:
                    repos[repo["id"]] = repo
            match = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("Link", ""))
            path = match.group(1) if match else None
            params = None
        return sorted(repos.values(), key=lambda repo: repo["full_name"].casefold())

    def search_count(self, kind, query):
        # total_count is independent of the 1,000-item search retrieval cap.
        for attempt in range(3):
            data, _ = self.get(f"/search/{kind}", {"q": query, "per_page": 1})
            if data.get("incomplete_results") is False:
                return count(data.get("total_count"), kind)
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
        raise DataError(f"Incomplete GitHub {kind} search; snapshot preserved.")


def collect(client, username, now, include_forks=False):
    profile, _ = client.get(f"/users/{quote(username)}")
    if profile.get("type") != "User":
        raise DataError("This profile dashboard requires a personal GitHub account.")
    repos = client.repositories(username)
    public_repos = count(profile.get("public_repos"), "public repositories")
    if len(repos) != public_repos:
        raise DataError("Repository count changed during collection; retry for a consistent snapshot.")
    end = now.date().isoformat()
    commit_query = f"author:{username} author-date:{now.year}-01-01..{end} is:public"
    pr_query = f"is:pr author:{username} is:public"
    commits = client.search_count("commits", commit_query)
    pull_requests = client.search_count("issues", pr_query)
    languages = Counter()
    provenance = []
    for repo in repos:
        language_bytes = None
        if include_forks or not repo["fork"]:
            language_bytes, _ = client.get(f"/repos/{quote(repo['full_name'], safe='/')}/languages")
            if not isinstance(language_bytes, dict):
                raise DataError("Invalid repository language response.")
            for language, size in language_bytes.items():
                languages[language] += count(size, f"language bytes in {repo['full_name']}")
        provenance.append({
            "repository": repo["full_name"], "fork": repo["fork"],
            "stars": count(repo.get("stargazers_count"), "stars"),
            "language_bytes": language_bytes,
        })
    return {
        "schema_version": 1, "username": profile["login"], "year": now.year,
        "through_date_utc": end, "include_forks": include_forks,
        "metrics": {"commits": commits, "pull_requests": pull_requests,
                    "stars": sum(r["stars"] for r in provenance), "public_repositories": public_repos},
        "queries": {"commits": commit_query, "pull_requests": pr_query},
        "language_bytes": dict(sorted(languages.items())), "repositories": provenance,
    }


def language_segments(language_bytes):
    ranked = sorted(((name, size) for name, size in language_bytes.items() if size > 0),
                    key=lambda item: (-item[1], item[0]))
    total = sum(size for _, size in ranked)
    if len(ranked) > 6:
        ranked = ranked[:5] + [("Other languages", sum(size for _, size in ranked[5:]))]
    return [(name, size / total * 100) for name, size in ranked]


def markdown_escape(value):
    """Protect table cells from markup, pipes and line breaks in API text."""
    value = escape(str(value), quote=False).replace("\n", " ").replace("\r", " ")
    for char in ("\\", "`", "*", "_", "[", "]"):
        value = value.replace(char, "\\" + char)
    return value.replace("|", "&#124;")


def render(snapshot):
    metrics = snapshot['metrics']
    username = markdown_escape(snapshot['username'])
    stamp = snapshot['updated_at'].replace('T', ' ').replace('Z', ' UTC')
    lines = [
        '## \u2726 GitHub Observatory', '',
        '**\u2726 LIVE DEVELOPER ACTIVITY \u2726**', '',
        f'Public GitHub snapshot for **@{username}** ? refreshed every 6 hours.', '',
        '### GitHub Statistics', '',
        '| Metric | Total | Scope |',
        '| :--- | ---: | :--- |',
        f"| Commits ? {snapshot['year']} | **{metrics['commits']:,}** | Public default branches, current UTC year |",
        f"| Pull requests | **{metrics['pull_requests']:,}** | Authored public PRs ? all time, all states |",
        f"| Stars received | **{metrics['stars']:,}** | Owned public repositories |",
        f"| Public repositories | **{metrics['public_repositories']:,}** | Owned repositories, including forks |",
        '', '### Language Explorer', '',
    ]
    segments = language_segments(snapshot['language_bytes'])
    if segments:
        lines += ['| Language | Share | Distribution |', '| :--- | ---: | :--- |']
        for name, percent in segments:
            filled = round(percent / 100 * 20)
            bar = '\u2588' * filled + '\u2591' * (20 - filled)
            percentage = '&lt;0.1%' if percent < .05 else f'{percent:.1f}%'
            lines.append(f'| {markdown_escape(name)} | **{percentage}** | `{bar}` |')
    else:
        lines.append('No language bytes reported by GitHub.')
    forks = 'Forks included' if snapshot['include_forks'] else 'Forks excluded'
    lines += ['', f'> {forks}. Shares measure code bytes, not time or expertise. Bars are rounded to 5% steps.',
              '', f'*Last published snapshot: {stamp}*', '']
    # Keep audit data in the same atomically updated file, invisible when rendered.
    metadata = json.dumps(snapshot, sort_keys=True, ensure_ascii=True)
    metadata = metadata.replace('<', r'\u003c').replace('>', r'\u003e').replace('-', r'\u002d')
    lines.append('<!-- observatory-data: ' + metadata + ' -->')
    return '\n'.join(lines)


def publish(snapshot, readme, now):
    original = readme.read_bytes().decode('utf-8')
    if original.count(START) != 1 or original.count(END) != 1:
        raise DataError('README must contain exactly one Observatory start/end marker pair.')
    start = original.index(START) + len(START)
    end = original.index(END)
    if start > end:
        raise DataError('README Observatory markers are out of order.')
    previous = None
    match = re.search(r'<!-- observatory-data: (.*?) -->', original[start:end])
    if match:
        try:
            previous = json.loads(match.group(1))
        except ValueError:
            pass
    old_data = {k: v for k, v in (previous or {}).items() if k != 'updated_at'}
    snapshot = dict(snapshot)
    snapshot['updated_at'] = (previous['updated_at'] if old_data == snapshot and previous.get('updated_at')
                              else now.strftime('%Y-%m-%dT%H:%M:%SZ'))
    newline = '\r\n' if '\r\n' in original else '\n'
    section = render(snapshot).replace('\n', newline)
    content = original[:start] + newline + newline + section + newline + newline + original[end:]
    if content == original:
        return False
    # Only the marked block changes; a failed fetch never reaches this atomic write.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=readme.parent,
                                     suffix='.tmp', delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temporary, readme)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', help='Default: repository owner, then origin remote')
    parser.add_argument('--include-forks', action='store_true', help='Include forks in language shares')
    parser.add_argument('--readme', type=Path, default=ROOT / 'README.md')
    args = parser.parse_args(argv)
    try:
        username = detect_username(args.username)
        now = datetime.now(timezone.utc)
        client = GitHub(os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN'))
        snapshot = collect(client, username, now, args.include_forks)
        changed = publish(snapshot, args.readme, now)
        print(f"{'Updated' if changed else 'Unchanged'}: @{username}; checked {now:%Y-%m-%d %H:%M UTC}.")
        print(json.dumps(snapshot['metrics'], sort_keys=True))
        return 0
    except (DataError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f'Observatory refresh failed ({type(exc).__name__}): {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
