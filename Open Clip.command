#!/bin/bash
nohup "$(dirname "$0")/bin/clip" "$@" >/dev/null 2>&1 &
