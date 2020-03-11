# To be detailed

Basically make sure you pip -r requirements.txt install

Tests should be included in .github/actions later on but you can also run them

python3 -m pytest -rpP tests/test_Smile.py

# Important

Don't commit test-data in `tests/anna` or `tests/adam` that shouldn't be available to 'the internet'.
To prevent this we've included a pre-commit hook that checks and validates that no private information is there (but do double-check yourselves!)
See 'pre-commit.sh' for details

