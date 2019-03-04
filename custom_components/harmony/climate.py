"""
Support for Harmony Hub devices as a Climate Component.

https://github.com/so3n/HA_harmony_climate_component
"""
import asyncio
import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.climate import (
    ClimateDevice, PLATFORM_SCHEMA, STATE_OFF, STATE_IDLE, STATE_HEAT, 
    STATE_COOL, STATE_AUTO, ATTR_OPERATION_MODE, SUPPORT_OPERATION_MODE, 
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE, SUPPORT_ON_OFF)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE, CONF_NAME, CONF_HOST, 
    CONF_PORT, CONF_CUSTOMIZE)
from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity

REQUIREMENTS = ['aioharmony==0.1.8']

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = (
    SUPPORT_TARGET_TEMPERATURE | 
    SUPPORT_OPERATION_MODE | 
    SUPPORT_FAN_MODE | 
    SUPPORT_ON_OFF
)

CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_TARGET_TEMP_STEP = 'target_temp_step'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_OPERATIONS = 'operations'
CONF_FAN_MODES = 'fan_modes'
CONF_DEFAULT_OPERATION = 'default_operation'
CONF_DEFAULT_FAN_MODE = 'default_fan_mode'
CONF_DEVICE_ID = 'device_id'

CONF_DEFAULT_OPERATION_FROM_IDLE = 'default_operation_from_idle'

DEFAULT_NAME = 'Harmony Hub Climate'
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 30
DEFAULT_TARGET_TEMP = 20
DEFAULT_TARGET_TEMP_STEP = 1
DEFAULT_OPERATION_LIST = [STATE_OFF, STATE_HEAT, STATE_COOL, STATE_AUTO]
DEFAULT_FAN_MODE_LIST = ['low', 'mid', 'high', 'auto']
DEFAULT_OPERATION = 'off'
DEFAULT_FAN_MODE = 'auto'

CUSTOMIZE_SCHEMA = vol.Schema({
    vol.Optional(CONF_OPERATIONS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_FAN_MODES): vol.All(cv.ensure_list, [cv.string])
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): 
        cv.string,
    vol.Required(CONF_HOST): 
        cv.string,
    vol.Required(CONF_DEVICE_ID): 
        cv.string,
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP):
        cv.positive_int,
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP):
        cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP):
        cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP_STEP, default=DEFAULT_TARGET_TEMP_STEP): 
        cv.positive_int,
    vol.Optional(CONF_TEMP_SENSOR): 
        cv.entity_id,
    vol.Optional(CONF_CUSTOMIZE, default={}): 
        CUSTOMIZE_SCHEMA,
    vol.Optional(CONF_DEFAULT_OPERATION, default=DEFAULT_OPERATION): 
        cv.string,
    vol.Optional(CONF_DEFAULT_FAN_MODE, default=DEFAULT_FAN_MODE): 
        cv.string,
    vol.Optional(CONF_DEFAULT_OPERATION_FROM_IDLE): 
        cv.string
})

async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Harmony Hub Climate platform."""
    name = config.get(CONF_NAME)
    ip_addr = config.get(CONF_HOST)
    device_id = config.get(CONF_DEVICE_ID)
      
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    target_temp_step = config.get(CONF_TARGET_TEMP_STEP)
    temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)
    operation_list = (
        config.get(CONF_CUSTOMIZE).get(CONF_OPERATIONS, []) or 
        DEFAULT_OPERATION_LIST)
    fan_list = (
        config.get(CONF_CUSTOMIZE).get(CONF_FAN_MODES, []) or 
        DEFAULT_FAN_MODE_LIST)
    default_operation = config.get(CONF_DEFAULT_OPERATION)
    default_fan_mode = config.get(CONF_DEFAULT_FAN_MODE)
    
    default_operation_from_idle = config.get(CONF_DEFAULT_OPERATION_FROM_IDLE)
   
    from aioharmony.harmonyapi import HarmonyAPI as HarmonyClient
    
    harmony_device = HarmonyClient(ip_address=ip_addr)

    if harmony_device is None:
        _LOGGER.error("Failed to connect to Harmony Hub")
        return
    else:
        _LOGGER.debug(
            "Connected to Harmony Hub Climate Component: %s at %s",
            name, ip_addr)
    
    async_add_entities([
        HarmonyIRClimate(hass, name, harmony_device, device_id, min_temp, 
                         max_temp, target_temp, target_temp_step,
                         temp_sensor_entity_id, operation_list, fan_list, 
                         default_operation, default_fan_mode, 
                         default_operation_from_idle)
    ])

class HarmonyIRClimate(ClimateDevice, RestoreEntity):

    def __init__(self, hass, name, harmony_device, device_id, min_temp, 
                max_temp, target_temp, target_temp_step, 
                temp_sensor_entity_id, operation_list, fan_list, 
                default_operation, default_fan_mode, 
                default_operation_from_idle):
        """Initialize Harmony IR Climate device."""
        self.hass = hass
        self._name = name

        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temperature = target_temp
        self._target_temperature_step = target_temp_step
        self._unit_of_measurement = hass.config.units.temperature_unit

        self._current_temperature = 0
        self._temp_sensor_entity_id = temp_sensor_entity_id

        self._current_operation = default_operation
        self._last_operation = default_operation
        self._current_fan_mode = default_fan_mode
        
        if self._last_operation.lower() in ('off', 'idle'):
            for op in operation_list:
                if op.lower() not in ('off', 'idle'):
                    self._last_operation = op
                    break
        
        self._operation_list = operation_list
        self._fan_list = fan_list

        self._default_operation_from_idle = default_operation_from_idle

        self._harmony_device = harmony_device
        self._device_id = device_id

        if temp_sensor_entity_id:
            async_track_state_change(hass, temp_sensor_entity_id, 
                                     self._async_temp_sensor_changed)
            sensor_state = hass.states.get(temp_sensor_entity_id)    
            if sensor_state:
                self._async_update_current_temp(sensor_state)
    
    
    async def async_send_ir(self):     
        """Send command to harmony device"""
        from aioharmony.harmonyapi import SendCommandDevice
        import aioharmony.exceptions as aioexc

        mode = self._current_operation.capitalize()
        fan = self._current_fan_mode.capitalize()
        temp = str(int(self._target_temperature))
        command = 'Off' if mode in ('Off', 'Idle') else mode + fan + temp
        
        send_command = SendCommandDevice(
            device=self._device_id,
            command=command,
            delay=0
        )
        _LOGGER.debug(
            "Sending command %s to device %s", command, self._device_id
        )
        await self._harmony_device.send_commands([send_command])
        
    async def _async_temp_sensor_changed(self, entity_id, old_state, 
                                         new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_current_temp(new_state)
        await self.async_update_ha_state()
        
    @callback
    def _async_update_current_temp(self, state):
        """Update thermostat with latest state from sensor."""
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            _state = state.state
            if self.represents_float(_state):
                self._current_temperature = (
                    self.hass.config.units.temperature(float(_state), unit))
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)    

    def represents_float(self, s):
        try: 
            float(s)
            return True
        except ValueError:
            return False     

    
    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def state(self):
        """Return the current state."""
        if self.current_operation != STATE_OFF:
            return self.current_operation
        return STATE_OFF

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature
        
    @property
    def min_temp(self):
        """Return the polling state."""
        return self._min_temp
        
    @property
    def max_temp(self):
        """Return the polling state."""
        return self._max_temp    
        
    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature
        
    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._target_temperature_step

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool, idle."""
        return self._current_operation

    @property
    def last_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_operation

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return self._operation_list

    @property
    def current_fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def fan_list(self):
        """Return the list of available fan modes."""
        return self._fan_list
        
    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS        
 
    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            self._target_temperature = kwargs.get(ATTR_TEMPERATURE)
            
            if not (self._current_operation.lower() == 'off' 
                    or self._current_operation.lower() == 'idle'):
                await self.async_send_ir()
            elif self._default_operation_from_idle is not None:
                await self.async_set_operation_mode(self._default_operation_from_idle)

            await self.async_update_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        self._current_fan_mode = fan_mode
        
        if not (self._current_operation.lower() == 'off'
                or self._current_operation.lower() == 'idle'):
            await self.async_send_ir()
            
        await self.async_update_ha_state()

    async def async_set_operation_mode(self, operation_mode):
        """Set operation mode."""
        self._current_operation = operation_mode
        if not (self._current_operation.lower() == 'off' 
                or self._current_operation.lower() == 'idle'):
            self._last_operation = self._current_operation

        await self.async_send_ir()
        await self.async_update_ha_state()

    async def async_turn_on(self):
        """Turn thermostat on."""
        await self.async_set_operation_mode(self.last_operation)

    async def async_turn_off(self):
        """Turn thermostat off."""
        await self.async_set_operation_mode(STATE_OFF)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
    
        last_state = await self.async_get_last_state()
        
        if last_state is not None:
            self._target_temperature = last_state.attributes['temperature']
            self._current_operation = last_state.attributes['operation_mode']
            self._current_fan_mode = last_state.attributes['fan_mode']
