"""Plugwise Home Assistant module."""

import time
import pytest
import pytest_asyncio
import pytest_aiohttp

import asyncio
import aiohttp
import codecov
import os

from lxml import etree

from Plugwise_Smile.Smile import Smile

# Prepare aiohttp app routes
# taking smile_setup (i.e. directory name under tests/{smile_app}/
# as inclusion point
async def setup_app():
    global smile_setup
    if not smile_setup:
        return False
    app = aiohttp.web.Application()
    app.router.add_get('/core/appliances',smile_appliances)
    app.router.add_get('/core/direct_objects',smile_direct_objects)
    app.router.add_get('/core/domain_objects',smile_domain_objects)
    app.router.add_get('/core/locations',smile_locations)
    app.router.add_get('/core/modules',smile_modules)

    app.router.add_route('PUT', '/core/locations{tail:.*}', smile_set_temp_or_preset)
    app.router.add_route('PUT', '/core/rules{tail:.*}', smile_set_schedule)
    return app

# Wrapper for appliances uri
async def smile_appliances(request):
    global smile_setup
    f=open('tests/{}/core.appliances.xml'.format(smile_setup),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_direct_objects(request):
    global smile_setup
    f=open('tests/{}/core.direct_objects.xml'.format(smile_setup),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_domain_objects(request):
    global smile_setup
    f=open('tests/{}/core.domain_objects.xml'.format(smile_setup),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_locations(request):
    global smile_setup
    f=open('tests/{}/core.locations.xml'.format(smile_setup),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_modules(request):
    global smile_setup
    f=open('tests/{}/core.modules.xml'.format(smile_setup),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_set_temp_or_preset(request):
    text="<xml />"
    raise aiohttp.web.HTTPAccepted(text=text)

async def smile_set_schedule(request):
    text="<xml />"
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
    port =  aiohttp.test_utils.unused_port()

    app = await setup_app()

    server = aiohttp.test_utils.TestServer(app,port=port,scheme='http',host='127.0.0.1')
    await server.start_server()

    client = aiohttp.test_utils.TestClient(server)
    websession = client.session

    url = '{}://{}:{}/core/modules'.format(server.scheme,server.host,server.port)
    resp = await websession.get(url)
    assert resp.status == 200
    text = await resp.text()
    assert 'xml' in text
    assert '<vendor_name>Plugwise</vendor_name>' in text

    smile = Smile( host=server.host, password='abcdefgh', port=server.port, websession=websession)
    assert smile._timeout == 20
    assert smile._domain_objects is None
    assert smile._smile_type is None

    """Connect to the smile"""
    connection = await smile.connect()
    assert connection is True
    assert smile._smile_type is not None
    return server,smile,client


# GEneric list_devices
@pytest.mark.asyncio
async def list_devices(server,smile):
    device_list={}
    devices = await smile.get_devices()
    ctrl_id = None
    plug_id = None
    #for dev in devices:
    #    if dev['name'] == 'Controlled Device':
    #        ctrl_id = dev['id']
    #    if dev['name'] == 'Home' and smile._smile_type == 'power':
    #        ctrl_id = dev['id']
    print(devices)
    for dev in devices:
        print(dev)
        if dev['name'] == 'Controlled Device':
            ctrl_id = dev['id']
        elif dev['name'] == 'Home' and smile._smile_type == 'power':
            ctrl_id = dev['id']
        elif dev['type'] == 'plug':
            plug_id = dev['id']

    for dev in devices:
        if dev['name'] != 'Controlled Device':
            device_list[dev['id']]={'name': dev['name'], 'ctrl': ctrl_id, 'plug': plug_id}
    print(device_list)
    return device_list


# Generic disconnect
@pytest.mark.asyncio
async def disconnect(server,client):
    if not server:
        return False
    await client.session.close()
    await server.close()

# Actual test for directory 'Anna' without a boiler
@pytest.mark.asyncio
async def test_connect_anna_without_boiler():
    # testdata is a dictionary with key ctrl_id_dev_id => keys:values
    #testdata={
    #             'ctrl_id': { 'outdoor+temp': 20.0, }
    #             'ctrl_id:dev_id': { 'type': 'thermostat', 'battery': None, }
    #         }
    testdata={
        "c46b4794d28149699eacf053deedd003": {
                'type': 'heater_central',
                'outdoor_temp': 10.8,
                'illuminance': 35.0,
        },
        "c46b4794d28149699eacf053deedd003_c34c6864216446528e95d88985e714cc": {
                'type': 'thermostat',
                'setpoint_temp': 16.0,
                'current_temp': 20.62,
                'selected_schedule': 'Normal',
                'last_used': 'Test',
                'boiler_state': None,
                'battery': None,
            }
        }
    global smile_setup
    smile_setup = 'anna_without_boiler'
    server,smile,client = await connect()
    device_list = await list_devices(server,smile)
    assert smile._smile_type == 'thermostat'
    print(device_list)
    for dev_id,details in device_list.items():
        ctrl = details['ctrl']
        plug = details['plug']
        data = smile.get_device_data(dev_id, ctrl, plug)
        test_id = '{}_{}'.format(ctrl,dev_id)
        #assert test_id in testdata
        if test_id not in testdata:
            continue
        #for item,value in data.items():
        #    print(item)
        #    print(value)
        for testkey in testdata[test_id]:
            print('Device asserting {}'.format(testkey))
            assert data[testkey] == testdata[test_id][testkey]

    ctrl = details['ctrl']
    plug = details['plug']
    data = smile.get_device_data(None, ctrl, plug)
    print(data)
    assert ctrl in testdata
    for testkey in testdata[ctrl]:
        print('Controller asserting {}'.format(testkey))
        assert data[testkey] == testdata[ctrl][testkey]

    locations=smile.get_location_list()
    for location_dict in locations:
        test_id = '{}_{}'.format(details['ctrl'],location_dict['id'])
        # TODO: And plug?
        # See also below, but we should make these test routines more
        # generic and just call 'change_parameters) and call with '20.0, asleep,...'
        # that way we can be more sure
        # below statements (and in next TODO are for the Anna+Adam situation
        # but this will explode fast :)
        if test_id not in testdata:
            continue
        if 'type' not in testdata[test_id]:
            continue
        if testdata[test_id]['type'] != 'thermostat':
            continue
        print('Location: {}'.format(location_dict['name']))
        print(' - Adjusting temperature')
        temp_change = await smile.set_temperature(location_id, 20.0)
        assert temp_change == True
        print(' - Adjusting preset')
        sched_change = await smile.set_preset(location_id, 'asleep')
        assert sched_change == True
        print(' - Adjusting schedule')
        schema_change = await smile.set_schedule_state(location_id, 'Test', 'auto')
        assert schema_change == True
        schema_change = await smile.set_schedule_state(location_id, 'NoSuchSchema', 'auto')
        assert schema_change == False

    await smile.close_connection()
    await disconnect(server,client)

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

# Actual test for directory 'Adam + Anna'
@pytest.mark.asyncio
async def test_connect_adam_plus_anna():
    #testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata={
        '2743216f626f43948deec1f7ab3b3d70': {
                'type': 'heater_central',
                'outdoor_temp': 11.9,
                'illuminance': None,
        },
        '2743216f626f43948deec1f7ab3b3d70_009490cc2f674ce6b576863fbb64f867': {
                'type': 'thermostat',
                'setpoint_temp': 20.5,
                'current_temp': 20.46,
                'active_preset': 'home',
                'selected_schedule': 'Weekschema',
                'last_used': 'Weekschema',
                'boiler_state': None,
                'battery': None,
                'dhw_state': False,
            }
        }
    global smile_setup
    smile_setup = 'adam_plus_anna'
    server,smile,client = await connect()
    device_list = await list_devices(server,smile)
    assert smile._smile_type == 'thermostat'
    print(device_list)
    for dev_id,details in device_list.items():
        data = smile.get_device_data(dev_id, details['ctrl'], details['plug'])
        test_id = '{}_{}'.format(details['ctrl'],dev_id)
        # If test_id in testdata, check it, otherwise next
        if test_id not in testdata:
            continue
        #for item,value in data.items():
        #    print(item)
        #    print(value)
        for testkey in testdata[test_id]:
            print('Asserting {}'.format(testkey))
            assert data[testkey] == testdata[test_id][testkey]

    ctrl = details['ctrl']
    plug = details['plug']
    data = smile.get_device_data(None, ctrl, plug)
    print(data)
    assert ctrl in testdata
    for testkey in testdata[ctrl]:
        print('Controller asserting {}'.format(testkey))
        assert data[testkey] == testdata[ctrl][testkey]

    locations=smile.get_location_list()
    print(locations)
    for location_dict in locations:
        test_id = '{}_{}'.format(details['ctrl'],location_dict['id'])
        # TODO: And plug?
        if test_id not in testdata:
            continue
        if 'type' not in testdata[test_id]:
            continue
        if testdata[test_id]['type'] != 'thermostat':
            continue
        print('Location: {}'.format(location_dict['name']))
        print(' - Adjusting temperature')
        temp_change = await smile.set_temperature(location_id, 20.0)
        assert temp_change == True
        print(' - Adjusting preset')
        sched_change = await smile.set_preset(location_id, 'asleep')
        assert sched_change == True
        print(' - Adjusting schedule')
        schema_change = await smile.set_schedule_state(location_id, 'Weekschema', 'auto')
        assert schema_change == True
        schema_change = await smile.set_schedule_state(location_id, 'NoSuchSchema', 'auto')
        assert schema_change == False

    await smile.close_connection()
    await disconnect(server,client)


# {'electricity_consumed_peak_point': 644.0, 'electricity_consumed_off_peak_point': 0.0, 'electricity_consumed_peak_cumulative': 7702167.0, 'electricity_consumed_off_peak_cumulative': 10263159.0, 'electricity_produced_off_peak_point': 0.0, 'electricity_produced_peak_cumulative': 0.0, 'electricity_produced_off_peak_cumulative': 0.0}
# Actual test for directory 'P1 v3'
@pytest.mark.asyncio
async def test_connect_p1v3():
    #testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata={
        'a455b61e52394b2db5081ce025a430f3': {
                'electricity_consumed_peak_point': 644.0,
                'electricity_produced_peak_cumulative': 0.0,
                'electricity_consumed_off_peak_cumulative': 10263159.0,
        }
    }
    global smile_setup
    smile_setup = 'p1v3'
    server,smile,client = await connect()
    device_list = await list_devices(server,smile)

    assert smile._smile_type == 'power'
    ctrl = None
    data = {}
    for dev_id,details in device_list.items():
        ctrl = details['ctrl']
        print(ctrl)
    data = smile.get_device_data(None, ctrl, None)
    print(ctrl)
    print(data)
    for testkey in testdata[ctrl]:
        print('Controller asserting {}'.format(testkey))
        assert data[testkey] == testdata[ctrl][testkey]

    await smile.close_connection()
    await disconnect(server,client)
