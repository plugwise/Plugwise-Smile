# To be detailed

Basically make sure you pip -r requirements.txt install

Tests should be included in .github/actions later on but you can also run them

python3 -m pytest -rpP tests/test_Smile.py

# Directories

Intended:

 - [x] p1v3 => A P1 v3 with only electricity
 - [x] p1v3solarfake => Same one as above but using fake data -> who's willing to share actual?
 - [ ] p1v3solargas - looking for someone with solar & gas included as well
 - [ ] p1v3gas - looking for someone with electricity and gas
 - [x] smile_p1_v2 => A P1 v2.5
 - [ ] adam => An Adam setup with a boiler, Floor, Koen, Plug, Tom and Lisa (i.e. the whole shebang)
 - [x] adam_living_floor_plus_3_rooms => An Adam setup with a boiler, Floor, Lisa and 3x Toms
 - [ ] adam_without_boiler => An Adam setup without a boiler, but with Lisa and either a Plug or a Tom
 - [ ] anna => An Anna setup with a boiler
 - [x] anna_without_boiler => Just an Anna (i.e. attached to city heating)
 - [x] anna_legacy => An Anna setup with a boiler, but legacy firmware

If you see an unchecked item and feel your setup fits in, please **MAIL** one of the authors the output of the below links. Feel free to create a PR if you follow the below privacy hint:

They should al start with `<xml` and copied as plain text (i.e. not preformatted like Chrome and Safari do).
Either use wget/curl or use your 'developer view' from your browser to copy the source text
 
```
http://{ip_of_your_smile}/core/appliances
http://{ip_of_your_smile}/core/direct_objects
http://{ip_of_your_smile}/core/domain_objects
http://{ip_of_your_smile}/core/locations
http://{ip_of_your_smile}/core/modules
```

# Important

Don't commit test-data in `tests/anna` or `tests/adam` that shouldn't be available to 'the internet'.
To prevent this we've included a pre-commit hook that checks and validates that no private information is there (but do double-check yourselves!)
See 'pre-commit.sh' for details

Excerpt:

 - [ ] modify `domain_objects` and `modules` and set all occurances of `mac-address` to `0123456789AB`
 - [ ] modify `domain_objects` and set `short_id` to `abcdefgh`
 - [ ] modify `domain_objects` and set `wifi_ip` to `127.0.0.1`
 - [ ] modify `domain_objects` and set `lan_ip` to `127.0.0.1`
 - [ ] modify `domain_objects` and set all `ip_addresses` to `127.0.0.1`
 - [ ] modify `domain_objects` and set `hostname` to `smile000000`
 - [ ] modify `domain_objects` and set `longitude` to `4.49`
 - [ ] modify `domain_objects` and set `latitude` to `52.21`
 - [ ] modify `domain_objects` and set `city` to `Sassenheim`
 - [ ] modify `domain_objects` and set `postal_code` to `2171`


