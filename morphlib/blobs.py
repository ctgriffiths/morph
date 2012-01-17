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


class Blob(object):

    def __init__(self, parent, morph):
        self.parent = parent
        self.morph = morph
        self.dependencies = set()
        self.dependents = set()

    def add_dependency(self, other):
        self.dependencies.add(other)
        other.dependents.add(self)

    def remove_dependency(self, other):
        self.dependencies.remove(other)
        other.dependents.remove(self)

    def depends_on(self, other):
        return other in self.dependencies

    @property
    def chunks(self):
        if self.morph.chunks:
            return self.morph.chunks
        else:
            return { self.morph.name: ['.'] }

    def __str__(self):
        return str(self.morph)


class Chunk(Blob):

    pass


class Stratum(Blob):

    pass


class System(Blob):

    pass
