#!/usr/bin/python

from email.mime.text import MIMEText
from collections import deque
import json
from optparse import OptionParser
import os
import pprint
import re
import shutil
import subprocess
import sys
from threading import Thread
import time
from yaml import load

import executor
import gerrit_connection
import log

fdir = os.path.dirname(os.path.realpath(__file__))
conf_dir = os.path.dirname(fdir)
with open(conf_dir + '/sos-ci.yaml') as stream:
    cfg = load(stream)

# Misc settings
DATA_DIR =\
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/data'
if cfg['Data']['data_dir']:
    DATA_DIR = cfg['Data']['data_dir']

logger = log.setup_logger(DATA_DIR + '/os-ci.log')
event_queue = deque()
pipeline = deque()


class InstanceBuildException(Exception):
    def __init__(self, message):
        Exception.__init__(self, message)


def _is_my_ci_recheck(event):
    if (event.get('type', 'nill') == 'comment-added' and
            cfg['AccountInfo']['recheck_string'] in event['comment'] and
            event['change']['project'] in cfg['AccountInfo']['project_names'] and
            event['change']['branch'] == 'master'):
        logger.info('Detected recheck request for event: %s', event)
        return True
    return False


def _is_my_ci_master(event):
    if (event.get('type', 'nill') == 'comment-added' and
            'Verified+1' in event['comment'] and
            event['change']['project'] in cfg['AccountInfo']['project_names'] and
            event['author']['username'] == 'jenkins' and
            event['change']['branch'] == 'master'):
        logger.info('Detected valid event: %s', event)
        return True
    return False

# Note(jrosenboom): shamelessly copied from zuul.connection.gerrit
depends_on_re = re.compile(r"^Depends-On: (I[0-9a-f]{40})\s*$",
                               re.MULTILINE | re.IGNORECASE)

def _get_depends(event):
    records = "%(project)s:%(branch)s:%(id)s/%(patchset)s" % {
               'project': event['change']['project'],
               'branch': event['change']['branch'],
               'id': event['change']['number'],
               'patchset': event['patchSet']['number']}
    seen = set()
    with gerrit_connection.conn('query', cfg['AccountInfo'], logger) as conn:
        for match in depends_on_re.findall(event['change']['commitMessage']):
            if match in seen:
                logger.debug("Ignoring duplicate Depends-On: %s" %
                               (match,))
                continue
            seen.add(match)
            query = "change:%s" % (match,)
            logger.debug("Updating %s: Running query %s "
                         "to find needed changes" %
                         (event['change']['number'], query,))
            args = '--commit-message --current-patch-set'
            cmd = 'gerrit query --format json %s %s' % (args, query)
            try:
                inp, out, err = conn.exec_command(cmd)
                lines = out.read().split('\n')
                data = [json.loads(line) for line in lines
                        if line.startswith('{')]
                if data:
                    logger.debug("Received data from Gerrit query: \n%s" %
                                 (pprint.pformat(data)))
                    del data[-1]
                    for d in data:
                        ref = "%(project)s:%(branch)s:%(id)s/%(patchset)s^" % {
                               'project': d['project'],
                               'branch': d['branch'],
                               'id': d['number'],
                               'patchset': d['currentPatchSet']['number']}
                        logger.debug("Ref: %s" % ref)
                        records = ref + records
            except:
                e = sys.exc_info()[0]
                logger.error("Error while querying gerrit: %s" % e)
                raise

    return records

def _filter_ci_events(event):
    if _is_my_ci_recheck(event) or _is_my_ci_master(event):
        event['dependsOn'] = _get_depends(event)

        logger.info('Adding review id %s to job queue...' %
                    event['change']['number'])

        # One log to act as a data store, and another just to look at
        with open(DATA_DIR + '/valid-event.log', 'a') as f:
            json.dump(event, f)
            f.write('\n')
        with open(DATA_DIR + '/pretty-event.log', 'a') as f:
            json.dump(event, f, indent=2)
        return event
    else:
        return None


def _send_notification_email(subject, msg):
    if cfg['Email']['enable_notifications']:
        msg = MIMEText(msg)
        msg["From"] = cfg['Email']['from_address']
        msg["To"] = cfg['Email']['to_address']
        msg["Subject"] = subject
        p = subprocess.Popen(["/usr/sbin/sendmail", "-t"],
                             stdin=subprocess.PIPE)
        p.communicate(msg.as_string())


class JobThread(Thread):
    """ Thread to process the gerrit events. """

    def _post_results_to_gerrit(self, log_location, passed, commit_id):
        logger.debug("Post results to gerrit using %(location)s\n "
                     "passed: %(passed)s\n commit_id: %(commit_id)s\n",
                     {'location': log_location,
                      'passed': passed,
                      'commit_id': commit_id})

        cmd = "gerrit review -m "
        subject = ''
        msg = ''
        logger.debug('Building gerrit review message...')
        msg = 'Commit: %s\nLogs: %s\n' % (commit_id, log_location)
        if passed:
            subject += " %s SUCCESS" % cfg['AccountInfo']['ci_name']
            msg += "Result: SUCCESS"
            cmd += """"* %s %s : SUCCESS " %s""" % \
                   (cfg['AccountInfo']['ci_name'], log_location, commit_id)
            logger.debug("Created success cmd: %s", cmd)
        else:
            subject += " %s FAILED" % cfg['AccountInfo']['ci_name']
            msg += "Result: FAILED"
            cmd += """"* %s %s : FAILURE " %s""" % \
                   (cfg['AccountInfo']['ci_name'], log_location, commit_id)
            logger.debug("Created failed cmd: %s", cmd)

        logger.debug('Issue notification email, '
                     'Subject: %(subject)s, %(msg)s',
                     {'subject': subject, 'msg': msg})

        _send_notification_email(subject, msg)

        ssh = gerrit_connection.conn('voting', cfg['AccountInfo'], logger)

        logger.info('Issue vote: %s', cmd)
        stdin, stdout, stderr = ssh.exec_command(cmd)

    def _run_subunit2sql(self, results_dir, ref_name):
        if not cfg['DataBase']['enable_subunit2sql']:
            logger.info('DataBase.enable_subunit2sql is not enabled, '
                        'skipping data base operations')
            return

        subunit_file = results_dir + '/' + ref_name + '/testrepository.subunit'
        cmd = 'subunit2sql --database-connection %s %s' % \
            (cfg['DataBase']['database_connection_string'], subunit_file)
        subunit2sql_proc = subprocess.Popen(cmd,
                                            shell=True,
                                            stdout=subprocess.PIPE)
        output = subunit2sql_proc.communicate()[0]
        logger.debug('Response from subunit2sql: %s', output)
        return

    def run(self):
        counter = 60
        while True:
            counter -= 1
            if not event_queue:
                time.sleep(60)
            else:
                event = event_queue.popleft()
                logger.debug("Processing event from queue:\n%s", event)

                # Add a goofy pipeline queue so we know
                # not only when nothing is in the queue
                # but when nothings outstanding so we can
                # run cleanup on the backend device
                pipeline.append(valid_event)

                # Launch instance, run tempest etc etc etc
                patchset_ref = event['patchSet']['ref']
                depends_on = event.get('dependsOn')
                revision = event['patchSet']['revision']
                logger.debug('Grabbed revision from event: %s', revision)

                ref_name = patchset_ref.replace('/', '-')
                results_dir = DATA_DIR + '/' + ref_name

                # This might be a recheck, if so we've presumably
                # run things once and published, so delete the
                # local copy and run it again
                if os.path.isdir(results_dir):
                    shutil.rmtree(results_dir)
                os.mkdir(results_dir)

                commit_id = revision

                try:
                    success, output = \
                        executor.just_doit(patchset_ref, depends_on,
                                           results_dir)
                    logger.info('Completed just_doit: %(commit)s, '
                                '%(success)s, %(output)s',
                                {'commit': commit_id,
                                 'success': success,
                                 'output': output})

                except InstanceBuildException:
                    logger.error('Received InstanceBuildException...')
                    pass

                logger.info("Completed %s", cfg['AccountInfo']['ci_name'])
                url_name = patchset_ref.replace('/', '-')
                log_location = cfg['Logs']['log_dir'] + '/' + url_name
                self._post_results_to_gerrit(log_location, success, commit_id)
                #self._run_subunit2sql(results_dir, ref_name)

                try:
                    pipeline.remove(valid_event)
                except ValueError:
                    pass


class GerritEventStream(object):
    def __init__(self, *args, **kwargs):
        self.ssh = gerrit_connection.conn('stream-events', cfg['AccountInfo'], logger)

        self.stdin, self.stdout, self.stderr =\
            self.ssh.exec_command("gerrit stream-events")

    def __iter__(self):
        return self

    def next(self):
        return self.stdout.readline()


def process_options():
    usage = "usage: %prog [options]\nos_ci.py."
    parser = OptionParser(usage, version='%prog 0.1')

    parser.add_option('-n', '--num-threads', action='store',
                      type='int',
                      default=3,
                      dest='number_of_worker_threads',
                      help='Number of job threads to run (default = 3).')
    parser.add_option('-m', action='store_true',
                      dest='event_monitor_only',
                      help='Just monitor Gerrit stream, dont process events.')
    (options, args) = parser.parse_args()
    return options


if __name__ == '__main__':
    event_queue = deque()
    options = process_options()

    for i in xrange(options.number_of_worker_threads):
        JobThread().start()

    while True:
        events = []
        try:
            events = GerritEventStream(cfg['AccountInfo']['ci_name'])
        except Exception as ex:
            logger.exception('Error connecting to Gerrit: %s', ex)
            time.sleep(60)
            pass

        for event in events:
            try:
                event = json.loads(event)
            except Exception as ex:
                logger.error('Failed json.loads on event: %s', event)
                logger.exception(ex)
                break
            with open(DATA_DIR + '/received-events.log', 'a') as f:
                json.dump(event, f)
                f.write('\n')
            valid_event = _filter_ci_events(event)
            if valid_event:
                logger.debug('Identified valid event, sending to queue...')
                if not options.event_monitor_only:
                    logger.debug("Adding event to queue:%s\n", valid_event)
                    event_queue.append(valid_event)
