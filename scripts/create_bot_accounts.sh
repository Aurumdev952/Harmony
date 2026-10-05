#!/bin/bash

pushd $(dirname $0) &>/dev/null

./create_user.py --automation_user

popd &> /dev/null
