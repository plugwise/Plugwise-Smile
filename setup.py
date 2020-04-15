from setuptools import setup


def readme():
    with open("README.md") as f:
        return f.read()


setup(
    name="Plugwise_Smile",
    version="0.1.20",
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
