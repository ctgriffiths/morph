# Copyright (C) 2011-2012  Codethink Limited
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import binascii
import cliapp
import ConfigParser
import logging
import os
import re
import StringIO

import morphlib


class NoMorphs(Exception):

    def __init__(self, repo, ref):
        Exception.__init__(self, 'Cannot find any morpologies at %s:%s' %
                           (repo, ref))


class TooManyMorphs(Exception):

    def __init__(self, repo, ref, morphs):
        Exception.__init__(self, 'Too many morphologies at %s:%s: %s' %
                           (repo, ref, ', '.join(morphs)))


class InvalidReferenceError(cliapp.AppException):

    def __init__(self, repo, ref):
        Exception.__init__(self, '%s is an invalid reference for repo %s' %
                           (ref, repo))


class Treeish(object):

    def __init__(self, repo, original_repo, ref, msg=logging.debug):
        self.repo = repo
        self.msg = msg
        self.sha1 = None
        self.ref = None
        self.original_repo = original_repo
        self._resolve_ref(ref) 

    def __hash__(self):
        return hash((self.repo, self.ref))

    def __eq__(self, other):
        return other.repo == self.repo and other.ref == self.ref

    def __str__(self):
        return '%s:%s' % (self.repo, self.ref)

    def _resolve_ref(self, ref):
        ex = morphlib.execute.Execute(self.repo, self.msg)
        try:
            refs = ex.runv(['git', 'show-ref', ref]).split('\n')

            # drop the refs that are not from origin
            refs = [x.split() for x in refs if 'origin' in x]

            binascii.unhexlify(refs[0][0]) #Valid hex?
            self.sha1 = refs[0][0]
            self.ref = refs[0][1]
        except morphlib.execute.CommandFailure:
            self._is_sha(ref)

    def _is_sha(self, ref):
        if len(ref) != 40:
            raise InvalidReferenceError(self.original_repo, ref)

        try:
                binascii.unhexlify(ref)
                ex = morphlib.execute.Execute(self.repo, self.msg)
                ex.runv(['git', 'rev-list', '--no-walk', ref])
                self.sha1=ref
        except (TypeError, morphlib.execute.CommandFailure):
            raise InvalidReferenceError(self.original_repo, ref)


class NoModulesFileError(cliapp.AppException):

    def __init__(self, treeish):
        Exception.__init__(self, '%s has no .gitmodules file.' % treeish)


class Submodule(object):

    def __init__(self, parent_treeish, name, url, path):
        self.parent_treeish = parent_treeish
        self.name = name
        self.url = url
        self.path = path


class ModulesFileParseError(cliapp.AppException):

    def __init__(self, treeish, message):
        Exception.__init__(self, 'Failed to parse %s:.gitmodules: %s' %
                           (treeish, message))


class InvalidSectionError(cliapp.AppException):

    def __init__(self, treeish, section):
        Exception.__init__(self,
                           '%s:.gitmodules: Found a misformatted section '
                           'title: [%s]' % (treeish, section))


class MissingSubmoduleCommitError(cliapp.AppException):

    def __init__(self, treeish, submodule):
        Exception.__init__(self,
                           '%s:.gitmodules: No commit object found for '
                           'submodule "%s"' % (treeish, submodule))


class Submodules(object):

    def __init__(self, treeish, msg=logging.debug):
        self.treeish = treeish
        self.msg = msg
        self.submodules = []

    def load(self):
        content = self._read_gitmodules_file()

        io = StringIO.StringIO(content)
        parser = ConfigParser.RawConfigParser()
        parser.readfp(io)

        self._validate_and_read_entries(parser)
        self._resolve_commits()

    def _read_gitmodules_file(self):
        try:
            # try to read the .gitmodules file from the repo/ref
            ex = morphlib.execute.Execute(self.treeish.repo, self.msg)
            content = ex.runv(['git', 'cat-file', 'blob', '%s:.gitmodules' %
                               self.treeish.ref])

            # drop indentation in sections, as RawConfigParser cannot handle it
            return '\n'.join([line.strip() for line in content.splitlines()])
        except morphlib.execute.CommandFailure:
            raise NoModulesFileError(self.treeish)

    def _validate_and_read_entries(self, parser):
        for section in parser.sections():
            # validate section name against the 'section "foo"' pattern
            section_pattern = r'submodule "(.*)"'
            if re.match(section_pattern, section):
                # parse the submodule name, URL and path
                name = re.sub(section_pattern, r'\1', section)
                url = parser.get(section, 'url')
                path = parser.get(section, 'path')

                # add a submodule object to the list
                submodule = Submodule(self.treeish, name, url, path)
                self.submodules.append(submodule)
            else:
                raise InvalidSectionError(self.treeish, section)

    def _resolve_commits(self):
        ex = morphlib.execute.Execute(self.treeish.repo, self.msg)
        for submodule in self.submodules:
            try:
                # list objects in the parent repo tree to find the commit
                # object that corresponds to the submodule
                commit = ex.runv(['git', 'ls-tree', self.treeish.ref,
                                  submodule.name])

                # read the commit hash from the output
                submodule.commit = commit.split()[2]

                # fail if the commit hash is invalid
                if len(submodule.commit) != 40:
                    raise MissingSubmoduleCommitError(self.treeish,
                                                      submodule.name)
            except morphlib.execute.CommandFailure:
                raise MissingSubmoduleCommitError(self.treeish, submodule.name)

    def __iter__(self):
        for submodule in self.submodules:
            yield submodule

    def __len__(self):
        return len(self.submodules)


def export_sources(treeish, tar_filename, msg=logging.debug):
    '''Export the contents of a specific commit into a compressed tarball.'''
    ex = morphlib.execute.Execute('.', msg=msg)
    ex.env['GIT_DIR'] = os.path.join(treeish.repo, '.git')
    ex.runv(['git', 'archive', '-o', tar_filename, treeish.sha1])

def get_morph_text(treeish, filename, msg=logging.debug):
    '''Return a morphology from a git repository.'''
    ex = morphlib.execute.Execute(treeish.repo, msg=msg)
    return ex.runv(['git', 'cat-file', 'blob', '%s:%s'
                   % (treeish.sha1, filename)])

def extract_bundle(location, bundle, msg=logging.debug):
    '''Extract a bundle into git at location'''
    ex = morphlib.execute.Execute(location, msg=msg)
    return ex.runv(['git', 'bundle', 'unbundle', bundle])

def clone(location, repo, msg=logging.debug):
    '''clone at git repo into location'''
    ex = morphlib.execute.Execute('.', msg=msg)
    return ex.runv(['git', 'clone', '-l', repo, location])

def init(location, msg=logging.debug):
    '''initialise git repo at location'''
    os.mkdir(location)
    ex = morphlib.execute.Execute(location, msg=msg)
    return ex.runv(['git', 'init'])

def add_remote(gitdir, name, url, msg=logging.debug):
    '''add remote with name 'name' for url at gitdir'''
    ex = morphlib.execute.Execute(gitdir, msg=msg)
    return ex.runv(['git', 'remote', 'add', '-f', name, url])

def update_remote(gitdir, name, msg=logging.debug):
    ex = morphlib.execute.Execute(gitdir, msg=msg)
    return ex.runv(['git', 'remote', 'update', name])
