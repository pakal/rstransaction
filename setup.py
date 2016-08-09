#!/usr/bin/env python

import sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # security

from setuptools import setup

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

classifiers = """\
Development Status :: 2 - Pre-Alpha
Intended Audience :: Developers
Intended Audience :: Information Technology
License :: OSI Approved :: MIT License
Programming Language :: Python
Topic :: Software Development :: Libraries :: Python Modules
Operating System :: Microsoft :: Windows
Operating System :: Unix
Operating System :: MacOS :: MacOS X
"""


setup(
    name='RSTransaction',
    version=read("VERSION"),
    author='Pascal Chambon',
    author_email='pythoniks@gmail.com',
    url='https://github.com/pakal/rstransaction',
    license="http://www.opensource.org/licenses/mit-license.php",
    platforms=["any"],
    description="Extendable transaction system, to build workflows with commit/rollback semantic.",
    classifiers=filter(None, classifiers.split("\n")),
    long_description=read("README.rst"),

    #package_dir={'': 'src'},
    packages=("rstransaction",),

    # test_suite='your.module.tests',

    use_2to3=False,
    #convert_2to3_doctests=['src/your/module/README.txt'],
    #use_2to3_fixers=['your.fixers'],
    #use_2to3_exclude_fixers=['lib2to3.fixes.fix_import'],
)

