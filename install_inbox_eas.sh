#!/bin/bash

if [ -d "${INBOX_ROOT}/inbox-eas" ]; then 
    echo "Found inbox-eas, doing development install"
    pip install -r ${INBOX_ROOT}/inbox-eas/requirements.txt
    pip install -e ${INBOX_ROOT}/inbox-eas
else
    echo "No inbox-eas found!"
fi
