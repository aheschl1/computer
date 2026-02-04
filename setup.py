from setuptools import setup, find_packages

setup(
    name="computer",
    version="0.1.0",
    description="A small Python package for the agent project",
    # Use the standard layout: let find_packages discover 'computer' and subpackages
    packages=find_packages(),
    include_package_data=True,
    install_requires=[],
    python_requires=">=3.8",
)
