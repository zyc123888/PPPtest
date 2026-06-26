# 示例流程

## 用户输入

```text
请分析这个需求文档并生成测试用例，最后输出成导图。
附件：
- AI Dashboard-AI波动分析助手.md
- 文档中的若干图片链接
```

## 第一步：testcase-orchestrator

输出：

- mode = `full`
- required_artifacts:
  - `EvidenceTrace.yaml`
  - `FunctionPoints.yaml`
  - `TestcasePackage.yaml`
  - `ReviewReport.yaml`
  - `AI Dashboard-AI波动分析助手.xmind`

## 第二步：requirement-analyzer

读取：

- Markdown 正文
- Markdown 中的图片链接

内部顺序：

1. 先提取图片链接
2. 再下载图片
3. 再看图片
4. 再读正文
5. 再做图文对齐

输出：

- `EvidenceTrace.yaml`
- `FunctionPoints.yaml`

## 第三步：testcase-designer

读取：

- `EvidenceTrace.yaml`
- `FunctionPoints.yaml`

约束：

- 不重新读取原始 Markdown
- 不重新读取原始截图
- 只根据 `FunctionPoints.yaml` 生成用例

输出：

- `TestcasePackage.yaml`

## 第四步：quality-reviewer

读取：

- `EvidenceTrace.yaml`
- `FunctionPoints.yaml`
- `TestcasePackage.yaml`

输出：

- `ReviewReport.yaml`

## 第五步：artifact-exporter

读取：

- `TestcasePackage.yaml`
- `ReviewReport.yaml`

输出：

- `AI Dashboard-AI波动分析助手.xmind`

可选内部产物：

- `TestCases_Full.md`
- `AI Dashboard-AI波动分析助手.xmindmark`
- `DeliverySummary.md`
