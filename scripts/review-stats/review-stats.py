#!/usr/bin/python -t
VERSION = "3.0"

# $Id: review-stats.py,v 1.12 2010/01/15 05:14:10 tibbs Exp $
# Note: This script presently lives in internal git and external cvs.  External
# cvs is:
# http://cvs.fedoraproject.org/viewvc/status-report-scripts/review-stats.py?root=fedora
# or check it out with
# CVSROOT=:pserver:anonymous@cvs.fedoraproject.org:/cvs/fedora cvs co status-report-scripts
#
# Internal is in the puppet configs repository on puppet1.  It needs to be
# there so that puppet can distribute to the servers.  I recommend doing the
# work in the public cvs first, then copying to puppet's git after.

import bugzilla
import datetime
import glob
import logging
import operator
import os
import string
import sys
import tempfile
import time
from configobj import ConfigObj, flatten_errors
from copy import deepcopy
from genshi.template import TemplateLoader
from optparse import OptionParser
from validate import Validator

# Red Hat's bugzilla
url = 'https://bugzilla.redhat.com/xmlrpc.cgi'

# Some magic bug numbers
ACCEPT      = 163779
BUNDLED     = 658489
FEATURE     = 654686
GUIDELINES  = 197974
LEGAL       = 182235
NEEDSPONSOR = 177841
SCITECH     = 505154

# These will show up in a query but aren't actual review tickets
trackers = set([ACCEPT, BUNDLED, FEATURE, NEEDSPONSOR, GUIDELINES, SCITECH])

# So the bugzilla module has some way to complain
logging.basicConfig()
#logging.basicConfig(level=logging.DEBUG)

def parse_commandline():
    usage = "usage: %prog [options] -c <bugzilla_config> -d <dest_dir> -t <template_dir>"
    parser = OptionParser(usage)
    parser.add_option("-c", "--config", dest="configfile",
              help="configuration file name")
    parser.add_option("-d", "--destination", dest="dirname",
              help="destination directory")
    parser.add_option("-f", "--frequency", dest="frequency",
              help="update frequency", default="60")
    parser.add_option("-t", "--templatedir", dest="templdir",
              help="template directory")

    (options, args) = parser.parse_args()
    tst = str(options.dirname)
    if str(options.dirname) == 'None':
        parser.error("Please specify destination directory")
    if not os.path.isdir(options.dirname):
        parser.error("Please specify an existing destination directory")

    if str(options.templdir) == 'None':
        parser.error("Please specify templates directory")
    if not os.path.isdir(options.templdir):
        parser.error("Please specify an existing template directory")

    return options

def parse_config(file):
    v = Validator()

    spec = '''
    [global]
        url = string(default='https://bugzilla.redhat.com/xmlrpc.cgi')
        username = string()
        password = string()
    '''.splitlines()

    cfg = ConfigObj(file, configspec=spec)
    res = cfg.validate(v, preserve_errors=True)

    for entry in flatten_errors(cfg, res):
        section_list, key, error = entry
        section_list.append(key)
        section_string = ','.join(section_list)
        if error == False:
            error = 'Missing value or section.'
        print ','.join(section_list), '=', error
        sys.exit(1)

    return cfg['global']

def nobody(str):
    '''Shorten the long "nobody's working on it" string.'''
    if (str == "Nobody's working on this, feel free to take it"
            or str == "nobody@fedoraproject.org"):
        return "(Nobody)"
    return str

def nosec(str):
    '''Remove the seconds from an hh:mm:ss format string.'''
    return str[0:str.rfind(':')]

def human_date(t):
    '''Turn an ISO date into something more human-friendly.'''
    t = str(t)
    return t[0:4] + '-' + t[4:6] + '-' + t[6:8]

def human_time(t):
    '''Turn an ISO date into something more human-friendly, with time.'''
    t = str(t)
    return t[0:4] + '-' + t[4:6] + '-' + t[6:8] + ' ' + t[9:]

def to_unicode(object, encoding='utf8', errors='replace'):
    if isinstance(object, basestring):
        if isinstance(object, str):
            return unicode(object, encoding, errors)
        else:
            return object
    return u''

def reporter(bug):
    '''Extract the reporter from a bug, replacing an empty value with "(none)".
    Yes, bugzilla will return a blank reporter for some reason.'''
    if (bug.reporter) == '':
        return "(none)"
    return bug.reporter

def yrmonth(d):
    '''Turn a bugzilla date into Month YYYY string.'''
    m = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
            'August', 'September', 'October', 'November', 'December']

    #year = str.split('-')[0]
    #month = int(str.split('-')[1])-1
    str = d.value
    year = str[0:4]
    month = int(str[4:6])-1
    return m[month] + ' ' + year

def seq_max_split(seq, max_entries):
    """ Given a seq, split into a list of lists of length max_entries each. """
    ret = []
    num = len(seq)
    seq = list(seq) # Trying to use a set/etc. here is bad
    beg = 0
    while num > max_entries:
        end = beg + max_entries
        ret.append(seq[beg:end])
        beg += max_entries
        num -= max_entries
    ret.append(seq[beg:])
    return ret

def run_query(bz):
    querydata = {}
    bugdata = {}
    interesting = {}
    alldeps = set([])
    closeddeps = set([])
    needinfo = set([])
    usermap = {}

    querydata['include_fields'] = ['id', 'creation_time', 'last_change_time', 'bug_severity',
            'alias', 'assigned_to', 'product', 'creator', 'creator_id', 'status', 'resolution',
            'component', 'blocks', 'depends_on', 'summary',
            'whiteboard', 'flags']
    #querydata['extra_values'] = []
    querydata['bug_status'] = ['NEW', 'ASSIGNED', 'MODIFIED']
    querydata['product'] = ['Fedora', 'Fedora EPEL']
    querydata['component'] = ['Package Review']
    querydata['query_format'] = 'advanced'

    # Look up tickets with no fedora-review flag set
    querydata['f1'] = 'flagtypes.name'
    querydata['o1'] = 'notregexp'
    querydata['v1'] = 'fedora-review[-+?]'
    bugs = filter(lambda b: b.id not in trackers, bz.query(querydata))

    for bug in bugs:
        bugdata[bug.id] = {}
        bugdata[bug.id]['hidden'] = 0
        bugdata[bug.id]['needinfo'] = 0
        bugdata[bug.id]['blocks'] = bug.blocks
        bugdata[bug.id]['depends'] = bug.depends_on
        bugdata[bug.id]['reviewflag'] = ' '

        if bug.depends_on:
            alldeps.update(bug.depends_on)

        if bug.flags.find('needinfo?') >= 0:
            needinfo.add(bug.id)

    # Get the status of each "interesting" bug
    for i in seq_max_split(alldeps.union(needinfo), 500):
        for bug in filter(None, bz._proxy.Bug.get_bugs({'ids':i, 'permissive': 1, 'extra_fields': ['flags']})['bugs']):
            interesting[bug['id']] = bug

    # Note the dependencies which are closed
    for i in alldeps:
        if interesting[i]['status'] == 'CLOSED':
            closeddeps.add(i)

    # Note the ones flagged needinfo->reporter
    for i in needinfo:
        for j in interesting[i]['flags']:
            if (j['name'] == 'needinfo'
                    and j['status'] == '?'
                    and j['requestee'] == interesting[i]['creator']):
                bugdata[i]['needinfo'] = 1
                bugdata[i]['hidden'] = 1

    # Hide tickets blocked by other bugs or whose with various blockers and
    # statuses.
    def opendep(id): return id not in closeddeps
    for bug in bugs:
        wb = string.lower(bug.whiteboard)
        if (bug.bug_status != 'CLOSED' and
            (wb.find('notready') >= 0
                    or wb.find('buildfails') >= 0
                    or wb.find('stalledsubmitter') >= 0
                    or wb.find('awaitingsubmitter') >= 0
                    or BUNDLED in bugdata[bug.id]['blocks']
                    or LEGAL in bugdata[bug.id]['blocks']
                    or filter(opendep, bugdata[bug.id]['depends']))):
            bugdata[bug.id]['hidden'] = 1

    # Now we need to look up the names of the users
    for i in bugs:
        if select_needsponsor(i, bugdata[i.id]):
           usermap[i.reporter] = ''

    for i in bz._proxy.User.get({'names': usermap.keys()})['users']:
        usermap[i['name']] = i['real_name']

    # Now process the other three flags; not much special processing for them
    querydata['o1'] = 'equals'
#    for i in ['-', '+', '?']:
    for i in ['-', '?']:
        querydata['v1'] = 'fedora-review' + i
        b1 = bz.query(querydata)
        for bug in b1:
            bugdata[bug.id] = {}
            bugdata[bug.id]['hidden'] = 0
            bugdata[bug.id]['blocks'] = []
            bugdata[bug.id]['depends'] = []
            bugdata[bug.id]['reviewflag'] = i
        bugs += b1

    bugs.sort(key=operator.attrgetter('id'))

    return [bugs, bugdata, usermap]

    # Need to generate reports:
    #  "Accepted" and closed 
    #  "Accepted" but still open
    #    "Accepted" means either fedora-review+ or blocking FE-ACCEPT
    #  fedora-review- and closed
    #  fedora-review- but still open
    #  fedora-review? and still optn
    #  fedora-review? but closed
    #  Tickets awaiting review but which were hidden for some reason
    # That should be all tickets in the Package Review component

def write_html(loader, template, data, dir, fname):
    '''Load and render the given template with the given data to the given
       filename in the specified directory.'''
    tmpl = loader.load(template)
    output = tmpl.generate(**data)

    path = os.path.join(dir, fname)
    try:
        f = open(path, "w")
    except IOError, (err, strerr):
        print 'ERROR: %s: %s' % (strerr, path)
        sys.exit(1)

    f.write(output.render())
    f.close()

# Selection functions (should all be predicates)
def select_hidden(bug, bugd):
    if bugd['hidden'] == 1:
        return 1
    return 0

def select_merge(bug, bugd):
    if (bugd['reviewflag'] == ' '
            and bug.bug_status != 'CLOSED'
            and bug.short_desc.find('Merge Review') >= 0):
        return 1
    return 0

def select_needsponsor(bug, bugd):
    wb = string.lower(bug.whiteboard)
    if (bugd['reviewflag'] == ' '
            and bugd['needinfo'] == 0
            and NEEDSPONSOR in bugd['blocks']
            and LEGAL not in bugd['blocks']
            and bug.bug_status != 'CLOSED'
            and nobody(bug.assigned_to) == '(Nobody)'
            and wb.find('buildfails') < 0
            and wb.find('notready') < 0
            and wb.find('stalledsubmitter') < 0
            and wb.find('awaitingsubmitter') < 0):
        return 1
    return 0

def select_review(bug, bugd):
    if bugd['reviewflag'] == '?':
        return 1
    return 0

def select_trivial(bug, bugd):
    if (bugd['reviewflag'] == ' '
            and bug.bug_status != 'CLOSED'
            and string.lower(bug.status_whiteboard).find('trivial') >= 0):
        return 1
    return 0

def select_epel(bug, bugd):
    '''If someone assigns themself to a ticket, it's theirs regardless of
    whether they set the flag properly or not.'''
    if (bugd['reviewflag'] == ' '
            and bug.product == 'Fedora EPEL'
            and bug.bug_status != 'CLOSED'
            and bugd['hidden'] == 0
            and nobody(bug.assigned_to) == '(Nobody)'
            and bug.short_desc.find('Merge Review') < 0):
        return 1
    return 0

def select_new(bug, bugd):
    '''If someone assigns themself to a ticket, it's theirs regardless of
    whether they set the flag properly or not.'''
    if (bugd['reviewflag'] == ' '
            and bug.product == 'Fedora'
            and bug.bug_status != 'CLOSED'
            and bugd['hidden'] == 0
            and nobody(bug.assigned_to) == '(Nobody)'
            and bug.short_desc.find('Merge Review') < 0):
        return 1
    return 0

def rowclass_plain(count):
    rowclass = 'bz_row_even'
    if count % 2 == 1:
        rowclass = 'bz_row_odd'

# Yes, the even/odd classes look backwards, but it looks better this way
def rowclass_with_sponsor(bug, count):
    rowclass = 'bz_row_odd'
    if NEEDSPONSOR in bug['blocks']:
        rowclass = 'bz_state_NEEDSPONSOR'
    elif FEATURE in bug['blocks']:
        rowclass = 'bz_state_FEATURE'
    elif count % 2 == 1:
        rowclass = 'bz_row_even'
    return rowclass

# The data from a standard row in a bug list
def std_row(bug, rowclass):
    return {'id': bug.id,
            'alias': to_unicode(bug.alias),
            'assignee': nobody(to_unicode(bug.assigned_to)),
            'class': rowclass,
            'lastchange': human_time(bug.last_change_time),
            'status': bug.bug_status,
            'summary': to_unicode(bug.short_desc),
            }

# Report generators
def report_hidden(bugs, bugdata, loader, tmpdir, subs):
    data = deepcopy(subs)
    data['description'] = 'This page lists all review tickets are hidden from the main review queues'
    data['title'] = 'Hidden reviews'
    curmonth = ''

    for i in bugs:
        if select_hidden(i, bugdata[i.id]):
            rowclass = rowclass_with_sponsor(bugdata[i.id], data['count'])
            data['bugs'].append(std_row(i, rowclass))
            data['count'] +=1

    write_html(loader, 'plain.html', data, tmpdir, 'HIDDEN.html')

    return data['count']

def report_review(bugs, bugdata, loader, tmpdir, subs):
    data = deepcopy(subs)
    data['description'] = 'This page lists tickets currently under review'
    data['title'] = 'Tickets under review'

    for i in bugs:
        if select_review(i, bugdata[i.id]):
            rowclass = rowclass_plain(data['count'])
            data['bugs'].append(std_row(i, rowclass))
            data['count'] +=1

    write_html(loader, 'plain.html', data, tmpdir, 'REVIEW.html')

    return data['count']

def report_trivial(bugs, bugdata, loader, tmpdir, subs):
    data = deepcopy(subs)
    data['description'] = 'This page lists review tickets marked as trivial'
    data['title'] = 'Trivial reviews'

    for i in bugs:
        if select_trivial(i, bugdata[i.id]):
            rowclass = rowclass_plain(data['count'])
            data['bugs'].append(std_row(i, rowclass))
            data['count'] +=1

    write_html(loader, 'plain.html', data, tmpdir, 'TRIVIAL.html')

    return data['count']

def report_merge(bugs, bugdata, loader, tmpdir, subs):
    data = deepcopy(subs)
    data['description'] = 'This page lists all merge review tickets which need reviewers'
    data['title'] = 'Merge reviews'

    for i in bugs:
        if select_merge(i, bugdata[i.id]):
            rowclass = rowclass_plain(data['count'])
            data['bugs'].append(std_row(i, rowclass))
            data['count'] +=1

    write_html(loader, 'plain.html', data, tmpdir, 'MERGE.html')

    return data['count']

def report_needsponsor(bugs, bugdata, loader, usermap, tmpdir, subs):
    data = deepcopy(subs)
    data['description'] = 'This page lists all new NEEDSPONSOR tickets (those without the fedora-revlew flag set).'
    data['title'] = 'NEEDSPONSOR tickets'
    curreporter = ''
    curcount = 0
    oldest = {}
    selected = []

    for i in bugs:
        if select_needsponsor(i, bugdata[i.id]):
            selected.append(i)

    # Determine the oldest reported bug
    for i in selected:
        if i.reporter not in oldest:
            oldest[i.reporter] = i.creation_time
        elif i.creation_time < oldest[i.reporter]:
            oldest[i.reporter] = i.creation_time

    selected.sort(key=reporter)
    selected.sort(key=lambda a: oldest[a.reporter])

    for i in selected:
        rowclass = rowclass_plain(data['count'])
        r = i.reporter;

        if curreporter != r:
            if (r in usermap and len(usermap[r])):
                name = usermap[r]
            else:
                name = r
            data['packagers'].append({'email': r, 'name': name, 'oldest': human_date(oldest[r]), 'bugs': []})
            curreporter = r
            curcount = 0

        data['packagers'][-1]['bugs'].append(std_row(i, rowclass))
        data['count'] +=1
        curcount +=1

    write_html(loader, 'needsponsor.html', data, tmpdir, 'NEEDSPONSOR.html')

    return data['count']

def report_epel(bugs, bugdata, loader, tmpdir, subs):
    data = deepcopy(subs)
    data['description'] = 'This page lists new, reviewable EPEL package review tickets.  Tickets colored green require a sponsor.'
    data['title'] = 'New EPEL package review tickets'

    curmonth = ''
    curcount = 0

    for i in bugs:
        if select_epel(i, bugdata[i.id]):
            if curmonth != yrmonth(i.creation_time):
                if curcount > 0:
                    data['months'][-1]['month'] += (" (%d)" % curcount)
                data['months'].append({'month': yrmonth(i.creation_time), 'bugs': []})
                curmonth = yrmonth(i.creation_time)
                curcount = 0

            rowclass = rowclass_with_sponsor(bugdata[i.id], curcount)
            data['months'][-1]['bugs'].append(std_row(i, rowclass))
            data['count'] +=1
            curcount +=1

    if curcount > 0:
        data['months'][-1]['month'] += (" (%d)" % curcount)

    write_html(loader, 'bymonth.html', data, tmpdir, 'EPEL.html')

    return data['count']

def report_new(bugs, bugdata, loader, tmpdir, subs):
    data = deepcopy(subs)
    data['description'] = 'This page lists new, reviewable Fedora package review tickets (excluding merge reviews).  Tickets colored green require a sponsor.'
    data['title'] = 'New package review tickets'

    curmonth = ''
    curcount = 0

    for i in bugs:
        if select_new(i, bugdata[i.id]):
            if curmonth != yrmonth(i.creation_time):
                if curcount > 0:
                    data['months'][-1]['month'] += (" (%d)" % curcount)
                data['months'].append({'month': yrmonth(i.creation_time), 'bugs': []})
                curmonth = yrmonth(i.creation_time)
                curcount = 0

            rowclass = rowclass_with_sponsor(bugdata[i.id], curcount)
            data['months'][-1]['bugs'].append(std_row(i, rowclass))
            data['count'] +=1
            curcount +=1

    if curcount > 0:
        data['months'][-1]['month'] += (" (%d)" % curcount)

    write_html(loader, 'bymonth.html', data, tmpdir, 'NEW.html')

    return data['count']

if __name__ == '__main__':
    options = parse_commandline()
    config = parse_config(options.configfile)
    bz = bugzilla.RHBugzilla(url=config['url'], cookiefile=None, user=config['username'], password=config['password'])
    #bz = bugzilla.RHBugzilla(url=config['url'], cookiefile=None)
    t = time.time()
    (bugs, bugdata, usermap) = run_query(bz)
    querytime = time.time() - t

    # Don't bother running this stuff until the query completes, since it fails
    # so often.
    loader = TemplateLoader(options.templdir)
    tmpdir = tempfile.mkdtemp(dir=options.dirname)

    # The initial set of substitutions that's shared between the report functions
    subs = {
            'update': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'querytime': querytime,
            'version': VERSION,
            'count': 0,
            'months': [],
            'packagers': [],
            'bugs': [],
            }
    args = {'bugs':bugs, 'bugdata':bugdata, 'loader':loader, 'tmpdir':tmpdir, 'subs':subs}

    t = time.time()

    subs['new'] =         report_new(**args)
    subs['epel'] =        report_epel(**args)
    subs['hidden'] =      report_hidden(**args)
    subs['merge'] =       report_merge(**args)
    subs['needsponsor'] = report_needsponsor(usermap=usermap, **args)
    subs['review'] =      report_review(**args)
    subs['trivial'] =     report_trivial(**args)
#    data['accepted_closed'] = report_accepted_closed(bugs, bugdata, loader, tmpdir)
#    data['accepted_open'] = report_accepted_open(bugs, bugdata, loader, tmpdir)
#    data['rejected_closed'] = report_rejected_closed(bugs, bugdata, loader, tmpdir)
#    data['rejected_open'] = report_rejected_open(bugs, bugdata, loader, tmpdir)
#    data['review_closed'] = report_review_closed(bugs, bugdata, loader, tmpdir)
#    data['review_open'] = report_review_open(bugs, bugdata, loader, tmpdir)
    subs['outputtime'] = time.time() - t
    write_html(loader, 'index.html', subs, tmpdir, 'index.html')

    for filename in glob.glob(os.path.join(tmpdir, '*')):
        newFilename = os.path.basename(filename)
        os.rename(filename, os.path.join(options.dirname, newFilename))

    os.rmdir(tmpdir)

    sys.exit(0)
