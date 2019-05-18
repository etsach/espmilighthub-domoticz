# Domoticz plugin for the ESP8266 Milight hub
Domoticz Python plugin which implements support for ESP8266 Milight hub (https://github.com/sidoh/esp8266_milight_hub).

### Features:
- Lamps will be automatically found and added to Domoticz device database when using the original remotes
- State in Domoticz in synchronized with device state

### Prerequisites (general):
- Working Domoticz installation
- Working MQTT server
- ESP8266 Milight Hub hardware configured with MQTT

### Instructions:
- Clone this project into Domoticz 'plugins' folder
- Restart Domoticz
- Create hardware of type "ESP8266 Milight Hub"
  - Set MQTT IP and port
  - Set "Debug" to "Verbose" for debug log
  - Set mqtt_topic_pattern and mqtt_state_topic_pattern as in the hub web interface
  - Allow new devices in Domoticz settings or they will not appear!
