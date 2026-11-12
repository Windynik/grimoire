from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="grimoire-mtg",
    version="1.0.0",
    author="Nikhil Prem",
    description="Offline MTG companion: collection enrichment, viewer, and deck forge",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=[
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.32.0",
        "httpx>=0.27.2",
        "pydantic>=2.9.2",
        "python-multipart>=0.0.17",
        "aiofiles>=24.1.0",
        "segno>=1.6",
    ],
    entry_points={
        "console_scripts": [
            "grimoire=main:run",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["frontend/*"],
        "backend": ["data/*.json"],
    },
)
