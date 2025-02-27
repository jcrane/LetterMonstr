#!/usr/bin/env python3
"""
Setup script for LetterMonstr application.
"""

from setuptools import setup, find_packages

setup(
    name="lettermonstr",
    version="0.1.0",
    author="LetterMonstr Team",
    description="Newsletter aggregator and summarizer using Claude",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/lettermonstr",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=[
        "imaplib2>=2.57.3",
        "email-validator>=2.0.0",
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.2",
        "lxml>=4.9.3",
        "nltk>=3.8.1",
        "python-dateutil>=2.8.2",
        "SQLAlchemy>=2.0.19",
        "pyyaml>=6.0.1",
        "schedule>=1.2.0",
        "secure-smtplib>=0.1.1",
        "anthropic>=0.5.0",
        "python-dotenv>=1.0.0",
        "tqdm>=4.66.1",
    ],
    entry_points={
        "console_scripts": [
            "lettermonstr=src.main:main",
        ],
    },
) 