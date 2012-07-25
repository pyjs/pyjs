#!/usr/bin/env python
# Copyright (C) 2010 Sujan Shakya, suzan.shakya@gmail.com
#
# This script works with the google closure compiler
# http://closure-compiler.googlecode.com/files/compiler-latest.zip 
#
# The closure compiler requires java to be installed and an entry for your java directory in your system PATH
# 
# The script needs the path to your google closure compiler.jar file:
# Pass the path to your compiler as the second argument or
# create an environment variable COMPILER=/path/to/google/compiler

# Then run this script. This will reduce the output size to ~50%.

# To run type:
# python pyjscompressor.py <path_to_your_pyjamas_output_directory> [<compiler path>]
# from command line in the directory of this script
import re, os, sys, shutil, subprocess


MERGE_SCRIPTS = re.compile('</script>\s*(?:<!--.*?-->\s*)*<script(?:(?!\ssrc).)*?>', re.DOTALL)
SCRIPT = re.compile('<script(?:(?!\ssrc).)*?>(.*?)</script>', re.DOTALL)

def compile(js_file, js_output_file, html_file=''):
    # SIMPLE_OPTIMIZATIONS has some problem with Opera, so we'll use
    # WHITESPACE_ONLY for opera
    if 'opera' in html_file:
        level = 'WHITESPACE_ONLY'
    else:
        level = 'SIMPLE_OPTIMIZATIONS'
    args = ['java', '-jar', COMPILER, '--compilation_level', level, '--js', js_file, '--js_output_file', js_output_file]
    error = subprocess.call(args=args, stdout=open(os.devnull, 'w'), stderr=open(os.devnull, 'w'))
    if error:
        shutil.rmtree("temp")
        raise Exception, 'Error(s) occurred while compiling %s, possible cause: file may be invalid javascript.' % js_file

def compress_css(css_file):
    sys.stdout.write('Compressing %-40s' % css_file)
    sys.stdout.flush()
    css_output_file = 'temp/%s.ccss' % os.path.basename(css_file)
    f = open(css_file)
    css = f.read()
    css = re.sub(r"\s+([!{};:>+\(\)\],])", r"\1", css)
    css = re.sub(r"([!{}:;>+\(\[,])\s+", r"\1", css)
    css = re.sub(r"\s+", " ", css)

    f = open(css_output_file, 'w')
    f.write(css)
    f.close()
    return finish_compressors(css_output_file, css_file)

def compress_js(js_file):
    sys.stdout.write('Compressing %-40s' % js_file)
    sys.stdout.flush()
    js_output_file = 'temp/%s.cjs' % os.path.basename(js_file)
    compile(js_file, js_output_file)
    return finish_compressors(js_output_file, js_file)

def compress_html(html_file):
    sys.stdout.write('Compressing %-40s' % html_file)
    sys.stdout.flush()
    js_file = 'temp/pyjs%d.js'
    js_output_file = 'temp/pyjs%d.cjs'
    html_output_file = 'temp/compiled.html'

    f = open(html_file)
    html = f.read()
    f.close()

    # remove comments betn <script> and merge all <script>
    html = MERGE_SCRIPTS.sub('', html)

    # now extract the merged scripts
    template = '<!--compiled-js-%d-->'
    scripts = []
    def script_repl(matchobj):
        scripts.append(matchobj.group(1))
        return '<script type="text/javascript">%s</script>' % template % \
                             (len(scripts)-1)
    html = SCRIPT.sub(script_repl, html)

    # save js files in temp dir and compile them with simple optimizations
    for i, script in enumerate(scripts):
        f = open(js_file % i, 'w')
        f.write(script)
        f.close()
        compile(js_file % i, js_output_file % i, html_file)

    # now write all compiled js back to html file
    for i in xrange(len(scripts)):
        f = open(js_output_file % i)
        script = f.read()
        f.close()
        html = html.replace(template % i, script)

    f = open(html_output_file, 'w')
    f.write(html)
    f.close()
    return finish_compressors(html_output_file, html_file)

def finish_compressors(new_path, old_path):
    p_size, n_size = getsize(old_path),getsize(new_path)
    os.remove(old_path)
    os.rename(new_path, old_path)
    print ' Ratio: %4.1f%%'% getcompression(p_size, n_size)
    return p_size, n_size

def compress(path):
    ext = os.path.splitext(path)[1]
    if ext == '.css':
        return compress_css(path)
    elif ext == '.js':
        return compress_js(path)
    elif ext == '.html':
        return compress_html(path)
    uncomp_type_size = getsize(path)
    return (uncomp_type_size, uncomp_type_size)

def getsize(path):
    return os.path.getsize(path)

def getcompression(p_size, n_size):
    try:
        return n_size / float(p_size) * 100
    except ZeroDivisionError:
        return 100.0

def compress_all(path):
    if not os.path.exists('temp'):
        os.makedirs('temp')

    print '%17s %45s' % ('Files', 'Compression')
    p_size = 0
    n_size = 0
    if os.path.isfile(path):
        p_size, n_size = compress(path)
    else:
        for root, dirs, files in os.walk(path):
            if 'temp' in root:
                continue
            for file in files:
                dp, dn = compress(os.path.join(root, file))
                p_size += dp
                n_size += dn
    
    compression = getcompression(p_size, n_size)
    shutil.rmtree("temp")

    sizes = "Initial size: %.1fKB  Final size: %.1fKB" % \
            (p_size/1024., n_size/1024.)
    print '%s %s' % (sizes.ljust(51), "%4.1f%%" % compression)

if __name__ == '__main__':
    if len(sys.argv) == 1:
        print('usage: python pyjs_compressor.py <pyjamas_output_dir> [<path to compiler.jar>]')
        sys.exit()
    elif len(sys.argv) == 2:
        dir = sys.argv[1]
        if not os.environ.has_key('COMPILER'):
            sys.exit('environment variable COMPILER is not defined.\n'
                     'In bash, export '
                     'COMPILER=/home/me/google/compiler/compiler.jar or pass the path to your compiler.jar as the second argument.')
        COMPILER = os.environ['COMPILER']
    else:
        dir = sys.argv[1]
        COMPILER = sys.argv[2]
        
    if not os.path.isfile(COMPILER):
        raise Exception, 'Compiler path "%s" not valid. Check the path to your compiler is correct.' % COMPILER
    compress_all(dir)
