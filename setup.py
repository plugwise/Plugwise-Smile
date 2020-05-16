import codecs
import os.path
from setuptools import setup

def read(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, rel_path), 'r') as fp:
        return fp.read()

def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith('__version__'):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    else:
        raise RuntimeError("Unable to find version string.")

def readme():
    with open("README.md") as f:
        return f.read()


setup(
    name="Plugwise_Smile",
    version=get_version("Plugwise_Smile/__init__.py"),
    description="Plugwise_Smile (Anna/Adam/P1) API to use in conjunction with Home Assistant.",
    long_description="Plugwise Smile API to use in conjunction with Home Assistant, but it can also be used without Home Assistant as a module.",
    keywords="HomeAssistant HA Home Assistant Anna Adam P1 Smile Plugwise",
    url="https://github.com/plugwise/Plugwise-Smile",
    author="Plugwise",
    author_email="info@compa.nl",
    license="MIT",
    packages=["Plugwise_Smile"],
    install_requires=[
        "asyncio",
        "aiohttp",
        "async_timeout",
        "datetime",
        "lxml",
        "pytz",
        "python-dateutil",
        "semver",
    ],
    zip_safe=False,
)
