from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="scryfall-enhancer",
    version="1.0.0",
    author="Your Name",
    description="Enrich ManaBox MTG collection exports with Scryfall data",
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
    ],
    entry_points={
        "console_scripts": [
            "scryfall-enhancer=main:run",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["frontend/*"],
    },
)
