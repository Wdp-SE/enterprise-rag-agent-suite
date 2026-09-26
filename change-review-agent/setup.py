from setuptools import find_packages, setup


setup(
    name="evidence-document-workflow-agent",
    version="1.0.0",
    description="Evidence-driven enterprise R&D document drafting and review workflow",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.10,<3",
        "httpx>=0.27,<1",
        "python-docx>=1.2,<2",
    ],
    python_requires=">=3.12",
    entry_points={"console_scripts": ["document-workflow=run_document_workflow:main"]},
)
