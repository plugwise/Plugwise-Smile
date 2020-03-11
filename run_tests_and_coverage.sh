#!/bin/sh
PYTHONPATH=`pwd` coverage run --source=. -m pytest -rpP tests/test_Smile.py
