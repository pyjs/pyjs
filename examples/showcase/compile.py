#!/usr/bin/env python

""" compile.py

    Build the pyjamas-showcase web application.

    We firstly scan through all the demo modules, pulling out the module
    docstrings and the source code, and adding this information to the
    demoInfo.py module.  We then call Pyjamas to compile the application, and
    finally open a web browser window to show the compiled application.

"""
import subprocess
import cStringIO
import os
import os.path
import sys
import webbrowser

import pyColourize

#############################################################################

# Modify the following to refer to the full path to your Pyjamas installation,
# relative to the pyjamas-showcase source directory:

here = os.path.dirname(os.path.abspath(__file__))
PATH_TO_PYJAMAS = os.path.dirname(os.path.dirname(here))

#############################################################################

def main():
    """ Our main program.
    """
    # Extract the source code to each demo file, storing the results into the
    # demoInfo.py file.

    # Load all our demonstrations into memory.

    demoInfo = {}
    for section in ["widgets", "panels", "other"]:
        for fName in os.listdir(os.path.join("src", "demos_" + section)):
            if fName.startswith(".") or not fName.endswith(".py"):
                continue

            f = file(os.path.join("src", "demos_" + section, fName), "r")
            src = f.read()
            f.close()

            demoName = fName[:-3]
            docstring,htmlSrc = parseDemo(fName, src)

            demoInfo[demoName] = {'section' : section,
                                  'doc'     : docstring,
                                  'src'     : src,
                                  'htmlSrc' : htmlSrc}

    # Calculate the list of imports to use for the combined module.

    imports = set()
    for demo in demoInfo.values():
        imports.update(extractImports(demo['src']))

    # Write the combined demos into a single file.

    s = []
    s.append('""" demoInfo.py')
    s.append('')
    s.append('    DO NOT EDIT THE CONTENTS OF THIS FILE!')
    s.append('')
    s.append('    This file is created automatically by the compile.py')
    s.append('    script out of the various demonstration modules.')
    s.append('"""')
    s.append('')
    for imp in imports:
        s.append(imp + "")
    s.append('')
    s.append('')

    for demo in demoInfo.keys():
        s.append(removeDocstringAndImports(demoInfo[demo]['src']))
        s.append('')
        s.append('')

    s.append('def getDemos():')
    s.append('    demos = []')

    sortKeys = []
    for name in demoInfo.keys():
        sortKeys.append((demoInfo[name]['section'], name))
    sortKeys.sort()

    for section,name in sortKeys:
        demo = demoInfo[name]
        capName = name[0].upper() + name[1:]
        prefix = "ui."
        if demo["section"] == "other":
            prefix = ""
        s.append('    demos.append({"name" : "' + name + '",')
        s.append('                  "title" : "' + prefix + capName + '",')
        s.append('                  "section" : "' + demo['section'] + '",')
        s.append('                  "doc" : """' + demo['doc'] + '""",')
        s.append('                  "src" : """' + demo['htmlSrc'] + '""",')
        s.append('                  "example" : ' + capName + 'Demo()})')
        s.append('')

    s.append('    return demos')
    s.append('')

    f = file(os.path.join("src", "demoInfo.py"), "w")
    f.write("\n".join(s))
    f.close()

    options = " ".join(sys.argv[1:]) + " --enable-signatures --enable-preserve-libs --disable-debug --dynamic-link"
    # Compile the application using Pyjamas.
    if sys.platform == "win32":
        stmt = (sys.executable + " " + os.path.join(PATH_TO_PYJAMAS, 'bin', 'pyjsbuild.py') +
                " " + options +
                " -o " + os.path.join(here, '..', '__output__') + " " +
                " -I " + os.path.join(here, 'src') + " " +
                'Showcase')
    else:
        stmt = (sys.executable + " " + os.path.join(PATH_TO_PYJAMAS, 'bin', 'pyjsbuild') +
                " " + options +
                " -o " + os.path.join(here, '..', '__output__') + " " +
                " -I " + os.path.join(here, 'src') + " " +
                'Showcase' +
                " > /dev/null")

    e = subprocess.Popen(stmt, shell=True)
    retcode = e.wait()
    if retcode != 0: return

    # Finally, launch a web browser to show the compiled application.

    #webbrowser.open("file://" + os.path.abspath("output/Showcase.html"))

#############################################################################

def parseDemo(fName, src):
    """ Parse the given demonstration file.

        'fName' is the name of the demonstration module, and 'src' is a copy of
        the module's contents.

        We return a (docstring, src) tuple, containing the documentation string
        and source code for the given demonstration module.
    """
    if src.startswith('"""'):
        # We have a docstring.  Search for the ending docstring, and pull the
        # remaining source code out.
        i = src.find('"""', 3)
        if i == -1:
            docstring = src[3:]
            src       = ""
        else:
            docstring = src[3:i].lstrip()
            src       = src[i+3:].lstrip()
    else:
        # We have no docstring at all.
        docstring = ""

    # Tidy up the paragraphs in the docstring.  We do the following:
    #
    #  * If a paragraph starts with " * ", treat it as an unordered list item.
    #
    #  * If all the lines in a paragraph start with "    ", treat it as an
    #    indented code block.
    #
    #  * Otherwise, join the lines in the paragraph together to avoid line
    #    break issues.

    paragraphs = docstring.split("\n\n")
    for i in range(len(paragraphs)):
        indented = True
        for line in paragraphs[i].split("\n"):
            if not line.startswith("    "):
                indented = False

        if indented:
            # Treat the paragraph as a code block.
            paragraphs[i] = "<blockquote><pre>" + paragraphs[i] + \
                            "</pre></blockquote>"
        else:
            paragraphs[i] = paragraphs[i].replace("\n", " ")

            if paragraphs[i].startswith(" * "):
                paragraphs[i] = "<ul><li>" + paragraphs[i][3:] + "</li></ul>"

    docstring = "\n\n".join(paragraphs)

    # Colourize the source code.

    buff = cStringIO.StringIO()
    pyColourize.Parser(src, pyColourize._Eriks_Style,
                       fName, buff).format(None, None)
    html = buff.getvalue()

    # Replace any quotes in the source code with the equivalent HTML entity
    # codes.

    html = html.replace('"""', '&quot;&quot;&quot;')

    # That's all, folks!

    return docstring,html

#############################################################################

def extractImports(src):
    """ Extract the set of import statements in the given source code.

        We return a set object containing the import statements in the given
        source code.
    """
    imports = set()
    for line in src.split("\n"):
        if line.startswith("import"):
            imports.add(line)
        elif line.startswith("from "):
            i = line.find(" import ")
            if i > -1:
                fromModule = line[5:i]
                modules = line[i+8:].split(",")
                for module in modules:
                    imports.add("from "+fromModule+" import "+module.strip())
    return imports

#############################################################################

def removeDocstringAndImports(src):
    """ Remove the docstring and import statements from the given code.

        We return the source code, minus the initial docstring (if any) and any
        import statements.
    """
    if src.startswith('"""'):
        # We have a docstring.  Search for the ending docstring, and pull the
        # remaining source code out.
        i = src.find('"""', 3)
        if i == -1:
            src = ""
        else:
            src = src[i+3:].lstrip()

    dst = []
    for line in src.split("\n"):
        if not line.startswith("import") and not line.startswith("from"):
            dst.append(line)
    return "\n".join(dst)

#############################################################################

if __name__ == "__main__":
    main()

