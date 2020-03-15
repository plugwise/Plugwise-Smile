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

POWER_MEASUREMENTS = [
    'electricity_consumed',
    'electricity_produced',
    'gas_consumed',
    ]

TARIFF_MEASUREMENTS = [
    'electricity_consumption_tariff_structure',
    'electricity_consumption_peak_tariff',
    'electricity_consumption_off_peak_tariff',
    'electricity_production_peak_tariff',
    'electricity_production_off_peak_tariff',
    'electricity_consumption_single_tariff',
    'electricity_production_single_tariff',
    'gas_consumption_tariff',
    ]


class Smile:
    """Define the Plugwise object."""
    # pylint: disable=too-many-instance-attributes, too-many-public-methods

    def __init__(
                 self, host, password, username='smile', port=80,
                 smile_type='thermostat', timeout=DEFAULT_TIMEOUT,
                 websession=None):
        """Set the constructor for this class."""

        if websession is None:
            async def _create_session():
                return aiohttp.ClientSession()

            loop = asyncio.get_event_loop()
            self.websession = loop.run_until_complete(_create_session())
        else:
            self.websession = websession

        self._auth = aiohttp.BasicAuth(username, password=password)

        self._timeout = timeout
        self._endpoint = "http://" + host + ":" + str(port)
        self._appliances = None
        self._direct_objects = None
        self._domain_objects = None
        self._locations = None
        self._modules = None
        self._power_tariff = None
        self._rules = None
        self._smile_type = smile_type

    async def connect(self, retry=2):
        """Connect to Plugwise device."""
        # pylint: disable=too-many-return-statements
        url = self._endpoint + MODULES
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.get(url, auth=self._auth)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            if retry < 1:
                _LOGGER.error("Error connecting to Plugwise", exc_info=True)
                return False
            return await self.connect(retry - 1)

        result = await resp.text()
        if '<vendor_name>Plugwise</vendor_name>' not in result:
            _LOGGER.error('Connected but expected text not returned, \
                          we got %s', result)
            return False

        # Update all endpoints on first connect
        await self.full_update_device()

        return True

    async def close_connection(self):
        """Close the Plugwise connection."""
        await self.websession.close()

    async def request(self, command, retry=3, method='get', data={},
                      headers={'Content-type': 'text/xml'}):
        """Request data."""
        # pylint: disable=too-many-return-statements

        url = self._endpoint + command
        # _LOGGER.debug("Plugwise command: %s",command)
        # _LOGGER.debug("Plugwise command type: %s",method)
        # _LOGGER.debug("Plugwise command data: %s",data)

        try:
            with async_timeout.timeout(self._timeout):
                if method == 'get':
                    resp = await self.websession.get(url, auth=self._auth)
                if method == 'put':
                    # _LOGGER.debug("Sending: command/url %s with data %s
                    #               using headers %s", command, data, headers)
                    resp = await self.websession.put(url, data=data,
                                                     headers=headers,
                                                     auth=self._auth)
        except asyncio.TimeoutError:
            if retry < 1:
                _LOGGER.error("Timed out sending command to Plugwise: %s",
                              command)
                return None
            return await self.request(command, retry - 1)
        except aiohttp.ClientError:
            _LOGGER.error("Error sending command to Plugwise: %s", command,
                          exc_info=True)
            return None

        result = await resp.text()

        # _LOGGER.debug(result)
        _LOGGER.debug('Plugwise network traffic to %s- talking to Smile with \
                      %s', self._endpoint, command)

        if not result or 'error' in result:
            return None

        # Encode to ensure utf8 parsing
        return etree.XML(self.escape_illegal_xml_characters(result).encode())

    # Appliances
    async def update_appliances(self):
        """Request data."""
        new_data = await self.request(APPLIANCES)
        if new_data is not None:
            self._appliances = new_data

    # Direct objects
    async def update_direct_objects(self):
        """Request data."""
        new_data = await self.request(DIRECT_OBJECTS)
        if new_data is not None:
            self._direct_objects = new_data

    # Domain objects
    async def update_domain_objects(self):
        """Request data."""
        new_data = await self.request(DOMAIN_OBJECTS)
        if new_data is not None:
            self._domain_objects = new_data

    # Locations
    async def update_locations(self):
        """Request data."""
        new_data = await self.request(LOCATIONS)
        if new_data is not None:
            self._locations = new_data

    async def full_update_device(self):
        """Update device."""
        await self.update_appliances()
        await self.update_domain_objects()
        await self.update_direct_objects()
        await self.update_locations()
        return True

    async def get_devices(self):
        # self.sync_update_device()
        # await self.update_appliances()
        # await self.update_locations()

        appl_dict = self.get_appliance_dictionary()
        loc_dict = self.get_location_dictionary()

        keys = ['name', 'id']
        thermostats = []
        for appl_id, type in appl_dict.items():
            thermostat = []
            if ('heater_central' in type):
                thermostat.append('Controlled Device')
                thermostat.append(appl_id)
                if thermostat != []:
                    thermostats.append(thermostat)

        for loc_id, location in loc_dict.items():
            thermostat = []
            # TODO: Unused statement????
            # device = self.get_thermostat_from_id(loc_id)
            thermostat.append(location)
            thermostat.append(loc_id)
            if thermostat != []:
                thermostats.append(thermostat)
        data = [{k: v for k, v in zip(keys, n)} for n in thermostats]
        return data

    def get_device_data(self, dev_id, ctrl_id):
        """Provides the device-data, based on location_id, from APPLIANCES."""

        # Exception for Smile P1(v3) as it has only a ctrl device
        if self._smile_type == 'power':
            self.get_power_tariff()
            device_data = self.get_direct_objects_from_ctrl_id(ctrl_id)
        # Anna/Adam
        else:
            if ctrl_id:
                controller_data = self.get_appliance_from_appl_id(ctrl_id)
            device_data = {}
            if dev_id:
                device_data = self.get_appliance_from_loc_id(dev_id)
                preset = self.get_preset_from_id(dev_id)
                presets = self.get_presets_from_id(dev_id)
                schemas = self.get_schema_names_from_id(dev_id)
                last_used = self.get_last_active_schema_name_from_id(dev_id)
                a_sch = []
                l_sch = None
                s_sch = None
                if schemas:
                    for a, b in schemas.items():
                        a_sch.append(a)
                        if b:
                            s_sch = a
                if last_used:
                    l_sch = last_used
                if device_data is not None:
                    device_data.update({'active_preset': preset})
                    device_data.update({'presets':  presets})
                    device_data.update({'available_schedules': a_sch})
                    device_data.update({'selected_schedule': s_sch})
                    device_data.update({'last_used': l_sch})
                    if controller_data is not None:
                        device_data.update({'boiler_state': controller_data['boiler_state']})
                        device_data.update({'central_heating_state': controller_data['central_heating_state']})
                        device_data.update({'cooling_state': controller_data['cooling_state']})
                        device_data.update({'dhw_state': controller_data['dhw_state']})
            else:
                # Only fetch on controller, not device
                outdoor_temp = self.get_outdoor_temperature()
                illuminance = self.get_illuminance()

                device_data['type'] = 'heater_central'
                if 'boiler_temp' in controller_data:
                    device_data.update({'boiler_temp':
                                       controller_data['boiler_temp']})
                if 'water_pressure' in controller_data:
                    device_data.update({'water_pressure':
                                       controller_data['water_pressure']})
                device_data.update({'outdoor_temp': outdoor_temp})
                device_data.update({'illuminance': illuminance})
                device_data.update({'boiler_state':
                                   controller_data['boiler_state']})
                device_data.update({'central_heating_state':
                                   controller_data['central_heating_state']})
                device_data.update({'cooling_state':
                                   controller_data['cooling_state']})
                device_data.update({'dhw_state':
                                   controller_data['dhw_state']})

        return device_data

    def get_appliance_dictionary(self):
        """Obtains the existing appliance types and ids - from APPLIANCES."""
        appliance_dictionary = {}
        for appliance in self._appliances:
            appliance_name = appliance.find('name').text
            if "Gateway" not in appliance_name:
                appliance_id = appliance.attrib['id']
                appliance_type = appliance.find('type').text
                if appliance_type == 'heater_central':
                    appliance_dictionary[appliance_id] = appliance_type

        return appliance_dictionary

    def get_location_dictionary(self):
        """Obtains the existing locations and connected
           applicance_id's - from LOCATIONS."""
        location_dictionary = {}
        for location in self._locations:
            location_name = location.find('name').text
            location_id = location.attrib['id']
            # For P1(v3) all about Home, Anna/Adam should skip home
            if location_name != "Home" or self._smile_type != "thermostat":
                location_dictionary[location_id] = location_name

        return location_dictionary

    def get_thermostat_from_id(self, dev_id):
        """Obtains the main thermostat connected to the
           location_id - from APPLIANCES."""
        device_list = []
        temp_list = []
        appliances = self._appliances.findall('.//appliance')
        for appliance in appliances:
            appliance_type = appliance.find('type').text
            # TODO: unused variable?
            # appliance_id = appliance.attrib['id']
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
        """Obtains the appliance-data connected to a location -
           from APPLIANCES."""
        # TODO: unusde variabe
        # appliance_data = {}
        appliances = self._appliances.findall('.//appliance')
        appl_dict = {}
        appl_list = []
        locator_string = ".//logs/point_log[type='{}']/period/measurement"
        thermostatic_types = ['zone_thermostat',
                              'thermostatic_radiator_valve',
                              'thermostat']
        for appliance in appliances:
            if appliance.find('type') is not None:
                appliance_type = appliance.find('type').text
                if "gateway" not in appliance_type:
                    if appliance.find('location') is not None:
                        appl_location = appliance.find('location').attrib['id']
                        if appl_location == dev_id:
                            if appliance_type in thermostatic_types:
                                appl_dict['type'] = appliance_type
                                locator = locator_string.format('battery')
                                appl_dict['battery'] = None
                                if appliance.find(locator) is not None:
                                    battery = appliance.find(locator).text
                                    value = float(battery)
                                    battery = '{:.2f}'.format(round(value, 2))
                                    appl_dict['battery'] = battery
                                locator = locator_string.format('thermostat')
                                appl_dict['setpoint_temp'] = None
                                if appliance.find(locator) is not None:
                                    thermostat = appliance.find(locator).text
                                    thermostat = float(thermostat)
                                    appl_dict['setpoint_temp'] = thermostat
                                locator = locator_string.format('temperature')
                                appl_dict['current_temp'] = None
                                if appliance.find(locator) is not None:
                                    temperature = appliance.find(locator).text
                                    temperature = float(temperature)
                                    appl_dict['current_temp'] = temperature
                                appl_list.append(appl_dict.copy())

        # TODO: what is this???
        # the if statement doesn't do anything
        for dict in sorted(appl_list, key=lambda k: k['type'], reverse=True):
            if dict['type'] == "zone_thermostat":
                return dict
            else:
                return dict

    # Smile P1 specific
    def get_power_tariff(self):
        """Obtains power tariff information from Smile"""
        self._power_tariff = {}
        for t in TARIFF_MEASUREMENTS:
            locator = ("./gateway/gateway_environment/{}".format(t))
            self._power_tariff[t] = self._domain_objects.find(locator).text

        return True

    def get_direct_objects_from_ctrl_id(self, ctrl_id):
        """Obtains the appliance-data from appliances without a location
           - from DIRECT_OBJECTS."""
        direct_data = {}
        home_object = None
        for direct_object in self._direct_objects:
            direct_object_name = direct_object.find('name').text
            if "Home" in direct_object_name:
                home_object = direct_object.find('logs')

        if home_object is not None and self._power_tariff is not None:
            log_list = ['point_log', 'cumulative_log']
            peak_list = ['nl_peak']
            tariff_structure = 'electricity_consumption_tariff_structure'
            if self._power_tariff[tariff_structure] == 'double':
                peak_list.append('nl_offpeak')

            loc_string = ".//{}[type='{}']/period/measurement[@tariff='{}']"
            for measurement in POWER_MEASUREMENTS:
                for log_type in log_list:
                    for peak_select in peak_list:
                        locator = loc_string.format(log_type, measurement,
                                                    peak_select)
                        if home_object.find(locator) is not None:
                            peak = peak_select.split('_')[1]
                            log_type = log_type.split('_')[0]
                            key_string = '{}_{}_{}'.format(measurement,
                                                           peak, log_type)
                            val = float(home_object.find(locator).text)
                            direct_data[key_string] = val

        if direct_data != {}:
            return direct_data

    def get_appliance_from_appl_id(self, dev_id):
        """Obtains the appliance-data from appliances without a location -
           from APPLIANCES."""
        appl_data = {}
        loc_string = ".//logs/point_log[type='{}']/period/measurement"
        for appliance in self._appliances:
            appliance_name = appliance.find('name').text
            if "Gateway" not in appliance_name:
                appliance_id = appliance.attrib['id']
                if appliance_id == dev_id:
                    appliance_type = appliance.find('type').text
                    appl_data['type'] = appliance_type
                    boiler_temperature = None
                    loc = loc_string.format('boiler_temperature')
                    if appliance.find(loc) is not None:
                        measurement = appliance.find(loc).text
                        value = float(measurement)
                        boiler_temperature = '{:.1f}'.format(round(value, 1))
                        appl_data['boiler_temp'] = boiler_temperature
                    water_pressure = None
                    loc = loc_string.format('central_heater_water_pressure')
                    if appliance.find(loc) is not None:
                        measurement = appliance.find(loc).text
                        value = float(measurement)
                        water_pressure = '{:.1f}'.format(round(value, 1))
                        appl_data['water_pressure'] = water_pressure
                    direct_objects = self._direct_objects
                    appl_data['boiler_state'] = None
                    loc = loc_string.format('boiler_state')
                    if direct_objects.find(loc) is not None:
                        boiler_state = (direct_objects.find(loc).text == "on")
                        appl_data['boiler_state'] = boiler_state
                    appl_data['central_heating_state'] = None
                    loc = loc_string.format('central_heating_state')
                    if direct_objects.find(loc) is not None:
                        chs = (direct_objects.find(loc).text == "on")
                        appl_data['central_heating_state'] = chs
                    appl_data['cooling_state'] = None
                    loc = loc_string.format('cooling_state')
                    if direct_objects.find(loc) is not None:
                        cooling_state = (direct_objects.find(loc).text == "on")
                        appl_data['cooling_state'] = cooling_state
                    appl_data['dhw_state'] = None
                    loc = loc_string.format('domestic_hot_water_state')
                    if direct_objects.find(loc) is not None:
                        dhw_state = (direct_objects.find(loc).text == "on")
                        appl_data['dhw_state'] = dhw_state

        if appl_data != {}:
            return appl_data

    def get_preset_from_id(self, dev_id):
        """Obtains the active preset based on the location_id -
           from DOMAIN_OBJECTS."""
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
        # _LOGGER.debug("Plugwise locator and id: %s -> %s",locator,dev_id)
        rule_ids = self.get_rule_id_and_zone_location_by_template_tag_with_id(locator, dev_id)
        if rule_ids is None:
            rule_ids = self.get_rule_id_and_zone_location_by_name_with_id('Thermostat presets', dev_id)
            if rule_ids is None:
                return None

        presets = {}
        for key, val in rule_ids.items():
            if val == dev_id:
                presets = self.get_preset_dictionary(key)
        return presets

    def get_schema_names_from_id(self, dev_id):
        """Obtains the available schemas or schedules based on the
           location_id."""
        rule_ids = {}
        locator = 'zone_preset_based_on_time_and_presence_with_override'
        # _LOGGER.debug("Plugwise locator and id: %s -> %s",locator,dev_id)
        rule_ids = self.get_rule_id_and_zone_location_by_template_tag_with_id(locator, dev_id)
        schemas = {}
        l_schemas = {}
        if rule_ids:
            for key, val in rule_ids.items():
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
        # _LOGGER.debug("Plugwise locator and id: %s -> %s",locator,dev_id)
        rule_ids = self.get_rule_id_and_zone_location_by_template_tag_with_id(locator, dev_id)
        schemas = {}
        if rule_ids:
            for key, val in rule_ids.items():
                if val == dev_id:
                    schema_name = self._domain_objects.find("rule[@id='" + key + "']/name").text
                    schema_date = self._domain_objects.find("rule[@id='" + key + "']/modified_date").text
                    schema_time = parse(schema_date)
                    schemas[schema_name] = (schema_time - epoch).total_seconds()
                last_modified = sorted(schemas.items(), key=lambda kv: kv[1])[-1][0]
                return last_modified

    def get_rule_id_and_zone_location_by_template_tag_with_id(self, rule_name, dev_id):
        """Obtains the rule_id based on the given template_tag and
           location_id."""
        # _LOGGER.debug("Plugwise rule and id: %s -> %s",rule_name,dev_id)
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
        locator = (".//logs/point_log[type='outdoor_temperature']/period/measurement")
        if self._domain_objects.find(locator) is not None:
            measurement = self._domain_objects.find(locator).text
            value = float(measurement)
            value = float('{:.1f}'.format(round(value, 1)))
            return value

    def get_illuminance(self):
        """Obtain the illuminance value from the thermostat."""
        locator = (".//logs/point_log[type='illuminance']/period/measurement")
        if self._domain_objects.find(locator) is not None:
            measurement = self._domain_objects.find(locator).text
            value = float(measurement)
            value = float('{:.1f}'.format(round(value, 1)))
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

    async def set_schedule_state(self, loc_id, name, state):
        """Sets the schedule, with the given name, connected to a location, to true or false - DOMAIN_OBJECTS."""
        # _LOGGER.debug("Changing schedule state to: %s", state)
        schema_rule_ids = {}
        schema_rule_ids = self.get_rule_id_and_zone_location_by_name_with_id(str(name), loc_id)
        if not schema_rule_ids:
            return False
        for schema_rule_id, location_id in schema_rule_ids.items():
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

                await self.request(uri, method='put', data=data)

                # All get_schema related items check domain_objects so update that
                await asyncio.sleep(1)
                await self.update_domain_objects()

        return True

    async def set_preset(self, loc_id, preset):
        """Sets the given location-preset on the relevant thermostat -
           from LOCATIONS."""
        # _LOGGER.debug("Changing preset for %s - %s to: %s", loc_id, loc_type, preset)
        current_location = self._locations.find("location[@id='" + loc_id + "']")
        location_name = current_location.find('name').text
        location_type = current_location.find('type').text

        uri = "{};id={}".format(LOCATIONS, loc_id)

        data = "<locations>" \
            + '<location id="' \
            + loc_id \
            + '">' \
            + "<name>" \
            + location_name \
            + "</name>" \
            + "<type>" \
            + location_type \
            + "</type>" \
            + "<preset>" \
            + preset \
            + "</preset>" \
            + "</location>" \
            + "</locations>"

        await self.request(uri, method='put', data=data)

        # All get_preset related items check domain_objects so update that
        await asyncio.sleep(1)
        await self.update_domain_objects()

        return True

    async def set_temperature(self, dev_id, temperature):
        """Sends a temperature-set request to the relevant thermostat,
           connected to a location."""
        uri = self.__get_temperature_uri(dev_id)
        temperature = str(temperature)
        data = "<thermostat_functionality><setpoint>" \
               + temperature \
               + "</setpoint></thermostat_functionality>"

        if uri is not None:
            await self.request(uri, method='put', data=data)

        else:
            CouldNotSetTemperatureException("Could not obtain the temperature_uri.")
            return False

        await asyncio.sleep(1)
        await self.update_appliances()

        return True

    def __get_temperature_uri(self, dev_id):
        """Determine the location-set_temperature uri - from LOCATIONS."""
        locator = ("location[@id='{}']/actuator_functionalities/thermostat_functionality").format(dev_id)
        thermostat_functionality_id = self._locations.find(locator).attrib['id']

        temperature_uri = (LOCATIONS + ";id=" + dev_id + "/thermostat;id=" + thermostat_functionality_id)

        return temperature_uri

    @staticmethod
    def escape_illegal_xml_characters(xmldata):
        """Replace illegal &-characters."""
        return re.sub(r"&([^a-zA-Z#])", r"&amp;\1", xmldata)
