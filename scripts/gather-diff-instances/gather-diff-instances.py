#!/usr/bin/python
# skvidal
# fedoraproject.org -
# run the json outputter
# output to /var/log/instance-lists/timestamp
# compare newest one to the last one
# mail results to mailto, if any
# ignore instances with a key_name in blacklist


destdir='/var/log/instance-lists/'
mailto='admin@fedoraproject.org'
blacklist=['buildsys']  


import sys
import time
import json
import glob
import os
import smtplib
from email.MIMEText import MIMEText

from nova import context
from nova import db
from nova import flags



def list_vms(host=None):
    """
      make a list of vms and expand out their fixed_ip and floating ips sensibly
    """
    flags.parse_args([])
    my_instances  = []
    if host is None:
        instances = db.instance_get_all(context.get_admin_context())
    else:
        instances = db.instance_get_all_by_host(
                      context.get_admin_context(), host)

    for instance in instances:
        my_inst = {}
        my_inst = dict(instance).copy()
        for (k,v) in my_inst.items():
            try:
                json.encoder(v)
            except TypeError, e:
                v = str(v)
                my_inst[k] = v

        ec2_id = db.get_ec2_instance_id_by_uuid(context.get_admin_context(), instance.uuid)
        ec2_id = 'i-' + hex(int(ec2_id)).replace('0x', '').zfill(8)
        my_inst['ec2_id'] = ec2_id
        try:
                fixed_ips = db.fixed_ip_get_by_instance(context.get_admin_context(), instance.uuid)
        except:
                pass
        my_inst['fixed_ips'] = [ ip.address for ip in fixed_ips ]
        my_inst['floating_ips'] = []
        for ip in fixed_ips:
            my_inst['floating_ips'].extend([ f_ip.address for f_ip in db.floating_ip_get_by_fixed_address(context.get_admin_context(), ip.address)])

        my_instances.append(my_inst)
    return my_instances



def diff_instances(old, new):
    """ 
        Take 2 lists of instances @old, @new
        diff them and return a list of strings citing changes.
    """
    old_uuids = {}
    new_uuids = {}
    for vm in old:
        old_uuids[vm['uuid']] = vm

    for vm in new:
        new_uuids[vm['uuid']] = vm

    uuids = set(new_uuids.keys() + old_uuids.keys())
    ret = []
    ret_added = []
    ret_removed = []
    removed = []
    added = []
    for uuid in sorted(uuids):
        if uuid not in new_uuids:
            vm = old_uuids[uuid]
            removed.append(vm)
   
        elif uuid not in old_uuids:
            vm = new_uuids[uuid]
            added.append(vm)
   

        else:
            old_vm = old_uuids[uuid]
            new_vm = new_uuids[uuid]
            changed = []
            for k,v in old_vm.items():
                if v != new_vm.get(k, 'NOT_A_MATCH'):
                   changed.append(k)
            if changed:
                ret.append('Changes to: %s' % uuid)
                for k in changed:
                    ret.append("   %s changed from '%s' to '%s'" % (k, old_vm[k], new_vm[k]))

    for vm in added:
        if vm['key_name'] not in blacklist:
            ret_added.append('  %s %s %s %s' % (uuid, vm['display_name'], vm['floating_ips'][0], vm['key_name']))
    if ret_added:
        ret_added[:0].append('Instance(s) Added:\n')

    for vm in removed:
        if vm['floating_ips'][0] and (vm['key_name'] not in blacklist):
            ret_removed.append('  %s %s %s %s' % (uuid, vm['display_name'], vm['floating_ips'][0], vm['key_name'])) 
    if ret_removed:
        ret_removed[:0].append('Instance(s) Removed:\n')   

    ret = ret + ret_added + ret_removed
    return ret



def email(to, subject, text):
    """
       send email
    """
    mail_from = 'cloudadmin@fedoraproject.org'
    mail_to = '%s' % to

    output = text

    msg = MIMEText(output)
    msg['Subject'] = subject
    msg['From'] = mail_from
    msg['To'] = mail_to
    s = smtplib.SMTP()
    s.connect()
    s.sendmail(mail_from, [mail_to], msg.as_string())
    s.close()


def main():
    if not os.path.exists(destdir):
        os.makedirs(destdir)
    

    # get the instances list
    new_instances = list_vms()
    now=time.strftime('%Y-%m-%d-%H:%M.json')
    f = open(destdir + '/' + now, 'w')
    f.write(json.dumps(new_instances))
    f.close()

    # get the last one
    fns = [fn for fn in glob.glob(destdir + '/*.json') ]
    if len(fns) < 2:
        return

    last = sorted(fns)[-2]
    old_instances = json.load(open(last))
    res = diff_instances(old_instances, new_instances)

    if res:
        email(mailto, "Changes to cloud instances", '\n'.join(res))
                   

if __name__ == "__main__":
    main()
    
