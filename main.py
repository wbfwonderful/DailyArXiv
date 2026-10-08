import sys
import time
import pytz
from datetime import datetime

from utils import get_daily_papers_by_keyword_with_retries, generate_table, back_up_files,\
    restore_files, remove_backups, get_daily_date


beijing_timezone = pytz.timezone('Asia/Shanghai')

# NOTE: arXiv API seems to sometimes return an unexpected empty list.

# get current beijing time date in the format of "2021-08-01"
current_date = datetime.now(beijing_timezone).strftime("%Y-%m-%d")
# get last update date from README.md
with open("README.md", "r") as f:
    while True:
        line = f.readline()
        if "Last update:" in line: break
    last_update_date = line.split(": ")[1].strip()
    # if last_update_date == current_date:
        # sys.exit("Already updated today!")

topics = [
    {
        "name": "Video Anomaly Detection", 
        "variants": ["Video Anom", "Video Abnormal"]
    },
    {
        "name": "Video Understanding", 
        "variants": ["Video Reason"]
    },
    {
        "name": "Multimodal Large Language Model",
        "variants": ["MLLM", "Multimodal LLM"],
    },
]

max_result = 25 # maximum query results from arXiv API for each topic
issues_result = 25 # maximum papers to be included in the issue

# all columns: Title, Authors, Abstract, Link, Tags, Comment, Submitted, Updated

column_names = ["Title", "Link", "Submitted", "Updated", "Comment"]

back_up_files() # back up README.md and ISSUE_TEMPLATE.md

# write to README.md
f_rm = open("README.md", "w") # file for README.md
f_rm.write("# Daily Papers\n")
f_rm.write("The project automatically fetches the latest papers from arXiv based on topics and their keyword variants.\n\nThe subheadings represent topics. Each topic searches its name and variants in paper titles or abstracts. See [CONFIGURATION.md](CONFIGURATION.md) for configuration.\n\nPapers are sorted by last update time, with up to {0} query results per topic before subject filtering. First Submitted shows the first submission date; Last Updated shows the latest revision date.\n\nYou can click the 'Watch' button to receive daily email notifications.\n\nLast update: {1}\n\n".format(max_result, current_date))

# write to ISSUE_TEMPLATE.md
f_is = open(".github/ISSUE_TEMPLATE.md", "w") # file for ISSUE_TEMPLATE.md
f_is.write("---\n")
f_is.write("title: Latest {0} Papers - {1}\n".format(issues_result, get_daily_date()))
f_is.write("labels: documentation\n")
f_is.write("---\n")
f_is.write("**Please check the [Github](https://github.com/zezhishao/MTS_Daily_ArXiv) page for a better reading experience and more papers.**\n\n")

for topic in topics:
    f_rm.write("## {0}\n".format(topic["name"]))
    f_is.write("## {0}\n".format(topic["name"]))
    keywords = [topic["name"]] + topic.get("variants", [])
    papers = get_daily_papers_by_keyword_with_retries(keywords, column_names, max_result)
    if papers is None: # failed to get papers
        print("Failed to get papers!")
        f_rm.close()
        f_is.close()
        restore_files()
        sys.exit("Failed to get papers!")
    rm_table = generate_table(papers)
    is_table = generate_table(papers[:issues_result])
    f_rm.write(rm_table)
    f_rm.write("\n\n")
    f_is.write(is_table)
    f_is.write("\n\n")
    time.sleep(5) # avoid being blocked by arXiv API

f_rm.close()
f_is.close()
remove_backups()
