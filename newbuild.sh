#!/bin/bash 
[[ ! -d $BUILDPATH/usr/lib/python2.6/site-packages ]] && mkdir -p $BUILDPATH/usr/lib/python2.6/site-packages
python setup.py build #--release $REVISION --changelog="$CHANGELOG"
python setup.py install --skip-build --root $BUILDPATH --install-lib=$BUILDPATH/usr/lib/python2.6/site-packages
