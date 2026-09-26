from setuptools import find_packages, setup


setup(
    name="enterprise-rd-document-rag",
    version="1.0.0",
    description="Enterprise R&D document knowledge service",
    packages=find_packages(include=["src", "src.*"]),
)
