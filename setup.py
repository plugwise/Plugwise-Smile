from setuptools import setup

def readme():
    with open('README.md') as f:
        return f.read()

setup(
    name='Plugwise-Smile',
    version='0.0.3',
    description='Plugwise-Smile (Anna/Adam/P1) API to use in conjunction with Home Assistant.',
    long_description='Plugwise Smile API to use in conjunction with Home Assistant, but it can also be used without Home Assistant.',
    keywords='HomeAssistant HA Home Assistant Anna Adam P1 Smile Plugwise',
    url='https://github.com/plugwise/Plugwise-Smile',
    author='Plugsiwe',
    author_email='info@compa.nl',
    license='MIT',
    packages=['Plugwise-Smile'],
    install_requires=['asyncio','aiohttp','async_timeout','datetime','pytz','python-dateutil'],
    zip_safe=False
)

