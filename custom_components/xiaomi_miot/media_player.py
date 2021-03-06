"""Support for Xiaomi WiFi speakers."""
import logging
from datetime import timedelta

from homeassistant.const import *
from homeassistant.components.media_player import (
    DOMAIN as ENTITY_DOMAIN,
    MediaPlayerEntity,
    DEVICE_CLASS_TV,
    DEVICE_CLASS_SPEAKER,
    DEVICE_CLASS_RECEIVER,
)
from homeassistant.components.media_player.const import *

from . import (
    DOMAIN,
    CONF_MODEL,
    XIAOMI_CONFIG_SCHEMA as PLATFORM_SCHEMA,  # noqa: F401
    MiotDevice,
    MiotToggleEntity,
    bind_services_to_entries,
)
from .core.miot_spec import (
    MiotSpec,
    MiotService,
)

_LOGGER = logging.getLogger(__name__)
DATA_KEY = f'{ENTITY_DOMAIN}.{DOMAIN}'
SCAN_INTERVAL = timedelta(seconds=60)

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
    miot = config.get('miot_type')
    if miot:
        spec = await MiotSpec.async_from_type(hass, miot)
        for srv in spec.get_services('play_control', 'television'):
            if not srv.mapping():
                continue
            cfg = {
                **config,
                'name': f"{config.get('name')} {srv.description}"
            }
            entities.append(MiotMediaPlayerEntity(cfg, srv))
    for entity in entities:
        hass.data[DOMAIN]['entities'][entity.unique_id] = entity
    async_add_entities(entities, update_before_add=True)
    bind_services_to_entries(hass, SERVICE_TO_METHOD)


class MiotMediaPlayerEntity(MiotToggleEntity, MediaPlayerEntity):
    def __init__(self, config: dict, miot_service: MiotService):
        name = config[CONF_NAME]
        host = config[CONF_HOST]
        token = config[CONF_TOKEN]
        _LOGGER.info('Initializing %s with host %s (token %s...)', name, host, token[:5])

        mapping = miot_service.spec.services_mapping(
            'play_control', 'intelligent_speaker', 'speaker',
            'microphone', 'clock', 'input_control',
        ) or {}
        mapping.update(miot_service.mapping())
        self._device = MiotDevice(mapping, host, token)
        super().__init__(name, self._device, miot_service)

        self._prop_state = miot_service.get_property('playing_state')

        self._speaker = miot_service.spec.get_service('speaker')
        self._prop_volume = self._speaker.get_property('volume')
        self._prop_mute = self._speaker.get_property('mute')

        if miot_service.get_action('play'):
            self._supported_features |= SUPPORT_PLAY
        if miot_service.get_action('pause'):
            self._supported_features |= SUPPORT_PAUSE
        if miot_service.get_action('previous'):
            self._supported_features |= SUPPORT_PREVIOUS_TRACK
        if miot_service.get_action('next'):
            self._supported_features |= SUPPORT_NEXT_TRACK
        if miot_service.get_action('stop'):
            self._supported_features |= SUPPORT_STOP
        if miot_service.get_action('turn_on'):
            self._supported_features |= SUPPORT_TURN_ON
        if miot_service.get_action('turn_off'):
            self._supported_features |= SUPPORT_TURN_OFF
        if self._prop_volume:
            self._supported_features |= SUPPORT_VOLUME_SET
        if self._prop_mute:
            self._supported_features |= SUPPORT_VOLUME_MUTE

        self._state_attrs.update({'entity_class': self.__class__.__name__})

    @property
    def device_class(self):
        typ = f'{self._model} {self._miot_service.spec.type}'
        if typ.find('speaker') >= 0:
            return DEVICE_CLASS_SPEAKER
        if typ.find('receiver') >= 0:
            return DEVICE_CLASS_RECEIVER
        if typ.find('tv') >= 0 or typ.find('television') >= 0:
            return DEVICE_CLASS_TV
        return None

    @property
    def state(self):
        if self._prop_state:
            sta = self._prop_state.from_dict(self._state_attrs)
            if sta is not None:
                if sta == self._prop_state.list_value('Playing'):
                    return STATE_PLAYING
                if sta == self._prop_state.list_value('Pause'):
                    return STATE_PAUSED
                if sta == self._prop_state.list_value('Idle'):
                    return STATE_IDLE
        if self.available:
            return STATE_UNKNOWN
        return STATE_UNAVAILABLE

    def turn_on(self):
        act = self._miot_service.get_action('turn_on')
        if act:
            return self.miot_action(self._miot_service.iid, act.iid)
        return False

    def turn_off(self):
        act = self._miot_service.get_action('turn_off')
        if act:
            return self.miot_action(self._miot_service.iid, act.iid)
        return False

    @property
    def is_volume_muted(self):
        if self._prop_mute:
            return self._prop_mute.from_dict(self._state_attrs) and True
        return None

    def mute_volume(self, mute):
        if self._prop_mute:
            return self.set_property(self._prop_mute.full_name, True if mute else False)
        return False

    @property
    def volume_level(self):
        if self._prop_volume:
            return round(self._prop_volume.from_dict(self._state_attrs) or 0) / 100
        return None

    def set_volume_level(self, volume):
        if self._prop_volume:
            vol = round(volume * (self._prop_volume.range_max() or 1))
            stp = self._prop_volume.range_step()
            if stp and stp > 1:
                vol = round(vol / stp) * stp
            return self.set_property(self._prop_volume.full_name, vol)
        return False

    def media_play(self):
        act = self._miot_service.get_action('play')
        if act:
            if self.miot_action(self._miot_service.iid, act.iid):
                if self._prop_state:
                    self.update_attrs({
                        self._prop_state.full_name: self._prop_state.list_value('Playing'),
                    })
                return True
        return False

    def media_pause(self):
        act = self._miot_service.get_action('pause')
        if act:
            if self.miot_action(self._miot_service.iid, act.iid):
                if self._prop_state:
                    self.update_attrs({
                        self._prop_state.full_name: self._prop_state.list_value('Pause'),
                    })
                return True
        return False

    def media_stop(self):
        act = self._miot_service.get_action('stop')
        if act:
            if self.miot_action(self._miot_service.iid, act.iid):
                if self._prop_state:
                    self.update_attrs({
                        self._prop_state.full_name: self._prop_state.list_value('Stopped', 'Stop', 'Idle'),
                    })
                return True
        return self.media_pause()

    def media_previous_track(self):
        act = self._miot_service.get_action('previous')
        if act:
            return self.miot_action(self._miot_service.iid, act.iid)
        return False

    def media_next_track(self):
        act = self._miot_service.get_action('next')
        if act:
            return self.miot_action(self._miot_service.iid, act.iid)
        return False

    def media_seek(self, position):
        return False

    def play_media(self, media_type, media_id, **kwargs):
        return False

    def select_source(self, source):
        return False

    def select_sound_mode(self, sound_mode):
        return False

    def clear_playlist(self):
        return False

    def set_shuffle(self, shuffle):
        return False

    def set_repeat(self, repeat):
        return False
