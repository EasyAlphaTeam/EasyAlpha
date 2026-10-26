#!/usr/bin/env bash

set -e
set -x

coverage run -m pytest tests/ tests_auth/
coverage report
coverage html --title "${@-coverage}"
