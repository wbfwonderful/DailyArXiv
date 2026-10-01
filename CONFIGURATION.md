# 主题与检索变体

在 `main.py` 的 `topics` 中配置主题：

```python
topics = [
    {"name": "Video Anomaly Detection", "variants": []},
    {
        "name": "Multimodal Large Language Model",
        "variants": ["MLLM", "Multimodal LLM"],
    },
]
```

- `name`：README 和 Issue 中的主题标题，也自动参与检索。
- `variants`：该主题的其他检索写法；没有变体时设为 `[]`，也可以省略该字段。

每种写法都在论文标题或摘要中检索，多词写法使用带双引号的短语查询。各写法之间使用 `OR`，单词缩写也允许只在标题或摘要中匹配。例如，上面的多模态主题会生成：

```text
(ti:"Multimodal Large Language Model" OR abs:"Multimodal Large Language Model") OR (ti:"MLLM" OR abs:"MLLM") OR (ti:"Multimodal LLM" OR abs:"Multimodal LLM")
```

一个主题只发送一次合并查询，匹配多种写法的同一篇论文不会因分别查询变体而重复添加。不同主题之间仍可能出现同一篇论文。

`max_result` 控制每个主题合并查询的结果上限，当前为 20，按最后更新时间降序获取。随后保留带有 `cs.*` 或 `stat.*` 标签的论文，因此最终条数可能少于上限。Issue 展示每个主题前 `issues_result` 篇，当前为 15。

表格的 `Date` 使用首次提交日期；它与查询排序依据的最后更新时间不同。

修改配置后，在仓库根目录运行 `python main.py`，或等待下一次 GitHub Actions 自动更新。脚本会重新生成 README 和 Issue 模板。直接编辑生成的表格会在下一次运行时被覆盖。
