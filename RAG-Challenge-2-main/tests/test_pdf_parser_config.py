from src.pdf_parsing import PDFParser


def test_pdf_parser_can_disable_ocr_without_changing_the_default(monkeypatch):
    monkeypatch.setattr(PDFParser, "_create_document_converter", lambda self: object())

    default_parser = PDFParser()
    text_pdf_parser = PDFParser(do_ocr=False)

    assert default_parser.do_ocr is True
    assert text_pdf_parser.do_ocr is False
