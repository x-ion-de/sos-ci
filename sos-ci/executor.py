import os
import subprocess

import log

from yaml import load

fdir = os.path.dirname(os.path.realpath(__file__))
conf_dir = os.path.dirname(fdir)
with open(conf_dir + '/sos-ci.yaml') as stream:
    cfg = load(stream)

""" EZ-PZ just call our ansible playbook.

Would be great to write a playbook runner at some point, but
this is super straight forward and it works so we'll use it for now.

"""


def just_doit(patchset_ref, results_dir):
    """ Do the dirty work, or let ansible do it. """

    ref_name = patchset_ref.replace('/', '-')
    logger = log.setup_logger(results_dir + '/ansible.out')
    logger.debug('Attempting ansible tasks on ref-name: %s', ref_name)
    vars = "instance_name=%s" % (ref_name)
    vars += " patchset_ref=%s" % patchset_ref
    vars += " results_dir=%s" % results_dir
    cmd = 'ansible-playbook --extra-vars '\
          '\"%s\" %s/run_ci.yml' % (vars, cfg['Ansible']['ansible_dir'])

    logger.debug('Running ansible run_ci command: %s', cmd)
    ansible_proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    output = ansible_proc.communicate()[0]
    logger.debug('Response from ansible: %s', output)

    vars = "ref_name=%s" % (ref_name)
    vars += " results_dir=%s" % results_dir
    cmd = 'ansible-playbook --extra-vars '\
          '\"%s\" %s/publish.yml' % (vars, cfg['Ansible']['ansible_dir'])
    logger.debug('Running ansible publish command: %s', cmd)

    # This output is actually the ansible output
    # should fix this up and have it just return the status
    # and the tempest log that we xfrd over
    ansible_proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    output += ansible_proc.communicate()[0]
    logger.debug('Response from ansible: %s', output)

    success = False
    hash_id = None
    console_log = results_dir + '/' + 'console.log.out'
    logger.debug('Looking for console log at: %s', console_log)
    if os.path.isfile(console_log):
        logger.debug('Found the console log...')
        if 'Failed: 0' in open(console_log).read():
            logger.debug('Evaluated run as successful')
            success = True

        logger.info('Status from console logs: %s', success)
        # We grab the abbreviated sha from the first line of the
        # console.out file
        with open(console_log) as f:
            first_line = f.readline()
        print "Attempting to parse: %s" % first_line
        hash_id = first_line.split()[1]

    # Finally, delete the instance regardless of pass/fail
    # NOTE it's moved out of tasks here otherwise it won't
    # run if preceeded by a failure
    vars = "instance_name=%s" % (ref_name)
    vars += " patchset_ref=%s" % patchset_ref
    cmd = 'ansible-playbook --extra-vars '\
          '\"%s\" %s/teardown.yml' % (vars, cfg['Ansible']['ansible_dir'])

    logger.debug('Running ansible teardown command: %s', cmd)
    ansible_proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    output += ansible_proc.communicate()[0]

    return (hash_id, success, output)
