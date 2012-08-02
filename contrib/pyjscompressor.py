#!/usr/bin/env python
# Copyright (C) 2010 Sujan Shakya, suzan.shakya@gmail.com
# Copyright (C) 2012 PJSHAB <pjbraby@gmail.com>
# Copyright (C) 2012 Alok Parlikar <aup@cs.cmu.edu>
#
# This script works with the google closure compiler
# http://closure-compiler.googlecode.com/files/compiler-latest.zip
#
# The closure compiler requires java to be installed and an entry for
# your java directory in your system PATH
#
# The script needs the path to your google closure compiler.jar file:
# Pass the path to your compiler as the second argument or
# create an environment variable COMPILER=/path/to/google/compiler

# Then run this script. This will reduce the output size to ~50%.

# Usage:
# python pyjscompressor.py [-c COMPILER] [-j NUM] <pyjs_output_directory>
#
# optional arguments:
#  -h, --help            show this help message and exit
#  -c COMPILER, --compiler COMPILER
#                        Path to Google Closure compiler.jar
#
#  -j NUM                Run NUM processes in parallel
#
# Running with -j 0 will run as many processes as cpu count.

import os
import re
import shutil
import subprocess
import sys
import tempfile


try:
    import multiprocessing
    enable_multiprocessing = True
except ImportError:
    enable_multiprocessing = False


MERGE_SCRIPTS = re.compile(
    '</script>\s*(?:<!--.*?-->\s*)*<script(?:(?!\ssrc).)*?>', re.DOTALL)
SCRIPT = re.compile('<script(?:(?!\ssrc).)*?>(.*?)</script>', re.DOTALL)


def compile(js_file, js_output_file, html_file=''):
    # SIMPLE_OPTIMIZATIONS has some problem with Opera, so we'll use
    # WHITESPACE_ONLY for opera
    if 'opera' in html_file:
        level = 'WHITESPACE_ONLY'
    else:
        level = 'SIMPLE_OPTIMIZATIONS'

    global compiler_path

    args = ['java',
            '-jar', compiler_path,
            '--compilation_level', level,
            '--js', js_file,
            '--js_output_file', js_output_file]

    error = subprocess.call(args=args,
                            stdout=open(os.devnull, 'w'),
                            stderr=subprocess.STDOUT)

    if error:
        raise Exception(' '.join([
            'Error(s) occurred while compiling %s' % js_file,
            'possible cause: file may be invalid javascript.']))


def compress_css(css_file):
    css_output_file = tempfile.NamedTemporaryFile()
    f = open(css_file)
    css = f.read()
    css = re.sub(r"\s+([!{};:>+\(\)\],])", r"\1", css)
    css = re.sub(r"([!{}:;>+\(\[,])\s+", r"\1", css)
    css = re.sub(r"\s+", " ", css)

    css_output_file.write(css)
    css_output_file.flush()
    return finish_compressors(css_output_file.name, css_file)


def compress_js(js_file):
    js_output_file = tempfile.NamedTemporaryFile()
    compile(js_file, js_output_file.name)
    return finish_compressors(js_output_file.name, js_file)


def compress_html(html_file):
    html_output_file = tempfile.NamedTemporaryFile()

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
                             (len(scripts) - 1)

    html = SCRIPT.sub(script_repl, html)

    # save js files as temporary files and compile them with simple
    # optimizations

    js_output_files = []
    for script in scripts:
        js_file = tempfile.NamedTemporaryFile()
        js_file.write(script)
        js_file.flush()
        js_output_file = tempfile.NamedTemporaryFile()
        js_output_files.append(js_output_file)
        compile(js_file.name, js_output_file.name, html_file)

    # now write all compiled js back to html file
    for idx, js_output_file in enumerate(js_output_files):
        script = js_output_file.read()
        html = html.replace(template % idx, script)

    html_output_file.write(html)
    html_output_file.flush()
    return finish_compressors(html_output_file.name, html_file)


def finish_compressors(new_path, old_path):
    p_size, n_size = getsize(old_path), getsize(new_path)
    shutil.copyfile(new_path, old_path)
    return p_size, n_size, old_path


def compress(path):
    try:
        ext = os.path.splitext(path)[1]
        if ext == '.css':
            return compress_css(path)
        elif ext == '.js':
            return compress_js(path)
        elif ext == '.html':
            return compress_html(path)
        uncomp_type_size = getsize(path)
        return (uncomp_type_size, uncomp_type_size, path)
    except KeyboardInterrupt:
        # This function runs in child processes under multiprocessing,
        # and any ^C on the terminal is not handled properly. The
        # parent (see main) handles KeyboardInterrupt, so we ignore
        # it.

        if enable_multiprocessing:
            pass
        else:
            # Raise the error if single processing is on.
            raise


def getsize(path):
    return os.path.getsize(path)


def getcompression(p_size, n_size):
    try:
        return n_size / float(p_size) * 100
    except ZeroDivisionError:
        return 100.0


def getsmallpath(path, max_chars):
    """Returns a shortened path to fit into max_chars for pretty
    output on the screen

    """
    if len(path) <= max_chars:
        return path

    # First remove the path and keep last name
    smallpath = os.path.basename(path)
    if len(smallpath) <= max_chars:
        return smallpath

    # Split the filename and insert ellipsis in the middle
    max_chars = max_chars - 3  # 3 characters of ellipsis

    first_half = smallpath[:(max_chars / 2)]
    second_half = smallpath[-(max_chars / 2):]

    smallpath = ''.join([first_half, '...', second_half])
    return smallpath


def compress_all(path):
    # Print headers for progress output
    print('%45s  %s' % ('Files', 'Compression'))

    global num_procs

    p_size = 0
    n_size = 0

    if os.path.isfile(path):
        # Don't need to run multiprocessing for what is a single file
        p_size, n_size, oldpath = compress(path)
    else:
        files_to_compress = []
        for root, dirs, files in os.walk(path):
            for file in files:
                files_to_compress.append(os.path.join(root, file))

        if num_procs > 1:
            proc_pool = multiprocessing.Pool(num_procs)

            # Run the compress function using imap. Chunk size is 1 so
            # that we can update progress report as soon as entries
            # are processed.
            result = proc_pool.imap(compress, files_to_compress, 1)

            count_done = 0
            count_total = len(files_to_compress)
            try:
                # If a keyboad interrupt occurs while we are waiting
                # for output, we need to handle it and quit.

                compression_result = None
                while count_done < count_total:
                    try:
                        # Poll for new results every half a second
                        compression_result = result.next(0.5)
                        count_done += 1
                    except multiprocessing.TimeoutError:
                        continue
                    dp, dn, path = compression_result
                    p_size += dp
                    n_size += dn

                    ratio = getcompression(dp, dn)
                    smallpath = getsmallpath(path, 40)
                    print('%45s  %4.1f%%' % (smallpath, ratio))
            except KeyboardInterrupt:
                # Stop child processes, and pass on the error to caller
                proc_pool.terminate()
                raise
        else:
            # Running on single process
            for file in files_to_compress:
                try:
                    (dp, dn, path) = compress(file)
                except TypeError:
                    # Could occur upon KeyboardInterrupt in compress function
                    break
                p_size += dp
                n_size += dn
                ratio = getcompression(dp, dn)
                smallpath = getsmallpath(path, 40)
                print('%45s  %4.1f%%' % (smallpath, ratio))

    compression = getcompression(p_size, n_size)

    sizes = "Initial size: %.1fKiB  Final size: %.1fKiB" % \
            (p_size / 1024., n_size / 1024.)
    print('%s %s' % (sizes.ljust(51), "%4.1f%%" % compression))


if __name__ == '__main__':
    try:
        import argparse
        # Available only on Python 2.7+
        mode = 'argparse'
    except ImportError:
        import optparse
        mode = 'optparse'

    # Take one position argument (directory)
    # and optional arguments for compiler path and multiprocessing

    global compiler_path
    global num_procs

    num_procs = 1  # By default, disable multiprocessing

    if mode == 'argparse':
        parser = argparse.ArgumentParser(
            description='Compress HTML, CSS and JS in PYJS output')

        parser.add_argument('directory', type=str,
                            help='Pyjamas Output Directory')
        parser.add_argument('-c', '--compiler', type=str, default='',
                            help='Path to Google Closure compiler.jar')
        parser.add_argument('-j', metavar='NUM', default=0, type=int,
                            dest='num_procs',
                            help='Run NUM processes in parallel')
        args = parser.parse_args()
        directory = args.directory
        compiler_path = args.compiler
        num_procs = args.num_procs
    else:
        # Use optparse
        usage = 'usage: %prog [options] <pyjamas-output-directory>'
        parser = optparse.OptionParser(usage=usage)
        parser.add_option('-c', '--compiler', type=str, default='',
                          help='Path to Google Closure compiler.jar')
        parser.add_option('-j', metavar='NUM', default=0, type=int,
                          dest='num_procs',
                          help='Run NUM processes in parallel')
        options, args = parser.parse_args()
        if len(args) != 1:
            parser.error('Please specify the directory to compress')

        directory = args[0]
        compiler_path = options.compiler
        num_procs = options.num_procs

    if not compiler_path:
        # Not specified on command line
        # Try environment
        try:
            compiler_path = os.environ['COMPILER']
        except KeyError:
            sys.exit('Closure compiler not found\n'
                     'Either specify it using the -c option,\n'
                     'or set the COMPILER environment variable to \n'
                     'the location of compiler.jar')

    if not os.path.isfile(compiler_path):
        sys.exit('\n'.join([
            'Compiler path "%s" not valid.' % compiler_path,
            'Check the path to your compiler is correct.']))

    if not enable_multiprocessing:
        # Even if user has specified -j we can't use it if
        # multiprocessing module doesn't exist
        num_procs = 1
        print("multiprocessing not available.")

    if num_procs == 0:
        print("Detecting cpu_count")
        try:
            num_procs = multiprocessing.cpu_count()
        except NotImplementedError:
            print("Could not determine CPU Count. Using One process")
            num_procs = 1

    print("Running %d processes" % num_procs)

    try:
        compress_all(directory)
    except KeyboardInterrupt:
        print('')
        print('Compression Aborted')
