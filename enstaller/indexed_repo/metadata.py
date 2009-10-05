import os
import sys
import re
import bz2
import string
import StringIO
import zipfile
import hashlib
from collections import defaultdict
from os.path import basename, dirname, join, getsize

from dist_naming import is_valid_eggname
from requirement import Req


def parse_index(data):
    """
    Given the data of an index file, such as index-depend.txt, return a
    dictionary mapping the distribution names to the content of the
    cooresponding section.
    """
    d = defaultdict(list)
    sep_pat = re.compile(r'==>\s*(\S+)\s*<==')
    for line in data.splitlines():
        m = sep_pat.match(line)
        if m:
            fn = m.group(1)
            continue
        d[fn].append(line.rstrip())

    res = {}
    for fn in d.iterkeys():
        res[fn] = '\n'.join(d[fn])
    return res


def data_from_spec(spec):
    """
    Given a spec dictionary, returns a the spec file as a well formed string.
    Also this function is a reference for metadata version 1.1
    """
    str_None = str, type(None)
    for var, typ in [
        ('name', str), ('version', str), ('build', int),
        ('arch', str_None), ('platform', str_None), ('osdist', str_None),
        ('python', str_None), ('packages', list)]:
        assert isinstance(spec[var], typ), spec
        if isinstance(spec[var], str):
            s = spec[var]
            assert s == s.strip(), spec
            assert s != '', spec
    assert spec['build'] >= 0, spec

    cnames = set()
    for req_string in spec['packages']:
        r = Req(req_string)
        assert r.strictness >= 1
        cnames.add(r.name)
    # make sure no project is listed more than once
    assert len(cnames) == len(spec['packages'])

    lst = ["""\
metadata_version = '1.1'
name = %(name)r
version = %(version)r
build = %(build)i

arch = %(arch)r
platform = %(platform)r
osdist = %(osdist)r
python = %(python)r""" % spec]

    if spec['packages']:
        lst.append('packages = [')
        deps = spec['packages']
        for req in sorted(deps, key=string.lower):
            lst.append("  %r," % req)
        lst.append(']')
    else:
        lst.append('packages = []')

    lst.append('')
    return '\n'.join(lst)


def parse_data(data, index=False):
    """
    Given the content of a dependency spec file, return a dictionary mapping
    the variables to their values.

    index: If True, makes sure the md5 and size is also contained in the data.
    """
    spec = {}
    exec data.replace('\r', '') in spec
    assert spec['metadata_version'] >= '1.1', spec

    var_names = [ # these must be present
        'metadata_version', 'name', 'version', 'build',
        'arch', 'platform', 'osdist', 'python', 'packages']
    if index:
        # An index spec also has these
        var_names.extend(['md5', 'size'])
        assert isinstance(spec['md5'], str) and len(spec['md5']) == 32
        assert isinstance(spec['size'], int)

    res = {}
    for name in var_names:
        res[name] = spec[name]
    return res


def parse_depend_index(data):
    """
    Given the data of index-depend.bz2, return a dict mapping each distname
    to a dict mapping variable names to their values.
    """
    d = parse_index(data)
    for fn in d.iterkeys():
        # convert the values from a text string (of the spec file) to a dict
        d[fn] = parse_data(d[fn], index=True)
    return d


def rawspec_from_dist(zip_path):
    """
    Returns the raw spec data, i.e. content of spec/depend as a string.
    """
    arcname = 'EGG-INFO/spec/depend'
    z = zipfile.ZipFile(zip_path)
    if arcname not in z.namelist():
        z.close()
        raise KeyError("arcname=%r not in zip-file %s" % (arcname, zip_path))
    data = z.read(arcname)
    z.close()
    return data


def spec_from_dist(zip_path):
    """
    Returns the spec dictionary from a zip-file distribution.
    """
    return parse_data(rawspec_from_dist(zip_path))


def index_section(zip_path):
    """
    Returns a section corresponding to the zip-file, which can be appended
    to an index.
    """
    h = hashlib.new('md5')
    fi = open(zip_path, 'rb')
    while True:
        chunk = fi.read(4096)
        if not chunk:
            break
        h.update(chunk)
    fi.close()

    return ('==> %s <==\n' % basename(zip_path) +
            'size = %i\n'  % getsize(zip_path) +
            'md5 = %r\n\n' % h.hexdigest() +
            rawspec_from_dist(zip_path) + '\n')


def compress_txt(src, verbose=False):
    """
    Reads the file 'src', which must end with '.txt' and writes the bz2
    compressed data to a file alongside 'src', where the txt extension is
    replaced by bz2.
    """
    assert src.endswith('.txt')
    dst = src[:-4] + '.bz2'
    if verbose:
        print "Compressing:", src
        print "       into:", dst

    data = open(src, 'rb').read()

    fo = open(dst, 'wb')
    fo.write(bz2.compress(data))
    fo.close()


def write_index(dir_path, compress=False, valid_eggnames=True, verbose=True):
    """
    Updates index-depend.txt in the directory specified.

    compress:         also write index-depend.bz2

    valid_eggnames:   only add eggs with valid egg file names to the index
    """
    txt_path = join(dir_path, 'index-depend.txt')
    if verbose:
        print "Updating:", txt_path

    # since accumulating the new data takes a while, we first write to memory
    # and then write the file in one shot.
    faux = StringIO.StringIO()
    n = 0
    for fn in sorted(os.listdir(dir_path), key=string.lower):
        if not fn.endswith('.egg'):
            continue
        if valid_eggnames and not is_valid_eggname(fn):
            continue
        faux.write(index_section(join(dir_path, fn)))
        if verbose:
            sys.stdout.write('.')
            sys.stdout.flush()
        n += 1
    if verbose:
        print n

    fo = open(txt_path, 'w')
    fo.write(faux.getvalue())
    fo.close()

    if compress:
        compress_txt(txt_path, verbose)


def append_dist(zip_path, compress=False, verbose=False):
    """
    Appends a the distribution to index-depend.txt (and optionally
    index-depend.bz2), in the directory in which the distribution is located.
    """
    txt_path = join(dirname(zip_path), 'index-depend.txt')
    if verbose:
        print "Adding index file of:", zip_path
        print "                  to:", txt_path
    f = open(txt_path, 'a')
    f.write(index_section(zip_path))
    f.close()

    if compress:
        compress_txt(txt_path, verbose)
