# Domain Corpus v0.1

This directory freezes the first public-document validation corpus for the
generic RAG baseline. The scenario is special-equipment use management, but
none of the core RAG code is domain-specific.

## Layout

- `source_pdfs/`: byte-for-byte copies of the audited source PDFs.
- `ingestion_inputs/`: ASCII-named copies of only the parseable default-index
  documents. This avoids native Windows filename corruption while preserving
  the original Chinese filenames in `source_pdfs/` and metadata.
- `domain_corpus_manifest.json`: frozen corpus identity, document metadata,
  parsing audit, and inclusion decisions.
- `subset.csv`: metadata lookup consumed by the existing PDF parser.
- `debug_data/`: generated parsing artifacts.
- `databases/`: generated chunk documents and normalized FAISS indexes.

`TSG 08—2017` is retained only for version tests and is excluded from the
default index. Documents marked `OCR_REQUIRED` remain part of the frozen source
corpus but are not treated as successfully ingested until a verified Chinese
OCR path exists.
