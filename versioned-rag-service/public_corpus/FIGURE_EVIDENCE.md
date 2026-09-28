# 固定版本图片证据清单

`figure_evidence.json` 是离线审计产物，扫描当前 `corpus_manifest.json` 中的 Apache DolphinScheduler 官方 Markdown。相对图片链接从原文档路径解析到同一 Git commit 的仓库路径，记录引用章节、行号、原始 alt 文本和固定提交的 raw URL。alt 文本只说明 Markdown 作者写了什么，**不代表图片中的文字已被识别**。

截至本次清单：132 份来源含 608 处相对图片引用，归并为 307 张按提交固定的图片；另有 24 处外部图片引用。仅抽查了当前版本的 6 张业务相关图片：6 张实际下载、完整解码并记录 SHA-256，5 张由本机 Tesseract 取得 OCR 候选文字，1 张未检测到文字。其余 301 张只有固定 URL，尚未验证可用性。清单不保存图片二进制；单张下载上限为 2 MB。

生成清单（无网络）：

```powershell
py -3.11 versioned-rag-service/scripts/figure_evidence.py
```

重新核验预选的 6 张图片并在本机有 Tesseract 时执行中英文 OCR：

```powershell
py -3.11 versioned-rag-service/scripts/figure_evidence.py --fetch-selected --max-images 6
```

这里的 `validation.status=verified` 要求 HTTP 内容类型、图片签名和 Pillow 完整解码均通过。`ocr.status=text_extracted` 仅表示 OCR 工具返回了文字，`mean_confidence` 也不能证明术语或事实正确；这些结果的 `quality=unreviewed` 和 `index_review_status=pending` 表明它们尚未进入检索索引。若运行环境没有 Pillow，下载结果标为 `fetched_unchecked`；没有 Tesseract，OCR 标为 `tool_unavailable`。命令失败或 404 会留下相应状态，不会补写猜测的文本。

建议只针对参数配置、工作流执行、监控等文字资料不足的图建立人工校对队列。审核时同时查看图片、所属固定版本文档及上下文；通过后再把校对文字作为独立图像片段加入索引，保留图片 SHA、提交、原文档与行号。对图片内容的问题单独增加评测例，核验图片片段确实提高命中与回答依据。当前 OCR 输出中已有混杂符号和截断词，直接投入检索会引入噪声。
