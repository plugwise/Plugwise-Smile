"""Plugwise Home Assistant module."""

import asyncio
import logging
from lxml import etree
# Time related
import datetime as dt
import pytz
from dateutil.parser import parse
# For XML corrections
import re

import aiohttp
import async_timeout

APPLIANCES = "/core/appliances"
DIRECT_OBJECTS = "/core/direct_objects"
DOMAIN_OBJECTS = "/core/domain_objects"
LOCATIONS = "/core/locations"
MODULES = "/core/modules"
RULES = "/core/rules"

DEFAULT_TIMEOUT = 20

_LOGGER = logging.getLogger(__name__)

class Smile:
    """Define the Plugwise object."""
    # pylint: disable=too-many-instance-attributes, too-many-public-methods

    def __init__(
        self, host, password, username='smile', port=80, timeout=DEFAULT_TIMEOUT, websession=None):
        """Set the constructor for this class."""

        if websession is None:
            async def _create_session():
                return aiohttp.ClientSession()

            loop = asyncio.get_event_loop()
            self.websession = loop.run_until_complete(_create_session())
        else:
            self.websession = websession

        self._auth=aiohttp.BasicAuth(username, password=password)

        self._timeout = timeout
        self._endpoint = "http://" + host + ":" + str(port)
        self._appliances = None
        self._direct_objects = None
        self._domain_objects = None
        self._locations = None
        self._modules = None
        self._rules = None

    async def connect(self, retry=2):
        """Connect to Plugwise device."""
        # pylint: disable=too-many-return-statements
        url = self._endpoint + MODULES
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.get(url,auth=self._auth)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            if retry < 1:
                _LOGGER.error("Error connecting to Plugwise", exc_info=True)
                return False
            return await self.connect(retry - 1)

        result = await resp.text()
        if not '<vendor_name>Plugwise</vendor_name>' in result:
            _LOGGER.error('Connected but expected text not returned, we got %s',result)
            return False

        await self.update_device()

        return True

    def sync_connect(self):
        """Close the Plugwise connection."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.connect())
        loop.run_until_complete(task)

    async def close_connection(self):
        """Close the Plugwise connection."""
        await self.websession.close()

    def sync_close_connection(self):
        """Close the Plugwise connection."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.close_connection())
        loop.run_until_complete(task)

    async def request(self, command, retry=3):
        """Request data."""
        # pylint: disable=too-many-return-statements

        url = self._endpoint + command
        _LOGGER.debug("Plugwise command: %s",command)

        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.get(url,auth=self._auth)
        except asyncio.TimeoutError:
            if retry < 1:
                _LOGGER.error("Timed out sending command to Plugwise: %s", command)
                return None
            return await self.request(command, retry - 1)
        except aiohttp.ClientError:
            _LOGGER.error("Error sending command to Plugwise: %s", command, exc_info=True)
            return None

        result = await resp.text()

        #_LOGGER.debug(result)

	# B*llsh*t for now, but we should parse it (xml, not json)
        if not result or result == '{"errorCode":0}':
            return None

        # Encode to ensure utf8 parsing
        return etree.XML(self.escape_illegal_xml_characters(result).encode())

    def sync_request(self, command, retry=2):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.request(command, retry))
        return loop.run_until_complete(task)

    # Appliances
    async def update_appliances(self):
        """Request data."""
        self._appliances = await self.request(APPLIANCES)
        return self._appliances

    def sync_update_appliances(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_appliances())
        loop.run_until_complete(task)

    # Direct objects 
    async def update_direct_objects(self):
        """Request data."""
        self._direct_objects = await self.request(APPLIANCES)
        return self._direct_objects

    def sync_update_direct_objects(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_appliances())
        loop.run_until_complete(task)

    # Domain objects
    async def update_domain_objects(self):
        """Request data."""
        self._domain_objects = await self.request(DOMAIN_OBJECTS)
        return self._domain_objects

    def sync_update_domain_objects(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_domain_objects())
        loop.run_until_complete(task)

    # Locations
    async def update_locations(self):
        """Request data."""
        self._locations = await self.request(LOCATIONS)
        return self._locations

    def sync_update_locations(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_locations())
        loop.run_until_complete(task)

    async def update_device(self):
        """Update device."""
        await self.update_appliances()
        await self.update_domain_objects()
        await self.update_direct_objects()
        await self.update_locations()

    def sync_update_device(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_device())
        loop.run_until_complete(task)

    def get_devices(self):
        #self.sync_update_device()

        appl_dict = self.get_appliance_dictionary()
        loc_dict = self.get_location_dictionary()

        keys = ['name','id']
        thermostats = []
        for appl_id,type in appl_dict.items():
            thermostat = []
            if ('heater_central' in type):
                thermostat.append('Controlled Device')
                thermostat.append(appl_id)
                if thermostat != []:
                    thermostats.append(thermostat)
        
        for loc_id,loc_list in loc_dict.items():
            thermostat = []
            device = self.get_thermostat_from_id(loc_id)
            thermostat.append(loc_list[0])
            thermostat.append(loc_id)
            if thermostat != []:
                thermostats.append(thermostat)
        data = [{k:v for k,v in zip(keys, n)} for n in thermostats]
        return data

    def get_device_data(self, dev_id, ctrl_id):
        """Provides the device-data, based on location_id, from APPLIANCES."""

        if ctrl_id:
            controller_data = self.get_appliance_from_appl_id(ctrl_id)
        device_data = {}
        if dev_id:  
            _LOGGER.debug("Plugwise id: %s",dev_id)
            _LOGGER.debug("Plugwise ctrl_id: %s",ctrl_id)
            device_data = self.get_appliance_from_loc_id(dev_id)
            preset = self.get_preset_from_id(dev_id)
            presets = self.get_presets_from_id(dev_id)
            schemas = self.get_schema_names_from_id(dev_id)
            last_used = self.get_last_active_schema_name_from_id(dev_id)
            a_sch = []
            l_sch = None
            s_sch = None
            if schemas:
                for a,b in schemas.items():
                   a_sch.append(a)
                   if b == True:
                      s_sch = a
            if last_used:
                l_sch = last_used
            if device_data is not None:
                device_data.update( {'active_preset': preset} )
                device_data.update( {'presets':  presets} )
                device_data.update( {'available_schedules': a_sch} )
                device_data.update( {'selected_schedule': s_sch} )
                device_data.update( {'last_used': l_sch} )
                if controller_data is not None:
                    device_data.update( {'boiler_state': controller_data['boiler_state']} )
                    device_data.update( {'central_heating_state': controller_data['central_heating_state']} )
                    device_data.update( {'cooling_state': controller_data['cooling_state']} )
                    device_data.update( {'dhw_state': controller_data['dhw_state']} )
        else:
            device_data['type'] = 'heater_central'
            device_data.update( {'boiler_temp': controller_data['boiler_temp']} )
            device_data.update( {'boiler_state': controller_data['boiler_state']} )
            device_data.update( {'central_heating_state': controller_data['central_heating_state']} )
            device_data.update( {'cooling_state': controller_data['cooling_state']} )
            device_data.update( {'dhw_state': controller_data['dhw_state']} )

        return device_data

    def get_location_dictionary(self):
        """Obtains the existing locations and connected applicance_id's - from LOCATIONS."""
        location_dictionary = {}
        for location in self._locations:
            location_name = location.find('name').text
            location_id = location.attrib['id']
            preset = location.find('preset').text
            therm_loc = (".//logs/point_log[type='thermostat']/period/measurement")
            if location.find(therm_loc) is not None:
                setpoint = location.find(therm_loc).text
                setp_val = float(setpoint)
            temp_loc = (".//logs/point_log[type='temperature']/period/measurement")
            setp_val = None
            temp_val = None
            if location.find(therm_loc) is not None:
                temperature = location.find(temp_loc).text
                temp_val = float(temperature)
            appl_id_list = []
            for appliance in location.iter('appliance'):
                appliance_id = appliance.attrib['id']
                appl_id_list.append(appliance_id)
            if location_name != "Home":
                location_dictionary[location_id] = [location_name, appl_id_list, preset, setp_val, temp_val]
            
        return location_dictionary

    def get_thermostat_from_id(self, dev_id):
        """Obtains the main thermostat connected to the location_id - from APPLIANCES."""
        device_list = []
        temp_list = []
        appliances = self._appliances.findall('.//appliance')
        for appliance in appliances:
            appliance_type = appliance.find('type').text
            appliance_id = appliance.attrib['id']
            for location in appliance.iter('location'):
                if location.attrib is not None:
                    location_id = location.attrib['id']
                if location_id == dev_id:
                    temp_list.append(appliance_type)
        if 'zone_thermostat' in temp_list:
            device_list.append('zone_thermostat')
        else:
            if 'thermostatic_radiator_valve' in temp_list:
                device_list = temp_list
          
        if device_list != []:
            return device_list

    def get_appliance_from_loc_id(self, dev_id):
        """Obtains the appliance-data connected to a location - from APPLIANCES."""
        appliance_data = {}
        appliances = self._appliances.findall('.//appliance')
        appl_dict = {}
        appl_list = []
        for appliance in appliances:
            if appliance.find('type') is not None:
                appliance_type = appliance.find('type').text
                if "gateway" not in appliance_type:
                    if appliance.find('location') is not None:
                        appl_location = appliance.find('location').attrib['id']
                        if appl_location == dev_id:
                            if (appliance_type == 'zone_thermostat') or (appliance_type == 'thermostatic_radiator_valve') or (appliance_type == 'thermostat'):
                                appl_dict['type'] = appliance_type
                                locator = (".//logs/point_log[type='battery']/period/measurement")
                                appl_dict['battery'] = None
                                if appliance.find(locator) is not None:
                                    battery = appliance.find(locator).text
                                    value = float(battery)
                                    battery = '{:.2f}'.format(round(value, 2))
                                    appl_dict['battery'] = battery
                                locator = (".//logs/point_log[type='thermostat']/period/measurement")
                                appl_dict['setpoint_temp'] = None
                                if appliance.find(locator) is not None:
                                    thermostat = appliance.find(locator).text
                                    thermostat = float(thermostat)
                                    appl_dict['setpoint_temp'] = thermostat
                                locator = (".//logs/point_log[type='temperature']/period/measurement")
                                appl_dict['current_temp'] = None
                                if appliance.find(locator) is not None:
                                    temperature = appliance.find(locator).text
                                    temperature = float(temperature)
                                    appl_dict['current_temp'] = temperature
                                appl_list.append(appl_dict.copy())
        
        for dict in sorted(appl_list, key=lambda k: k['type'], reverse=True):
            if dict['type'] == "zone_thermostat":
                return dict
            else:
                return dict

    def get_appliance_from_appl_id(self, dev_id):
        """Obtains the appliance-data from appliances without a location - from APPLIANCES."""
        appliance_data = {}
        for appliance in self._appliances:
            appliance_name = appliance.find('name').text
            if "Gateway" not in appliance_name:
                appliance_id = appliance.attrib['id']
                if appliance_id == dev_id:
                    appliance_type = appliance.find('type').text
                    appliance_data['type'] = appliance_type
                    boiler_temperature = None
                    locator = (".//logs/point_log[type='boiler_temperature']/period/measurement")
                    if appliance.find(locator) is not None:
                        measurement = appliance.find(locator).text
                        value = float(measurement)
                        boiler_temperature = '{:.1f}'.format(round(value, 1))
                        appliance_data['boiler_temp'] = boiler_temperature
                    locator = (".//logs/point_log[type='boiler_state']/period/measurement")
                    appliance_data['boiler_state'] = None
                    if appliance.find(locator) is not None:
                        boiler_state = (appliance.find(locator).text == "on")
                        appliance_data['boiler_state'] = boiler_state
                    locator = (".//logs/point_log[type='central_heating_state']/period/measurement")
                    appliance_data['central_heating_state'] = None
                    if appliance.find(locator) is not None:
                        central_heating_state = (appliance.find(locator).text == "on")
                        appliance_data['central_heating_state'] = central_heating_state
                    locator = (".//logs/point_log[type='cooling_state']/period/measurement")
                    appliance_data['cooling_state'] = None
                    if appliance.find(locator) is not None:                      
                        cooling_state = (appliance.find(locator).text == "on")
                        appliance_data['cooling_state'] = cooling_state
                    locator = (".//logs/point_log[type='domestic_hot_water_state']/period/measurement")
                    appliance_data['dhw_state'] = None
                    if appliance.find(locator) is not None:                      
                        domestic_hot_water_state = (appliance.find(locator).text == "on")
                        appliance_data['dhw_state'] = domestic_hot_water_state
     
        if appliance_data != {}:
            return appliance_data

    def get_appliance_dictionary(self):
        """Obtains the existing appliance types and ids - from APPLIANCES."""
        appliance_dictionary = {}
        for appliance in self._appliances:
            appliance_name = appliance.find('name').text
            if "Gateway" not in appliance_name:
                appliance_id = appliance.attrib['id']
                appliance_type = appliance.find('type').text
                if appliance_type != 'heater_central':
                    locator = (".//logs/point_log[type='battery']/period/measurement")
                    battery = None
                    if appliance.find(locator) is not None:
                        battery = appliance.find(locator).text
                    appliance_dictionary[appliance_id] = (appliance_type, battery)
                else:
                    boiler_temperature = None
                    locator = (".//logs/point_log[type='boiler_temperature']/period/measurement")
                    if appliance.find(locator) is not None:
                        measurement = appliance.find(locator).text
                        value = float(measurement)
                        boiler_temperature = '{:.1f}'.format(round(value, 1))
                    locator = (".//logs/point_log[type='boiler_state']/period/measurement")
                    boiler_state =  None
                    if appliance.find(locator) is not None:
                        boiler_state = (appliance.find(locator).text == "on")
                    locator = (".//logs/point_log[type='central_heating_state']/period/measurement")
                    central_heating_state = None
                    if appliance.find(locator) is not None:
                        central_heating_state = (appliance.find(locator).text == "on")
                    locator = (".//logs/point_log[type='cooling_state']/period/measurement")
                    cooling_state =  None
                    if appliance.find(locator) is not None:                      
                        cooling_state = (appliance.find(locator).text == "on")
                    locator = (".//logs/point_log[type='domestic_hot_water_state']/period/measurement")
                    domestic_hot_water_state =  None
                    if appliance.find(locator) is not None:                      
                        domestic_hot_water_state = (appliance.find(locator).text == 'on')                    
                    appliance_dictionary[appliance_id] = (
                        appliance_type,
                        boiler_temperature, boiler_state,
                        central_heating_state, cooling_state,
                        domestic_hot_water_state
                        )
        return appliance_dictionary

    def get_preset_from_id(self, dev_id):
        """Obtains the active preset based on the location_id - from DOMAIN_OBJECTS."""
        for location in self._domain_objects:
            location_id = location.attrib['id']
            if location.find('preset') is not None:
                preset = location.find('preset').text
                if location_id == dev_id:
                    return preset

    def get_presets_from_id(self, dev_id):
        """Gets the presets from the thermostat based on location_id."""
        rule_ids = {}
        locator = 'zone_setpoint_and_state_based_on_preset'
        _LOGGER.debug("Plugwise locator and id: %s -> %s",locator,dev_id)
        rule_ids = self.get_rule_id_and_zone_location_by_template_tag_with_id(locator, dev_id)
        if rule_ids is None:
            rule_ids = self.get_rule_id_and_zone_location_by_name_with_id('Thermostat presets', dev_id)
            if rule_ids is None:
                return None

        presets = {}
        for key,val in rule_ids.items():
            if val == dev_id:
                presets = self.get_preset_dictionary(key)
        return presets

    def get_schema_names_from_id(self, dev_id):
        """Obtains the available schemas or schedules based on the location_id."""
        rule_ids = {}
        locator = 'zone_preset_based_on_time_and_presence_with_override'
        _LOGGER.debug("Plugwise locator and id: %s -> %s",locator,dev_id)
        rule_ids = self.get_rule_id_and_zone_location_by_template_tag_with_id(locator, dev_id)
        schemas = {}
        l_schemas = {}
        if rule_ids:
            for key,val in rule_ids.items():
                if val == dev_id:
                    name = self._domain_objects.find("rule[@id='" + key + "']/name").text
                    active = False
                    if self._domain_objects.find("rule[@id='" + key + "']/active").text == 'true':
                        active = True
                    schemas[name] = active
        if schemas != {}:
            return schemas

    def get_last_active_schema_name_from_id(self, dev_id):
        """Determine the last active schema."""
        epoch = dt.datetime(1970, 1, 1, tzinfo=pytz.utc)
        rule_ids = {}
        locator = 'zone_preset_based_on_time_and_presence_with_override'
        _LOGGER.debug("Plugwise locator and id: %s -> %s",locator,dev_id)
        rule_ids = self.get_rule_id_and_zone_location_by_template_tag_with_id(locator, dev_id)
        schemas = {}
        if rule_ids:
            for key,val in rule_ids.items():
                if val == dev_id:
                    schema_name = self._domain_objects.find("rule[@id='" + key + "']/name").text
                    schema_date = self._domain_objects.find("rule[@id='" + key + "']/modified_date").text
                    schema_time = parse(schema_date)
                    schemas[schema_name] = (schema_time - epoch).total_seconds()
                last_modified = sorted(schemas.items(), key=lambda kv: kv[1])[-1][0]
                return last_modified

    def get_rule_id_and_zone_location_by_template_tag_with_id(self, rule_name, dev_id):
        """Obtains the rule_id based on the given template_tag and location_id."""
        _LOGGER.debug("Plugwise rule and id: %s -> %s",rule_name,dev_id)
        schema_ids = {}
        rules = self._domain_objects.findall('.//rule')
        for rule in rules:
            try:
                name = rule.find('template').attrib['tag']
            except KeyError:
                name = None
            if (name == rule_name):
                rule_id = rule.attrib['id']
                for elem in rule.iter('location'):
                    if elem.attrib is not None:
                        location_id = elem.attrib['id']
                        if location_id == dev_id:
                            schema_ids[rule_id] = location_id
        if schema_ids != {}:
            return schema_ids

    def get_rule_id_and_zone_location_by_name_with_id(self, rule_name, dev_id):
        """Obtains the rule_id and location_id based on the given name and location_id."""
        schema_ids = {}
        rules = self._domain_objects.findall('.//rule')
        for rule in rules:
            try:
                name = rule.find('name').text
            except AttributeError:
                name = None
            if (name == rule_name):
                rule_id = rule.attrib['id']
                for elem in rule.iter('location'):
                    if elem.attrib is not None:
                        location_id = elem.attrib['id']
                        if location_id == dev_id:
                            schema_ids[rule_id] = location_id
        if schema_ids != {}:
            return schema_ids

    def get_outdoor_temperature(self):
        """Obtains the outdoor_temperature from the thermostat."""
        locations = self._domain_objects.findall(".//location")
        for location in locations:
            locator = (".//logs/point_log[type='outdoor_temperature']/period/measurement")
            if location.find(locator) is not None:
                measurement = location.find(locator).text
                value = float(measurement)
                value = '{:.1f}'.format(round(value, 1))
                return value

    def get_water_pressure(self):
        """Obtains the water pressure value from the thermostat"""
        appliances = self._domain_objects.findall(".//appliance")
        for appliance in appliances:
            locator = (".//logs/point_log[type='central_heater_water_pressure']/period/measurement")
            if appliance.find(locator) is not None:
                measurement = appliance.find(locator).text
                value = float(measurement)
                value = '{:.1f}'.format(round(value, 1))
                return value

    def get_preset_dictionary(self, rule_id):
        """Obtains the presets from a rule based on rule_id."""
        preset_dictionary = {}
        directives = self._domain_objects.find(
            "rule[@id='" + rule_id + "']/directives"
        )
        for directive in directives:
            preset = directive.find("then").attrib
            keys, values = zip(*preset.items())
            if str(keys[0]) == 'setpoint':
                preset_dictionary[directive.attrib["preset"]] = [float(preset["setpoint"]), 0]
            else:
                preset_dictionary[directive.attrib["preset"]] = [float(preset["heating_setpoint"]), float(preset["cooling_setpoint"])]
        if preset_dictionary != {}:
            return preset_dictionary

    def _set_schema_state(self, loc_id, name, state):
        """Sets the schedule, helper-function."""
        schema_rule_ids = {}
        schema_rule_ids = self.get_rule_id_and_zone_location_by_name_with_id(self._domain_objects, str(name), loc_id)
        for schema_rule_id,location_id in schema_rule_ids.items():
            if location_id == loc_id:
                templates = self._domain_objects.findall(".//*[@id='{}']/template".format(schema_rule_id))
                template_id = None
                for rule in templates:
                    template_id = rule.attrib['id']

                uri = '{};id={}'.format(RULES, schema_rule_id)

                state = str(state)
                data = '<rules><rule id="{}"><name><![CDATA[{}]]></name>' \
                       '<template id="{}" /><active>{}</active></rule>' \
                       '</rules>'.format(schema_rule_id, name, template_id, state)

                xml = requests.put(
                      self._endpoint + uri,
                      auth=(self._username, self._password),
                      data=data,
                      headers={'Content-Type': 'text/xml'},
                      timeout=10
                )

                if xml.status_code != requests.codes.ok: # pylint: disable=no-member
                    CouldNotSetTemperatureException("Could not set the schema to {}.".format(state) + xml.text)
                return '{} {}'.format(xml.text, data)

    def _set_preset(self, loc_id, loc_type, preset):
        """Sets the preset, helper function."""
        location_ids = []
        appliances = self._domain_objects.findall('.//appliance')
        for appliance in appliances:
            if appliance.find('type') is not None:
                appliance_type = appliance.find('type').text
                if appliance_type == loc_type:
                    for location in appliance.iter('location'):
                        if location.attrib is not None:
                            location_id = location.attrib['id']
                            if location_id == loc_id:
                                locations_root = self.get_locations()
                                current_location = locations_root.find("location[@id='" + location_id + "']")
                                location_name = current_location.find('name').text
                                location_type = current_location.find('type').text

                                xml = requests.put(
                                        self._endpoint
                                        + LOCATIONS
                                        + ";id="
                                        + location_id,
                                        auth=(self._username, self._password),
                                        data="<locations>"
                                        + '<location id="'
                                        + location_id
                                        + '">'
                                        + "<name>"
                                        + location_name
                                        + "</name>"
                                        + "<type>"
                                        + location_type
                                        + "</type>"
                                        + "<preset>"
                                        + preset
                                        + "</preset>"
                                        + "</location>"
                                        + "</locations>",
                                        headers={"Content-Type": "text/xml"},
                                        timeout=10,
                                    )
                                if xml.status_code != requests.codes.ok: # pylint: disable=no-member
                                    raise CouldNotSetPresetException("Could not set the given preset: " + xml.text)
                                return xml.text

    def _set_temp(self, loc_id, loc_type, temperature):
        """Sends a temperature-set request, helper function."""
        uri = self.__get_temperature_uri(root, loc_id, loc_type)
        temperature = str(temperature)

        if uri is not None:
            xml = requests.put(
                self._endpoint + uri,
                auth=(self._username, self._password),
                data="<thermostat_functionality><setpoint>" + temperature + "</setpoint></thermostat_functionality>",
                headers={"Content-Type": "text/xml"},
                timeout=10,
            )

            if xml.status_code != requests.codes.ok: # pylint: disable=no-member
                CouldNotSetTemperatureException("Could not set the temperature." + xml.text)
            return xml.text
        else:
            CouldNotSetTemperatureException("Could not obtain the temperature_uri.")

    def __get_temperature_uri(self, loc_id, loc_type):
        """Determine the location-set_temperature uri - from DOMAIN_OBJECTS."""
        location_ids = []
        appliances = self._domain_objects.findall('.//appliance')
        for appliance in appliances:
            if appliance.find('type') is not None:
                appliance_type = appliance.find('type').text
                if appliance_type == loc_type:
                    for location in appliance.iter('location'):
                        if location.attrib is not None:
                            location_id = location.attrib['id']
                            if location_id == loc_id:
                                locator = (
                                    "location[@id='"
                                    + location_id
                                    + "']/actuator_functionalities/thermostat_functionality"
                                )
                                thermostat_functionality_id = self._domain_objects.find(locator).attrib['id']
                                
                                temperature_uri = (
                                    LOCATIONS
                                    + ";id="
                                    + location_id
                                    + "/thermostat;id="
                                    + thermostat_functionality_id
                                )
                                
                                return temperature_uri



    def set_schedule_state(self, loc_id,name, state):
        """Sets the schedule, with the given name, connected to a location, to true or false - DOMAIN_OBJECTS."""
        self._set_schema_state(loc_id, name, state)
        
    def set_preset(self, domain_objects, loc_id, loc_type, preset):
        """Sets the given location-preset on the relevant thermostat - from DOMAIN_OBJECTS."""
        self._set_preset(loc_id, loc_type, preset)
        
    def set_temperature(self, loc_id, loc_type, temperature):
        """Sends a temperature-set request to the relevant thermostat, connected to a location - from DOMAIN_OBJECTS."""
        #selfdomain_objects = self.get_domain_objects()
        self._set_temp(loc_id, loc_type, temperature)

    @staticmethod
    def escape_illegal_xml_characters(xmldata):
        """Replace illegal &-characters."""
        return re.sub(r"&([^a-zA-Z#])", r"&amp;\1", xmldata)



