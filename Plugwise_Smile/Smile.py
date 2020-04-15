"""Plugwise Home Assistant module."""

import asyncio
import datetime as dt
import logging

# For XML corrections
import re

import aiohttp
import async_timeout

# Time related
import pytz

# Version detection
import semver
from dateutil.parser import parse
from lxml import etree

APPLIANCES = "/core/appliances"
DIRECT_OBJECTS = "/core/direct_objects"
DOMAIN_OBJECTS = "/core/domain_objects"
LOCATIONS = "/core/locations"
MODULES = "/core/modules"
RULES = "/core/rules"

DEFAULT_TIMEOUT = 20

_LOGGER = logging.getLogger(__name__)

HOME_MEASUREMENTS = {
    "electricity_consumed": "power",
    "electricity_produced": "power",
    "gas_consumed": "gas",
    "outdoor_temperature": "temperature",
}

# Excluded:
# zone_thermosstat 'temperature_offset'
# radiator_valve 'uncorrected_temperature', 'temperature_offset'
DEVICE_MEASUREMENTS = [
    "thermostat",  # HA setpoint
    "temperature",  # HA current_temperature
    "battery",
    "valve_position",
    "temperature_difference",
    "electricity_consumed",
    "electricity_produced",
    "relay",
    "outdoor_temperature",
    "domestic_hot_water_state",
    "boiler_temperature",
    "central_heating_state",
    "central_heater_water_pressure",
    "cooling_state",  # marcelveldt
    "boiler_state",  # a legacy Anna user has this as heating-is-on indication
    "slave_boiler_state",  # marcelveldt
    "compressor_state",  # marcelveldt
    "flame_state",  # added to reliably detect a gas-type local heater device
]

SMILES = {
    "smile_open_therm_v30": {"type": "thermostat", "friendly_name": "Adam",},
    "smile_open_therm_v23": {"type": "thermostat", "friendly_name": "Adam",},
    "smile_thermo_v40": {"type": "thermostat", "friendly_name": "Anna",},
    "smile_thermo_v31": {"type": "thermostat", "friendly_name": "Anna",},
    "smile_thermo_v18": {
        "type": "thermostat",
        "friendly_name": "Anna",
        "legacy": True,
    },
    "smile_v33": {"type": "power", "friendly_name": "P1",},
    "smile_v25": {"type": "power", "friendly_name": "P1", "legacy": True,},
}


class Smile:
    """Define the Plugwise object."""

    # pylint: disable=too-many-instance-attributes, too-many-public-methods

    def __init__(
        self,
        host,
        password,
        username="smile",
        port=80,
        timeout=DEFAULT_TIMEOUT,
        websession=None,
    ):
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
        self._home_location = None
        self._locations = None
        self._modules = None
        self._smile_subtype = None
        self._smile_legacy = False
        self._thermo_master_id = None

        self.gateway_id = None
        self.heater_id = None
        self.smile_name = None
        self.smile_type = None
        self.smile_version = ()

    async def connect(self, retry=2):
        """Connect to Plugwise device."""
        # pylint: disable=too-many-return-statements
        url = self._endpoint + DOMAIN_OBJECTS
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.get(url, auth=self._auth)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            if retry < 1:
                _LOGGER.error("Error connecting to Plugwise", exc_info=True)
                return False
            return await self.connect(retry - 1)

        result = await resp.text()

        if "<vendor_name>Plugwise</vendor_name>" not in result:
            if "<dsmrmain id" not in result:
                _LOGGER.error(
                    "Connected but expected text not returned, \
                              we got %s",
                    result,
                )
                return False

        # TODO creat this as another function NOT part of connect!
        # just using request to parse the data
        do_xml = etree.XML(self.escape_illegal_xml_characters(result).encode())
        gateway = do_xml.find(".//gateway")

        if gateway is None:
            # Assume legacy
            self._smile_legacy = True
            # Try if it is an Anna, assuming appliance thermostat
            anna = do_xml.find('.//appliance[type="thermostat"]')
            # Fake insert version assuming Anna
            # couldn't find another way to identify as legacy Anna
            smile_version = "1.8.0"
            smile_model = "smile_thermo"
            if anna is None:
                # P1 legacy
                if "<dsmrmain id" in result:
                    # Fake insert version assuming P1
                    # yes we could get this from system_status
                    smile_version = "2.5.9"
                    smile_model = "smile"
                else:
                    _LOGGER.error("Connected but no gateway device information found")
                    return False

            _LOGGER.debug("Assuming legacy device")

        if not self._smile_legacy:
            smile_model = do_xml.find(".//gateway/vendor_model").text
            smile_version = do_xml.find(".//gateway/firmware_version").text

        if smile_model is None or smile_version is None:
            _LOGGER.error("Unable to find model or version information")
            return False

        _LOGGER.debug("Plugwise model %s version %s", smile_model, smile_version)
        ver = semver.parse(smile_version)

        target_smile = "{}_v{}{}".format(smile_model, ver["major"], ver["minor"])
        if target_smile not in SMILES:
            _LOGGER.error(
                'Your version Smile type "{}" with version "{}" \
                          seems unsupported by our plugin, please create \
                          an issue on github.com/plugwise/Plugwise-Smile!\
                          '.format(
                    smile_model, smile_version
                )
            )
            return False

        self.smile_name = SMILES[target_smile]["friendly_name"]
        self.smile_type = SMILES[target_smile]["type"]
        self.smile_version = (smile_version, ver)

        if "legacy" in SMILES[target_smile]:
            self._smile_legacy = SMILES[target_smile]["legacy"]

        # Update all endpoints on first connect
        await self.full_update_device()

        return True

    async def close_connection(self):
        """Close the Plugwise connection."""
        await self.websession.close()

    async def request(
        self,
        command,
        retry=3,
        method="get",
        data={},
        headers={"Content-type": "text/xml"},
    ):
        """Request data."""
        # pylint: disable=too-many-return-statements

        url = self._endpoint + command

        try:
            with async_timeout.timeout(self._timeout):
                if method == "get":
                    resp = await self.websession.get(url, auth=self._auth)
                if method == "put":
                    resp = await self.websession.put(
                        url, data=data, headers=headers, auth=self._auth
                    )
        except asyncio.TimeoutError:
            if retry < 1:
                _LOGGER.error("Timed out sending command to Plugwise: %s", command)
                return None
            return await self.request(command, retry - 1)
        except aiohttp.ClientError:
            _LOGGER.error(
                "Error sending command to Plugwise: %s", command, exc_info=True
            )
            return None

        result = await resp.text()

        _LOGGER.debug(
            "Plugwise network traffic to %s- talking to Smile with \
                      %s",
            self._endpoint,
            command,
        )

        if not result or "error" in result:
            return None

        # Encode to ensure utf8 parsing
        return etree.XML(self.escape_illegal_xml_characters(result).encode())

    async def update_appliances(self):
        """Request appliance data."""
        if self._smile_legacy and self.smile_type == "power":
            return True

        new_data = await self.request(APPLIANCES)
        if new_data is not None:
            self._appliances = new_data

    async def update_direct_objects(self):
        """Request direct_objects data."""
        if self._smile_legacy and self.smile_type == "power":
            return True

        new_data = await self.request(DIRECT_OBJECTS)
        if new_data is not None:
            self._direct_objects = new_data

    async def update_domain_objects(self):
        """Request domain_objects data."""
        new_data = await self.request(DOMAIN_OBJECTS)
        if new_data is not None:
            self._domain_objects = new_data

    async def update_locations(self):
        """Request locations data."""
        new_data = await self.request(LOCATIONS)
        if new_data is not None:
            self._locations = new_data

    async def full_update_device(self):
        """Update all XML data from device."""
        await self.update_appliances()
        await self.update_direct_objects()
        await self.update_domain_objects()
        await self.update_locations()
        return True

    def _types_finder(self, data):
        """Detect types within locations from logs."""
        types = set([])
        for measure, measure_type in HOME_MEASUREMENTS.items():
            locator = './/logs/point_log[type="{}"]'.format(measure)
            if data.find(locator):
                log = data.find(locator)

                if measure == "outdoor_temperature":
                    types.add(measure_type)

                p_locator = ".//electricity_point_meter"
                if log.find(p_locator) is not None:
                    if log.find(p_locator).get("id"):
                        types.add(measure_type)

        return types

    def get_all_appliances(self):
        """Determine available appliances from inventory."""
        appliances = {}

        locations, home_location = self.get_all_locations()

        if self._smile_legacy and self.smile_type == "power":
            """
            Inject home_location as dev_id for legacy.

            get_appliance_data can use loc_id for dev_id
            """
            appliances[self._home_location] = {
                "name": "Smile P1",
                "types": set(["power", "home"]),
                "class": "gateway",
                "location": home_location,
            }
            return appliances

        # TODO: add locations with members as appliance as well
        # example 'electricity consumed/produced and relay' on Adam
        # Basically walk locations for 'members' not set[] and
        # scan for the same functionality

        # Find gateway and heater devices
        for appliance in self._appliances:
            if appliance.find("type").text == "gateway":
                self.gateway_id = appliance.attrib["id"]
            if appliance.find("type").text == "heater_central":
                self.heater_id = appliance.attrib["id"]

        # for legacy it is the same device
        if self._smile_legacy and self.smile_type == "thermostat":
            self.gateway_id = self.heater_id

        for appliance in self._appliances:
            appliance_location = None
            appliance_types = set([])

            appliance_id = appliance.attrib["id"]
            appliance_class = appliance.find("type").text
            appliance_name = appliance.find("name").text

            # Nothing useful in opentherm so skip it
            if appliance_class == "open_therm_gateway":
                continue

            # Appliance with location (i.e. a device)
            if appliance.find("location") is not None:
                appliance_location = appliance.find("location").attrib["id"]
                for appl_type in self._types_finder(appliance):
                    appliance_types.add(appl_type)
            else:
                # Return all types applicable to home
                appliance_types = locations[home_location]["types"]
                # If heater or gatweay override registering
                if appliance_class == "heater_central":
                    appliance_id = self.heater_id
                    appliance_name = self.smile_name
                if appliance_class == "gateway":
                    appliance_id = self.gateway_id
                    appliance_name = self.smile_name

            # Determine appliance_type from funcitonality
            if appliance.find(".//actuator_functionalities/relay_functionality"):
                appliance_types.add("plug")
            elif appliance.find(".//actuator_functionalities/thermostat_functionality"):
                appliance_types.add("thermostat")

            appliances[appliance_id] = {
                "name": appliance_name,
                "types": appliance_types,
                "class": appliance_class,
                "location": appliance_location,
            }
        return appliances

    def get_all_locations(self):
        """Determine available locations from inventory."""
        home_location = None
        locations = {}
        # Legacy Anna has no locations, create one containing all appliances
        if len(self._locations) == 0 and self._smile_legacy:
            appliances = set([])
            home_location = 0

            # Add Anna appliances
            for appliance in self._appliances:
                appliances.add(appliance.attrib["id"])

            locations[0] = {
                "name": "Legacy",
                "types": set(["temperature"]),
                "members": appliances,
            }
            return locations, home_location

        for location in self._locations:
            location_name = location.find("name").text
            location_id = location.attrib["id"]
            location_types = set([])
            location_members = set([])

            # Group of appliances
            locator = ".//appliances/appliance"
            if location.find(locator) is not None:
                for member in location.findall(locator):
                    location_members.add(member.attrib["id"])

            if location_name == "Home":
                home_location = location_id
                location_types.add("home")

                for location_type in self._types_finder(location):
                    location_types.add(location_type)

            # Legacy P1 right location has 'services' filled
            # test data has 5 for example
            locator = ".//services"
            if self._smile_legacy and len(location.find(locator)) > 0:
                # Override location name found to match
                location_name = "Home"
                home_location = location_id
                location_types.add("home")
                location_types.add("power")

            locations[location_id] = {
                "name": location_name,
                "types": location_types,
                "members": location_members,
            }

        self._home_location = home_location
        return locations, home_location

    def single_master_thermostat(self):
        """Is there a single master thermostats in the system?"""
        count = 0
        locations, home_location = self.scan_thermostats()
        for item, data in locations.items():
            if "master_prio" in data:
                count += 1
        
        if count == 0:
            single_mr_therm = None
        elif count == 1:
            single_mr_therm = True
        else:
            single_mr_therm = False

        return single_mr_therm    

    def scan_thermostats(self, debug_text="missing text"):
        """Update locations with actual master/slave thermostats."""
        locations, home_location = self.match_locations()
        appliances = self.get_all_appliances()

        thermo_matching = {
            "thermostat": 3,
            "zone_thermostat": 2,
            "thermostatic_radiator_valve": 1,
        }

        high_prio = 0
        for loc_id, location_details in locations.items():
            locations[loc_id] = location_details

            if "thermostat" in location_details["types"] and loc_id != home_location:
                locations[loc_id].update(
                    {"master": None, "master_prio": 0, "slaves": set([])}
                )
            elif loc_id == 0 and self._smile_legacy:
                locations[loc_id].update(
                    {"master": None, "master_prio": 0, "slaves": set([])}
                )
            else:
                _LOGGER.debug(
                    "skipping ",
                    location_details["name"],
                    " types ",
                    location_details["types"],
                )
                continue

            for appliance_id, appliance_details in appliances.items():

                a_class = appliance_details["class"]
                if loc_id == appliance_details["location"]:
                    if a_class in thermo_matching:

                        # Pre-elect new master
                        if thermo_matching[a_class] > locations[loc_id]["master_prio"]:

                            # Demote former master
                            if locations[loc_id]["master"] is not None:
                                locations[loc_id]["slaves"].add(
                                    locations[loc_id]["master"]
                                )

                            # Crown master
                            locations[loc_id]["master_prio"] = thermo_matching[a_class]
                            locations[loc_id]["master"] = appliance_id

                        else:
                            locations[loc_id]["slaves"].add(appliance_id)

                # Find highest ranking thermostat
                if a_class in thermo_matching:
                    if thermo_matching[a_class] > high_prio:
                        high_prio = thermo_matching[a_class]
                        self._thermo_master_id = appliance_id

            if locations[loc_id]["master"] is None:
                _LOGGER.debug(
                    "Location ", location_details["name"], " has no (master) thermostat"
                )

        # Return location including slaves
        return locations, home_location

    def match_locations(self):
        """Update locations with used types of appliances."""
        match_locations = {}

        locations, home_location = self.get_all_locations()
        appliances = self.get_all_appliances()

        for location_id, location_details in locations.items():
            for appliance_id, appliance_details in appliances.items():
                if appliance_details["location"] == location_id:
                    for appl_type in appliance_details["types"]:
                        location_details["types"].add(appl_type)

            match_locations[location_id] = location_details

        return match_locations, home_location

    def get_all_devices(self):
        """Determine available devices from inventory."""
        devices = {}

        appliances = self.get_all_appliances()
        # locations, home_location = self.get_all_locations()
        thermo_locations, home_location = self.scan_thermostats()

        for appliance, details in appliances.items():
            loc_id = details["location"]
            if loc_id is None:
                details["location"] = home_location

            # Override slave thermostat class
            if loc_id in thermo_locations:
                if "slaves" in thermo_locations[loc_id]:
                    if appliance in thermo_locations[loc_id]["slaves"]:
                        details["class"] = "thermo_sensor"

            devices[appliance] = details
        return devices

    def get_device_data(self, dev_id):
        """Provide device-data, based on location_id, from APPLIANCES."""
        devices = self.get_all_devices()
        if dev_id in devices:
            details = devices[dev_id]

        thermostat_classes = [
            "thermostat",
            "zone_thermostat",
            "thermostatic_radiator_valve",
        ]

        device_data = self.get_appliance_data(dev_id)

        # Anna, Lisa, Tom/Floor
        if details["class"] in thermostat_classes:
            device_data["active_preset"] = self.get_preset(details["location"])
            device_data["presets"] = self.get_presets(details["location"])

            avail_schemas, sel_schema = self.get_schemas(details["location"])
            device_data["available_schedules"] = avail_schemas
            device_data["selected_schedule"] = sel_schema
            if self._smile_legacy:
                device_data["last_used"] = "".join(map(str, avail_schemas))
            else:
                device_data["last_used"] = self.get_last_active_schema(
                    details["location"]
                )

        # Anna specific
        if details["class"] in ["thermostat"]:
            device_data["illuminance"] = self.get_object_value(
                "appliance", dev_id, "illuminance"
            )

        # Generic
        if details["class"] == "gateway" or dev_id == self.gateway_id:

            # Try to get P1 data
            power_data = self.get_direct_objects_from_location(details["location"])
            if power_data is not None:
                device_data.update(power_data)

            outdoor_temperature = self.get_object_value(
                "location", self._home_location, "outdoor_temperature"
            )
            if outdoor_temperature:
                device_data["outdoor_temperature"] = outdoor_temperature

        return device_data

    def get_appliance_data(self, dev_id):
        """
        Obtain the appliance-data connected to a location.

        Determined from APPLIANCES or legacy DOMAIN_OBJECTS.
        """
        data = {}
        search = self._appliances

        if self._smile_legacy and self.smile_type == "power":
            search = self._domain_objects

        appliances = search.findall('.//appliance[@id="{}"]'.format(dev_id))

        p_locator = ".//logs/point_log[type='{}']/period/measurement"
        i_locator = ".//logs/interval_log[type='{}']/period/measurement"
        c_locator = ".//logs/cumulative_log[type='{}']/period/measurement"

        for appliance in appliances:
            for measurement in DEVICE_MEASUREMENTS:

                pl_value = p_locator.format(measurement)
                if appliance.find(pl_value) is not None:
                    if self._smile_legacy and measurement == "domestic_hot_water_state":
                        measure = "off"
                    else:
                        measure = appliance.find(pl_value).text

                    data[measurement] = self._format_measure(measure)

                il_value = i_locator.format(measurement)
                if appliance.find(il_value) is not None:
                    measurement = "{}_interval".format(measurement)
                    measure = appliance.find(il_value).text

                    data[measurement] = self._format_measure(measure)
                cl_value = c_locator.format(measurement)
                if appliance.find(cl_value) is not None:
                    measurement = "{}_cumulative".format(measurement)
                    measure = appliance.find(cl_value).text

                    data[measurement] = self._format_measure(measure)

        return data

    def _format_measure(self, measure):
        """Format measure to correct type."""
        try:
            measure = int(measure)
        except ValueError:
            try:
                measure = float("{:.2f}".format(round(float(measure), 2)))
            except ValueError:
                if measure == "on":
                    measure = True
                elif measure == "off":
                    measure = False
        return measure

    def get_direct_objects_from_location(self, loc_id):
        """
        Obtain the appliance-data from appliances without a location.

        Determined from DIRECT_OBJECTS.
        """
        direct_data = {}
        search = self._direct_objects
        t_string = "tariff"

        if self._smile_legacy and self.smile_type == "power":
            search = self._domain_objects
            t_string = "tariff_indicator"

        loc_logs = search.find(".//location[@id='{}']/logs".format(loc_id))

        if loc_logs is not None:
            log_list = ["point_log", "cumulative_log", "interval_log"]
            peak_list = ["nl_peak", "nl_offpeak"]

            tariff_structure = "electricity_consumption_tariff_structure"

            lt_string = ".//{}[type='{}']/period/measurement[@{}=\"{}\"]"
            l_string = ".//{}[type='{}']/period/measurement"
            # meter_string = ".//{}[type='{}']/"
            for measurement in HOME_MEASUREMENTS:
                for log_type in log_list:
                    for peak_select in peak_list:
                        locator = lt_string.format(
                            log_type, measurement, t_string, peak_select
                        )

                        # Only once try to find P1 Legacy values
                        if (
                            loc_logs.find(locator) is None
                            and self.smile_type == "power"
                        ):
                            locator = l_string.format(log_type, measurement)

                            # Skip peak if not split (P1 Legacy)
                            if peak_select == "nl_offpeak":
                                continue

                        if loc_logs.find(locator) is not None:
                            peak = peak_select.split("_")[1]
                            if peak == "offpeak":
                                peak = "off_peak"
                            log_found = log_type.split("_")[0]
                            key_string = f"{measurement}_{peak}_{log_found}"
                            if "gas" in measurement:
                                key_string = f"{measurement}_{log_found}"
                            net_string = f"net_electricity_{log_found}"
                            val = float(loc_logs.find(locator).text)

                            # Energy differential
                            if "electricity" in measurement:
                                diff = 1
                                if "produced" in measurement:
                                    diff = -1
                                if net_string not in direct_data:
                                    direct_data[net_string] = float()
                                direct_data[net_string] += float(val * diff)

                            direct_data[key_string] = val

        if direct_data != {}:
            return direct_data

    def get_preset(self, loc_id):
        """
        Obtain the active preset based on the location_id.

        Determined from DOMAIN_OBJECTS.
        """
        if self._smile_legacy:
            active_rule = self._domain_objects.find(
                "rule[active='true']/directives/when/then"
            )
            if active_rule is not None:
                if "icon" in active_rule.keys():
                    return active_rule.attrib["icon"]

        locator = ".//location[@id='{}']/preset".format(loc_id)
        preset = self._domain_objects.find(locator)
        if preset is not None:
            return preset.text

    def get_presets(self, loc_id):
        """Get the presets from the thermostat based on location_id."""
        presets = {}
        tag = "zone_setpoint_and_state_based_on_preset"

        if self._smile_legacy:
            return self.__get_presets_legacy()

        # _LOGGER.debug("Plugwise locator and id: %s -> %s",locator,dev_id)
        rule_ids = self.get_rule_ids_by_tag(tag, loc_id)
        if rule_ids is None:
            rule_ids = self.get_rule_ids_by_name("Thermostat presets", loc_id)
            if rule_ids is None:
                return None

        for rule_id in rule_ids:
            directives = self._domain_objects.find(
                "rule[@id='{}']/directives".format(rule_id)
            )

            for directive in directives:
                preset = directive.find("then").attrib
                keys, values = zip(*preset.items())
                if str(keys[0]) == "setpoint":
                    presets[directive.attrib["preset"]] = [float(preset["setpoint"]), 0]
                else:
                    presets[directive.attrib["preset"]] = [
                        float(preset["heating_setpoint"]),
                        float(preset["cooling_setpoint"]),
                    ]

        return presets

    def get_schemas(self, loc_id):
        """Obtain the available schemas or schedules based on the location_id."""
        rule_ids = {}
        schemas = {}
        available = []
        selected = None

        if self._smile_legacy:  # Only one schedule allowed
            schedules = self._domain_objects.findall(".//rule")
            name = None
            for schema in schedules:
                rule_name = schema.find("name").text
                if rule_name:
                    if "preset" not in rule_name:
                        name = rule_name

            log_type = "schedule_state"
            locator = (
                "appliance[type='thermostat']/logs/point_log[type='"
                + log_type
                + "']/period/measurement"
            )
            active = False
            if self._domain_objects.find(locator) is not None:
                active = self._domain_objects.find(locator).text == "on"

            if name is not None:
                schemas[name] = active

        else:
            tag = "zone_preset_based_on_time_and_presence_with_override"
            rule_ids = self.get_rule_ids_by_tag(tag, loc_id)
            if rule_ids is not None:
                for rule_id, location_id in rule_ids.items():
                    if location_id == loc_id:
                        active = False
                        name = self._domain_objects.find(
                            "rule[@id='{}']/name".format(rule_id)
                        ).text
                        if (
                            self._domain_objects.find(
                                "rule[@id='{}']/active".format(rule_id)
                            ).text
                            == "true"
                        ):
                            active = True
                        schemas[name] = active

        for a, b in schemas.items():
            available.append(a)
            if b:
                selected = a

        return available, selected

    def get_last_active_schema(self, loc_id):
        """Determine the last active schema."""
        epoch = dt.datetime(1970, 1, 1, tzinfo=pytz.utc)
        rule_ids = {}
        schemas = {}
        last_modified = None

        tag = "zone_preset_based_on_time_and_presence_with_override"

        rule_ids = self.get_rule_ids_by_tag(tag, loc_id)
        if rule_ids is not None:
            for rule_id, location_id in rule_ids.items():
                if location_id == loc_id:
                    schema_name = self._domain_objects.find(
                        "rule[@id='{}']/name".format(rule_id)
                    ).text
                    schema_date = self._domain_objects.find(
                        "rule[@id='{}']/modified_date".format(rule_id)
                    ).text
                    schema_time = parse(schema_date)
                    schemas[schema_name] = (schema_time - epoch).total_seconds()

            last_modified = sorted(schemas.items(), key=lambda kv: kv[1])[-1][0]

        return last_modified

    def get_rule_ids_by_tag(self, tag, loc_id):
        """Obtain the rule_id based on the given template_tag and location_id."""
        schema_ids = {}
        rules = self._domain_objects.findall(".//rule")
        locator1 = './/template[@tag="{}"]'.format(tag)
        locator2 = './/contexts/context/zone/location[@id="{}"]'.format(loc_id)
        for rule in rules:
            if rule.find(locator1) is not None and rule.find(locator2) is not None:
                schema_ids[rule.attrib["id"]] = loc_id
        if schema_ids != {}:
            return schema_ids

    def get_rule_ids_by_name(self, name, loc_id):
        """Obtain the rule_id on the given name and location_id."""
        schema_ids = {}
        rules = self._domain_objects.findall('.//rule[name="{}"]'.format(name))
        locator = './/contexts/context/zone/location[@id="{}"]'.format(loc_id)
        for rule in rules:
            if rule.find(locator) is not None:
                schema_ids[rule.attrib["id"]] = loc_id
        if schema_ids != {}:
            return schema_ids

    def get_object_value(self, obj_type, appl_id, measurement):
        """Obtain the illuminance value from the thermostat."""
        search = self._direct_objects

        if self._smile_legacy and self.smile_type == "power":
            search = self._domain_objects

        locator = ".//{}[@id='{}']/logs/point_log[type='{}']/period/measurement".format(
            obj_type, appl_id, measurement
        )

        if search.find(locator) is not None:
            data = search.find(locator).text
            val = float(data)
            val = float("{:.1f}".format(round(val, 1)))
            return val

    async def set_schedule_state(self, loc_id, name, state):
        """
        Set the schedule, with the given name, connected to a location.

        Determined from - DOMAIN_OBJECTS.
        """
        if self._smile_legacy:
            return await self.set_schedule_state_legacy(name, state)

        schema_rule_ids = self.get_rule_ids_by_name(str(name), loc_id)
        if schema_rule_ids == {} or schema_rule_ids is None:
            return False
        for schema_rule_id, location_id in schema_rule_ids.items():
            if location_id == loc_id:
                templates = self._domain_objects.findall(
                    ".//*[@id='{}']/template".format(schema_rule_id)
                )
                template_id = None
                for rule in templates:
                    template_id = rule.attrib["id"]

                uri = "{};id={}".format(RULES, schema_rule_id)

                state = str(state)
                data = (
                    '<rules><rule id="{}"><name><![CDATA[{}]]></name>'
                    '<template id="{}" /><active>{}</active></rule>'
                    "</rules>".format(schema_rule_id, name, template_id, state)
                )

                await self.request(uri, method="put", data=data)

        return True

    async def set_preset(self, loc_id, preset):
        """Set the given location-preset on the relevant thermostat - from LOCATIONS."""
        if self._smile_legacy:
            return await self.set_preset_legacy(preset)

        current_location = self._locations.find("location[@id='{}']".format(loc_id))
        location_name = current_location.find("name").text
        location_type = current_location.find("type").text

        if preset not in self.get_presets(loc_id):
            return False

        uri = "{};id={}".format(LOCATIONS, loc_id)

        data = (
            "<locations>"
            + '<location id="'
            + loc_id
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
            + "</locations>"
        )

        if uri is not None:
            await self.request(uri, method="put", data=data)
        else:
            return False

        return True

    async def set_temperature(self, loc_id, temperature):
        """Send temperature-set request to the locations thermostat."""
        uri = self.__get_temperature_uri(loc_id)
        temperature = str(temperature)
        data = (
            "<thermostat_functionality><setpoint>"
            + temperature
            + "</setpoint></thermostat_functionality>"
        )

        if uri is not None:
            await self.request(uri, method="put", data=data)
        else:
            return False

        return True

    def __get_temperature_uri(self, loc_id):
        """Determine the location-set_temperature uri - from LOCATIONS."""
        if self._smile_legacy:
            return self.__get_temperature_uri_legacy()

        locator = (
            "location[@id='{}']/actuator_functionalities/thermostat_functionality"
        ).format(loc_id)
        thermostat_functionality_id = self._locations.find(locator).attrib["id"]

        temperature_uri = (
            LOCATIONS
            + ";id="
            + loc_id
            + "/thermostat;id="
            + thermostat_functionality_id
        )

        return temperature_uri

    async def set_relay_state(self, appl_id, state):
        """Switch the Plug to off/on."""
        locator = "appliance[@id='{}']/actuator_functionalities/relay_functionality".format(
            appl_id
        )
        relay_functionality_id = self._appliances.find(locator).attrib["id"]
        uri = APPLIANCES + ";id=" + appl_id + "/relay;id=" + relay_functionality_id
        state = str(state)
        data = "<relay_functionality><state>{}</state></relay_functionality>".format(
            state
        )

        if uri is not None:
            await self.request(uri, method="put", data=data)
        else:
            return False

        return True

    @staticmethod
    def escape_illegal_xml_characters(xmldata):
        """Replace illegal &-characters."""
        return re.sub(r"&([^a-zA-Z#])", r"&amp;\1", xmldata)

    # LEGACY Anna functions

    def __get_presets_legacy(self):
        """Get presets from domain_objects for legacy Smile."""
        preset_dictionary = {}
        directives = self._domain_objects.findall("rule/directives/when/then")
        for directive in directives:
            if directive is not None and "icon" in directive.keys():
                # Ensure list of heating_setpoint, cooling_setpoint
                preset_dictionary[directive.attrib["icon"]] = [
                    float(directive.attrib["temperature"]),
                    0,
                ]
        return preset_dictionary

    async def set_preset_legacy(self, preset):
        """Set the given preset on the thermostat - from DOMAIN_OBJECTS."""
        locator = "rule/directives/when/then[@icon='{}'].../.../...".format(preset)
        rule = self._domain_objects.find(locator)
        if rule is None:
            return False

        uri = "{}".format(RULES)

        data = (
            "<rules>"
            + '<rule id="'
            + rule.attrib["id"]
            + '">'
            + "<active>true</active>"
            + "</rule>"
            + "</rules>"
        )

        await self.request(uri, method="put", data=data)

        return True

    def __get_temperature_uri_legacy(self):
        """Determine the location-set_temperature uri - from APPLIANCES."""
        locator = ".//appliance[type='thermostat']"
        appliance_id = self._appliances.find(locator).attrib["id"]
        return APPLIANCES + ";id=" + appliance_id + "/thermostat"

    async def set_schedule_state_legacy(self, name, state):
        """Send a set request to the schema with the given name."""
        rules = self._domain_objects.findall("rule")
        schema_rule_id = None
        for rule in rules:
            if rule.find("name").text == name:
                schema_rule_id = rule.attrib["id"]

        if schema_rule_id is not None:
            templates = self._domain_objects.findall(
                ".//*[@id='{}']/template".format(schema_rule_id)
            )
            template_id = None
            for rule in templates:
                template_id = rule.attrib["id"]

            uri = "{};id={}".format(RULES, schema_rule_id)

            state = str(state)
            data = (
                '<rules><rule id="{}"><name><![CDATA[{}]]></name>'
                '<template id="{}" /><active>{}</active></rule>'
                "</rules>".format(schema_rule_id, name, template_id, state)
            )

            await self.request(uri, method="put", data=data)
            return True
        else:
            return False

    # LEGACY P1 functions
