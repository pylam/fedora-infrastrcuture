#!/usr/bin/python -tt
# -*- coding: utf-8 -*-
#
# Copyright © 2008  Red Hat, Inc. All rights reserved.
#
# This copyrighted material is made available to anyone wishing to use, modify,
# copy, or redistribute it subject to the terms and conditions of the GNU
# General Public License v.2.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY expressed or implied, including the
# implied warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.  You should have
# received a copy of the GNU General Public License along with this program;
# if not, write to the Free Software Foundation, Inc., 51 Franklin Street,
# Fifth Floor, Boston, MA 02110-1301, USA. Any Red Hat trademarks that are
# incorporated in the source code or documentation are not subject to the GNU
# General Public License and may only be used or replicated with the express
# permission of Red Hat, Inc.
#
# Red Hat Author(s): Nigel Jones <nigjones@redhat.com>
#


from configobj import ConfigObj
import os
import sys
import subprocess

config = ConfigObj("/etc/zabbixhelper.cfg")

try:
    command = config['commands'][sys.argv[1]]
except KeyError:
    print "Invalid command passed to script, check input"
    sys.exit(1)
except IndexError:
    print "No parameters passed to script"
    sys.exit(1)

devnull = open("/dev/null", "w")
ret = subprocess.Popen(command.split(), stderr=devnull, stdout=devnull).wait()

if ret != 0:
    print "Execution Failed"

sys.exit(ret)
