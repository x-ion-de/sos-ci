#!/bin/bash
GIT_BASE=git://git.openstack.org

echo Dependencies are: $depends_on

# Split dependencies at "^"
dependencies=(${depends_on//^/ })

# Clone dependencies
for info in "${dependencies[@]}"; do
  # Split info at ":"
  parts=(${info//:/ })
  repo=${parts[0]}
  short_repo=$(basename $repo)
  branch=${parts[1]}
  # Split last part at "/"
  ids=(${parts[2]//// })
  change_id=${ids[0]}
  ps_num=${ids[1]}

  git clone $GIT_BASE/$repo
  pushd $short_repo
  git checkout $branch
  git fetch origin refs/changes/${change_id: -2}/$change_id/$ps_num
  git checkout FETCH_HEAD
  popd
done

