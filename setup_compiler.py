from setuptools import setup
__VERSION__='0.8.1'

packages=['pyjs', 'pyjs.builtin', 'pyjs.lib', 'pyjs.lib.os', 'pyjs.lib.test',
          'pyjs.lib_trans', 'pyjs.lib_trans.pycompiler', 'pyjs.lib_trans.pyparser', 'pyjs.lib_trans.test',
          'pyjs.boilerplate',
          'pgen', 'pgen.lib2to3', 'pgen.lib2to3.pgen2', 'pgen.lib2to3.compiler', ]
package_dir = {'pyjs':'pyjs/src/pyjs',
               'pgen':'pgen'}
package_data={'pyjs': ['boilerplate/*.html', 'boilerplate/pyjampiler_wrapper.js.tmpl',
                       'builtin/__builtin__.py.in', 'builtin/public/*.js',],
              }
install_requires=[]
entry_points = {'console_scripts':[
    'pyjampiler=pyjs.pyjampiler:Builder',
    'pyjscompile=pyjs.translator:main',
    'pyjsbuild=pyjs.browser:build_script',
]}

install_requires=[]

'''
setup(
    name="pyjs_compiler",
    version=__VERSION__,
    packages=packages,
    package_dir = package_dir,
    package_data=package_data,
    zip_safe = False,
    install_requires = ['pyjs_pgen']+install_requires,
    entry_points = entry_points,
    )
'''
