#!/usr/bin/python
#
# CGI script to handle file updates for the rpms CVS repository. There
# is nothing really complex here other than tedious checking of our
# every step along the way...
#
# License: GPL

import os
import sys
import cgi
import tempfile
import grp
import urllib2
try:
    import hashlib
    md5_constructor = hashlib.md5
except ImportError:
    import md5
    md5_constructor = md5.new

# Reading buffer size
BUFFER_SIZE = 4096

# We check modules exist from this dircetory
CVSREPO = '/cvs/pkgs/rpms'

# Lookaside cache directory
CACHE_DIR = '/srv/cache/lookaside/pkgs'

# Fedora Packager Group
PACKAGER_GROUP = 'packager'

def send_error(text):
    print text
    sys.exit(1)

def check_form(form, var):
    ret = form.getvalue(var, None)
    if ret is None:
        send_error('Required field "%s" is not present.' % var)
    if isinstance(ret, list):
        send_error('Multiple values given for "%s". Aborting.' % var)
    return ret

def check_auth(username):
    authenticated = False
    try:
        if username in grp.getgrnam(PACKAGER_GROUP)[3]:
            authenticated = True
    except KeyError:
        pass
    return authenticated

def main():
    os.umask(002)

    username = os.environ.get('SSL_CLIENT_S_DN_CN', None)
    if not check_auth(username):
        print 'Status: 403 Forbidden'
        print 'Content-type: text/plain'
        print
        print 'You must connect with a valid certificate and be in the %s group to upload.' % PACKAGER_GROUP
        sys.exit(0)

    print 'Content-Type: text/plain'
    print

    assert os.environ['REQUEST_URI'].split('/')[1] == 'repo'

    form = cgi.FieldStorage()
    name = check_form(form, 'name')
    md5sum = check_form(form, 'md5sum')

    action = None
    upload_file = None
    filename = None

    # Is this a submission or a test?
    # in a test, we don't get a file, just a filename.
    # In a submission, we don;t get a filename, just the file.
    if form.has_key('filename'):
        action = 'check'
        filename = check_form(form, 'filename')
        filename = os.path.basename(filename)
        print >> sys.stderr, '[username=%s] Checking file status: NAME=%s FILENAME=%s MD5SUM=%s' % (username, name, filename, md5sum)
    else:
        action = 'upload'
        if form.has_key('file'):
            upload_file = form['file']
            if not upload_file.file:
                send_error('No file given for upload. Aborting.')
            filename = os.path.basename(upload_file.filename)
        elif form.has_key('url'):
            url = form['url']
            try:
                upload_file = urllib2.urlopen(url)
            except urllib2.HTTPError, e:
                send_error('Could not download %s: %s' % (url, e))
            filename = os.path.basename(upload_file.geturl())
        else:
            send_error('No "file" or "url" value given.')
        print >> sys.stderr, '[username=%s] Processing upload request: NAME=%s FILENAME=%s MD5SUM=%s' % (username, name, filename, md5sum)

    module_dir = os.path.join(CACHE_DIR, name)
    md5_dir =  os.path.join(module_dir, filename, md5sum)

    # first test if the module really exists
    cvs_dir = os.path.join(CVSREPO, name)
    if not os.path.isdir(cvs_dir):
        print >> sys.stderr, '[username=%s] Unknown module: %s' % (username, name)
        send_error('Module "%s" does not exist!' % name)
        
    # try to see if we already have this file...
    dest_file = os.path.join(md5_dir, filename)
    if os.path.exists(dest_file):
        if action == 'check':
            print 'Available'
        else:
            upload_file.file.close()
            dest_file_stat = os.stat(dest_file)
            print 'File %s already exists' % filename
            print 'File: %s Size: %d' % (dest_file, dest_file_stat.st_size)
        sys.exit(0)
    elif action == 'check':
        print 'Missing'
        sys.exit(0)

    # check that all directories are in place
    if not os.path.isdir(module_dir):
        os.makedirs(module_dir, 02775)

    # grab a temporary filename and dump our file in there
    tempfile.tempdir = module_dir
    tmpfile = tempfile.mkstemp(md5sum)
    tmpfd = open(tmpfile, 'w')

    # now read the whole file in
    m = md5_constructor()
    filesize = 0
    while True:
        data = upload_file.file.read(BUFFER_SIZE)
        if not data:
            break
        tmpfd.write(data)
        m.update(data)
        filesize += len(data)

    # now we're done reading, check the MD5 sum of what we got
    tmpfd.close()
    check_md5sum = m.hexdigest()
    if md5sum != check_md5sum:
        send_error("MD5 check failed. Received %s instead of %s." % (check_md5sum, md5sum))

    # wow, even the MD5SUM matches. make sure full path is valid now
    if not os.path.isdir(md5_dir):
        os.makedirs(md5_dir, 02775)
        print >> sys.stderr, '[username=%s] mkdir %s' % (username, md5_dir)

    os.rename(tmpfile, dest_file)
    print >> sys.stderr, '[username=%s] Stored %s (%d bytes)' % (username, dest_file, filesize)
    print 'File %s size %d MD5 %s stored OK' % (filename, filesize, md5sum)

if __name__ == '__main__':
    main()
