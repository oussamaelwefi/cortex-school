#!/bin/sh
set -e

if [ -f /secrets/.env ]; then
  set -a && . /secrets/.env && set +a
fi

pip install -q -r requirements.txt
exec uvicorn main:app --host 0.0.0.0 --port 9000 --reload
