#!/usr/bin/env python

# Copyright (c) 2015 SnapDisco Pty Ltd, Australia.
# All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# [ MIT license: https://opensource.org/licenses/MIT ]

# Usage:
#  python pmgen.py nimmodule.nim

import datetime
import glob
import os
import re
#import shutil
import subprocess
import sys

from libpy.UsefulConfigParser import UsefulConfigParser


NIM_COMPILER_EXE_PATH = "nim"
NIM_COMPILER_FLAGS = []
NIM_COMPILER_FLAG_OPTIONS = dict(
        nimSetIsRelease=["-d:release"],
)
NIM_COMPILER_COMMAND = "%s %s" % (NIM_COMPILER_EXE_PATH, " ".join(NIM_COMPILER_FLAGS))

MAKE_EXE_PATH = "make"


NIM_CFG_FNAME = "nim.cfg"
NIM_CFG_CONTENT = """# Auto-generated by "pmgen.py" on %(datestamp)s.
# Any changes will be overwritten by the next run of "pmgen.py".
cincludes:"%(pymod_root_dir)s"
cincludes:"/usr/include/python2.7"
listCmd
parallelBuild:"1"
passC:"-Wall -O3 -fPIC"
passL:"-O3 -fPIC"
path:"%(pymod_root_dir)s"
%(any_other_module_paths)s
verbosity:"2"
"""


PMGEN_DIRNAME = "pmgen"
PMGEN_PREFIX = "pmgen"
PMGEN_RULE_TARGET = "pmgen"

MAKEFILE_FNAME_TEMPLATE = "Makefile.pmgen-%s"
MAKEFILE_PMGEN_VARIABLE = """PMGEN = --define:pmgen --noLinking --noMain"""
MAKEFILE2_FNAME_TEMPLATE = "Makefile"

MAKEFILE_CLEAN_RULES = """allclean: clean soclean

soclean:
\trm -f *.so

clean:
\trm -rf nimcache
\trm -f nim.cfg
\trm -f %(pmgen_prefix)s*_capi.c
\trm -f %(pmgen_prefix)s*_incl.nim
\trm -f %(pmgen_prefix)s*_wrap.nim
\trm -f %(pmgen_prefix)s*_wrap.nim.cfg
"""
MAKEFILE_CONTENT = """# Auto-generated by "pmgen.py" on %(datestamp)s.
# Any changes will be overwritten by the next run of "pmgen.py".

%(variables)s

%(build_rules)s

%(clean_rules)s
"""


PMINC_FNAME_TEMPLATE = "%(pmgen_prefix)s%(modname_basename)s_incl.nim"
PMINC_CONTENT = """# Auto-generated by "pmgen.py" on %(datestamp)s.
# Any changes will be overwritten by the next run of "pmgen.py".

# These must be included rather than imported, so the static global variables
# can be evaluated at compile time.
include pymodpkg/private/includes/realmacrodefs

include pymodpkg/private/includes/pyobjecttypedefs

# Modules to be imported by the auto-generated Nim wrappers.
%(imports)s

# Modules to be included into this Nim code, so their procs can be exportpy'd.
%(includes)s
"""


def main():
    pymod_root_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    (nim_modfiles, nim_modnames) = get_nim_modnames_as_relpaths(sys.argv[1:])
    if len(nim_modnames) < 1:
        die("no Nim module names specified")

    global CONFIG
    CONFIG = readPymodConfig()
    global NIM_COMPILER_COMMAND
    NIM_COMPILER_COMMAND = getCompilerCommand()

    orig_dir = os.getcwd()
    if not (os.path.exists(PMGEN_DIRNAME) and os.path.isdir(PMGEN_DIRNAME)):
        os.mkdir(PMGEN_DIRNAME)
    os.chdir(PMGEN_DIRNAME)

    generate_nim_cfg_file(pymod_root_dir)
    pminc_basename = generate_pminc_file(nim_modnames)
    pmgen_fnames = generate_pmgen_files(nim_modfiles, pminc_basename)

    # FIXME:  This (simply globbing by filenames) is highly dodgy.
    # Work out a better way of doing this.
    nim_wrapper_glob = "%(pmgen_prefix)s*_wrap.nim" % dict(
            pmgen_prefix=PMGEN_PREFIX)
    nim_wrapper_fnames = glob.glob(nim_wrapper_glob)

    pymodule_fnames = extract_pymodule_fnames_from_glob(nim_wrapper_fnames,
            nim_wrapper_glob)
    compile_generated_nim_wrappers(nim_wrapper_fnames, pymodule_fnames,
            nim_modfiles, pminc_basename)
    #for pymodule_fname in pymodule_fnames:
    #    shutil.copyfile(pymodule_fname, os.path.join("..", pymodule_fname))

    os.chdir(orig_dir)


def getCompilerCommand():
    nim_compiler_flags = NIM_COMPILER_FLAGS[:]
    if any(CONFIG.getboolean("all", "nimSetIsRelease")):
        nim_compiler_flags.extend(NIM_COMPILER_FLAG_OPTIONS["nimSetIsRelease"])
        #print "nimSetIsRelease: True"

    cmd = "%s %s" % (NIM_COMPILER_EXE_PATH, " ".join(nim_compiler_flags))
    #print "Nim compiler command:", cmd
    return cmd


def readPymodConfig():
    c = UsefulConfigParser()
    cfg_files_read = c.read("pymod.cfg")
    return c


def get_nim_modnames_as_relpaths(cmdline_args):
    nim_modfiles = []
    nim_modnames = []
    for arg in cmdline_args:
        if arg.endswith(".nim"):
            if os.path.exists(arg):
                nim_modfiles.append(os.path.relpath(arg))
                nim_modnames.append(os.path.relpath(arg[:-4]))
            else:
                die("file not found: %s" % arg)
        else:  # not arg.endswith(".nim")
            if os.path.exists(arg + ".nim"):
                nim_modfiles.append(os.path.relpath(arg + ".nim"))
                nim_modnames.append(os.path.relpath(arg))
            else:
                die("file not found: %s.nim" % arg)

    return (nim_modfiles, nim_modnames)


def extract_pymodule_fnames_from_glob(nim_wrapper_fnames, nim_wrapper_glob):
    nim_wrapper_pattern = nim_wrapper_glob.replace("*", "(.+)")
    regex = re.compile(nim_wrapper_pattern)
    pymodule_fnames = [
            "%s.so" % regex.match(wrapper_fname).group(1)
            for wrapper_fname in nim_wrapper_fnames]
    return pymodule_fnames


def get_datestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d at %H:%M:%S")


def generate_nim_cfg_file(pymod_root_dir):
    datestamp = get_datestamp()

    any_other_module_paths = []
    for optval in CONFIG.get("all", "nimAddModulePath"):
        path = stripAnyQuotes(optval)
        if not path.startswith("/"):
            # It's a relative path rather than an absolute path.
            # Since it's relative to the parent directory, it needs to
            # be updated because we are now in the "pmgen" directory.
            path = dotdot(path)
        path = os.path.realpath(path)
        any_other_module_paths.append('path:"%s"' % path)
    #print "nimAddModulePath:", any_other_module_paths

    with open(NIM_CFG_FNAME, "w") as f:
        f.write(NIM_CFG_CONTENT % dict(
                datestamp=datestamp,
                pymod_root_dir=pymod_root_dir,
                any_other_module_paths="\n".join(any_other_module_paths)))


def stripAnyQuotes(s):
    if s.startswith('"""') and s.endswith('"""'):
        return s[3:-3]
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def dotdot(relpath):
    # Assumes that `relpath` is a relative path that was obtained from the
    # command-line arguments by the function `get_nim_modnames_as_relpaths`.
    return os.path.join("..", relpath)


def generate_pminc_file(nim_modnames):
    datestamp = get_datestamp()

    # We need to "dot-dot" one level, because we are in the "pmgen" subdir.
    nim_modnames = [dotdot(modname) for modname in nim_modnames]
    register_to_import = ["registerNimModuleToImport(\"%s\")" % modname
            for modname in nim_modnames]
    includes = ["include %s" % modname for modname in nim_modnames]

    last_nim_modname_basename = os.path.basename(nim_modnames[-1])
    pminc_fname = PMINC_FNAME_TEMPLATE % dict(
            modname_basename=last_nim_modname_basename,
            pmgen_prefix=PMGEN_PREFIX)
    with open(pminc_fname, "w") as f:
        f.write(PMINC_CONTENT % dict(
                datestamp=datestamp,
                imports="\n".join(register_to_import),
                # Leave an empty line between each include.
                includes="\n\n".join(includes)))

    return last_nim_modname_basename


def generate_pmgen_files(nim_modfiles, pminc_basename):
    datestamp = get_datestamp()

    # Create the Makefile.
    rule_target = PMGEN_RULE_TARGET
    pminc_fname = PMINC_FNAME_TEMPLATE % dict(
            modname_basename=pminc_basename,
            pmgen_prefix=PMGEN_PREFIX)
    # We need to "dot-dot" one level, because we are in the "pmgen" subdir.
    nim_modfiles = [dotdot(modfname) for modfname in nim_modfiles]
    prereqs = [pminc_fname] + nim_modfiles
    compile_rule = "%s: %s\n\t%s compile $(PMGEN) %s" % \
            (rule_target, " ".join(prereqs), NIM_COMPILER_COMMAND, pminc_fname)

    makefile_fname = MAKEFILE_FNAME_TEMPLATE % pminc_basename
    makefile_clean_rules = MAKEFILE_CLEAN_RULES % dict(
            pmgen_prefix=PMGEN_PREFIX)
    with open(makefile_fname, "w") as f:
        f.write(MAKEFILE_CONTENT % dict(
                datestamp=datestamp,
                variables=MAKEFILE_PMGEN_VARIABLE,
                build_rules=compile_rule,
                clean_rules=makefile_clean_rules))

    make_command = [MAKE_EXE_PATH, "-f", makefile_fname, rule_target]
    print " ".join(make_command)
    subprocess.check_call(make_command)


def compile_generated_nim_wrappers(nim_wrapper_fnames, pymodule_fnames,
        nim_modfiles, pminc_basename):
    datestamp = get_datestamp()

    # Create the Makefile.
    # We need to "dot-dot" one level, because we are in the "pmgen" subdir.
    nim_modfiles_rel_pmgen_dir = [dotdot(modfname) for modfname in nim_modfiles]

    script_cmd = sys.argv[0]
    if os.path.isabs(script_cmd):
        abspath_to_pmgen_py = script_cmd
    else:
        abspath_to_pmgen_py = os.path.abspath(dotdot(script_cmd))

    pminc_fname = PMINC_FNAME_TEMPLATE % dict(
            modname_basename=pminc_basename,
            pmgen_prefix=PMGEN_PREFIX)
    build_rules = [
            "all: %s" % " ".join(pymodule_fnames)
            ] + [
            "%s: %s\n\t%s compile %s\n\tmv -f %s ../" %
                    (pymodule_fname, nim_fname, NIM_COMPILER_COMMAND, nim_fname,
                            pymodule_fname)
            for nim_fname, pymodule_fname in zip(nim_wrapper_fnames, pymodule_fnames)
            ] + [
            "%s: %s\n\t%s compile $(PMGEN) %s" %
                    # FIXME: This is not necessarily correct.
                    # The `pminc_fname` for THIS invocation is not necessarily
                    # the `pminc_fname` that was used to generate this
                    # "pmgen*_wrap.nim" file in a previous invocation of
                    # "pmgen.py".
                    (nim_fname, pminc_fname, NIM_COMPILER_COMMAND, pminc_fname)
                    for nim_fname in nim_wrapper_fnames
            ] + [
            "%s: %s\n\tcd .. ; python %s %s" %
                    (pminc_fname, " ".join(nim_modfiles_rel_pmgen_dir),
                            abspath_to_pmgen_py, " ".join(nim_modfiles))
            ]

    makefile_fname = MAKEFILE2_FNAME_TEMPLATE
    makefile_clean_rules = MAKEFILE_CLEAN_RULES % dict(
            pmgen_prefix=PMGEN_PREFIX)
    with open(makefile_fname, "w") as f:
        f.write(MAKEFILE_CONTENT % dict(
                datestamp=datestamp,
                variables=MAKEFILE_PMGEN_VARIABLE,
                build_rules="\n\n".join(build_rules),
                clean_rules=makefile_clean_rules))

    make_command = [MAKE_EXE_PATH, "-f", makefile_fname]
    print " ".join(make_command)
    subprocess.check_call(make_command)


def die(msg):
    print >> sys.stderr, "%s: %s\nAborted." % (sys.argv[0], msg)
    sys.exit(1)


if __name__ == "__main__":
    main()
