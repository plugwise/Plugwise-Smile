#!/bin/sh
PYTHONPATH=`pwd` pytest -rpP tests/test_Smile.py --cov='.'
