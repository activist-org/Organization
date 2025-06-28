# SPDX-License-Identifier: GPL-3.0-or-later
"""
Calculate the top organization community contributors for a Community Spotlight Matrix message.

Notes
-----
- Fetches commit data from GitHub for all organization projects over the past month
- Period is the 25th of last month to 25th of current month
- Organization members are filtered out
- Formats a message for a Matrix channel
- Ran via GitHub Actions workflow that requires GitHub environment variables
"""

import requests
from datetime import datetime
from collections import defaultdict
import os

ORG_ID = "activist-org"
ORG_NAME = "activist"
TOP_N = 5


def get_date_range():
    """
    Calculate the date range: 25th of last month to 25th of current month.
    """
    today = datetime.now()
    start_month = today.month - 1 if today.month > 1 else 12
    start_year = today.year if today.month > 1 else today.year - 1
    start_date = datetime(start_year, start_month, 25)
    end_date = datetime(today.year, today.month, 25)

    return start_date, end_date


def get_org_members():
    """
    Fetch all members of the organization.
    """
    members = set()
    page = 1
    headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}

    while True:
        url = f"https://api.github.com/orgs/{ORG_ID}/members?per_page=100&page={page}"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            print(f"Error fetching org members: {r.status_code} {r.text}")
            break

        data = r.json()
        if not data:
            break

        members.update(user["login"] for user in data)
        page += 1

    return members


def get_repos():
    """
    Fetch all repository names for the organization.
    """
    repos = []
    page = 1
    headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}

    while True:
        url = f"https://api.github.com/orgs/{ORG_ID}/repos?per_page=100&page={page}"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            print(f"Error fetching repos: {r.status_code} {r.text}")
            break

        data = r.json()
        if not data:
            break

        repos += [repo["name"] for repo in data]
        page += 1

    return repos


def get_commits(repo, start_date, end_date):
    """
    Fetch commits for a repository within the date range.
    """
    commits = []
    page = 1
    headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}

    while True:
        url = (
            f"https://api.github.com/repos/{ORG_ID}/{repo}/commits?"
            f"since={start_date.isoformat()}Z&until={end_date.isoformat()}Z&per_page=100&page={page}"
        )
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            print(f"Error fetching commits for {repo}: {r.status_code}")
            break

        data = r.json()
        if not isinstance(data, list) or not data:
            break

        commits += data
        page += 1

    return commits


def get_user_prs(username, repos, start_date, end_date):
    """
    Fetch pull requests for a user across specified repositories.
    """
    prs_by_repo = defaultdict(list)
    headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}

    for repo in repos:
        page = 1
        while True:
            url = (
                f"https://api.github.com/repos/{ORG_ID}/{repo}/pulls?"
                f"state=all&per_page=100&page={page}"
            )
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                print(f"Error fetching PRs for {repo}: {r.status_code}")
                break

            data = r.json()
            if not data:
                break

            for pr in data:
                created_at = datetime.strptime(pr["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                if (
                    pr["user"]["login"] == username
                    and start_date <= created_at <= end_date
                ):
                    prs_by_repo[repo].append(pr["html_url"])

            page += 1

    return prs_by_repo


def main():
    """
    Calculate top non-org contributors and format the Community Spotlight message.
    """
    # Initialize contributor tracking.
    contribution_count = defaultdict(int)

    # Get date range, org members and repositories.
    start_date, end_date = get_date_range()
    org_members = get_org_members()
    repos = get_repos()

    users_to_ignore = ["weblate", "dependabot[bot]", "to-sta"]

    # Count commits per author while excluding org members.
    for repo in repos:
        commits = get_commits(repo, start_date, end_date)
        for commit in commits:
            author = commit.get("author")
            if (
                author
                and author.get("login")
                and author["login"] not in org_members
                and author["login"] not in users_to_ignore
            ):
                contribution_count[author["login"]] += 1

    # Sort contributors by commit count.
    top_contributors = sorted(
        contribution_count.items(), key=lambda x: x[1], reverse=True
    )[:TOP_N]

    # Build the message.
    message = (
        "**Monthly Community Spotlight 👥🎉**\n\n"
        f"Here are the top community contributors on GitHub to all **{ORG_NAME}** projects from "
        f"**{start_date.strftime('%B %d')}** to **{end_date.strftime('%B %d')}** "
        "(organization members not included):\n\n"
    )

    # Fetch PRs for each top contributor.
    for user, count in top_contributors:
        prs_by_repo = get_user_prs(user, repos, start_date, end_date)
        message += f"- [{user}](https://github.com/{user}) ({count} commits)\n"
        if prs_by_repo:
            for repo, pr_urls in prs_by_repo.items():
                pr_list = ", ".join(
                    f"[PR#{url.split('/')[-1]}]({url})" for url in pr_urls
                )
                message += f"    - [{repo}](https://github.com/{ORG_ID}/{repo}/pulls?q=is%3Apr+author%3A{user}+created%3A{start_date.strftime('%Y-%m-%d')}..{end_date.strftime('%Y-%m-%d')}) ({pr_list})\n"

        else:
            message += "    - No pull requests found\n"

    message += "\n\nThank you all for the amazing work over the last month! ❤️"

    # Write message to file for reference.
    with open("message.txt", "w") as f:
        f.write(message)

    # Set GitHub Actions output.
    with open(os.getenv("GITHUB_OUTPUT"), "a") as f:
        f.write(f"message<<EOF\n{message}\nEOF\n")

    # Log summary for debugging.
    with open(os.getenv("GITHUB_STEP_SUMMARY"), "a") as f:
        f.write("**Community Spotlight Summary** 🟢\n")
        f.write(
            f"Date Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n"
        )
        f.write(f"Repositories Scanned: {len(repos)}\n")
        f.write(f"Organization Members Excluded: {len(org_members)}\n")
        f.write("Top Non-Organization Contributors:\n")

        for user, count in top_contributors:
            f.write(f"- {user}: {count} commits\n")
            prs_by_repo = get_user_prs(user, repos, start_date, end_date)
            for repo, pr_urls in prs_by_repo.items():
                f.write(f"  - {repo}: {len(pr_urls)} PRs\n")

        f.write("\nMessage prepared for Matrix channel.\n")


if __name__ == "__main__":
    main()
