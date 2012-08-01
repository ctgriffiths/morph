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


import cliapp

import morphlib


class BuildPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('build', self.build,
                                arg_synopsis='(REPO REF FILENAME)...')

    def disable(self):
        pass

    def build(self, args):
        '''Build a binary from a morphology.

        Command line arguments are the repository, git tree-ish reference,
        and morphology filename. Morph takes care of building all dependencies
        before building the morphology. All generated binaries are put into the
        cache.

        (The triplet of command line arguments may be repeated as many
        times as necessary.)

        '''

        build_command = morphlib.buildcommand.BuildCommand(self.app)
        build_command = self.app.hookmgr.call('new-build-command',
                                              build_command)
        build_command.build(args)
