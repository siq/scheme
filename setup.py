import os
from distutils.core import setup

VERSION = '1.0.0'
try:
    revision = os.environ['REVISION']
except Exception:
    pass
else:
    VERSION = revision

try:
    VERSION = os.environ['INTERNAL_VERSION']
except:
    pass

setup(
    name='scheme',
    version=VERSION,
    description='A declarative schema framework.',
    author='Jordan McCoy',
    author_email='mccoy.jordan@gmail.com',
    license='BSD',
    url='http://github.com/siq/scheme',
    packages=['scheme', 'scheme.json'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
