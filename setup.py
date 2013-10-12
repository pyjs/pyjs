from setuptools import setup
import setup_compiler, setup_pyjamas, setup_pyjd
__VERSION__='0.8.1'


setup(
    name="pyjs",
    version=__VERSION__,
    packages=setup_compiler.packages + 
             setup_pyjamas.packages + 
             setup_pyjd.packages,
    package_dir = dict(setup_compiler.package_dir.items()+
                       setup_pyjamas.package_dir.items()+
                       setup_pyjd.package_dir.items()),
    package_data = dict(setup_compiler.package_data.items()+
                        setup_pyjamas.package_data.items()+
                        setup_pyjd.package_data.items()),
    install_requires = setup_compiler.install_requires + 
                       setup_pyjamas.install_requires + 
                       setup_pyjd.install_requires,
    entry_points = dict(setup_compiler.entry_points.items()+
                        setup_pyjamas.entry_points.items()+
                        setup_pyjd.entry_points.items()),
    zip_safe = False,
    )


