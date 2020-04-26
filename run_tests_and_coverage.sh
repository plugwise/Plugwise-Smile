#!/bin/sh
echo "-----------------------------------------------------------"
echo "Running Plugwise/Smile.py through pytest including coverage"
echo "-----------------------------------------------------------"
PYTHONPATH=`pwd` pytest -rpP tests/test_Smile.py --cov='.'
pytest=`echo $?`
echo "-----------------------------------------------------------------"
echo "Running Plugwise/Smile.py through pylint (HA-core + own disables)"
echo "-----------------------------------------------------------------"
PYTHONPATH=`pwd` pylint --rcfile=pylintrc Plugwise_Smile/Smile.py
pylint=`echo $?`
echo "-----------------------------------------------------------------"
echo "pytest exit code: ${pytest}"
echo "pylint exit code: ${pylint}"
