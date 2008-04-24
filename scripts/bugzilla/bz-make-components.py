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
# Red Hat Author(s): Elliot Lee <sopwith@redhat.com>
#                    Toshio Kuratomi <tkuratom@redhat.com>
#

import sys
import os
import errno
import website
import crypt
import getopt
import xmlrpclib
from email.Message import Message
import smtplib


# Set this to the production bugzilla account when we're ready to go live
BZSERVER = 'https://bugdev.devel.redhat.com/bugzilla-cvs/xmlrpc.cgi'
#BZSERVER = 'https://bugzilla.redhat.com/xmlrpc.cgi'
#BZSERVER = 'https://bzprx.vip.phx.redhat.com/xmlrpc.cgi'
BZUSER='<%= bzAdminUser %>'
BZPASS='<%= bzAdminPassword %>'

DRY_RUN = False

class Bugzilla(object):
    def __init__(self, bzServer, username, password):
        self.productCache = {}
        self.bzXmlRpcServer = bzServer
        self.username = username
        self.password = password

        self.server = xmlrpclib.Server(bzServer)

    def add_edit_component(self, package, collection,owner, description,
            qacontact=None, cclist=None):
        '''Add or updatea component to have the values specified.
        '''
        initialCCList = cclist or list()

        # Lookup product
        try:
            product = self.productCache[collection]
        except KeyError:
            product = {}
            try:
                components = self.server.bugzilla.getProdCompDetails(collection,
                                self.username, self.password)
            except xmlrpclib.Fault, e:
                # Output something useful in args
                e.args = (e.faultCode, e.faultString)
                raise
            except xmlrpclib.ProtocolError, e:
                e.args = ('ProtocolError', e.errcode, e.errmsg)
                raise

            # This changes from the form:
            #   {'component': 'PackageName',
            #   'initialowner': 'OwnerEmail',
            #   'initialqacontact': 'QAContactEmail',
            #   'description': 'One sentence summary'}
            # to:
            #   product['packagename'] = {'component': 'PackageName',
            #     'initialowner': 'OwnerEmail',
            #     'initialqacontact': 'QAContactEmail',
            #     'description': 'One sentenct summary'}
            # This allows us to check in a case insensitive manner for the
            # package.
            for record in components:
                record['component'] = unicode(record['component'], 'utf-8')
                try:
                    record['description'] = unicode(record['description'], 'utf-8')
                except TypeError:
                    try:
                        record['description'] = unicode(record['description'].data, 'utf-8')
                    except:
                        record['description'] = None
                product[record['component'].lower()] = record

            self.productCache[collection] = product

        pkgKey = package.lower()
        if pkgKey in product:
            # edit the package information
            data = {}

            # Grab bugzilla email for things changable via xmlrpc
            owner = owner.lower()
            if qacontact:
                qacontact = qacontact.lower()
            else:
                qacontact = 'extras-qa@fedoraproject.org'

            # Check for changes to the owner, qacontact, or description
            if product[pkgKey]['initialowner'] != owner:
                data['initialowner'] = owner

            if product[pkgKey]['description'] != description:
                data['description'] = description
            if product[pkgKey]['initialqacontact'] != qacontact and (
                    qacontact or product[pkgKey]['initialqacontact']):
                data['initialqacontact'] = qacontact

            if len(product[pkgKey]['initialcclist']) != len(initialCCList):
                data['initialcclist'] = initialCCList
            else:
                for ccMember in product[pkgKey]['initialcclist']:
                    if ccMember not in initialCCList:
                        data['initialcclist'] = initialCCList
                        break

            if data:
                ### FIXME: initialowner has been made mandatory for some
                # reason.  Asking dkl why.
                data['initialowner'] = owner

                # Changes occurred.  Submit a request to change via xmlrpc
                data['product'] = collection
                data['component'] = product[pkgKey]['component']
                if DRY_RUN:
                    print '[EDITCOMP] Changing via editComponent(%s, %s, "xxxxx")' % (
                            data, self.username)
                    print '[EDITCOMP] Former values: %s|%s|%s' % (
                            product[pkgKey]['initialowner'],
                            product[pkgKey]['description'],
                            product[pkgKey]['initialqacontact'])
                else:
                    try:
                        self.server.bugzilla.editComponent(data, self.username,
                                self.password)
                    except xmlrpclib.Fault, e:
                        # Output something useful in args
                        e.args = (data, e.faultCode, e.faultString)
                        raise
                    except xmlrpclib.ProtocolError, e:
                        e.args = ('ProtocolError', e.errcode, e.errmsg)
                        raise
        else:
            # Add component
            owner = owner.lower()
            if qacontact:
                qacontact = qacontact
            else:
                qacontact = 'extras-qa@fedoraproject.org'

            data = {'product': collection,
                'component': package,
                'description': description,
                'initialowner': owner,
                'initialqacontact': qacontact}
            if initialCCList:
                data['initialcclist'] = initialCCList

            if DRY_RUN:
                print '[ADDCOMP] Adding new component AddComponent:(%s, %s, "xxxxx")' % (
                        data, self.username)
            else:
                try:
                    self.server.bugzilla.addComponent(data, self.username,
                            self.password)
                except xmlrpclib.Fault, e:
                    # Output something useful in args
                    e.args = (data, e.faultCode, e.faultString)
                    raise

def parseOwnerFile(curfile, warnings):
    pkgInfo = []
    ownerFile = file(curfile, 'r')
    while line in ownerFile:
        line = line.strip()
        if not line or line[0] == '#':
            continue
        pieces = line.split('|')
        try:
            product, component, summary, owner, qa = pieces[:5]
        except:
            warnings.append('%s: Invalid line %s' % (curfile, line))

        owners = owner.split(',')
        owner = owners[0]
        cclist = owners[1:] or []
        if not owner:
            warnings.append('%s: No owner in line %s' % (curfile, line))
            continue

        if len(pieces) > 5 and pieces[5].strip():
            for person in pieces[5].strip().split(','):
                cclist.append(person.strip())

        if product != 'Fedora' and not product.startswith('Fedora '):
            warnings.append('%s: Invalid product %s in line %s' %
                    (curfile, product, line))
            continue
        pkgInfo.append({'product': product, 'component': component,
            'owner': owner, 'summary': summary, 'qa': qa, 'cclist': cclist})

    return pkgInfo

def send_email(fromAddress, toAddress, subject, message):
    '''Send an email if there's an error.
    
    This will be replaced by sending messages to a log later.
    '''
    msg = Message()
    msg.add_header('To', toAddress)
    msg.add_header('From', fromAddress)
    msg.add_header('Subject', subject)
    msg.set_payload(message)
    smtp = smtplib.SMTP('bastion')
    smtp.sendmail(fromAddress, [toAddress], msg.as_string())
    smtp.quit()

if __name__ == '__main__':
    opts, args = getopt.getopt(sys.argv[1:], '', ('usage', 'help'))
    if len(args) < 1 or ('--usage','') in opts or ('--help','') in opts:
        print """Usage: bz-make-components.py FILENAME..."""
        sys.exit(1)

    # Initialize connection to bugzilla
    bugzilla = Bugzilla(BZSERVER, BZUSER, BZPASS)

    warnings = []
    # Iterate through the files in the argument list.  Grab the owner
    # information from each one and construct bugzilla information from it.
    pkgData = []
    for curfile in args:
        if not os.path.exists(curfile):
            warnings.append('%s does not exist' % curfile)
            continue
        pkgData.extend(parseOwnerFile(curfile, warnings))

    for pkgInfo in pkgData:
        try:
            bugzilla.add_edit_component(pkgInfo['product'],
                    pkgInfo['component'], pkgInfo['owner'], pkgInfo['summary'],
                    pkgInfo['qa'], pkgInfo['cclist'])
        except ValueError, e:
            # A username didn't have a bugzilla address
            warnings.append(str(e.args))
        except DataChangedError, e:
            # A Package or Collection was returned via xmlrpc but wasn't
            # present when we tried to change it
            warnings.append(str(e.args))
        except xmlrpclib.ProtocolError, e:
            # Unrecoverable and likely means that nothing is going to
            # succeed.
            warnings.append(str(e.args))
            break
        except xmlrpclib.Error, e:
            # An error occurred in the xmlrpc call.  Shouldn't happen but
            # we better see what it is
            warnings.append(str(e.args))

    if warnings:
        # print '[DEBUG]', '\n'.join(warnings)
        send_email('accounts@fedoraproject.org', 'a.badger@gmail.com',
                'Errors while syncing bugzilla with owners.list',
'''
The following errors were encountered while updating bugzilla with information
from owners.list files.  Please have the problem taken care of:

%s
''' % ('\n\n'.join(warnings),))

    sys.exit(0)
