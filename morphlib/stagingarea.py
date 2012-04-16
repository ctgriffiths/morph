# Copyright (C) 2012  Codethink Limited
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


import logging
import os
import shutil
import tarfile

import morphlib


class StagingArea(object):

    '''Represent the staging area for building software.
    
    The build dependencies of what will be built will be installed in the
    staging area. The staging area may be a dedicated part of the
    filesystem, used with chroot, or it can be the actual root of the
    filesystem, which is needed when bootstrap building Baserock. The
    caller chooses this by providing the root directory of the staging
    area when the object is created. The directory must already exist.
    
    The staging area can also install build artifacts.
    
    '''
    
    def __init__(self, dirname):
        self.dirname = dirname
        self._chroot = 'chroot' if os.getuid() == 0 else 'echo'

    # Wrapper to be overridden by unit tests.
    def _mkdir(self, dirname): # pragma: no cover
        os.mkdir(dirname)

    def _dir_for_source(self, source, suffix):
        dirname = os.path.join(self.dirname, 
                               '%s.%s' % (source.morphology['name'], suffix))
        self._mkdir(dirname)
        return dirname

    def builddir(self, source):
        '''Create a build directory for a given source project.
        
        Return path to directory.
        
        '''

        return self._dir_for_source(source, 'build')
        
    def destdir(self, source):
        '''Create an installation target directory for a given source project.
        
        This is meant to be used as $DESTDIR when installing chunks.
        Return path to directory.
        
        '''

        return self._dir_for_source(source, 'inst')

    def relative(self, filename):
        '''Return a filename relative to the staging area.'''

        dirname = self.dirname
        if not dirname.endswith('/'):
            dirname += '/'

        assert filename.startswith(dirname)
        return filename[len(dirname)-1:] # include leading slash

    def install_artifact(self, handle):
        '''Install a build artifact into the staging area.
        
        We access the artifact via an open file handle. For now, we assume
        the artifact is a tarball.
        
        '''
        
        tf = tarfile.open(fileobj=handle)
        tf.extractall(path=self.dirname)

    def remove(self):
        '''Remove the entire staging area.
        
        Do not expect anything with the staging area to work after this
        method is called. Be careful about calling this method if
        the filesystem root directory was given as the dirname.
        
        '''
        
        shutil.rmtree(self.dirname)

    def runcmd(self, argv, **kwargs): # pragma: no cover
        '''Run a command in a chroot in the staging area.'''
        ex = morphlib.execute.Execute('/', logging.debug)
        cwd = kwargs.get('cwd') or '/'
        if 'cwd' in kwargs:
            cwd = kwargs['cwd']
            del kwargs['cwd']
        else:
            cwd = '/'
        real_argv = [self._chroot, self.dirname, 
                     'sh', '-c', 'cd "$1" && shift && eval "$@"', '--',
                     cwd] + argv
        return ex.runv(real_argv, **kwargs)

