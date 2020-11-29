"""
Support for Harmony Hub devices as a Climate Component.

https://github.com/so3n/HA_harmony_climate_component
"""
import asyncio
import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv


from homeassistant.components.climate import ClimateEntity, PLATFORM_SCHEMA
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_HEAT, HVAC_MODE_COOL,
    HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY, HVAC_MODE_AUTO,
    FAN_ON, FAN_OFF, FAN_AUTO, FAN_LOW, FAN_MEDIUM,
    FAN_HIGH, FAN_MIDDLE, FAN_FOCUS, FAN_DIFFUSE,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE,
    HVAC_MODES, ATTR_HVAC_MODE)
from homeassistant.const import (
    CONF_NAME, CONF_CUSTOMIZE, STATE_ON, STATE_UNKNOWN, ATTR_TEMPERATURE,
    PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE)
from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = (
    SUPPORT_TARGET_TEMPERATURE | 
    SUPPORT_FAN_MODE
)

CONF_REMOTE_ENTITY = 'remote_entity'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_TARGET_TEMP_STEP = 'target_temp_step'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_HVAC_MODES = 'hvac_modes'
CONF_FAN_MODES = 'fan_modes'
CONF_NO_TEMP_HVAC_MODES = 'no_temp_hvac_modes'
CONF_DEVICE_ID = 'device_id'
CONF_DEBUG_MODE = 'debug_mode'
CONF_COMBINE_COMMANDS = 'combine_commands'
CONF_COMMAND_SET_TEMP = 'command_set_temp'

DEFAULT_NAME = 'Harmony Climate Controller'
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 30
DEFAULT_TARGET_TEMP = 20
DEFAULT_TARGET_TEMP_STEP = 1
DEFAULT_HVAC_MODES = {
    HVAC_MODE_OFF: 'off',
    HVAC_MODE_HEAT: 'heat',
    HVAC_MODE_COOL: 'cool',
    HVAC_MODE_AUTO: 'auto'
}
DEFAULT_NO_TEMP_HVAC_MODES = [HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY]
DEFAULT_FAN_MODES = {
    FAN_AUTO: 'FanAuto',
    FAN_HIGH: 'FanHigh',
    FAN_MEDIUM: 'FanMedium',
    FAN_LOW: 'FanLow'
}
DEFAULT_DEBUG_MODE = False
DEFAULT_COMBINE_COMMANDS = True
DEFAULT_COMMAND_SET_TEMP = '{temp:.0f}'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): 
        cv.string,
    vol.Required(CONF_REMOTE_ENTITY): 
        cv.entity_id,
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
    vol.Optional(CONF_DEBUG_MODE, default=DEFAULT_DEBUG_MODE): 
        cv.boolean,
    vol.Optional(CONF_COMBINE_COMMANDS, default=DEFAULT_COMBINE_COMMANDS): 
        cv.boolean,
    vol.Optional(CONF_COMMAND_SET_TEMP, default=DEFAULT_COMMAND_SET_TEMP): 
        cv.string,           
    vol.Optional(CONF_HVAC_MODES, default=DEFAULT_HVAC_MODES): {cv.string: cv.string},
    vol.Optional(CONF_FAN_MODES, default=DEFAULT_FAN_MODES): {cv.string: cv.string},
    vol.Optional(CONF_NO_TEMP_HVAC_MODES): vol.All(cv.ensure_list, [cv.string])
})

async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Harmony Hub Climate platform."""
    name = config.get(CONF_NAME)
    remote_entity = config.get(CONF_REMOTE_ENTITY)
    device_id = config.get(CONF_DEVICE_ID)
      
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    target_temp_step = config.get(CONF_TARGET_TEMP_STEP)
    temperature_sensor = config.get(CONF_TEMP_SENSOR)
    debug_mode = config.get(CONF_DEBUG_MODE)
    combine_commands = config.get(CONF_COMBINE_COMMANDS)
    command_set_temp = config.get(CONF_COMMAND_SET_TEMP)

    try:
        command_set_temp.format(**{'temp':0})
    except:
        _LOGGER.error(
                "Invalid command_set_temp %s", command_set_temp
            )
        command_set_temp = DEFAULT_COMMAND_SET_TEMP

    hvac_modes = config.get(CONF_HVAC_MODES)
    fan_modes = config.get(CONF_FAN_MODES)

    no_temp_hvac_modes = (
        config.get(CONF_NO_TEMP_HVAC_MODES, []) or 
        DEFAULT_NO_TEMP_HVAC_MODES)
         
    async_add_entities([
        HarmonyIRClimate(hass, name, remote_entity, device_id, min_temp, 
                         max_temp, target_temp, target_temp_step,
                         temperature_sensor, hvac_modes, fan_modes, 
                         debug_mode, no_temp_hvac_modes, combine_commands, 
                         command_set_temp)
    ])

class HarmonyIRClimate(ClimateEntity, RestoreEntity):

    def __init__(self, hass, name, remote_entity, device_id, min_temp, 
                max_temp, target_temp, target_temp_step, 
                temperature_sensor, hvac_modes, fan_modes, 
                debug_mode, no_temp_hvac_modes, combine_commands, 
                command_set_temp):
        """Initialize Harmony IR Climate device."""
        self.hass = hass
        self._name = name
        self._remote_entity = remote_entity
        self._device_id = device_id
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temperature = target_temp
        self._target_temperature_step = target_temp_step
        self._temperature_sensor = temperature_sensor
        self._debug_mode = debug_mode
        self._combine_commands = combine_commands
        self._command_set_temp = command_set_temp

        self._command_hvac_modes = hvac_modes
        self._command_fan_modes = fan_modes

        valid_hvac_modes = []
        for mode, command in hvac_modes.items():
            _LOGGER.debug(
                "Processing HVAC mode %s with command %s", mode, command
            )
            if mode in HVAC_MODES:
                valid_hvac_modes.append(mode)
            else:
                _LOGGER.warning(
                    "Invalid HVAC mode %s", mode
                )
                
        valid_no_temp_hvac_modes = [x for x in no_temp_hvac_modes if x in valid_hvac_modes]
        
        self._hvac_modes = valid_hvac_modes
        self._no_temp_hvac_modes = valid_no_temp_hvac_modes
        self._fan_modes = list(fan_modes.keys())

        self._hvac_mode = HVAC_MODE_OFF
        self._current_fan_mode = None
        self._last_on_operation = None

        self._current_temperature = None
        self._unit_of_measurement = hass.config.units.temperature_unit
        self._support_flags = SUPPORT_FLAGS


    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
    
        last_state = await self.async_get_last_state()
        
        if last_state is not None:
            self._hvac_mode = last_state.state
            self._current_fan_mode = last_state.attributes['fan_mode']
            self._target_temperature = last_state.attributes['temperature']

            if 'last_on_operation' in last_state.attributes:
                self._last_on_operation = last_state.attributes['last_on_operation']

        if self._temperature_sensor:
            async_track_state_change(self.hass, self._temperature_sensor, 
                                     self._async_temp_sensor_changed)

            temp_sensor_state = self.hass.states.get(self._temperature_sensor)
            if temp_sensor_state and temp_sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(temp_sensor_state)

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def state(self):
        """Return the current state."""
        if self.hvac_mode != HVAC_MODE_OFF:
            return self.hvac_mode
        return HVAC_MODE_OFF

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

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
    def hvac_modes(self):
        """Return the list of available hvac modes."""
        return self._hvac_modes

    @property
    def hvac_mode(self):
        """Return hvac mode ie. heat, cool."""
        return self._hvac_mode

    @property
    def last_on_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_on_operation
    
    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return self._fan_modes
        
    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags
        
    @property
    def should_poll(self):
        """Return the polling state."""
        return False
        
    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)  
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature:
            if temperature < self._min_temp or temperature > self._max_temp:
                _LOGGER.warning('The temperature value is out of min/max range') 
                return

            if self._target_temperature_step == PRECISION_WHOLE:
                self._target_temperature = round(temperature)
            else:
                self._target_temperature = round(temperature, 1)

        if hvac_mode:
            await self.async_set_hvac_mode(hvac_mode)
        
        if not self._hvac_mode == HVAC_MODE_OFF:
            if self._combine_commands:
                await self.async_send_commands()
            else:
                if not self._hvac_mode in _no_temp_hvac_modes:
                    params = {
                        'temp': self._target_temperature
                    }
                    command = self._command_set_temp.format(**params)
                    await self.async_send_command(command)

        await self.async_update_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""        
        self._hvac_mode = hvac_mode
        
        if hvac_mode == HVAC_MODE_OFF:
            command = self._command_hvac_modes[hvac_mode]
            await self.async_send_command(command)
        else:
            self._last_on_operation = hvac_mode
            if self._combine_commands:
                await self.async_send_commands()
            else:
                command = self._command_hvac_modes[hvac_mode]
                await self.async_send_command(command)
                await self.async_set_temperature()

        await self.async_update_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        self._current_fan_mode = fan_mode
        
        if not self._hvac_mode == HVAC_MODE_OFF:
            if self._combine_commands:            
                await self.async_send_commands()
            else:
                command = self._command_fan_modes[fan_mode]
                await self.async_send_command(command)

        await self.async_update_ha_state()

    async def async_turn_off(self):
        """Turn off."""
        await self.async_set_hvac_mode(HVAC_MODE_OFF)

    async def async_turn_on(self):
        """Turn on."""
        if self._last_on_operation is not None:
            await self.async_set_hvac_mode(self._last_on_operation)
        #else:
        #    await self.async_set_hvac_mode(self._hvac_modes[1])
        if not self._combine_commands:
            await self.async_set_fan_mode(self._current_fan_mode)
            await self.async_set_temperature()

    async def async_send_command(self, command):
        service_data = {
            'entity_id': self._remote_entity,
            'device': self._device_id,
            'command': command
        }

        _LOGGER.debug(
            "remote.send_command %s", service_data
        )

        if self._debug_mode:
            return

        await self.hass.services.async_call(
            'remote', 'send_command', service_data) 

    async def async_send_commands(self):     
        """Send command to harmony device"""

        params = {
            'temp': self._target_temperature
        }

        command_hvac_mode = self._command_hvac_modes[self._hvac_mode]
        command_fan_mode = self._command_fan_modes[self._fan_mode]
        command_set_temp = self._command_set_temp.format(**params)

        if self._hvac_mode in self._no_temp_hvac_modes:
            await self.async_send_command(f"{command_hvac_mode}{command_fan_mode}")
        else:
            await self.async_send_command(f"{command_hvac_mode}{command_fan_mode}{command_set_temp}")
            
    async def _async_temp_sensor_changed(self, entity_id, old_state, 
                                         new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_temp(new_state)
        await self.async_update_ha_state()
        
    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from temperature sensor."""
        try:
            if state.state != STATE_UNKNOWN:
                self._current_temperature = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)  
            