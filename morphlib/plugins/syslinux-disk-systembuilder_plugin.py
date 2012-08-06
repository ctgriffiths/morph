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


import json
import logging
import os
import shutil
import time
from collections import defaultdict
import tarfile
import traceback
import subprocess

import cliapp

import morphlib
from morphlib.artifactcachereference import ArtifactCacheReference
from morphlib.builder2 import (SystemKindBuilder, download_depends,
                               get_overlaps, log_overlaps, ldconfig,
                               write_overlap_metadata)


class SyslinuxDiskBuilder(SystemKindBuilder):  # pragma: no cover

    system_kind = 'syslinux-disk'

    def build_and_cache(self):
        with self.build_watch('overall-build'):
            arch = self.artifact.source.morphology['arch']

            rootfs_artifact = self.new_artifact(
                self.artifact.source.morphology['name'] + '-rootfs')
            handle = self.local_artifact_cache.put(rootfs_artifact)
            image_name = handle.name

            self._create_image(image_name)
            self._partition_image(image_name)
            self._install_mbr(arch, image_name)
            partition = self._setup_device_mapping(image_name)

            mount_point = None
            try:
                self._create_fs(partition)
                mount_point = self.staging_area.destdir(self.artifact.source)
                self._mount(partition, mount_point)
                factory_path = os.path.join(mount_point, 'factory')
                self._create_subvolume(factory_path)
                self.unpack_strata(factory_path)
                self.create_fstab(factory_path)
                self._create_extlinux_config(factory_path)
                self._create_subvolume_snapshot(
                    mount_point, 'factory', 'factory-run')
                factory_run_path = os.path.join(mount_point, 'factory-run')
                self._install_boot_files(arch, factory_run_path, mount_point)
                self._install_extlinux(mount_point)
                self.copy_kernel_into_artifact_cache(factory_path)
                self._unmount(mount_point)
            except BaseException, e:
                logging.error(traceback.format_exc())
                self.app.status(msg='Error while building system',
                                error=True)
                self._unmount(mount_point)
                self._undo_device_mapping(image_name)
                handle.abort()
                raise

            self._undo_device_mapping(image_name)
            handle.close()

        self.save_build_times()
        return [self.artifact]

    def _create_image(self, image_name):
        self.app.status(msg='Creating disk image %(filename)s',
                        filename=image_name, chatty=True)
        with self.build_watch('create-image'):
            morphlib.fsutils.create_image(
                self.app.runcmd, image_name,
                self.artifact.source.morphology['disk-size'])

    def _partition_image(self, image_name):
        self.app.status(msg='Partitioning disk image %(filename)s',
                        filename=image_name)
        with self.build_watch('partition-image'):
            morphlib.fsutils.partition_image(self.app.runcmd, image_name)

    def _install_mbr(self, arch, image_name):
        self.app.status(msg='Installing mbr on disk image %(filename)s',
                        filename=image_name, chatty=True)
        if arch not in ('x86', 'x86_64'):
            return
        with self.build_watch('install-mbr'):
            mbr_installed = False
            for path in self.app.settings['syslinux-mbr-search-paths']:
                if os.path.exists(path):
                    self.app.runcmd(['dd', 'if=' + path, 'of=' + image_name,
                                     'conv=notrunc'])
                    mbr_installed = True
                    break
            # A flag, rather than an else statement is used, since it must
            # fail if the search path is empty as well
            if not mbr_installed:
                raise morphlib.Error(
                    "No syslinux mbr found in search paths: %s" %
                    repr(self.app.settings['syslinux-mbr-search-paths']))

    def _setup_device_mapping(self, image_name):
        self.app.status(msg='Device mapping partitions in %(filename)s',
                        filename=image_name, chatty=True)
        with self.build_watch('setup-device-mapper'):
            return morphlib.fsutils.setup_device_mapping(self.app.runcmd,
                                                         image_name)

    def _create_fs(self, partition):
        self.app.status(msg='Creating filesystem on %(partition)s',
                        partition=partition, chatty=True)
        with self.build_watch('create-filesystem'):
            morphlib.fsutils.create_fs(self.app.runcmd, partition)

    def _mount(self, partition, mount_point):
        self.app.status(msg='Mounting %(partition)s on %(mount_point)s',
                        partition=partition, mount_point=mount_point,
                        chatty=True)
        with self.build_watch('mount-filesystem'):
            morphlib.fsutils.mount(self.app.runcmd, partition, mount_point)

    def _create_subvolume(self, path):
        self.app.status(msg='Creating subvolume %(path)s',
                        path=path, chatty=True)
        with self.build_watch('create-factory-subvolume'):
            self.app.runcmd(['btrfs', 'subvolume', 'create', path])

    def _create_extlinux_config(self, path):
        self.app.status(msg='Creating extlinux.conf in %(path)s',
                        path=path, chatty=True)
        with self.build_watch('create-extlinux-config'):
            config = os.path.join(path, 'extlinux.conf')
            with open(config, 'w') as f:
                f.write('default linux\n')
                f.write('timeout 1\n')
                f.write('label linux\n')
                f.write('kernel /boot/vmlinuz\n')
                f.write('append root=/dev/sda1 rootflags=subvol=factory-run '
                        'init=/sbin/init rw\n')

    def _create_subvolume_snapshot(self, path, source, target):
        self.app.status(msg='Creating subvolume snapshot '
                            '%(source)s to %(target)s',
                        source=source, target=target, chatty=True)
        with self.build_watch('create-runtime-snapshot'):
            self.app.runcmd(['btrfs', 'subvolume', 'snapshot', source, target],
                            cwd=path)

    def _install_boot_files(self, arch, sourcefs, targetfs):
        with self.build_watch('install-boot-files'):
            if arch in ('x86', 'x86_64'):
                self.app.status(msg='Installing boot files into root volume',
                                chatty=True)
                shutil.copy2(os.path.join(sourcefs, 'extlinux.conf'),
                             os.path.join(targetfs, 'extlinux.conf'))
                os.mkdir(os.path.join(targetfs, 'boot'))
                shutil.copy2(os.path.join(sourcefs, 'boot', 'vmlinuz'),
                             os.path.join(targetfs, 'boot', 'vmlinuz'))
                shutil.copy2(os.path.join(sourcefs, 'boot', 'System.map'),
                             os.path.join(targetfs, 'boot', 'System.map'))

    def _install_extlinux(self, path):
        self.app.status(msg='Installing extlinux to %(path)s',
                        path=path, chatty=True)
        with self.build_watch('install-bootloader'):
            self.app.runcmd(['extlinux', '--install', path])

            # FIXME this hack seems to be necessary to let extlinux finish
            self.app.runcmd(['sync'])
            time.sleep(2)

    def _unmount(self, mount_point):
        with self.build_watch('unmount-filesystem'):
            if mount_point is not None:
                self.app.status(msg='Unmounting %(mount_point)s',
                                mount_point=mount_point, chatty=True)
                morphlib.fsutils.unmount(self.app.runcmd, mount_point)

    def _undo_device_mapping(self, image_name):
        self.app.status(msg='Undoing device mappings for %(filename)s',
                        filename=image_name, chatty=True)
        with self.build_watch('undo-device-mapper'):
            morphlib.fsutils.undo_device_mapping(self.app.runcmd, image_name)


class SyslinuxDiskBuilderPlugin(cliapp.Plugin):

    def enable(self):
        # Only provide this system builder on architectures that are
        # supported by syslinux.
        if morphlib.util.arch() in ['x86_64', 'i386', 'i486', 'i586', 'i686']:
            self.app.settings.string_list(
                ['syslinux-mbr-search-paths'],
                'A list of files to search for to use as the syslinux mbr',
                default=['/usr/lib/extlinux/mbr.bin',
                         '/usr/share/syslinux/mbr.bin'])
            self.app.system_kind_builder_factory.register(SyslinuxDiskBuilder)

    def disable(self):
        pass
