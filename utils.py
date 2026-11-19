import os
import time
import pytz
import shutil
import datetime
from contextlib import closing
from email.utils import parsedate_to_datetime
from typing import List, Dict, Union
import urllib, urllib.request, urllib.error

import feedparser
from easydict import EasyDict


def remove_duplicated_spaces(text: str) -> str:
    return " ".join(text.split())

def build_arxiv_query(keyword: Union[str, List[str]], link: str = "OR") -> str:
    """Match any keyword phrase in the title or abstract of a paper."""
    if link not in ["OR", "AND"]:
        raise ValueError("link should be 'OR' or 'AND'")
    keywords = [keyword] if isinstance(keyword, str) else keyword
    clauses = []
    seen = set()
    for term in keywords:
        term = remove_duplicated_spaces(term)
        if not term:
            raise ValueError("Search keywords must not be empty")
        if '"' in term:
            raise ValueError("Search keywords must not contain double quotes")
        if term.casefold() in seen:
            continue
        seen.add(term.casefold())
        clauses.append('(ti:"{0}" {1} abs:"{0}")'.format(term, link))
    if not clauses:
        raise ValueError("At least one search keyword is required")
    return " OR ".join(clauses)

def request_paper_with_arXiv_api(keyword: Union[str, List[str]], max_results: int, link: str = "OR") -> List[Dict[str, str]]:
    query = build_arxiv_query(keyword, link)
    params = urllib.parse.urlencode({
        "search_query": query,
        "max_results": max_results,
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
    })
    url = "https://export.arxiv.org/api/query?" + params
    request = urllib.request.Request(url, headers={
        "User-Agent": "DailyArXiv/1.0 (https://github.com/wbfwonderful/DailyArXiv)",
    })
    with closing(urllib.request.urlopen(request, timeout=60)) as response:
        response = response.read().decode('utf-8')
    feed = feedparser.parse(response)

    # NOTE default columns: Title, Authors, Abstract, Link, Tags, Comment, Submitted, Updated
    papers = []
    for entry in feed.entries:
        entry = EasyDict(entry)
        paper = EasyDict()

        # title
        paper.Title = remove_duplicated_spaces(entry.title.replace("\n", " "))
        # abstract
        paper.Abstract = remove_duplicated_spaces(entry.summary.replace("\n", " "))
        # authors
        paper.Authors = [remove_duplicated_spaces(_["name"].replace("\n", " ")) for _ in entry.authors]
        # link
        paper.Link = remove_duplicated_spaces(entry.link.replace("\n", " "))
        # tags
        paper.Tags = [remove_duplicated_spaces(_["term"].replace("\n", " ")) for _ in entry.tags]
        # comment
        paper.Comment = remove_duplicated_spaces(entry.get("arxiv_comment", "").replace("\n", " "))
        # First submission and latest revision dates from arXiv.
        paper.Submitted = entry.published
        paper.Updated = entry.updated

        papers.append(paper)
    return papers

def filter_tags(papers: List[Dict[str, str]], target_fileds: List[str]=["cs", "stat"]) -> List[Dict[str, str]]:
    # filtering tags: only keep the papers in target_fileds
    results = []
    for paper in papers:
        tags = paper.Tags
        for tag in tags:
            if tag.split(".")[0] in target_fileds:
                results.append(paper)
                break
    return results

def retry_after_seconds(value: str) -> float:
    """Parse Retry-After as seconds or an HTTP date; ignore malformed values."""
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        try:
            retry_date = parsedate_to_datetime(value)
            if retry_date.tzinfo is None:
                retry_date = retry_date.replace(tzinfo=datetime.timezone.utc)
            return max(0, (retry_date - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0

def get_daily_papers_by_keyword_with_retries(keyword: Union[str, List[str]], column_names: List[str], max_result: int, link: str = "OR", retries: int = 4) -> List[Dict[str, str]]:
    if retries < 1:
        raise ValueError("retries must be at least 1")
    for attempt in range(retries):
        server_wait = 0
        try:
            papers = get_daily_papers_by_keyword(keyword, column_names, max_result, link)
            if papers:
                return papers
            reason = "Empty result after subject filtering"
        except urllib.error.HTTPError as error:
            # Configuration/client errors should fail immediately, rather than retry.
            if error.code not in (408, 429) and not 500 <= error.code < 600:
                raise
            server_wait = retry_after_seconds(error.headers.get("Retry-After") if error.headers else None)
            reason = "HTTP {0}".format(error.code)
            error.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            reason = str(error)
        if attempt == retries - 1:
            print("arXiv query {0!r} failed after {1} attempts: {2}".format(keyword, retries, reason), flush=True)
            break
        # Back off for 30, 60, 120, ... seconds, capped at 30 minutes.
        # A longer server Retry-After always takes precedence.
        wait = max(min(30 * 2 ** attempt, 1800), server_wait)
        print("arXiv query {0!r}, attempt {1}/{2}: {3}; retrying in {4:.0f}s".format(
            keyword, attempt + 1, retries, reason, wait), flush=True)
        time.sleep(wait)
    return None

def get_daily_papers_by_keyword(keyword: Union[str, List[str]], column_names: List[str], max_result: int, link: str = "OR") -> List[Dict[str, str]]:
    # get papers
    papers = request_paper_with_arXiv_api(keyword, max_result, link)
    # NOTE filtering tags: only keep the papers in cs field
    # TODO filtering more
    papers = filter_tags(papers)
    # select columns for display
    papers = [{column_name: paper[column_name] for column_name in column_names} for paper in papers]
    return papers

def generate_table(papers: List[Dict[str, str]], ignore_keys: List[str] = []) -> str:
    formatted_papers = []
    keys = papers[0].keys()
    for paper in papers:
        # process fixed columns
        formatted_paper = EasyDict()
        ## Title and Link
        formatted_paper.Title = "**" + "[{0}]({1})".format(paper["Title"], paper["Link"]) + "**"
        ## Display arXiv dates as YYYY-MM-DD without changing the query order.
        formatted_paper["First Submitted"] = paper["Submitted"].split("T")[0]
        formatted_paper["Last Updated"] = paper["Updated"].split("T")[0]
        
        # process other columns
        for key in keys:
            if key in ["Title", "Link", "Submitted", "Updated"] or key in ignore_keys:
                continue
            elif key == "Abstract":
                # add show/hide button for abstract
                formatted_paper[key] = "<details><summary>Show</summary><p>{0}</p></details>".format(paper[key])
            elif key == "Authors":
                # NOTE only use the first author
                formatted_paper[key] = paper[key][0] + " et al."
            elif key == "Tags":
                tags = ", ".join(paper[key])
                if len(tags) > 10:
                    formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(tags[:5], tags)
                else:
                    formatted_paper[key] = tags
            elif key == "Comment":
                if paper[key] == "":
                    formatted_paper[key] = ""
                elif len(paper[key]) > 20:
                    formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(paper[key][:5], paper[key])
                else:
                    formatted_paper[key] = paper[key]
        formatted_papers.append(formatted_paper)

    # generate header
    columns = formatted_papers[0].keys()
    # highlight headers
    columns = ["**" + column + "**" for column in columns]
    header = "| " + " | ".join(columns) + " |"
    header = header + "\n" + "| " + " | ".join(["---"] * len(formatted_papers[0].keys())) + " |"
    # generate the body
    body = ""
    for paper in formatted_papers:
        body += "\n| " + " | ".join(paper.values()) + " |"
    return header + body

def back_up_files():
    # back up README.md and ISSUE_TEMPLATE.md
    shutil.move("README.md", "README.md.bk")
    shutil.move(".github/ISSUE_TEMPLATE.md", ".github/ISSUE_TEMPLATE.md.bk")

def restore_files():
    # restore README.md and ISSUE_TEMPLATE.md
    shutil.move("README.md.bk", "README.md")
    shutil.move(".github/ISSUE_TEMPLATE.md.bk", ".github/ISSUE_TEMPLATE.md")

def remove_backups():
    # remove README.md and ISSUE_TEMPLATE.md
    os.remove("README.md.bk")
    os.remove(".github/ISSUE_TEMPLATE.md.bk")

def get_daily_date():
    # get beijing time in the format of "March 1, 2021"
    beijing_timezone = pytz.timezone('Asia/Shanghai')
    today = datetime.datetime.now(beijing_timezone)
    return today.strftime("%B %d, %Y")
