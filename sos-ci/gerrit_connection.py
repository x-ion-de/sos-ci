#!/usr/bin/python

import paramiko

def conn(name, account, logger):

        logger.debug('Connecting to gerrit for %(name)s '
                     '%(user)s@%(host)s:%(port)d '
                     'using keyfile %(key_file)s',
                     {'name': name,
                      'user': account['ci_account'],
                      'host': account['gerrit_host'],
                      'port': int(account['gerrit_port']),
                      'key_file': account['gerrit_ssh_key']})

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connected = False
        while not connected:
            try:
                ssh.connect(account['gerrit_host'],
                            int(account['gerrit_port']),
                            account['ci_account'],
                            key_filename=account['gerrit_ssh_key'])
                connected = True
            except paramiko.SSHException as e:
                logger.error('%s', e)
                logger.warn('Gerrit may be down, will pause and retry...')
                time.sleep(30)

        return ssh
