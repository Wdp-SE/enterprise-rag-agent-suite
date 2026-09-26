# 检索 API

POST /retrieve 请求：

    {
      "query": "接口异常时如何降级？",
      "top_k": 5,
      "scope": {
        "project_ids": ["project-a"],
        "document_types": ["design"]
      }
    }

响应只包含通过冻结资产和版本目录校验的证据：chunk_id、document_id、version_id、version_status、project_id、document_type、section_id、section_path、page_number、content、content_hash、similarity 和 rank。

POST /query 使用同一检索器。生成开启时，模型必须返回 final_answer 和 relevant_sources；运行时再次验证每个引用属于本次证据。结构错误、无有效引用或伪造引用会触发 Trusted QA 失败关闭。

接口不会在请求期间解析文档、重建向量或重建索引。
