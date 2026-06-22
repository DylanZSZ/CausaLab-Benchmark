#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from pathlib import Path

from setuptools import setup, find_packages


def read_requirements(path):
    requirements = []
    for line in Path(path).read_text().splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#"):
            continue
        requirements.append(requirement)
    return requirements


setup(
    name='causalab',
    description="CausaLab Reactor Lab benchmark and evaluation code.",
    author='Dylan Zhang',
    author_email='shizhuo2@illinois.edu',
    version=open(os.path.join("discoveryworld", "version.py")).readlines()[0].split("=")[-1].strip("' \n"),
    packages=find_packages(),
    include_package_data=True,
    url="https://github.com/DylanZSZ/CausaLab-Benchmark",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    install_requires=read_requirements("requirements.txt"),
    python_requires='>=3.9',
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
    ]
)
