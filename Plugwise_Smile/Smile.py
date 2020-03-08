"""Plugwise Home Assistant component."""

import asyncio
import logging
import xml.etree.cElementTree as Etree
# Time related
import datetime as dt
import pytz
from dateutil.parser import parse
# For XML corrections
import re

import aiohttp
import async_timeout

SMILE_PING_ENDPOINT = "/ping"
SMILE_DIRECT_OBJECTS_ENDPOINT = "/core/direct_objects"
SMILE_DOMAIN_OBJECTS_ENDPOINT = "/core/domain_objects"
SMILE_LOCATIONS_ENDPOINT = "/core/locations"
SMILE_APPLIANCES = "/core/appliances"
SMILE_RULES = "/core/rules"

DEFAULT_TIMEOUT = 10
MIN_TIME_BETWEEN_UPDATES = dt.timedelta(seconds=2)

_LOGGER = logging.getLogger(__name__)

class Smile:
    """Define the Plugwise object."""
    # pylint: disable=too-many-instance-attributes, too-many-public-methods

    def __init__(
        self, host, password, username='smile', port=80, timeout=DEFAULT_TIMEOUT, websession=None, legacy_anna=False,
    ):
        """Set the constructor for this class."""

        if websession is None:
            async def _create_session():
                return aiohttp.ClientSession()

            loop = asyncio.get_event_loop()
            self.websession = loop.run_until_complete(_create_session())
        else:
            self.websession = websession

        self._auth=aiohttp.BasicAuth(username, password=password)

        self._legacy_anna = legacy_anna
        self._timeout = timeout
        self._endpoint = "http://" + host + ":" + str(port)
        self._throttle_time = None
        self._throttle_all_time = None
        self._domain_objects = None

    async def connect(self, retry=2):
        """Connect to Plugwise device."""
        # pylint: disable=too-many-return-statements
        url = self._endpoint + SMILE_PING_ENDPOINT
        try:
            with async_timeout.timeout(self._timeout):
                resp = await self.websession.get(url,auth=self._auth)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            if retry < 1:
                _LOGGER.error("Error connecting to Plugwise", exc_info=True)
                return False
            return await self.connect(retry - 1)

        result = await resp.text()
        if not 'error' in result:
            _LOGGER.error('Connected but expected text not returned, we got %s',result)
            return False

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

        return Etree.fromstring(self.escape_illegal_xml_characters(result))

    def sync_request(self, command, retry=2):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.request(command, retry))
        return loop.run_until_complete(task)

    async def update_domain_objects(self):
        """Request data."""
        self._domain_objects = await self.request(SMILE_DOMAIN_OBJECTS_ENDPOINT)

        #_LOGGER.debug("Plugwise data update_domain_objects: %s",self._domain_objects)

        return self._domain_objects

    def sync_update_domain_objects(self):
        """Request data."""
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.update_domain_objects())
        loop.run_until_complete(task)

    async def throttle_update_domain_objects(self):
        """Throttle update device."""
        if (self._throttle_time is not None
                and dt.datetime.now() - self._throttle_time < MIN_TIME_BETWEEN_UPDATES):
            return
        self._throttle_time = dt.datetime.now()
        await self.update_domain_objects()

    async def update_device(self):
        """Update device."""
        await self.throttle_update_domain_objects()

    async def find_all_appliances(self):
        """Find all Plugwise devices."""
        #await self.update_rooms()
        #await self.update_heaters()
        await self.update_domain_objects()

    @staticmethod
    def escape_illegal_xml_characters(xmldata):
        """Replace illegal &-characters."""
        return re.sub(r"&([^a-zA-Z#])", r"&amp;\1", xmldata)

    @staticmethod
    def get_point_log_id(xmldata, log_type):
        """Get the point log ID based on log type."""
        locator = (
            "module/services/*[@log_type='" + log_type + "']/functionalities/point_log"
        )
        if xmldata.find(locator) is not None:
            return xmldata.find(locator).attrib["id"]
        return None

    @staticmethod
    def get_measurement_from_point_log(xmldata, point_log_id):
        """Get the measurement from a point log based on point log ID."""
        locator = "*/logs/point_log[@id='" + point_log_id + "']/period/measurement"
        if xmldata.find(locator) is not None:
            return xmldata.find(locator).text
        return None

    def get_current_preset(self):
        """Get the current active preset."""
        if self._legacy_anna:
            active_rule = self._domain_objects.find("rule[active='true']/directives/when/then")
            if active_rule is None or "icon" not in active_rule.keys():
                return "none"
            return active_rule.attrib["icon"]

        log_type = "preset_state"
        locator = (
            "appliance[type='thermostat']/logs/point_log[type='"
            + log_type
            + "']/period/measurement"
        )
        return self._domain_objects.find(locator).text

    def get_schedule_temperature(self):
        """Get the temperature setting from the selected schedule."""
        point_log_id = self.get_point_log_id(self._domain_objects, "schedule_temperature")
        if point_log_id:
            measurement = self.get_measurement_from_point_log(self._domain_objects, point_log_id)
            if measurement:
                value = float(measurement)
                return value
        return None

    def get_current_temperature(self):
        """Get the curent (room) temperature from the thermostat - match to HA name."""
        current_temp_point_log_id = self.get_point_log_id(self._domain_objects, "temperature")
        if current_temp_point_log_id:
            measurement = self.get_measurement_from_point_log(
                self._domain_objects, current_temp_point_log_id
            )
            value = float(measurement)
            return value
        return None


class SmileException(Exception):
    """Define Exceptions."""

    def __init__(self, arg1, arg2=None):
        """Set the base exception for interaction with the Smile gateway."""
        self.arg1 = arg1
        self.arg2 = arg2
        super(SmileException, self).__init__(arg1)


class RuleIdNotFoundException(SmileException):
    """Raise an exception for when the rule id is not found in the direct objects."""

    pass


class CouldNotSetPresetException(SmileException):
    """Raise an exception for when the preset can not be set."""

    pass


class CouldNotSetTemperatureException(SmileException):
    """Raise an exception for when the temperature could not be set."""

    pass
