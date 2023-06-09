"""Track packages from dbschenker via api"""
from urllib.parse import urlparse
import json
import logging
from datetime import timedelta

import requests

import voluptuous as vol

# For StringIO
import io

# For parsing print_r
import re

#from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    STATE_UNKNOWN,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util.json import load_json
from homeassistant.helpers.json import save_json
from homeassistant.util import Throttle
from homeassistant.helpers.entity_component import EntityComponent


_LOGGER = logging.getLogger(__name__)

DOMAIN = "dbschenker"

REGISTRATIONS_FILE = "dbschenker.conf"

SERVICE_REGISTER = "register"
SERVICE_UNREGISTER = "unregister"

ICON = "mdi:package-variant-closed"
SCAN_INTERVAL = timedelta(seconds=1800)

ATTR_PACKAGE_ID = "package_id"

SUBSCRIPTION_SCHEMA = vol.All(
    {
        vol.Required(ATTR_PACKAGE_ID): cv.string,
    }
)

ENTITY_ID_FORMAT = DOMAIN + ".{}"

DBSCHENKER_API_URL = 'https://skicka.dbschenker.com/schenker_se/tracking_interface/handle_request.php?reference_type=*PKG&reference_number={}&language=sv&output=xml'


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Setup the dbschenker sensor"""
    component = hass.data.get(DOMAIN)

    update_interval = config.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)

    # Use the EntityComponent to track all packages, and create a group of them
    if component is None:
        component = hass.data[DOMAIN] = EntityComponent(_LOGGER, DOMAIN, hass,
                update_interval)

    json_path = hass.config.path(REGISTRATIONS_FILE)

    registrations = _load_config(json_path)

    async def async_service_register(service):
        """Handle package registration."""
        package_id = service.data.get(ATTR_PACKAGE_ID).upper()

        if package_id in registrations:
            raise ValueError("Package allready tracked")

        registrations.append(package_id)

        await hass.async_add_job(save_json, json_path, registrations)

        return await component.async_add_entities([DbSchenkerSensor(hass, package_id)])

    hass.services.async_register(
        DOMAIN,
        SERVICE_REGISTER,
        async_service_register,
        schema=SUBSCRIPTION_SCHEMA,
    )

    async def async_service_unregister(service):
        """Handle package registration."""
        package_id = service.data.get(ATTR_PACKAGE_ID)

        registrations.remove(package_id)

        await hass.async_add_job(save_json, json_path, registrations)

        entity_id = ENTITY_ID_FORMAT.format(package_id.lower())

        return await component.async_remove_entity(entity_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_UNREGISTER,
        async_service_unregister,
        schema=SUBSCRIPTION_SCHEMA,
    )

    if registrations is None:
        return None

    return await component.async_add_entities([DbSchenkerSensor(hass, package_id) for package_id in registrations], False)


def _load_config(filename):
    """Load configuration."""
    try:
        return load_json(filename, [])
    except HomeAssistantError:
        pass
    return []


class DbSchenkerSensor(RestoreEntity):
    """DbSchenker Sensor."""

    def __init__(self, hass, package_id):
        """Initialize the sensor."""
        self.hass = hass
        self._package_id = package_id
        self._attributes = None
        self._state = None
        self._data = None

    @property
    def entity_id(self):
        """Return the entity_id of the sensor"""
        return ENTITY_ID_FORMAT.format(self._package_id.lower())

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Package {}".format(self._package_id)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    @property
    def icon(self):
        """Icon to use in the frontend."""
        return ICON

    RE_KV = re.compile(r'^\s*\[([^\]]+)\] => (.*)$')

    def _parse_array(self, data):
        # Decended into darkness
        parsed = {}

        line = data.readline()
        if not line.endswith('(\n'):
            raise Exception("Expected (, got: ", line)

        #[hittype] => singlehit
        line = data.readline()

        while not line.endswith(')\n'):
            if match := self.RE_KV.match(line):
                key = match.group(1)
                value = match.group(2)

                if value == 'Array':
                    parsed[key] = self._parse_array(data)
                elif value == '':
                    parsed[key] = None
                else:
                    parsed[key] = value

            line = data.readline()

        # Remove empty line
        line = data.readline()

        # The end is here
        return parsed

    def _parse_print_r(self, data):

        line = data.readline()

        if line != 'Array\n': 
            raise Exception("Expected Array, got: ", line)
        # ok, normal start.

        # Everythings array in php...
        return self._parse_array(data)

    def update(self):
        """Update sensor state."""
        response = requests.get(DBSCHENKER_API_URL.format(
            self._package_id), timeout=10)

        if response.status_code != 200:
            _LOGGER.error("API returned {}".format(response.status_code))
            return

        with io.StringIO() as f:
            f.write(response.text)
            f.seek(0)

            response = response = self._parse_print_r(f)

        if "hittype" not in response or "singlehit" not in response:
            _LOGGER.error("API returned unknown json structure")
            return

        if response["hittype"] != "singlehit":
            _LOGGER.error("API returned odd hittype")
            _LOGGER.error(response)

        if response["singlehit"]["pkg_number"] == self._package_id:
            shipment = response["singlehit"]

            # Found the right shipment
            self._attributes = {}
            self._attributes["from"] = shipment.get("from", {}).get("customername", STATE_UNKNOWN)
            self._attributes["type"] = shipment.get("product_name", STATE_UNKNOWN)

            self._attributes["delivery_date"] = shipment.get("delivery_date", STATE_UNKNOWN)
            self._attributes["delivery_time"] = shipment.get("delivery_time", STATE_UNKNOWN)

            self._attributes["weight"] = shipment.get("weight", STATE_UNKNOWN)
            self._attributes["height"] = shipment.get("height", STATE_UNKNOWN)
            self._attributes["width"] = shipment.get("width", STATE_UNKNOWN)
            self._attributes["length"] = shipment.get("length", STATE_UNKNOWN)

            if "events" in shipment and "0" in shipment["events"]:
                event = shipment["events"]["0"]
                self._attributes["location"] = event.get("location", STATE_UNKNOWN)
                self._state = event.get("short_description", STATE_UNKNOWN)
                self._attributes["long_description"] = event.get("long_description", STATE_UNKNOWN)
                self._attributes["desc_time"] = event.get("time", STATE_UNKNOWN)
                self._attributes["desc_date"] = event.get("date", STATE_UNKNOWN)


            # Flag where it is, if known
            # "ppc_name": "Ålidhem Postombud             ",
            if "to" in shipment:
                # Tell me where it is going
                self._attributes["ppc_name"] = shipment.get("to", {}).get("ppc_name", STATE_UNKNOWN)
        else:
            _LOGGER.info("Found other pkg_number {}".format(response["singlehit"]["pkg_number"]))

    async def async_added_to_hass(self):
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        if self._state is not None:
            return

        state = await self.async_get_last_state()
        self._state = state and state.state
        self._attributes = state and state.attributes
