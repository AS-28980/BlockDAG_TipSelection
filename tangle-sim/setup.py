from setuptools import setup, find_packages

setup(
    name="tangle-sim",
    version="1.0.0",
    description="Distributed IOTA Tangle simulator with MCMC and Hybrid tip selection",
    author="Anirudh Saikrishnan",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "pyzmq>=25.0.0",
        "networkx>=3.0",
        "matplotlib>=3.7.0",
        "numpy>=1.24.0",
        "pyyaml>=6.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "tangle-sim=scripts.run_simulation:main",
        ],
    },
)
