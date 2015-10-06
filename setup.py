from setuptools import setup
import os.path
import setup_pyjstools
import setup_pyjswidgets
__VERSION__='0.8.2'

packages=setup_pyjstools.packages+setup_pyjswidgets.packages
package_data=dict(setup_pyjstools.package_data.items())
package_data.update(dict(setup_pyjswidgets.package_data.items()))

entry_points=dict(setup_pyjstools.entry_points.items())
entry_points.update(dict(setup_pyjswidgets.entry_points.items()))

# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
# Source: https://pythonhosted.org/an_example_pypi_project/setuptools.html
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name="pyjs",
    version=__VERSION__,
    packages=packages,
    package_data=package_data,
    zip_safe = False,
    entry_points = entry_points,
    install_requires=['six>=1.9.0'],

    license="Apache",
    keywords=["js", "javascript"],
    url = "http://pyjs.org",
    long_description=read('README.rst'),
)
