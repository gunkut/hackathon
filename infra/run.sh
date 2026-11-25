#!/bin/bash
# Lambda entry: the Lambda Web Adapter layer forwards HTTP requests (with response streaming) to this server.
export PYTHONPATH=/var/task:${PYTHONPATH}
exec python3 /var/task/ui/server.py
