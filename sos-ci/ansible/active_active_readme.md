# solidfire-ci-active-active
# active-active cinder volume services for SolidFire CI

# Create Nova flavor
nova flavor-create ci-test 1337 3072 0 2

# Generate key
ssh-keygen -f id_rsa -b 1024 -P ""

# Add key
nova keypair-add --pub-key ~/.ssh/id_rsa.pub dev

# Retrieve cloud image
wget 192.168.137.1:/var/www/images/trusty-server-cloudimg-amd64-disk1.img ~/

# Load cloud image
glance image-create --name "UbuntuTest" --disk-format qcow2 --container-format bare --file ~/trusty-server-cloudimg-amd64-disk1.img --visibility public --progress

# Kick off primary
ansible-playbook -e "conf=localconf_active_active_master.base instance_name=master result_dir=/home/ubuntu/test_dir" active_active.yml

# Kick off secondary
ansible-playbook -e "conf=localconf_active_active_minion.base instance_name=minion result_dir=/home/ubuntu/test_dir" active_active.yml
