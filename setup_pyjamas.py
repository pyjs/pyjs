from setuptools import setup
__VERSION__='0.8.1'

packages=['pyjamaslibrary', 'pyjamaslibrary.pyjamas',
          'pyjamaslibrary.pyjamas.Canvas', 'pyjamaslibrary.pyjamas.builder',
          'pyjamaslibrary.pyjamas.chart', 'pyjamaslibrary.pyjamas.django',
          'pyjamaslibrary.pyjamas.dnd', 'pyjamaslibrary.pyjamas.feed',
          'pyjamaslibrary.pyjamas.gears', 'pyjamaslibrary.pyjamas.gears.database',
          'pyjamaslibrary.pyjamas.gears.localserver', 'pyjamaslibrary.pyjamas.gears.workerpool',
          'pyjamaslibrary.pyjamas.gmaps', 'pyjamaslibrary.pyjamas.graphael', 
          'pyjamaslibrary.pyjamas.logging', 'pyjamaslibrary.pyjamas.media', 
          'pyjamaslibrary.pyjamas.raphael', 'pyjamaslibrary.pyjamas.selection', 
          'pyjamaslibrary.pyjamas.ui', 'pyjamaslibrary.pyjamas.ui.public',
          'pyjamasaddons',
          ]
package_dir = {'pyjamaslibrary':'library',
               'pyjamasaddons' :'addons',
               }
package_data={'pyjamaslibrary': ['*.js',],
              'pyjamaslibrary/pyjamas/ui': ['public/*.html', 'public/css.d/*.css', 
                                            'public/images/*.png', 'public//images/*.gif'],
              }
install_requires=[]
entry_points = {}

'''
setup(
    name="pyjs_pyjamas",
    version=__VERSION__,
    packages=packages,
    package_dir = package_dir,
    package_data=package_data,
    install_requires=install_requires,
    entry_points=entry_points,
    zip_safe = False,
    )
'''
