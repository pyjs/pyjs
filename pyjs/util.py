import os
import shutil
import re
import logging

DEFAULT_SKIP_FILES=re.compile(
    r"^(.*%(sep)s)?("
    r"(\.[^%(sep)s]*)|"
    r"(#[^%(sep)s]*#)|"
    r"([^%(sep)s]*~)|"
    r"([^%(sep)s]*\.py[co])|"
    r"(.*%(sep)sRCS%(sep)s?.*)|"
    r"(.*%(sep)sCVS%(sep)s?.*)|"
    r"(.*\.egg-info.*)|"
    r")$" % {'sep': re.escape(os.path.sep)})

def copytree_exists(src, dst, symlinks=False,
                    skip_files=DEFAULT_SKIP_FILES):
    if not os.path.exists(src):
        return
    names = os.listdir(src)
    if not os.path.exists(dst):
        os.mkdir(dst)

    errors = []
    for name in names:
        srcname = os.path.join(src, name)
        if skip_files.match(srcname):
            logging.debug('Ignoring file \'%s\': File matches ignore regex.',
                          srcname)
            continue
        dstname = os.path.join(dst, name)
        try:
            if symlinks and os.path.islink(srcname):
                linkto = os.readlink(srcname)
                os.symlink(linkto, dstname)
            elif os.path.isdir(srcname):
                copytree_exists(srcname, dstname, symlinks, skip_files=skip_files)
            else:
                shutil.copy2(srcname, dstname)
        except (IOError, os.error) as why:
            errors.append((srcname, dstname, why))
    if errors:
        print(errors)

def copy_exists(srcname, dstname, symlinks=False):
    if not os.path.exists(srcname):
        return
    errors = []
    try:
        if symlinks and os.path.islink(srcname):
            linkto = os.readlink(srcname)
            os.symlink(linkto, dstname)
        else:
            shutil.copyfile(srcname, dstname)
            shutil.copystat(srcname, dstname)
    except (IOError, os.error) as why:
        errors.append((srcname, dstname, why))
    if errors:
        print(errors)

