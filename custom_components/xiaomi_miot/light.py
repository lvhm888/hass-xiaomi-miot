"""Support for Xiaomi lights."""
import logging

from homeassistant.const import *
from homeassistant.components.light import (
    DOMAIN as ENTITY_DOMAIN,
    LightEntity,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR_TEMP,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
)

from . import (
    DOMAIN,
    CONF_MODEL,
    XIAOMI_CONFIG_SCHEMA as PLATFORM_SCHEMA,  # noqa: F401
    MiotDevice,
    MiotToggleEntity,
    ToggleSubEntity,
    bind_services_to_entries,
)
from .core.miot_spec import (
    MiotSpec,
    MiotService,
)

_LOGGER = logging.getLogger(__name__)
DATA_KEY = f'{ENTITY_DOMAIN}.{DOMAIN}'

SERVICE_TO_METHOD = {}


async def async_setup_entry(hass, config_entry, async_add_entities):
    config = hass.data[DOMAIN]['configs'].get(config_entry.entry_id, dict(config_entry.data))
    await async_setup_platform(hass, config, async_add_entities)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    hass.data.setdefault(DATA_KEY, {})
    config.setdefault('add_entities', {})
    config['add_entities'][ENTITY_DOMAIN] = async_add_entities
    model = str(config.get(CONF_MODEL) or '')
    entities = []
    if model.find('mrbond.airer') >= 0:
        pass
    else:
        miot = config.get('miot_type')
        if miot:
            spec = await MiotSpec.async_from_type(hass, miot)
            for srv in spec.get_services(ENTITY_DOMAIN):
                if not srv.get_property('on'):
                    continue
                cfg = {
                    **config,
                    'name': f"{config.get('name')} {srv.description}"
                }
                entities.append(MiotLightEntity(cfg, srv))
    for entity in entities:
        hass.data[DOMAIN]['entities'][entity.unique_id] = entity
    async_add_entities(entities, update_before_add=True)
    bind_services_to_entries(hass, SERVICE_TO_METHOD)


class MiotLightEntity(MiotToggleEntity, LightEntity):
    def __init__(self, config: dict, miot_service: MiotService):
        name = config[CONF_NAME]
        host = config[CONF_HOST]
        token = config[CONF_TOKEN]
        _LOGGER.info('Initializing %s with host %s (token %s...)', name, host, token[:5])

        mapping = miot_service.spec.services_mapping(
            ENTITY_DOMAIN, 'yl_light', 'light_extension', 'battery',
            'night_light_times',
        ) or {}
        mapping.update(miot_service.mapping())
        self._device = MiotDevice(mapping, host, token)
        super().__init__(name, self._device, miot_service)

        self._prop_power = miot_service.get_property('on')
        self._prop_brightness = miot_service.get_property('brightness')
        self._prop_color_temp = miot_service.get_property('color_temperature')

        self._supported_features = 0
        if self._prop_brightness:
            self._supported_features |= SUPPORT_BRIGHTNESS
        if self._prop_color_temp:
            self._supported_features |= SUPPORT_COLOR_TEMP

        self._state_attrs.update({'entity_class': self.__class__.__name__})

    def turn_on(self, **kwargs):
        ret = False
        if not self.is_on:
            ret = self.set_property(self._prop_power.full_name, True)

        if self.supported_features & SUPPORT_BRIGHTNESS and ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            percent_brightness = round(100 * brightness / 255)
            _LOGGER.debug('Setting brightness: %s %s%%', brightness, percent_brightness)
            ret = self.set_property(self._prop_brightness.full_name, percent_brightness)

        if self.supported_features & SUPPORT_COLOR_TEMP and ATTR_COLOR_TEMP in kwargs:
            mired = kwargs[ATTR_COLOR_TEMP]
            color_temp = self.translate_mired(mired)
            _LOGGER.debug('Setting color temperature: %s mireds, %s ct', mired, color_temp)
            ret = self.set_property(self._prop_color_temp.full_name, color_temp)

        return ret

    @property
    def brightness(self):
        return round(255 / 100 * int(self._state_attrs.get(self._prop_brightness.full_name) or 0))

    @property
    def color_temp(self):
        return self.translate_mired(self._state_attrs.get(self._prop_color_temp.full_name) or 2700)

    @property
    def min_mireds(self):
        return self.translate_mired(self._prop_color_temp.value_range[1] or 5700)

    @property
    def max_mireds(self):
        return self.translate_mired(self._prop_color_temp.value_range[0] or 2700)

    @staticmethod
    def translate_mired(num):
        return round(1000000 / num)


class LightSubEntity(ToggleSubEntity, LightEntity):
    _brightness = None
    _color_temp = None

    def update(self):
        super().update()
        if self._available:
            attrs = self._state_attrs
            self._brightness = attrs.get('brightness', 0)
            self._color_temp = attrs.get('color_temp', 0)

    def turn_on(self, **kwargs):
        self.call_parent(['turn_on_light', 'turn_on'], **kwargs)

    def turn_off(self, **kwargs):
        self.call_parent(['turn_off_light', 'turn_off'], **kwargs)

    @property
    def brightness(self):
        return self._brightness

    @property
    def color_temp(self):
        return self._color_temp
