#           MQTT discovery plugin
#
"""
<plugin key="MilightESP8266" name="ESP8266 Milight Hub" version="0.0.7">
    <description>
      ESP8266 Milight Hub plugin using MQTT<br/><br/>
      Specify MQTT server and port.<br/>
      <br/>
      Automatically creates Domoticz device entries for all discovered devices.<br/>
    </description>
    <params>
        <param field="Address" label="MQTT Server address" width="300px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="300px" required="true" default="1883"/>
        <param field="Username" label="Username" width="300px"/>
        <param field="Password" label="Password" width="300px"/>
        <!-- <param field="Mode1" label="CA Filename" width="300px"/> -->
        <param field="Mode2" label="mqtt_topic_pattern" width="300px" default="milight/:device_id/:device_type/:group_id"/>
        <param field="Mode3" label="mqtt_state_topic_pattern" width="300px" default="milight/states/:device_id/:device_type/:group_id"/>
        <param field="Mode4" label="Ignored device topics (comma separated)" width="300px" default=""/>

        <param field="Mode5" label="Options" width="300px"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="Extra verbose: (Framework logs 2+4+8+16+64 + MQTT dump)" value="Verbose+"/>
                <option label="Verbose: (Framework logs 2+4+8+16+64 + MQTT dump)" value="Verbose"/>
                <option label="Normal: (Framework logs 2+4+8)" value="Debug"/>
                <option label="None" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
from datetime import datetime
from itertools import count, filterfalse
import json
import re
import time
import traceback

class MqttClient:
    Address = ""
    Port = ""
    mqttConn = None
    isConnected = False
    mqttConnectedCb = None
    mqttDisconnectedCb = None
    mqttPublishCb = None

    def __init__(self, destination, port, mqttConnectedCb, mqttDisconnectedCb, mqttPublishCb, mqttSubackCb):
        Domoticz.Debug("MqttClient::__init__")
        self.Address = destination
        self.Port = port
        self.mqttConnectedCb = mqttConnectedCb
        self.mqttDisconnectedCb = mqttDisconnectedCb
        self.mqttPublishCb = mqttPublishCb
        self.mqttSubackCb = mqttSubackCb
        self.Open()

    def __str__(self):
        Domoticz.Debug("MqttClient::__str__")
        if (self.mqttConn != None):
            return str(self.mqttConn)
        else:
            return "None"

    def Open(self):
        Domoticz.Debug("MqttClient::Open")
        if (self.mqttConn != None):
            self.Close()
        self.isConnected = False
        self.mqttConn = Domoticz.Connection(Name=self.Address, Transport="TCP/IP", Protocol="MQTT", Address=self.Address, Port=self.Port)
        self.mqttConn.Connect()

    def Connect(self):
        Domoticz.Debug("MqttClient::Connect")
        if (self.mqttConn == None):
            self.Open()
        else:
            ID = 'Domoticz_'+Parameters['Key']+'_'+str(Parameters['HardwareID'])+'_'+str(int(time.time()))
            Domoticz.Log("MQTT CONNECT ID: '" + ID + "'")
            self.mqttConn.Send({'Verb': 'CONNECT', 'ID': ID})

    def Ping(self):
        #Domoticz.Debug("MqttClient::Ping")
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'PING'})

    def Publish(self, topic, payload, retain = 0):
        Domoticz.Debug("MqttClient::Publish " + topic + " (" + payload + ")")
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'PUBLISH', 'Topic': topic, 'Payload': bytearray(payload, 'utf-8'), 'Retain': retain})

    def Subscribe(self, topics):
        Domoticz.Debug("MqttClient::Subscribe")
        subscriptionlist = []
        for topic in topics:
            subscriptionlist.append({'Topic':topic, 'QoS':0})
        if (self.mqttConn == None or not self.isConnected):
            self.Open()
        else:
            self.mqttConn.Send({'Verb': 'SUBSCRIBE', 'Topics': subscriptionlist})

    def Close(self):
        Domoticz.Log("MqttClient::Close")
        #TODO: Disconnect from server
        self.mqttConn = None
        self.isConnected = False

    def onConnect(self, Connection, Status, Description):
        Domoticz.Debug("MqttClient::onConnect")
        if (Status == 0):
            Domoticz.Log("Successful connect to: "+Connection.Address+":"+Connection.Port)
            self.Connect()
        else:
            Domoticz.Log("Failed to connect to: "+Connection.Address+":"+Connection.Port+", Description: "+Description)

    def onDisconnect(self, Connection):
        Domoticz.Log("MqttClient::onDisonnect Disconnected from: "+Connection.Address+":"+Connection.Port)
        self.Close()
        # TODO: Reconnect?
        if self.mqttDisconnectedCb != None:
            self.mqttDisconnectedCb()

    def onMessage(self, Connection, Data):
        topic = ''
        if 'Topic' in Data:
            topic = Data['Topic']
        payloadStr = ''
        if 'Payload' in Data:
            payloadStr = Data['Payload'].decode('utf8','replace')
            payloadStr = str(payloadStr.encode('unicode_escape'))
        #Domoticz.Debug("MqttClient::onMessage called for connection: '"+Connection.Name+"' type:'"+Data['Verb']+"' topic:'"+topic+"' payload:'" + payloadStr + "'")

        if Data['Verb'] == "CONNACK":
            self.isConnected = True
            if self.mqttConnectedCb != None:
                self.mqttConnectedCb()

        if Data['Verb'] == "SUBACK":
            if self.mqttSubackCb != None:
                self.mqttSubackCb()

        if Data['Verb'] == "PUBLISH":
            if self.mqttPublishCb != None:
                self.mqttPublishCb(topic, Data['Payload'])

CONF_DEVICE = 'device'
TOPIC_BASE = '~'



class BasePlugin:
    # MQTT settings
    mqttClient = None
    mqttserveraddress = ""
    mqttserverport = ""
    debugging = "Normal"
    registeredDevices = dict() #Key=topic, Value=Device Unit

    options = {"addDiscoveredDeviceUsed":True, # Newly discovered devices added as "used" (visible in swithces tab) or not (only visible in devices list)
              }

    def deviceStr(self, unit):
        name = "<UNKNOWN>"
        if unit in Devices:
            name = Devices[unit].Name
        return format(unit, '03d') + "/" + name

    def getUnit(self, device):
        unit = -1
        for k, dev in Devices.items():
            if dev == device:
                unit = k
        return unit

    def onStart(self):

        # Parse options
        self.debugging = Parameters["Mode6"]
        DumpConfigToLog()
        if self.debugging == "Verbose+":
            Domoticz.Debugging(2+4+8+16+64)
        if self.debugging == "Verbose":
            Domoticz.Debugging(2+4+8+16+64)
        if self.debugging == "Debug":
            Domoticz.Debugging(2+4+8)
        self.mqttserveraddress = Parameters["Address"].replace(" ", "")
        self.mqttserverport = Parameters["Port"].replace(" ", "")
        self.commands_topic_format = Parameters["Mode2"]
        self.states_topic_format = Parameters["Mode3"]
        
        self.ignoredtopics = []
        for ignoredtopic in Parameters["Mode4"].split(','):
            if len(ignoredtopic)>0:
                self.ignoredtopics.append(ignoredtopic)

        options = ""
        try:
            options = json.loads(Parameters["Mode5"])
        except ValueError:
            options = ""

        if type(options) == dict:
            self.options.add(options)
        Domoticz.Log("Plugin options: " + str(self.options))

        # Enable heartbeat
        Domoticz.Heartbeat(10)

        # Connect to MQTT server
        self.mqttClient = MqttClient(self.mqttserveraddress, self.mqttserverport, self.onMQTTConnected, self.onMQTTDisconnected, self.onMQTTPublish, self.onMQTTSubscribed)


    def onConnect(self, Connection, Status, Description):
        self.mqttClient.onConnect(Connection, Status, Description)

    def onDisconnect(self, Connection):
        self.mqttClient.onDisconnect(Connection)

    def onMessage(self, Connection, Data):
        self.mqttClient.onMessage(Connection, Data)

    def onMQTTConnected(self):
        Domoticz.Debug("onMQTTConnected")
        self.mqttClient.Subscribe(self.getTopics())

    def onMQTTDisconnected(self):
        Domoticz.Debug("onMQTTDisconnected")

    def onMQTTPublish(self, topic, rawmessage):
        message = ""
        try:
            message = json.loads(rawmessage.decode('utf8'))
        except ValueError:
            message = rawmessage.decode('utf8')

        topiclist = topic.split('/')
        if self.debugging == "Verbose" or self.debugging == "Verbose+":
            DumpMQTTMessageToLog(topic, rawmessage, 'onMQTTPublish: ')

        if topic in self.ignoredtopics:
            Domoticz.Debug("Topic: '"+topic+"' included in ignored topics, message ignored")
            return

        states_topic_format_list = self.states_topic_format.split('/')
        topiclist = topic.split('/')
        
        device_id = None
        device_type = None
        group_id = None
        format_ok = True
        if len(states_topic_format_list) == len(topiclist):
            for i in range(len(topiclist)):
                item = states_topic_format_list[i]
                if item==':device_id' or item==':hex_device_id':
                    device_id = topiclist[i]
                elif item==':device_type':
                    device_type = topiclist[i]
                elif item==':group_id':
                    group_id = topiclist[i]
                elif item!=topiclist[i]:
                    format_ok = False


        if format_ok and device_id and device_type and group_id:
            Domoticz.Debug("Topic: "+topic+" message : "+json.dumps(message))
            if topic not in self.registeredDevices:
                unit = self.setLightDevice(device_id, device_type, group_id, message)
                if unit>=0:
                    self.registeredDevices[topic] = unit
            self.updateLightDevice(device_id, device_type, group_id, message)


    def onMQTTSubscribed(self):
        # (Re)subscribed, refresh device info
        Domoticz.Debug("onMQTTSubscribed")
        topics = set()

# ==========================================================DASHBOARD COMMAND=============================================================
    def onCommand(self, Unit, Command, Level, sColor):
        Domoticz.Log(self.deviceStr(Unit) + ": Command: '" + str(Command) + "', Level: " + str(Level) + ", Color:" + str(sColor))

        if Unit in Devices:
            try:
                device = Devices[Unit]
                device_id = device.Options['device_id']
                device_type = device.Options['device_type']
                group_id = device.Options['group_id']
                topic = self.commands_topic_format.replace(":device_id", device_id) .replace(":hex_device_id", device_id).replace(":device_type", device_type).replace(":group_id", group_id) 
                disco_mode_command = "Disco Mode "

                #Alternate way of increasing/decreasing brightness
                if Command == "Bright Up":
                    Command = "Set Brightness"
                    Level = min(device.LastLevel + 5, 100)
                elif Command == "Bright Down":
                    Command = "Set Brightness"
                    Level = max(device.LastLevel - 5, 5)

                
                payload = dict()                
                if Command == "Set Brightness" or Command == "Set Level":
                    payload['level'] = int(Level)
                    if(Level>0):
                        payload['status'] = 'ON'
                elif Command == "On":
                    payload['status'] = 'ON'
                elif Command == "Set Full":
                    payload['status'] = 'ON'
                    payload['level'] = 100
                elif Command == "Off":
                    payload['status'] = 'OFF'
                elif Command == "Set White":
                        payload['command'] = 'set_white'
                elif Command == "Set Color":
                    try:
                        color = json.loads(sColor);
                    except (ValueError, KeyError, TypeError) as e:
                        Domoticz.Error("onCommand: Illegal color: '" + str(sColor) + "'")
                        
                    payload['level'] = int(Level)
                        
                    if color['m']==1:
                        payload['command'] = 'set_white'
                    elif color['m']==2 and 't' in color:
                        payload['command'] = 'set_white'
                        payload['temperature'] = int(color['t']*100/255)
                    elif color['m']==3 and 'r' in color and 'g' in color and 'b' in color:
                        payload['color'] = { 'r': color['r'], 'g': color['g'], 'b': color['b'] }
                elif Command.startswith(disco_mode_command):
                    disco_mode = int(Command[len(disco_mode_command)])
                    payload['mode'] = disco_mode-1
                elif Command == "Set Night":
                    payload['command'] = 'night_mode'
                elif Command == "Speed Up":
                    payload['command'] = 'mode_speed_up'
                elif Command == "Speed Down":
                    payload['command'] = 'mode_speed_down'
                #elif Command == "Bright Up":
                    #payload['command'] = 'level_up'    #Not supported by most devices                  
                #elif Command == "Bright Down":
                    #payload['command'] = 'level_down'    #Not supported by most devices
                     
                    
                if payload:
                    payloadstring = json.dumps(payload)
                    self.mqttClient.Publish(topic, payloadstring)

            except (ValueError, KeyError, TypeError) as e:
                Domoticz.Error("onCommand: Error: " + str(e))
        else:
            Domoticz.Debug("Device not found, ignoring command");

    def onDeviceAdded(self, Unit):
        #Domoticz.Log("onDeviceAdded " + self.deviceStr(Unit))
        return

    def onDeviceModified(self, Unit):
        if Unit in Devices:
            device = Devices[Unit]
            try:
                device_id = device.Options['device_id']
                device_type = device.Options['device_type']
                group_id = device.Options['group_id']
                Type = device.Type
                SubType = device.SubType
                
                if "@RGBCCT" in Devices[Unit].Name:
                    Type = 0xf1    # pTypeColorSwitch
                    SubType = 0x04 # sTypeColor_RGB_CW_WW
                elif "@CCT" in Devices[Unit].Name:
                    Type = 0xf1    # pTypeColorSwitch
                    SubType = 0x08
                elif "@RGBW" in Devices[Unit].Name:
                    Type = 0xf1    # pTypeColorSwitch
                    SubType = 0x01 # sTypeColor_RGB_W
                elif "@RGB" in Devices[Unit].Name:
                    Type = 0xf1    # pTypeColorSwitch
                    SubType = 0x02 # sTypeColor_RGB
                elif "@DIMMER" in Devices[Unit].Name:
                    Type = 0xf4        # pTypeGeneralSwitch
                    SubType = 0x49     # sSwitchGeneralSwitch
                    
                if Type!=device.Type or SubType!=device.SubType:
                    nValue = device.nValue
                    sValue = device.sValue
                    Options = device.Options
                    Switchtype = device.SwitchType
                    device.Update(nValue=nValue, sValue=sValue, Type=Type, Subtype=SubType, Switchtype=Switchtype, Options=Options, SuppressTriggers=True)
                
            except (ValueError, KeyError, TypeError) as e:
                Domoticz.Error("onDeviceModified: Error: " + str(e))

    def onDeviceRemoved(self, Unit):
        Domoticz.Log("onDeviceRemoved " + self.deviceStr(Unit))
        try:
            for topic,u in registeredDevices:
                if u==Unit:
                    registeredDevices[topic] = -1
        except (ValueError, KeyError, TypeError) as e:
            pass


    def onHeartbeat(self):
        if self.debugging == "Verbose" or self.debugging == "Verbose+":
            Domoticz.Debug("Heartbeating...")

        # Reconnect if connection has dropped
        if self.mqttClient.mqttConn is None or (not self.mqttClient.mqttConn.Connecting() and not self.mqttClient.mqttConn.Connected() or not self.mqttClient.isConnected):
            Domoticz.Debug("Reconnecting")
            self.mqttClient.Open()
        else:
            self.mqttClient.Ping()

    # Returns list of topics to subscribe to
    def getTopics(self):
        topics = set()
        
        topic = self.states_topic_format.replace(":device_id", "+") .replace(":hex_device_id", "+") .replace(":device_type", "+").replace(":group_id", "+") 
        topics.add(topic)
        
        Domoticz.Debug("getTopics: '" + str(topics) +"'")
        return list(topics)

    # Returns list of matching devices
    def getDevices(self, device_id, device_type, group_id):
        if self.debugging == "Verbose" or self.debugging == "Verbose+":
            Domoticz.Debug("getDevices device_id: '" + device_id + "' device_type: '" + device_type + "' group_id: '" + group_id + "'")
        matchingDevices = set()
        for k, Device in Devices.items():
            try:
                if Device.Options['device_id'] == device_id and Device.Options['device_type'] == device_type and Device.Options['group_id'] == group_id:
                    matchingDevices.add(k)
            except (ValueError, KeyError) as e:
                pass
        if self.debugging == "Verbose" or self.debugging == "Verbose+":
            Domoticz.Debug("getDevices found " + str(len(matchingDevices)) + " devices")
        return list(matchingDevices)

    def makeDevice(self, Name, Options, TypeName, switchTypeDomoticz, data):
        iUnit = next(filterfalse(set(Devices).__contains__, count(1))) # First unused 'Unit'
        Domoticz.Log("Creating device with unit: " + str(iUnit));
        Domoticz.Device(Name=Name, Unit=iUnit, TypeName=TypeName, Switchtype=switchTypeDomoticz, Options=Options, Used=self.options['addDiscoveredDeviceUsed']).Create()

    def makeDeviceRaw(self, Name, Options, Type, Subtype, switchTypeDomoticz, data):
        iUnit = next(filterfalse(set(Devices).__contains__, count(1))) # First unused 'Unit'
        Domoticz.Log("Creating device with unit: " + str(iUnit));
        Domoticz.Device(Name=Name, Unit=iUnit, Type=Type, Subtype=Subtype, Switchtype=switchTypeDomoticz, Options=Options, Used=self.options['addDiscoveredDeviceUsed']).Create()

    def isDeviceIgnored(self, topic):
        ignore = False
        for ignoredtopic in self.ignoredtopics:
            if topic.startswith(ignoredtopic):
                ignore = True
                Domoticz.Debug("isDeviceIgnored: " + subtopic +" "+ str(ignore))
        return ignore



# =============================================================DEVICE CONFIG==============================================================
    
    # Returns the device unit corresponding to this topic (created if necessary)
    def setLightDevice(self, device_id, device_type, group_id, message):
        Domoticz.Debug("setLightDevice device_id:"+device_id+" Type:"+device_type+" Group:"+group_id + " Message:"+json.dumps(message))

        TypeName = ''
        Type = 0
        Subtype = 0
        switchTypeDomoticz = 0 # OnOff
        hasCCT = False
        hasRGB = False
        
        if device_type == 'fut089' or device_type == 'rgb_cct':
            Domoticz.Debug("devicetype == RGBCCT")
            switchTypeDomoticz = 7 # Dimmer
            Type = 0xf1    # pTypeColorSwitch
            Subtype = 0x04 # sTypeColor_RGB_CW_WW
        elif device_type == 'cct' or device_type == 'fut091':
            Domoticz.Debug("devicetype == CCT")
            switchTypeDomoticz = 7 # Dimmer
            Type = 0xf1    # pTypeColorSwitch
            Subtype = 0x08
        elif device_type == 'rgbw':
            Domoticz.Debug("devicetype == RGBW")
            switchTypeDomoticz = 7 # Dimmer
            Type = 0xf1    # pTypeColorSwitch
            Subtype = 0x01 # sTypeColor_RGB_W
        elif device_type == 'rgb':
            Domoticz.Debug("devicetype == RGB")
            switchTypeDomoticz = 7 # Dimmer
            Type = 0xf1    # pTypeColorSwitch
            Subtype = 0x02 # sTypeColor_RGB
        # elif device_type == '':  # Currently we do not know how to identify dimmer only devices
            # Domoticz.Debug("devicetype == 'switch'")
            # TypeName = 'Switch'
            # Type = 0xf4        # pTypeGeneralSwitch
            # Subtype = 0x49     # sSwitchGeneralSwitch
        else:
            Domoticz.Debug("Unknown device type:'"+device_type+"'")
            return -1

        matchingDevices = self.getDevices(device_id, device_type, group_id)
        if len(matchingDevices) == 0:
            # Device not existing
            Domoticz.Log("setLightDevice: Did not find device with device_id:"+device_id+" Type:"+device_type+" Group:"+group_id)
            Domoticz.Log("setLightDevice: TypeName: '" + TypeName + "' Type: " + str(Type)+ " Subtype: " + str(Subtype))
            Options = {'device_id':device_id, 'device_type':device_type, 'group_id':group_id}
            Name = str(device_id)+'/'+str(device_type)+'/'+str(group_id)
            if TypeName != '':
                self.makeDevice(Name, Options, TypeName, switchTypeDomoticz, message)
                matchingDevices = self.getDevices(device_id, device_type, group_id)
            elif Type != 0:
                self.makeDeviceRaw(Name, Options, Type, Subtype, switchTypeDomoticz, message)
                matchingDevices = self.getDevices(device_id, device_type, group_id)
            
        if len(matchingDevices) > 0:
            u = matchingDevices[0]
            return u
        else:
            return -1
            
    def hs_to_rgb(self, h, s):
        if s == 0: return (255, 255, 255)
        i = int(h*6.0/360) # XXX assume int() truncates!
        f = (h*6.0/360)-i
        p = 255*(1.0-s/100)
        q = int(255*(1.0-s/100*f))
        t = int(255*(1.0-s/100*(1.0-f)))
        i%=6
        if i == 0: return (255, t, p)
        if i == 1: return (q, 255, p)
        if i == 2: return (p, 255, t)
        if i == 3: return (p, q, 255)
        if i == 4: return (t, p, 255)
        if i == 5: return (255, p, q)
        
    def rgb_to_hs(self,r,g,b):
        cmin = min(r,g,b)
        cmax = max(r,g,b)
        delta = cmax - cmin
        hue = 0
        sat = 0
        if delta>0:
            if r==cmax:
                hue = int((g-b)*60/delta)
            elif g==cmax:
                hue = int(120 + (b-r)*60/delta)
            else:
                hue = int(240 + (r-g)*60/delta)
            if hue<0:
                hue = hue+360
            elif hue>360:
                hue = hue-360
            
            if cmax>0:
                sat = int(delta/cmax*100)
        
        return (hue, sat)

# ==========================================================UPDATE STATUS from MQTT==============================================================
    def updateLightDevice(self, device_id, device_type, group_id, message):
        matchingDevices = self.getDevices(device_id, device_type, group_id)
        if len(matchingDevices) > 0:
            Unit = matchingDevices[0]
            Domoticz.Log(self.deviceStr(Unit) + ": State change: '" + str(message))
            device = Devices[Unit]
            nValue = device.nValue
            sValue = device.sValue

            hasCCT = False
            hasRGB = False
            if device.Type==0xf1:
                if device.SubType == 0x04:
                    hasCCT = True
                    hasRGB = True
                if device.SubType == 0x08:
                    hasCCT = True
                if device.SubType == 0x01:
                    hasCCT = True
                    hasRGB = True
                if device.SubType == 0x02:
                    hasCCT = True
                    hasRGB = True
                
            try:
                Color = json.loads(device.Color);
            except (ValueError, KeyError, TypeError) as e:
                Color = dict()
                pass

            hue = 0
            sat = 0
            if 'r' in Color and 'g' in Color and 'b' in Color:
                (hue, sat) = self.rgb_to_hs(Color['r'],Color['g'],Color['b'])
                
            if 'state' in message:
                if message['state']=='ON':
                    nValue = 1
                elif message['state']=='OFF':
                    nValue = 0

            if 'brightness' in message:
                sValue = str(int(message['brightness']*100/255))
                    
            if 'bulb_mode' in message:
                if message['bulb_mode']=='white':
                    if hasCCT:
                        Color['m'] = 2
                    else:
                        Color['m'] = 1
                elif message['bulb_mode']=='rgb' or message['bulb_mode']=='color':
                    Color['m'] = 3
                elif message['bulb_mode']=='scene' and 'mode' in message:
                    nValue = 24+message['mode']
                    sValue = "Disco Mode "+str(message['mode']+1)

            if 'color_temp' in message:
                Color['t'] = int(int(message['color_temp'])-153)*255/(370-153)
                   
            if 'hue' in message:
                hue = message['hue']
                (r,g,b) = self.hs_to_rgb(hue,sat)
                Color['r'] = r
                Color['g'] = g
                Color['b'] = b

            if 'saturation' in message:
                sat = message['saturation']
                (r,g,b) = self.hs_to_rgb(hue, sat)
                Color['r'] = r
                Color['g'] = g
                Color['b'] = b

            if 'color' in message:
                col = message['color']
                if 'r' in col:
                    Color['r'] = col['r']
                if 'g' in col:
                    Color['g'] = col['g']
                if 'b' in col:
                    Color['b'] = col['b']
  
            if Color:
                Color=json.dumps(Color)
                Domoticz.Debug("Update Color : "+Color)
                device.Update(nValue=nValue, sValue=sValue, Color=Color)
            else:
                device.Update(nValue=nValue, sValue=sValue)
            



global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)

def onDeviceAdded(Unit):
    global _plugin
    _plugin.onDeviceAdded(Unit)

def onDeviceModified(Unit):
    global _plugin
    _plugin.onDeviceModified(Unit)

def onDeviceRemoved(Unit):
    global _plugin
    _plugin.onDeviceRemoved(Unit)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Log( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Log("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Log("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Log("Device LastLevel: " + str(Devices[x].LastLevel))
        Domoticz.Log("Device Color:     " + str(Devices[x].Color))
        Domoticz.Log("Device Options:   " + str(Devices[x].Options))
    return

def DumpMQTTMessageToLog(topic, rawmessage, prefix=''):
    message = rawmessage.decode('utf8','replace')
    message = str(message.encode('unicode_escape'))
    Domoticz.Log(prefix+topic+":"+message)
