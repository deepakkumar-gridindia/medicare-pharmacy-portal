#!/usr/bin/env bash
set -o errexit

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python3 manage.py collectstatic --no-input
python3 manage.py migrate
