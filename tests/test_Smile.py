"""Plugwise Home Assistant module."""

import asyncio
import os
from pprint import PrettyPrinter

import aiohttp
import codecov
import pytest
import pytest_aiohttp
import pytest_asyncio
from lxml import etree

from Plugwise_Smile.Smile import Smile

pp = PrettyPrinter(indent=8)

# Prepare aiohttp app routes
# taking smile_setup (i.e. directory name under tests/{smile_app}/
# as inclusion point
async def setup_app():
    global smile_setup
    if not smile_setup:
        return False
    app = aiohttp.web.Application()
    app.router.add_get("/core/appliances", smile_appliances)
    app.router.add_get("/core/direct_objects", smile_direct_objects)
    app.router.add_get("/core/domain_objects", smile_domain_objects)
    app.router.add_get("/core/locations", smile_locations)
    app.router.add_get("/core/modules", smile_modules)

    app.router.add_route("PUT", "/core/locations{tail:.*}", smile_set_temp_or_preset)
    app.router.add_route("PUT", "/core/rules{tail:.*}", smile_set_schedule)
    app.router.add_route("PUT", "/core/appliances{tail:.*}", smile_set_relay)
    return app


# Wrapper for appliances uri
async def smile_appliances(request):
    global smile_setup
    f = open("tests/{}/core.appliances.xml".format(smile_setup), "r")
    data = f.read()
    f.close()
    return aiohttp.web.Response(text=data)


async def smile_direct_objects(request):
    global smile_setup
    f = open("tests/{}/core.direct_objects.xml".format(smile_setup), "r")
    data = f.read()
    f.close()
    return aiohttp.web.Response(text=data)


async def smile_domain_objects(request):
    global smile_setup
    f = open("tests/{}/core.domain_objects.xml".format(smile_setup), "r")
    data = f.read()
    f.close()
    return aiohttp.web.Response(text=data)


async def smile_locations(request):
    global smile_setup
    f = open("tests/{}/core.locations.xml".format(smile_setup), "r")
    data = f.read()
    f.close()
    return aiohttp.web.Response(text=data)


async def smile_modules(request):
    global smile_setup
    f = open("tests/{}/core.modules.xml".format(smile_setup), "r")
    data = f.read()
    f.close()
    return aiohttp.web.Response(text=data)


async def smile_set_temp_or_preset(request):
    text = "<xml />"
    raise aiohttp.web.HTTPAccepted(text=text)


async def smile_set_schedule(request):
    text = "<xml />"
    raise aiohttp.web.HTTPAccepted(text=text)


async def smile_set_relay(request):
    text = "<xml />"
    raise aiohttp.web.HTTPAccepted(text=text)


"""
# 20200312 - somehow this broke testing using travis today
#            with no obvious clue why loop_factory issues
#            were involved out of the blue, commented out for now

# Test if at least modules functions before going further
# note that this only tests the modules-app for functionality
# if this fails, none of the actual tests against the Smile library
# will function correctly
async def test_mock(aiohttp_client, loop):
    global smile_setup
    smile_setup = 'anna_without_boiler'
    app = aiohttp.web.Application()
    app.router.add_get('/core/modules',smile_modules)
    app.router.add_route('PUT', '/core/locations{tail:.*}', smile_set_temp_or_preset)
    client = await aiohttp_client(app)

    resp = await client.get('/core/modules')
    assert resp.status == 200
    text = await resp.text()
    assert 'xml' in text

    resp = await client.put('/core/locations;id=bla')
    assert resp.status == 202
"""

# Generic connect
@pytest.mark.asyncio
async def connect():
    global smile_setup
    if not smile_setup:
        return False
    port = aiohttp.test_utils.unused_port()

    app = await setup_app()

    server = aiohttp.test_utils.TestServer(
        app, port=port, scheme="http", host="127.0.0.1"
    )
    await server.start_server()

    client = aiohttp.test_utils.TestClient(server)
    websession = client.session

    url = "{}://{}:{}/core/modules".format(server.scheme, server.host, server.port)
    resp = await websession.get(url)
    assert resp.status == 200
    text = await resp.text()
    assert "xml" in text
    try:
        assert "<vendor_name>Plugwise</vendor_name>" in text
    except:
        # P1 v2 exception handling
        assert "<dsmrmain id" in text
        pass

    smile = Smile(
        host=server.host,
        password="abcdefgh",
        port=server.port,
        websession=websession,
        sleeptime=0,
    )
    assert smile._timeout == 20
    assert smile._domain_objects is None
    assert smile._smile_type is None

    """Connect to the smile"""
    connection = await smile.connect()
    assert connection is True
    assert smile._smile_type is not None
    return server, smile, client


# GEneric list_devices
@pytest.mark.asyncio
async def list_devices(server, smile):
    device_list = {}
    devices = await smile.get_all_devices()
    return devices
    ctrl_id = None
    plug_id = None
    ##for dev in devices:
    ##    if dev['name'] == 'Controlled Device':
    ##        ctrl_id = dev['id']
    ##    if dev['name'] == 'Home' and smile._smile_type == 'power':
    ##        ctrl_id = dev['id']
    for device, details in devices.items():
        # Detect home
        if "home" in details["type"]:
            ctrl_id = device
        elif "plug" in details["type"]:
            plug_id = device

        device_list[device] = {
            "name": details["name"],
            "type": details["type"],
            "ctrl": ctrl_id,
            "plug": plug_id,
            "location": details["location"],
        }

    return device_list


# Generic disconnect
@pytest.mark.asyncio
async def disconnect(server, client):
    if not server:
        return False
    await client.session.close()
    await server.close()


def show_setup(location_list, device_list):
    print("This smile looks like:")
    for loc_id, loc_info in location_list.items():
        pp = PrettyPrinter(indent=4)
        print("  --> Location: {} ({})".format(loc_info["name"], loc_id))
        for dev_id, dev_info in device_list.items():
            if dev_info["location"] == loc_id:
                print("      + Device: {} ({})".format(dev_info["name"], dev_id))


@pytest.mark.asyncio
async def test_device(smile=Smile, testdata={}):
    global smile_setup
    if testdata == {}:
        return False

    print("Asserting testdata:")
    device_list = smile.get_all_devices()
    location_list, home = smile.match_locations()

    show_setup(location_list, device_list)
    if True:
        print("Device list: %s", device_list)
        for dev_id, details in device_list.items():
            data = smile.get_device_data(dev_id)
            print("Device {} / {} data: {}".format(dev_id, details, data))

    for testdevice, measurements in testdata.items():
        for dev_id, details in device_list.items():
            if testdevice == dev_id:
                data = smile.get_device_data(dev_id)
                print(
                    "- Testing data for device {} ({})".format(details["name"], dev_id)
                )
                for measure_key, measure_assert in measurements.items():
                    print(
                        "  + Testing {} (should be {})".format(
                            measure_key, measure_assert
                        )
                    )
                    assert data[measure_key] == measure_assert


@pytest.mark.asyncio
async def tinker_relay(smile, dev_ids=[]):
    global smile_setup
    if not smile_setup:
        return False

    print("Asserting modifying settings for relay devices:")
    for dev_id in dev_ids:
        print("- Devices ({}):".format(dev_id))
        for new_state in ["off", "on", "off"]:
            print("- Switching {}".format(new_state))
            relay_change = await smile.set_relay_state(dev_id, new_state)
            assert relay_change == True


@pytest.mark.asyncio
async def tinker_thermostat(smile, loc_id, good_schemas=["Weekschema"]):
    global smile_setup
    if not smile_setup:
        return False

    print("Asserting modifying settings in location ({}):".format(loc_id))
    for new_temp in [20.0, 22.9]:
        print("- Adjusting temperature to {}".format(new_temp))
        temp_change = await smile.set_temperature(loc_id, new_temp)
        assert temp_change == True

    for new_preset in ["asleep", "home", "!bogus"]:
        assert_state = True
        warning = ""
        if new_preset[0] == "!":
            assert_state = False
            warning = " Negative test"
            new_preset = new_preset[1:]
        print("- Adjusting preset to {}{}".format(new_preset, warning))
        preset_change = await smile.set_preset(loc_id, new_preset)
        assert preset_change == assert_state

    if good_schemas is not []:
        good_schemas.append("!VeryBogusSchemaNameThatNobodyEverUsesOrShouldUse")
        for new_schema in good_schemas:
            assert_state = True
            warning = ""
            if new_schema[0] == "!":
                assert_state = False
                warning = " Negative test"
                new_schema = new_schema[1:]
            print("- Adjusting schedule to {}{}".format(new_schema, warning))
            schema_change = await smile.set_schedule_state(loc_id, new_schema, "auto")
            assert schema_change == assert_state
    else:
        print("- Skipping schema adjustments")


# Actual test for directory 'Anna' legacy
@pytest.mark.asyncio
async def test_connect_legacy_anna():
    # testdata is a dictionary with key ctrl_id_dev_id => keys:values
    # testdata={
    #             'ctrl_id': { 'outdoor+temp': 20.0, }
    #             'ctrl_id:dev_id': { 'type': 'thermostat', 'battery': None, }
    #         }
    testdata = {
        # Anna
        "7ffbb3ab4b6c4ab2915d7510f7bf8fe9": {
            "selected_schedule": "Normal",
            "illuminance": 35.0,
            "active_preset": "away",
        },
        # Gateway
        "a270735e4ccd45239424badc0578a2b1": {"outdoor_temperature": 10.8,},
        # Central-heater
        "c46b4794d28149699eacf053deedd003": {"central_heating_state": "off"},
    }
    global smile_setup
    smile_setup = "legacy_anna"
    server, smile, client = await connect()
    assert smile._smile_type == "thermostat"
    assert smile._smile_version[0] == "1.8.0"
    assert smile._smile_legacy == True
    await test_device(smile, testdata)
    # TODO looks like 'legacy_anna' has no schemas defined
    # check and/or create new test data from one that has
    await tinker_thermostat(
        smile, "c34c6864216446528e95d88985e714cc", good_schemas=[],
    )
    await smile.close_connection()
    await disconnect(server, client)


# Actual test for directory 'P1' v2
@pytest.mark.asyncio
async def test_connect_smile_p1_v2():
    # testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata = {
        # Gateway / P1 itself
        "938696c4bcdb4b8a9a595cb38ed43913": {
            "electricity_consumed_peak_point": 458.0,
            "net_electricity_point": 458.0,
            "gas_consumed_peak_cumulative": 584.433,
            "electricity_produced_peak_cumulative": 1296136.0,
        }
    }
    global smile_setup
    smile_setup = "smile_p1_v2"
    server, smile, client = await connect()
    assert smile._smile_type == "power"
    assert smile._smile_version[0] == "2.5.9"
    assert smile._smile_legacy == True
    await test_device(smile, testdata)
    await test_device(smile, testdata)
    await smile.close_connection()
    await disconnect(server, client)

    await smile.close_connection()
    await disconnect(server, client)


# Actual test for directory 'Anna' without a boiler
@pytest.mark.asyncio
async def test_connect_anna_without_boiler():
    # testdata is a dictionary with key ctrl_id_dev_id => keys:values
    # testdata={
    #             'ctrl_id': { 'outdoor+temp': 20.0, }
    #             'ctrl_id:dev_id': { 'type': 'thermostat', 'battery': None, }
    #         }
    testdata = {
        # Anna
        "7ffbb3ab4b6c4ab2915d7510f7bf8fe9": {
            "selected_schedule": "Normal",
            "illuminance": 35.0,
            "active_preset": "away",
        },
        # Gateway
        "a270735e4ccd45239424badc0578a2b1": {"outdoor_temperature": 10.8,},
        # Central-heater
        "c46b4794d28149699eacf053deedd003": {"central_heating_state": "off"},
    }
    global smile_setup
    smile_setup = "anna_without_boiler"
    server, smile, client = await connect()
    assert smile._smile_type == "thermostat"
    assert smile._smile_version[0] == "3.1.11"
    assert smile._smile_legacy == False
    await test_device(smile, testdata)
    await tinker_thermostat(
        smile, "c34c6864216446528e95d88985e714cc", good_schemas=["Test", "Normal"]
    )
    await smile.close_connection()
    await disconnect(server, client)


"""

# Actual test for directory 'Adam'
# living room floor radiator valve and separate zone thermostat
# an three rooms with conventional radiators
@pytest.mark.asyncio
async def test_connect_adam():
    global smile_setup
    smile_setup = 'adam_living_floor_plus_3_rooms'
    server,smile,client = await connect()
    device_list = await list_devices(server,smile)
    #assert smile._smile_type == 'thermostat'
    print(device_list)
    #testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata={}
    for dev_id,details in device_list.items():
        data = smile.get_device_data(dev_id, details['ctrl'], details['plug'])
        test_id = '{}_{}'.format(details['ctrl'],dev_id)
        #if test_id not in testdata:
        #    continue
        print(data)

    await smile.close_connection()
    await disconnect(server,client)

"""

# Actual test for directory 'Adam + Anna'
@pytest.mark.asyncio
async def test_connect_adam_plus_anna():
    # testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata = {
        # Anna
        "ee62cad889f94e8ca3d09021f03a660b": {
            "selected_schedule": "Weekschema",
            "last_used": "Weekschema",
            "illuminance": None,
            "active_preset": "home",
            "thermostat": 20.5,  # HA setpoint_temp
            "temperature": 20.46,  # HA current_temp
        },
        # Gateway
        "b128b4bbbd1f47e9bf4d756e8fb5ee94": {"outdoor_temperature": 11.9,},
        # Central-heater
        "2743216f626f43948deec1f7ab3b3d70": {
            "central_heating_state": "off",
            "central_heater_water_pressure": 6.0,
        },
        # Plug MediaCenter
        "aa6b0002df0a46e1b1eb94beb61eddfe": {
            "electricity_consumed": 10.31,
            "relay": "on",
        },
    }
    global smile_setup
    smile_setup = "adam_plus_anna"
    server, smile, client = await connect()
    assert smile._smile_type == "thermostat"
    assert smile._smile_version[0] == "3.0.15"
    assert smile._smile_legacy == False
    await test_device(smile, testdata)
    await tinker_thermostat(
        smile, "009490cc2f674ce6b576863fbb64f867", good_schemas=["Weekschema"]
    )
    await tinker_relay(smile, ["aa6b0002df0a46e1b1eb94beb61eddfe"])
    await smile.close_connection()
    await disconnect(server, client)

    await smile.close_connection()
    await disconnect(server, client)


# Actual test for directory 'Adam + Anna'
@pytest.mark.asyncio
async def test_connect_adam_zone_per_device():
    # testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata = {
        # Lisa WK
        "b59bcebaf94b499ea7d46e4a66fb62d8": {
            "thermostat": 21.5,
            "temperature": 21.1,
            "battery": 0.34,
        },
        # Floor WK
        "b310b72a0e354bfab43089919b9a88bf": {
            "thermostat": 21.5,
            "temperature": 26.22,
            "valve_position": 1.0,
        },
        # CV pomp
        "78d1126fc4c743db81b61c20e88342a7": {
            "electricity_consumed": 35.81,
            "relay": "on",
        },
        # Lisa Bios
        "df4a4a8169904cdb9c03d61a21f42140": {
            "thermostat": 13.0,
            "temperature": 16.5,
            "battery": 0.67,
        },
        # Gateway
        "fe799307f1624099878210aa0b9f1475": {"outdoor_temperature": 7.7,},
        # Central-heater
        "90986d591dcd426cae3ec3e8111ff730": {"central_heating_state": "on",},
        # Modem
        "675416a629f343c495449970e2ca37b5": {
            "electricity_consumed": 12.19,
            "relay": "on",
        },
    }
    global smile_setup
    smile_setup = "adam_zone_per_device"
    server, smile, client = await connect()
    assert smile._smile_type == "thermostat"
    assert smile._smile_version[0] == "3.0.15"
    assert smile._smile_legacy == False
    await test_device(smile, testdata)
    await test_device(smile, testdata)
    await tinker_thermostat(
        smile, "c50f167537524366a5af7aa3942feb1e", good_schemas=["GF7  Woonkamer"]
    )
    await tinker_thermostat(
        smile, "82fa13f017d240daa0d0ea1775420f24", good_schemas=["CV Jessie"]
    )
    await tinker_relay(smile, ["675416a629f343c495449970e2ca37b5"])
    await smile.close_connection()
    await disconnect(server, client)

    await smile.close_connection()
    await disconnect(server, client)


# Actual test for directory 'Adam + Anna'
@pytest.mark.asyncio

# {'electricity_consumed_peak_point': 644.0, 'electricity_consumed_off_peak_point': 0.0, 'electricity_consumed_peak_cumulative': 7702167.0, 'electricity_consumed_off_peak_cumulative': 10263159.0, 'electricity_produced_off_peak_point': 0.0, 'electricity_produced_peak_cumulative': 0.0, 'electricity_produced_off_peak_cumulative': 0.0}
# Actual test for directory 'Adam + Anna'
@pytest.mark.asyncio
async def test_connect_adam_multiple_devices_per_zone():
    global smile_setup
    smile_setup = "adam_multiple_devices_per_zone"
    server, smile, client = await connect()
    device_list = smile.get_all_devices()
    location_list, home = smile.match_locations()
    for loc_id, loc_info in location_list.items():
        print("  --> Location: {} ({}) - {}".format(loc_info["name"], loc_id, loc_info))
        for dev_id, dev_info in device_list.items():
            if dev_info["location"] == loc_id:
                print(
                    "      + Device: {} ({}) - {}".format(
                        dev_info["name"], dev_id, dev_info
                    )
                )
    print("Device list: %s", device_list)
    for dev_id, details in device_list.items():
        data = smile.get_device_data(dev_id)
        print("Device {} / {} data: {}".format(dev_id, details, data))


# {'electricity_consumed_peak_point': 644.0, 'electricity_consumed_off_peak_point': 0.0, 'electricity_consumed_peak_cumulative': 7702167.0, 'electricity_consumed_off_peak_cumulative': 10263159.0, 'electricity_produced_off_peak_point': 0.0, 'electricity_produced_peak_cumulative': 0.0, 'electricity_produced_off_peak_cumulative': 0.0}
# Actual test for directory 'P1 v3'
@pytest.mark.asyncio
async def test_connect_p1v3():
    # testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata = {
        # Gateway / P1 itself
        "ba4de7613517478da82dd9b6abea36af": {
            "electricity_consumed_peak_point": 644.0,
            "electricity_produced_peak_cumulative": 0.0,
            "electricity_consumed_off_peak_cumulative": 10263159.0,
        }
    }
    global smile_setup
    smile_setup = "p1v3"
    server, smile, client = await connect()
    assert smile._smile_type == "power"
    assert smile._smile_version[0] == "3.3.6"
    assert smile._smile_legacy == False
    await test_device(smile, testdata)
    await test_device(smile, testdata)
    await smile.close_connection()
    await disconnect(server, client)

    await smile.close_connection()
    await disconnect(server, client)


# Faked solar for differential, need actual p1v3 with solar data :)
@pytest.mark.asyncio
async def test_connect_p1v3solarfake():
    # testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata = {
        # Gateway / P1 itself
        "ba4de7613517478da82dd9b6abea36af": {
            "electricity_consumed_peak_point": 644.0,
            "electricity_produced_peak_cumulative": 20000.0,
            "electricity_consumed_off_peak_cumulative": 10263159.0,
            "net_electricity_point": 444.0,
        }
    }
    global smile_setup
    smile_setup = "p1v3solarfake"
    server, smile, client = await connect()
    assert smile._smile_type == "power"
    assert smile._smile_version[0] == "3.3.6"
    assert smile._smile_legacy == False
    await test_device(smile, testdata)
    await test_device(smile, testdata)
    await smile.close_connection()
    await disconnect(server, client)

    await smile.close_connection()
    await disconnect(server, client)
