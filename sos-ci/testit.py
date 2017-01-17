#!/usr/bin/python

import os
import sys

import executor


# patchset is of the form 'refs/changes/26/111226/3'
# depends_on is of the form 'openstack/cookbook-openstack-image:master:417834/3'
# results_dir is of the form '/home/user/test-dir'

patchset = str(sys.argv[1])
depends_on = str(sys.argv[2])
results_dir = str(sys.argv[3])

ref_name = patchset.replace('/', '-')

# build the dir
results_dir = results_dir + '/' + ref_name
os.mkdir(results_dir)

(hash_id, success, results) = executor.just_doit(patchset, depends_on, results_dir)
print "hash_id:%s", hash_id
print "success:%s", success
print "result:%s", results
