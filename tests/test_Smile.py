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
# taking smile_type (i.e. directory name under tests/{smile_app}/
# as inclusion point
async def setup_app():
    global smile_type
    if not smile_type:
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
    global smile_type
    f=open('tests/{}/core.appliances.xml'.format(smile_type),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_direct_objects(request):
    global smile_type
    f=open('tests/{}/core.direct_objects.xml'.format(smile_type),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_domain_objects(request):
    global smile_type
    f=open('tests/{}/core.domain_objects.xml'.format(smile_type),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_locations(request):
    global smile_type
    f=open('tests/{}/core.locations.xml'.format(smile_type),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_modules(request):
    global smile_type
    f=open('tests/{}/core.modules.xml'.format(smile_type),'r')
    data=f.read()
    f.close()
    return aiohttp.web.Response(text=data)

async def smile_set_temp_or_preset(request):
    text="<xml />"
    raise aiohttp.web.HTTPAccepted(text=text)

async def smile_set_schedule(request):
    text="<xml />"
    raise aiohttp.web.HTTPAccepted(text=text)

# Test if at least modules functions before going further
# note that this only tests the modules-app for functionality
# if this fails, none of the actual tests against the Smile library
# will function correctly
async def test_mock(aiohttp_client, loop):
    global smile_type
    smile_type = 'anna_without_boiler'
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

# Generic connect
@pytest.mark.asyncio
async def connect():
    global smile_type
    if not smile_type:
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
    assert smile._domain_objects == None

    """Connect to the smile"""
    connection = await smile.connect()
    assert connection == True
    return server,smile,client


# GEneric list_devices
@pytest.mark.asyncio
async def list_devices(server,smile):
    device_list={}
    devices = await smile.get_devices()
    for dev in devices:
        if dev['name'] == 'Controlled Device':
            ctrl_id = dev['id']
        else:
            device_list[dev['id']]={'name': dev['name'], 'ctrl': ctrl_id}
    #print(device_list)
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
    global smile_type
    smile_type = 'anna_without_boiler'
    server,smile,client = await connect()
    device_list = await list_devices(server,smile)
    #print(device_list)
    for dev_id,details in device_list.items():
        ctrl = details['ctrl']
        data = smile.get_device_data(dev_id, ctrl)
        test_id = '{}_{}'.format(ctrl,dev_id)
        assert test_id in testdata
        #for item,value in data.items():
        #    print(item)
        #    print(value)
        for testkey in testdata[test_id]:
            print('Device asserting {}'.format(testkey))
            assert data[testkey] == testdata[test_id][testkey]

    ctrl = details['ctrl']
    data = smile.get_device_data(None, ctrl)
    print(data)
    assert ctrl in testdata
    for testkey in testdata[ctrl]:
        print('Controller asserting {}'.format(testkey))
        assert data[testkey] == testdata[ctrl][testkey]

    locations=smile.get_location_dictionary()
    for location_id,description in locations.items():
        print('Location: {}'.format(description))
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
    global smile_type
    smile_type = 'adam_living_floor_plus_3_rooms'
    server,smile,client = await connect()
    device_list = await list_devices(server,smile)
    print(device_list)
    #testdata dictionary with key ctrl_id_dev_id => keys:values
    testdata={}
    for dev_id,details in device_list.items():
        data = smile.get_device_data(dev_id, details['ctrl'])
        test_id = '{}_{}'.format(details['ctrl'],dev_id)
        #assert test_id in testdata
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
                'outdoor_temp': 12.4,
                'illuminance': None,
        },
        '2743216f626f43948deec1f7ab3b3d70_009490cc2f674ce6b576863fbb64f867': {
                'type': 'thermostat',
                'setpoint_temp': 20.5,
                'current_temp': 20.55,
                'active_preset': 'home',
                'selected_schedule': 'Weekschema',
                'last_used': 'Weekschema',
                'boiler_state': None,
                'battery': None,
                'dhw_state': False,
            }
        }
    global smile_type
    smile_type = 'adam_plus_anna'
    server,smile,client = await connect()
    device_list = await list_devices(server,smile)
    #print(device_list)
    for dev_id,details in device_list.items():
        data = smile.get_device_data(dev_id, details['ctrl'])
        test_id = '{}_{}'.format(details['ctrl'],dev_id)
        #assert test_id in testdata
        #for item,value in data.items():
        #    print(item)
        #    print(value)
        for testkey in testdata[test_id]:
            print('Asserting {}'.format(testkey))
            assert data[testkey] == testdata[test_id][testkey]

    ctrl = details['ctrl']
    data = smile.get_device_data(None, ctrl)
    print(data)
    assert ctrl in testdata
    for testkey in testdata[ctrl]:
        print('Controller asserting {}'.format(testkey))
        assert data[testkey] == testdata[ctrl][testkey]

    locations=smile.get_location_dictionary()
    for location_id,description in locations.items():
        print('Location: {}'.format(description))
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
