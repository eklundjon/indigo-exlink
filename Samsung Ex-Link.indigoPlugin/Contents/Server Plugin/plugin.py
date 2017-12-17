#! /usr/bin/env python

import indigo
import serial
import threading
import binascii

################################################################################
class Plugin(indigo.PluginBase):
	#####################################
	# Begin Indigo plugin API functions #
	#####################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
		self.debug = pluginPrefs.get("DebugFlag", False)
		self.serialLocks = {}
		self.serialConns = {}

		for dev in indigo.devices.iter("self"):
			self.serialLocks[dev.id] = threading.Lock()


	def __del__(self):
		indigo.PluginBase.__del__(self)

	########################################
	def startup(self):
		self.logger.debug(u"startup called")

	########################################
	def shutdown(self):
		self.logger.debug(u"shutdown called")
		
	########################################
	def deviceStartComm(self, dev, blockIfBusy=True):
		#indigo.debugger()
		if self.serialLocks[dev.id].acquire(blockIfBusy):
			self.checkSerial(dev)
			self.serialLocks[dev.id].release()
		else:
			self.logger.debug(u"<<-- skipped deviceStartComm (startStop locked) -->>")

	########################################
	def deviceStopComm(self, dev, blockIfBusy=True):
		if self.serialLocks[dev.id].acquire(blockIfBusy):
			if self.serialConns.get(dev.id) is not None:
				self.serialConns[dev.id].close()
				self.serialConns[dev.id] = None
			self.serialLocks[dev.id].release()
		else:
			self.logger.debug(u"<<-- skipped deviceStopComm (startStop locked) -->>")

	########################################
	def closedPrefsConfigUi(self, valuesDict, userCancelled):
		self.logger.debug(u"closedPrefsConfigUi enter")
		if userCancelled:
			return

		self.debug = valuesDict.get("DebugFlag", False)
		if self.debug:
			indigo.server.log("Debug logging enabled")
		else:
			indigo.server.log("Debug logging disabled")


	########################################
	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		self.logger.debug(u"validateDeviceConfigUi enter")

		errorsDict = indigo.Dict()

		self.validateSerialPortUi(valuesDict, errorsDict, u"devicePortFieldId")
		if len(errorsDict) > 0:
			# Some UI fields are not valid, return corrected fields and error messages (client
			# will not let the dialog window close).
			return (False, valuesDict, errorsDict)

		# User choices look good, so return True (client will then close the dialog window).
		return (True, valuesDict)


	########################################
	def closedDeviceConfigUi(self, valuesDict, userCancelled, typeId, devId):
		self.logger.debug(u"closedDeviceConfigUi enter")
		if userCancelled:
			return

		#now that we're sure the device is actually being created,
		#we can finish variable initialization
		if self.serialLocks.get(devId) is None:
			self.serialLocks[devId] = threading.Lock()

	########################################
	def validateActionConfigUi(self, valuesDict, typeId, devId):
		self.logger.debug(u"validateActionConfigUi enter")
		errorsDict = indigo.Dict()
		for key in self.integerCommands:
			for command in valuesDict:
				if key == command:
					try:
						intval = int(valuesDict[key])
						min = self.integerCommands[key]["min"]
						max = self.integerCommands[key]["max"]
						if intval < min or intval > max:
							errorsDict[command] = "%s must be an integer between %i and %i" % (command, min, max)
					except: 
						self.logger.error(u"Internal error validating action "+typeId)
						pass
				
		if ("CommandGroup" in valuesDict):
			commandGroup = valuesDict.get("CommandGroup", "")
			if commandGroup == "NULL":
				self.logger.error("Please choose a command")
				errorsDict["CommandGroup"] = "Please choose a command"
			else:
				command = valuesDict.get("Command", "")
				for cmd in self.enumCommands:
					if (cmd.startswith(commandGroup) and not self.enumCommands[cmd].get("OneShot", False)):
						if command == "":
							self.logger.error("Group "+commandGroup+" needs a value")
							errorsDict["Command"] = "Please choose a value"
						else:
							self.logger.debug("Group "+commandGroup+" command "+command)

		if len(errorsDict) == 0:
			return (True, valuesDict)
		return (False, valuesDict, errorsDict)

	########################################
	def actionControlDevice(self, action, dev):
		self.logger.debug(u"actionControlDevice enter")
		
		if action.deviceAction == indigo.kDeviceAction.TurnOn: 
			self.powerOn(dev)			 
		
		if action.deviceAction == indigo.kDeviceAction.TurnOff:
			self.powerOff(dev)		
		
		if action.deviceAction == indigo.kDeviceAction.Toggle:
			if dev.onState == True:
				self.powerOff(dev)						
			elif dev.onState == False:
				self.powerOn(dev)		   
			else:			
				self.logger.error('"' + dev.name + '" in inconsistent state')		

	########################################
	#General Action callback
	def actionControlUniversal(self, action, dev):
		self.logger.debug(u"actionControlUniversal enter")
		###### STATUS REQUEST ######
		if action.deviceAction == indigo.kUniversalAction.RequestStatus:
			indigo.server.log(u"sent \"%s\" %s" % (dev.name, "status request"))
			self.serialLocks[dev.id].acquire()
			if self.checkSerial(dev) and self.isPowerOn(dev):
				self.logger.debug(u"Serial is OK and device is ON: querying additional status info")
				dev.updateStateOnServer("onOffState", True)
				self.updateInput(dev)
				if dev.states["input"] == "TV":
					self.updateChannel(dev)
				self.updateVolume(dev)
				self.updateMute(dev)
				self.updatePictureMode(dev)
				self.updatePictureSize(dev)
				self.update3dState(dev)
				self.updateSoundMode(dev)
			else:
				dev.updateStateOnServer("onOffState", False)

			self.serialLocks[dev.id].release()
		else:
			self.logger.info(u"EX-Link devices cannot beep and have no energy counters")

	########################################
	# Begin EX-Link specific functionality #
	########################################
	   #should these be in a separate object perhaps?
	   
	########################################
	# Protocol constants

	#most commands ack within 500mS but some of the status queries take a long time
	#Use a short timeout for power because the device won't respond at all if it's off
	defaultSerialTimeout = 5
	powerSerialTimeout = 0.5

	queries = {
		"POWER" : [0x08, 0x22, 0xF0, 0x00, 0x00, 0x00, 0xE6], #done
		"VOLUME" : [0x08, 0x22, 0xF0, 0x01, 0x00, 0x00, 0xE5], #done
		"MUTE" : [0x08, 0x22, 0xF0, 0x02, 0x00, 0x00, 0xE4], #done
		"CHANNEL" : [0x08, 0x22, 0xF0, 0x03, 0x00, 0x00, 0xE3], #done
		"INPUT" : [0x08, 0x22, 0xF0, 0x04, 0x00, 0x00, 0xE2], #done
		"PICTURE_SIZE" : [0x08, 0x22, 0xF0, 0x05, 0x00, 0x00, 0xE1], #done
		"3D_STATE" : [0x08, 0x22, 0xF0, 0x06, 0x00, 0x00, 0xE0], #need responses
		"PICTURE_MODE" : [0x08, 0x22, 0xF0, 0x07, 0x00, 0x00, 0xDF], #done
		"SOUND_MODE" : [0x08, 0x22, 0xF0, 0x08, 0x00, 0x00, 0xDE], #done
		#one might expect that other settings could be queried via successive
		#values of byte 4, but that doesn't seem to be the case on my TV
	}

	responses = {
		"ACK" : [0x03, 0x0C, 0xF1],
		"POWER" : [0x03, 0x0C, 0xF5, 0x08, 0xf0, 0x00, 0x00, 0x00, 0xf1, 0x05, 0x00, 0x00, 0x0e],
	}

	responseDataLength = 13 #all response messages (except command ack) are 13 bytes long
	#the responses below all omit the 030CF508F0 header
	#I could be smarter about constructing and parsing these on the fly, but I won't
	inputs = {
		#input responses don't seem to have any rhyme or reason to them
		"TV" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x00, 0x00, 0xCC],
				 "response" : [0x04, 0x00, 0x00, 0xf1, 0x00, 0x00, 0x00, 0x0f]
			},
		"AV1" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x01, 0x00, 0xCB],
				  "response" : [0x04, 0x00, 0x00, 0xf1, 0x1c, 0x00, 0x00, 0xf3]
			},
		"AV2" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x01, 0x01, 0xCA],
				  "response" : [0x04, 0x00, 0x00, 0xf1, 0x1d, 0x00, 0x00, 0xf2]
			},
		"AV3" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x01, 0x02, 0xC9],
				  "response" : [0x04, 0x00, 0x00, 0xf1, 0x1e, 0x00, 0x00, 0xf1]
			},
		"SVID1" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x02, 0x00, 0xCA],
					"response" : [] #no idea.  please email if you find it
			},
		"SVID2" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x02, 0x01, 0xC9],
					"response" : [] #no idea.  please email if you find it
			},
		"SVID3" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x02, 0x02, 0xC8],
					"response" : [] #no idea.  please email if you find it
			},
		"COMP1" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x03, 0x00, 0xC9],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x29, 0x00, 0x00, 0xe6]
			},
		"COMP2" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x03, 0x01, 0xC8],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x2a, 0x00, 0x00, 0xe5]
			},
		"COMP3" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x03, 0x02, 0xC7],
				 	"response" : [0x04, 0x00, 0x00, 0xf1, 0x2b, 0x00, 0x00, 0xe4]
			},
		"PC1" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x04, 0x00, 0xC8],
				  "response" :  [] #no idea.  please email if you find it
			},
		"PC2" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x04, 0x01, 0xC7],
				  "response" :  [] #no idea.  please email if you find it
			},
		"PC3" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x04, 0x02, 0xC6],
				  "response" :  [] #no idea.  please email if you find it
			},
		"HDMI1" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x05, 0x00, 0xC7],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x39, 0x00, 0x00, 0xd6]
			},
		"HDMI2" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x05, 0x01, 0xC6],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x3a, 0x00, 0x00, 0xd5]
			},
		"HDMI3" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x05, 0x02, 0xC5],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x3b, 0x00, 0x00, 0xd4]
			},
		"HDMI4" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x05, 0x03, 0xC4],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x3c, 0x00, 0x00, 0xd3]
			},
		"HDMI5" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x05, 0x04, 0xC3],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x3d, 0x00, 0x00, 0xd2]
			},
		"HDMI6" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x05, 0x05, 0xC2],
					"response" : [0x04, 0x00, 0x00, 0xf1, 0x3e, 0x00, 0x00, 0xd1]
			},
		"DVI1" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x06, 0x00, 0xC6],
				   "response" :  [] #no idea.  please email if you find it
			},
		"DVI2" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x06, 0x01, 0xC5],
				   "response" :  [] #no idea.  please email if you find it
			},
		"DVI3" : { "command" : [0x08, 0x22, 0x0a, 0x00, 0x06, 0x02, 0xC4],
				   "response" :  [] #no idea.  please email if you find it
			},
		"SMARTHUB" : { "command" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x8C, 0x3D],
				#note this response is sent for any app but not for the smarthub menu screen
				 "response" : [0x04, 0x00, 0x00, 0xf1, 0x59, 0x00, 0x00, 0xb6]
			},
		"NETFLIX" : { "command" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0xF3, 0xD6],
					  "response" : [] #netflix sends the generic smarthub response
			},
		"AMAZON" : { "command" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0xF4, 0xD5],
					 "response" :  [] #amazon sends the generic smarthub response
			}
		#I'm not sure why Netflix and Amazon are so special, but my TV doesn't have
		#direct access to any other smarthub apps.  Perhaps newer TVs do.
		}

	pictureModes = {
		"DYNAMIC" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x00, 0xCB],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x00, 0x00, 0x00, 0x0c]
			},
		"STANDARD" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x01, 0xCA],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x01, 0x00, 0x00, 0x0b]
			},
		"MOVIE" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x02, 0xC9],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x02, 0x00, 0x00, 0x0a]
			},
		"NATURAL" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x03, 0xC8],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x03, 0x00, 0x00, 0x09]
			},
		"CAL_NIGHT" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x04, 0xC7],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x04, 0x00, 0x00, 0x08]
			},
		"CAL_DAY" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x05, 0xC6],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x05, 0x00, 0x00, 0x07]
			},
		"BD_WISE" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x06, 0xC5],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x06, 0x00, 0x00, 0x06]
			},
		#I have no reference for the display names of modes 7-9, 11-12.
		#If you discover any, please let me know
		"MODE7" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x07, 0xC4],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x07, 0x00, 0x00, 0x05]
			},
		"MODE8" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x08, 0xC3],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x08, 0x00, 0x00, 0x04]
			},
		"MODE9" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x09, 0xC2],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x09, 0x00, 0x00, 0x03]
			},
		"RELAX" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x0a, 0xC1],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x0a, 0x00, 0x00, 0x02]
			},
		"MODE11" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x0b, 0xC0],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x0b, 0x00, 0x00, 0x01]
			},
		"MODE12" : { "command" : [0x08, 0x22, 0x0b, 0x00, 0x00, 0x0c, 0xBF],
					"response" : [0x07, 0x00, 0x00, 0xf1, 0x0c, 0x00, 0x00, 0x00]
			}
		}

	pictureSizes = {
		"SIXTEEN_NINE" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x00, 0xC0],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x00, 0x00, 0x00, 0x0E] },
		"ZOOM1" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x01, 0xBF],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x01, 0x00, 0x00, 0x0D] },
		"ZOOM2" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x02, 0xBE],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x02, 0x00, 0x00, 0x0C] },
		"WIDE_FIT" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x03, 0xBD],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x03, 0x00, 0x00, 0x0B] },
		"FOUR_THREE" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x04, 0xBC],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x04, 0x00, 0x00, 0x0A] },
		"SCREEN_FIT" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x05, 0xBB],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x05, 0x00, 0x00, 0x09] },
		"SMART_VIEW1" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x06, 0xBA],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x06, 0x00, 0x00, 0x08] },
		"SMART_VIEW2" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x01, 0x07, 0xB9],
					"response" : [0x05, 0x00, 0x00, 0xF1, 0x07, 0x00, 0x00, 0x07] },
		#any extra sizes to worry about down here?
	}
	
	soundModes = {
		"STANDARD" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x00, 0xCA],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x00, 0x00, 0x00, 0x0B] },
		"MUSIC" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x01, 0xC9],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x01, 0x00, 0x00, 0x0A] },
		"MOVIE" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x02, 0xC8],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x02, 0x00, 0x00, 0x09] },
		"CLEAR_VOICE" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x03, 0xC7],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x03, 0x00, 0x00, 0x08] },
		"AMPLIFY" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x04, 0xC6],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x04, 0x00, 0x00, 0x07] },
		#I have no reference for the display names of modes greater than 4.
		#If you discover any, please let me know
		"MODE5" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x05, 0xC5],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x05, 0x00, 0x00, 0x06] },
		"MODE6" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x06, 0xC4],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x06, 0x00, 0x00, 0x05] },
		"MODE7" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x07, 0xC3],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x07, 0x00, 0x00, 0x04] },
		"MODE8" : { "command" : [0x08, 0x22, 0x0c, 0x00, 0x00, 0x08, 0xC2],
					"response" : [0x08, 0x00, 0x00, 0xF1, 0x08, 0x00, 0x00, 0x03] },
	}

	#these commands are one-way only (can't read current setting from TV)
	integerCommands = {
		"Backlight" : { "command" : [ 0x08, 0x22, 0x0b, 0x01, 0x00],
							"min" : 0,
							"max" : 20},
		"Sharpness" : { "command" : [0x08, 0x22, 0x0b, 0x04, 0x00],
							"min" : 0,
							"max" : 100},
		"Contrast" : { "command" : [0x08, 0x22, 0x0b, 0x02, 0x00],
							"min" : 0,
							"max" : 100},
		"Brightness" : { "command" : [0x08, 0x22, 0x0b, 0x03, 0x00],
							"min" : 0,
							"max" : 100},
		"Color" : { "command" : [0x08, 0x22, 0x0b, 0x05, 0x00],
							"min" : 0,
							"max" : 100},
		"Tint" : { "command" : [0x08, 0x22, 0x0b, 0x06, 0x00],
							"min" : 0,
							"max" : 100},
		"Volume": { "command" : [0x08, 0x22, 0x01, 0x00, 0x00],
							"min" : 0,
							"max" : 100},
		"Channel" : { "command" : [0x08, 0x22, 0x04, 0x00, 0x00],
							"min" : 1,
							"max" : 999},
		"ShadowDetail" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x02],
							"min" : -2,
							"max" : 2},
		"Gamma" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x03],
							"min" : -2,
							"max" : 2},
		"WhiteBalanceROffset" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x07],
							"min" : 0,
							"max" : 50},
		"WhiteBalanceGOffset" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x08],
							"min" : 0,
							"max" : 50},
		"WhiteBalanceBOffset" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x09],
							"min" : 0,
							"max" : 50},
		"WhiteBalanceRGain" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x0a],
							"min" : 0,
							"max" : 50},
		"WhiteBalanceGGain" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x0b],
							"min" : 0,
							"max" : 50},
		"WhiteBalanceBGain" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x0c],
							"min" : 0,
							"max" : 50},
		"FleshTone" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x0e],
							"min" : 0,
							"max" : 50},
		"3DViewPoint" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x02],
							"min" : -5,
							"max" : 5},
		"3DDepth" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x03],
							"min" : 1,
							"max" : 10},
		"SoundBalance" : { "command" : [0x08, 0x22, 0x0c, 0x01, 0x00],
							"min" : 0,
							"max" : 20},
		"SoundEQ100Hz" : { "command" : [0x08, 0x22, 0x0c, 0x01, 0x01],
							"min" : 0,
							"max" : 20},
		"SoundEQ300Hz" : { "command" : [0x08, 0x22, 0x0c, 0x01, 0x02],
							"min" : 0,
							"max" : 20},
		"SoundEQ1kHz" : { "command" : [0x08, 0x22, 0x0c, 0x01, 0x03],
							"min" : 0,
							"max" : 20},
		"SoundEQ3kHz" : { "command" : [0x08, 0x22, 0x0c, 0x01, 0x04],
							"min" : 0,
							"max" : 20},
		"SoundEQ10kHz" : { "command" : [0x08, 0x22, 0x0c, 0x01, 0x05],
							"min" : 0,
							"max" : 20}
	}
	
	#This list captures actions that carry more than one integer value
	commandGroups = {
		"WhiteBalance" : ["WhiteBalanceRGain", "WhiteBalanceROffset", "WhiteBalanceBGain", "WhiteBalanceBOffset",
							"WhiteBalanceGGain", "WhiteBalanceGOffset"],
		"SoundEQ" : ["SoundEQ100Hz", "SoundEQ300Hz", "SoundEQ1kHz", "SoundEQ3kHz", "SoundEQ10kHz"]
	}
	
	#these commands are one-way only (can't read current setting from TV)
	enumCommands = {
		"PowerOff" : { "command" : [0x08, 0x22, 0x00, 0x00, 0x00, 0x01, 0xD5],
						"name" : "Off"},
		"PowerOn" : { "command" : [0x08, 0x22, 0x00, 0x00, 0x00, 0x02, 0xD4],
						"name" : "On"},

		"BlackToneOff" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x00, 0x00, 0xC4],
						"name" : "Off"},
		"BlackToneDark" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x00, 0x01, 0xC3],
						"name" : "Dark"},
		"BlackToneDarker" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x00, 0x02, 0xC2],
						"name" : "Darker"},
		"BlackToneDarkest" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x00, 0x03, 0xC1],
						"name" : "Darkest"},

		"DynamicCtstOff" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x01, 0x00, 0xC3],
						"name" : "Off"},
		"DynamicCtstLow" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x01, 0x01, 0xC2],
						"name" : "Low"},
		"DynamicCtstMedium" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x01, 0x02, 0xC1],
						"name" : "Medium"},
		"DynamicCtstHigh" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x01, 0x03, 0xC0],
						"name" : "High"},

		"RGBOnlyModeOff" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x05, 0x00, 0xBF],
						"name" : "Off"},
		"RGBOnlyModeRed" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x05, 0x01, 0xBE],
						"name" : "Red"},
		"RGBOnlyModeGreen" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x05, 0x02, 0xBD],
						"name" : "Green"},
		"RGBOnlyModeBlue" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x05, 0x03, 0xBC],
						"name" : "Blue"},

		"ClrSpaceAuto" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x06, 0x00, 0xBE],
						"name" : "Auto"},
		"ClrSpaceNative" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x06, 0x01, 0xBD],
						"name" : "Native"},
		"ClrSpaceCustom" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x06, 0x02, 0xBC],
						"name" : "Custom"},

		"EdgeEnhancementOff" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x0f, 0x00, 0xB5],
						"name" : "Off"},
		"EdgeEnhancementOn" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x0f, 0x01, 0xB4],
						"name" : "On"},

		"xvYCCOff" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x10, 0x00, 0xB4],
						"name" : "Off"},
		"xvYCCOn" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x10, 0x01, 0xB3],
						"name" : "On"},

		"MotionLightingOff" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x11, 0x00, 0xB3],
						"name" : "Off"},
		"MotionLightingOn" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x11, 0x01, 0xB2],
						"name" : "On"},

		"LEDMotionPlusOff" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x07, 0x00, 0xBA],
						"name" : "Off"},
		"LEDMotionPlusNormal" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x07, 0x01, 0xB9],
						"name" : "Normal"},
		"LEDMotionPlusCinema" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x07, 0x02, 0xB8],
						"name" : "Cinema"},
		"LEDMotionPlusTicker" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x07, 0x03, 0xB7],
						"name" : "Ticker"},
		
		"ClrToneCool" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x00, 0x00, 0xC1],
						"name" : "Cool"},
		"ClrToneNormal" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x00, 0x01, 0xC0],
						"name" : "Normal"},
		"ClrToneWarm1" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x00, 0x02, 0xBF],
						"name" : "Warm 1"},
		"ClrToneWarm2" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x00, 0x03, 0xBE],
						"name" : "Warm 2"},
		
		"DigitalNoiseFilterOff" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x02, 0x00, 0xBF],
						"name" : "Off"},
		"DigitalNoiseFilterLow" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x02, 0x01, 0xBE],
						"name" : "Low"},
		"DigitalNoiseFilterMedium" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x02, 0x02, 0xBD],
						"name" : "Medium"},
		"DigitalNoiseFilterHigh" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x02, 0x03, 0xBC],
						"name" : "High"},
		"DigitalNoiseFilterAuto" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x02, 0x04, 0xBB],
						"name" : "Auto"},
		"DigitalNoiseFilterAutoViz" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x02, 0x05, 0xBA],
						"name" : "Auto Visualizer"},
		
		"MPEGNoiseFilterOff" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x03, 0x00, 0xBE],
						"name" : "Off"},
		"MPEGNoiseFilterLow" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x03, 0x01, 0xBD],
						"name" : "Low"},
		"MPEGNoiseFilterMedium" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x03, 0x02, 0xBC],
						"name" : "Medium"},
		"MPEGNoiseFilterHigh" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x03, 0x03, 0xBB],
						"name" : "High"},
		"MPEGNoiseFilterAuto" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x03, 0x04, 0xBA],
						"name" : "Auto"},
		
		"HDMIBlackLevelNormal" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x04, 0x00, 0xBD],
						"name" : "Normal"},
		"HDMIBlackLevelLow" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x04, 0x01, 0xBC],
						"name" : "Low"},
		
		"FilmModeOff" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x05, 0x00, 0xBC],
						"name" : "Off"},
		"FilmModeAuto1" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x05, 0x01, 0xBB],
						"name" : "Auto 1"},
		"FilmModeAuto2" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x05, 0x02, 0xBA],
						"name" : "Auto 2"},
		
		"AutoMotionPlusOff" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x06, 0x00, 0xBB],
						"name" : "Off"},
		"AutoMotionPlusClear" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x06, 0x01, 0xBA],
						"name" : "Clear"},
		"AutoMotionPlusStandard" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x06, 0x02, 0xB9],
						"name" : "Standard"},
		"AutoMotionPlusSmooth" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x06, 0x03, 0xB8],
						"name" : "Smooth"},
		"AutoMotionPlusCustom" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x06, 0x04, 0xB7],
						"name" : "Custom"},
		"AutoMotionPlusDemo" : { "command" : [0x08, 0x22, 0x0b, 0x0a, 0x06, 0x05, 0xB6],
						"name" : "Demo"},
		
		"3DModeOff" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x00, 0xBF],
						"name" : "Off"},
		"3DMode2Dto3D" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x01, 0xBE],
						"name" : "2D to 3D"},
		"3DModeSideBySide" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x02, 0xBD],
						"name" : "Side by Side"},
		"3DModeTopBottom" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x03, 0xBC],
						"name" : "Top / Bottom"},
		"3DModeLineByLine" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x04, 0xBB],
						"name" : "Line by Line"},
		"3DModeVerticalLine" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x05, 0xBA],
						"name" : "Vertical Line"},
		"3DModeCheckerBD" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x06, 0xB9],
						"name" : "Checker BD"},
		"3DModeFrameSequence" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x00, 0x07, 0xB8],
						"name" : "Frame Sequence"},

		"3D2DOff" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x01, 0x00, 0xBE],
						"name" : "Off"},
		"3D2DOn" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x01, 0x01, 0xBD],
						"name" : "On"},

		"3DAutoViewOff" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x05, 0x00, 0xBA],
						"name" : "Off"},
		"3DAutoViewMessageNotice" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x05, 0x01, 0xB9],
						"name" : "Message Notice"},
		"3DAutoViewOn" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x05, 0x02, 0xB8],
						"name" : "On"},

		"3DPictureCorrection" : { "command" : [0x08, 0x22, 0x0b, 0x0c, 0x04, 0x00, 0xBB],
						"name" : "", "OneShot" : True},

		"SRSTruSurroundOff" : { "command" : [0x08, 0x22, 0x0c, 0x02, 0x00, 0x00, 0xC8],
						"name" : "Off"},
		"SRSTruSurroundOn" : { "command" : [0x08, 0x22, 0x0c, 0x02, 0x00, 0x01, 0xC7],
						"name" : "On"},
		
		"SRSTruDialogOff" : { "command" : [0x08, 0x22, 0x0c, 0x03, 0x00, 0x00, 0xC7],
						"name" : "Off"},
		"SRSTruDialogOn" : { "command" : [0x08, 0x22, 0x0c, 0x03, 0x00, 0x01, 0xC6],
						"name" : "On"},
		
		"LanguageEnglish" : { "command" : [0x08, 0x22, 0x0c, 0x04, 0x00, 0x00, 0xC6],
						"name" : "English"},
		"LanguageSpanish" : { "command" : [0x08, 0x22, 0x0c, 0x04, 0x00, 0x01, 0xC5],
						"name" : "Spanish"},
		"LanguageFrench" : { "command" : [0x08, 0x22, 0x0c, 0x04, 0x00, 0x02, 0xC4],
						"name" : "French"},
		"LanguageKorean" : { "command" : [0x08, 0x22, 0x0c, 0x04, 0x00, 0x03, 0xC3],
						"name" : "Korean"},
		"LanguageJapanese" : { "command" : [0x08, 0x22, 0x0c, 0x04, 0x00, 0x04, 0xC2],
						"name" : "Japanese"},
		#maybe there are more languages?  dont' know...
		
		"MTSMono" : { "command" : [0x08, 0x22, 0x0c, 0x05, 0x00, 0x00, 0xC5],
						"name" : "Mono"},
		"MTSStereo" : { "command" : [0x08, 0x22, 0x0c, 0x05, 0x00, 0x01, 0xC4],
						"name" : "Stereo"},
		"MTSSAP" : { "command" : [0x08, 0x22, 0x0c, 0x05, 0x00, 0x02, 0xC3],
						"name" : "SAP"},
		
		"AutoVolumeOff" : { "command" : [0x08, 0x22, 0x0c, 0x06, 0x00, 0x00, 0xC4],
						"name" : "Off"},
		"AutoVolumeNormal" : { "command" : [0x08, 0x22, 0x0c, 0x06, 0x00, 0x01, 0xC3],
						"name" : "Normal"},
		"AutoVolumeNight" : { "command" : [0x08, 0x22, 0x0c, 0x06, 0x00, 0x02, 0xC2],
						"name" : "Night"},
		
		"SpeakerSelectTV" : { "command" : [0x08, 0x22, 0x0c, 0x07, 0x00, 0x00, 0xC3],
						"name" : "Internal Speakers"},
		"SpeakerSelectExternal" : { "command" : [0x08, 0x22, 0x0c, 0x07, 0x00, 0x01, 0xC2],
						"name" : "External Speakers"},
		
		"TVModeCable" : { "command" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x7B, 0x4E],
						"name" : "Cable"},
		"TVModeAntenna" : { "command" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x7D, 0x4C],
						"name" : "Antenna"},

		"ResetWhiteBalance" : { "command" : [0x08, 0x22, 0x0b, 0x07, 0x0d, 0x00, 0xB7],
						"name" : "", "OneShot" : True},
		"ResetPicture" : { "command" : [0x08, 0x22, 0x0b, 0x0b, 0x00, 0x00, 0xC0],
						"name" : "", "OneShot" : True},
		"ResetSound" : { "command" : [0x08, 0x22, 0x0c, 0x09, 0x00, 0x00, 0xC1],
						"name" : "", "OneShot" : True},
		"ResetEqualizer" : { "command" : [0x08, 0x22, 0x0c, 0x01, 0x06, 0x00, 0xC3],
						"name" : "", "OneShot" : True}
	}

	########################################
	# Communication utility functions

	######################
	def checkSerial(self, dev):
		if self.serialConns.get(dev.id) is not None:
			junk = []
			while self.serialConns[dev.id].in_waiting:
				junk += self.serialConns[dev.id].read(1)
			if len(junk) > 0:
				length = str(len(junk))
				self.logger.warn(u"Received "+length+" unexpected bytes: "+binascii.hexlify(bytearray(junk)))
			return True

		#we need to figure out the serial type to find the port path
		portType = dev.pluginProps.get(u"devicePortFieldId_serialConnType", u"")
		portName = dev.pluginProps.get(u"devicePortFieldId_serialPortLocal", u"")
		if portType == "netRfc2217":
			portName = dev.pluginProps.get(u"devicePortFieldId_serialPortNetRfc2217", u"")
		elif portType == "netSocket":
			portName = dev.pluginProps.get(u"devicePortFieldId_serialPortNetSocket", u"")
		self.logger.info(u"opening serial port "+portName)
		self.serialConns[dev.id] = self.openSerial(dev.name, portName, 9600,
			timeout=self.defaultSerialTimeout)
		if self.serialConns[dev.id] is None:
			self.logger.error(u"unable to open serial port")
			return False
		else:
			self.serialConns[dev.id].flushInput() # abundance of caution
			self.serialConns[dev.id].flushOutput() # abundance of caution

		return True

	########################################
	def waitForAck(self, dev):
		if self.serialConns.get(dev.id) is not None:
			reply = []
			reply += self.serialConns[dev.id].read(3)
			if bytearray(reply) == bytearray(self.responses["ACK"]):
				self.logger.debug(u"Command ack received: "+binascii.hexlify(bytearray(reply)))
				return True
		self.logger.warn(u"Command not acknowledged by device")
		return False

	########################################
	def sendQuery(self, dev, query):
		if query not in self.queries:
			self.logger.error("Invalid query "+query)
			return
			
		if self.serialConns.get(dev.id) is not None:
			self.serialConns[dev.id].write(bytearray(self.queries[query]))
			if self.waitForAck(dev):
				reply = []
				reply += self.serialConns[dev.id].read(self.responseDataLength)
				length = str(len(reply))
				self.logger.debug(query+" query returned "+length+" bytes: "+binascii.hexlify(bytearray(reply)))
				return reply

		return []

	########################################
	def calculateChecksum(self, commandArray):
		sum = 0
		for i in commandArray:
			sum += i
		CRC = (0x100 - sum) & 0xFF
		#self.logger.debug(u"CRC for "+binascii.hexlify(bytearray(commandArray))+" is %x" % CRC)
		return CRC
		
	########################################
	def validateChecksum(self, response):
		if len(response) < 3:
			return False
		checksum = ord(response[-1])
		sum = 0
		for i in response[0:-1]:
			sum = (sum + ord(i)) & 0xFF

		if ord(response[-1]) == ((0x100 - sum) & 0xFF):
			return True

		return False
		
	########################################
	def sendIntegerCommand(self, dev, command, value):
		if command not in self.integerCommands:
			self.logger.error("Invalid integer command "+command)
			return
			
		cmdPacket = list(self.integerCommands[command]["command"])
		if self.checkSerial(dev):
			cmdPacket.append(value)
			cmdPacket.append(self.calculateChecksum(cmdPacket))
			self.serialConns[dev.id].write(bytearray(cmdPacket))
			if self.waitForAck(dev):
				self.logger.info(u"Sent %s = %s " % (command, str(value)))
				return True
			else:
				self.logger.error(u"Command "+command+" not acknowledged")
				return False
				
	########################################
	def sendEnumCommand(self, dev, command):
		if command not in self.enumCommands:
			self.logger.error("Invalid enum command "+command)
			return
			
		if self.checkSerial(dev):
			self.serialConns[dev.id].write(bytearray(self.enumCommands[command]["command"]))
			if self.waitForAck(dev):
				self.logger.info(u"Sent "+command)
				return True
			else:
				self.logger.error(u"Command "+command+" not acknowledged")
				return False


	########################################
	# Device state inquiries/updaters
	# Many of these are quite similar; perhaps they should be refactored

	########################################
	def isPowerOn(self, dev):
		#reduce serial read timeout before querying power so we don't wait forever
		#when the device is off
		self.serialConns[dev.id].timeout = self.powerSerialTimeout
		reply = self.sendQuery(dev, "POWER")
		self.serialConns[dev.id].timeout = self.defaultSerialTimeout
		if bytearray(reply) == bytearray(self.responses["POWER"]):
			self.logger.info(u"Device acknowledges power ON")
			return True
		elif len(reply) > 0:
			self.logger.info(u"Device sent unexpected response, but it must be on")
			return True;
		else:
			self.logger.debug(u"Power query not acknowleged. device must be off.")
			return False	

	########################################
	def updateInput(self, dev):
		reply = self.sendQuery(dev, "INPUT")
		for input in self.inputs:
			if bytearray(reply[-8:]) == bytearray(self.inputs[input]["response"]):
				self.logger.info(u"Active input is "+input)
				dev.updateStateOnServer("input", input)
				return
		
		if self.validateChecksum(reply):
			self.logger.warn(u"Input query returned unrecognized response "+binascii.hexlify(bytearray(reply)))
			self.logger.warn(u"Please let the author know which input this is!")
		else:
			self.logger.error(u"Input query response bad CRC: "+binascii.hexlify(bytearray(reply)))

			dev.updateStateOnServer("input", "UNKNOWN")		

	########################################
	def updatePictureMode(self, dev):
		reply = self.sendQuery(dev, "PICTURE_MODE")
		for mode in self.pictureModes:
			if bytearray(reply[-8:]) == bytearray(self.pictureModes[mode]["response"]):
				self.logger.info(u"Current Picture Mode is "+mode)
				if mode.startswith("MODE"):
					self.logger.warn(u"Please let the author know what your TV calls this mode!")
				dev.updateStateOnServer("pictureMode", mode)
				return
		
		if self.validateChecksum(reply):
			#unknown mode
			self.logger.warn(u"Picture Mode returned unknown response "+binascii.hexlify(bytearray(reply)))
		else:
			self.logger.error(u"Picture Mode query response bad CRC: "+binascii.hexlify(bytearray(reply)))

		dev.updateStateOnServer("pictureMode", "UNKNOWN")

	########################################
	def updateSoundMode(self, dev):
		reply = self.sendQuery(dev, "SOUND_MODE")
		for mode in self.soundModes:
			if bytearray(reply[-8:]) == bytearray(self.soundModes[mode]["response"]):
				self.logger.info(u"Current Picture Mode is "+mode)
				if mode.startswith("MODE"):
					self.logger.warn(u"Please let the author know what your TV calls this mode!")
				dev.updateStateOnServer("soundMode", mode)
				return
		
		if self.validateChecksum(reply):
			#unknown mode
			self.logger.warn(u"Sound Mode returned unknown response "+binascii.hexlify(bytearray(reply)))
		else:
			self.logger.error(u"Sound Mode query response bad CRC: "+binascii.hexlify(bytearray(reply)))

		dev.updateStateOnServer("soundMode", "UNKNOWN")

	########################################
	def updatePictureSize(self, dev):
		reply = self.sendQuery(dev, "PICTURE_SIZE")
		for mode in self.pictureSizes:
			if bytearray(reply[-8:]) == bytearray(self.pictureSizes[mode]["response"]):
				self.logger.info(u"Current Picture Mode is "+mode)
				#Should we add placeholders for unknown sizes?
				dev.updateStateOnServer("pictureSize", mode)
				return
		
		if self.validateChecksum(reply):
			#unknown mode
			self.logger.warn(u"Picture Size returned unknown response "+binascii.hexlify(bytearray(reply)))
		else:
			self.logger.error(u"Picture Size query response bad CRC: "+binascii.hexlify(bytearray(reply)))

		dev.updateStateOnServer("pictureSize", "UNKNOWN")

	########################################
	def update3dState(self, dev):
		reply = self.sendQuery(dev, "3D_STATE")
		if self.validateChecksum(reply):
			#TODO figure out messaging.  Not sure what exactly "3d state" means in this context
			self.logger.debug(u"Received valid 3D state response "+binascii.hexlify(bytearray(reply))+
					".  Someday we'll know what it means.")
		else:
			self.logger.error(u"3D State query response bad CRC: "+binascii.hexlify(bytearray(reply)))

	########################################
	def updateChannel(self, dev):
		reply = self.sendQuery(dev, "CHANNEL")
		if self.validateChecksum(reply):
			#value is in byte 9
			val = str(ord(reply[9]))
			self.logger.info(u"Current Channel is "+val)
			#value is an integer state
			dev.updateStateOnServer("channel", val)
		else:
			self.logger.error(u"Channel query response bad CRC: "+binascii.hexlify(bytearray(reply)))

	########################################
	def updateVolume(self, dev):
		reply = self.sendQuery(dev, "VOLUME")
		if self.validateChecksum(reply):
			#value is in byte 9
			val = str(ord(reply[9]))
			self.logger.info(u"Current Volume is "+val)
			#value is an integer state
			dev.updateStateOnServer("volume", val)
		else:
			self.logger.error(u"Volume query response bad CRC: "+binascii.hexlify(bytearray(reply)))

	########################################
	def updateMute(self, dev):
		reply = self.sendQuery(dev, "MUTE")
		if self.validateChecksum(reply):
			#value is in byte 9
			val = (ord(reply[9]) == 1)
			self.logger.info(u"Current Mute is "+str(val))
			#mute is a boolean state
			dev.updateStateOnServer("mute", val)
		else:
			self.logger.error(u"Mute query response bad CRC: "+binascii.hexlify(bytearray(reply)))

	########################################
	# Device commands : two-way synchronized

	########################################
	def powerOff(self, dev):
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			#reduce serial read timeout because if the TV is already off it won't
			#  ack the command and we don't want to hang the server
			self.serialConns[dev.id].timeout = self.powerSerialTimeout
			self.sendEnumCommand(dev, "PowerOff")
			dev.updateStateOnServer("onOffState", False)
			self.serialConns[dev.id].timeout = self.defaultSerialTimeout
		self.serialLocks[dev.id].release()
			
	########################################
	def powerOn(self, dev):
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			if self.sendEnumCommand(dev, "PowerOn"):
				dev.updateStateOnServer("onOffState", True)
		self.serialLocks[dev.id].release()
	
	########################################
	def selectInput(self, action):
		dev = indigo.devices[action.deviceId]
		input = action.props["Input"]
		if input not in self.inputs:
			self.logger.error(input+" is not a valid input")
			return
			
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			try:
				self.logger.debug(u"selecting input "+input)
				self.serialConns[dev.id].write(bytearray(self.inputs[input]["command"]))
				self.waitForAck(dev)
				self.updateInput(dev)
			except:
				self.logger.error("Internal error changing input")
				pass
		self.serialLocks[dev.id].release()

	########################################
	def setPictureMode(self, action):
		dev = indigo.devices[action.deviceId]
		mode = action.props["Mode"]
		if mode not in self.pictureModes:
			self.logger.error(mode+" is not a valid picture mode")
			return
			
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			try:
				self.logger.debug(u"selecting picture mode "+mode)
				self.serialConns[dev.id].write(bytearray(self.pictureModes[mode]["command"]))
				self.waitForAck(dev)
				self.updatePictureMode(dev)
			except:
				self.logger.error("Internal error updating picture mode")
				pass

		self.serialLocks[dev.id].release()

	########################################
	def setPictureSize(self, action):
		dev = indigo.devices[action.deviceId]
		size = action.props["Size"]
		if size not in self.pictureSizes:
			self.logger.error(size+" is not a valid picture size")
			return
			
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			try:
				self.logger.debug(u"selecting picture size "+size)
				self.serialConns[dev.id].write(bytearray(self.pictureSizes[size]["command"]))
				self.waitForAck(dev)
				self.updatePictureSize(dev)
			except:
				self.logger.error("Internal error changing picture size")
				pass

		self.serialLocks[dev.id].release()

	########################################
	def setSoundMode(self, action):
		dev = indigo.devices[action.deviceId]
		mode = action.props["Mode"]
		if mode not in self.soundModes:
			self.logger.error(mode+" is not a valid sound mode")
			return
			
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			try:
				self.logger.debug(u"selecting sound mode "+mode)
				self.serialConns[dev.id].write(bytearray(self.soundModes[mode]["command"]))
				self.waitForAck(dev)
				self.updateSoundMode(dev)
			except:
				self.logger.error("Internal error changing sound mode")
				pass

		self.serialLocks[dev.id].release()

	########################################
	def setChannel(self, action):
		dev = indigo.devices[action.deviceId]
		channel = 0
		try:
			channel = int(action.props["Channel"])
		except:
			self.logger.error('''"'''+action.props["Channel"]+'''" is not a valid channel''')
			return

		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			try:
				self.sendIntegerCommand(dev, "Channel", channel)
				self.updateChannel(dev)
			except:
				self.logger.error("Internal error changing channel")
				pass				
		self.serialLocks[dev.id].release()

	########################################
	def setVolume(self, action):
		dev = indigo.devices[action.deviceId]
		volume = 0
		try:
			volume = int(action.props["Volume"])
		except:
			self.logger.error('''"'''+action.props["Volume"]+'''" is not a valid volume''')
			return
		
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			try:
				self.sendIntegerCommand(dev, "Volume", volume)
				self.updateVolume(dev)
			except:
				self.logger.error("Internal error changing volume")
				pass				
		self.serialLocks[dev.id].release()

	########################################
	# Device commands : one-shot

	########################################
	# note *some* of the button events trigger status inquiries
	def sendSingleButton(self, action):
		buttons = {
			"MENU" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x1A, 0xAF],
			"UP" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x60, 0x69],
			"DOWN" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x61, 0x68],
			"LEFT" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x65, 0x64],
			"RIGHT" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x62, 0x67],
			"ENTER" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x68, 0x61],
			"EXIT" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x2D, 0x9C],
			"MUTE" : [0x08, 0x22, 0x02, 0x00, 0x00, 0x00, 0xD4],
			"VOLUP" : [0x08, 0x22, 0x01, 0x00, 0x01, 0x00, 0xD4],
			"VOLDOWN" : [0x08, 0x22, 0x01, 0x00, 0x02, 0x00, 0xD3],
			"CHUP" : [0x08, 0x22, 0x03, 0x00, 0x01, 0x00, 0xD2],
			"CHDOWN" : [0x08, 0x22, 0x03, 0x00, 0x02, 0x00, 0xD1],
			"PRECH" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x13, 0xB6],
			"FAVCH" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x44, 0x85],
			"CHADD" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x19, 0xB0],
			"CAPTION" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x25, 0xA4],
			"SLEEP" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x03, 0xC6],
			"GUIDE" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x4F, 0x7A],
			"INFO" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x1F, 0xAA],
			"RETURN" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x58, 0x71],
			"TOOLS" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x4B, 0x7E],
			"RED" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x6C, 0x5D],
			"GREEN" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x14, 0xB5],
			"YELLOW" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x15, 0xB4],
			"BLUE" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x16, 0xB3],
			"PLAY" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x47, 0x82],
			"PAUSE" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x4A, 0x7F],
			"STOP" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x46, 0x83],
			"REC" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x49, 0x80],
			"REW" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x45, 0x84],
			"FF" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x48, 0x81],
			"SKIPF" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x4E, 0x7B],
			"SKIPB" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x50, 0x79],
			"SOURCE" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x01, 0xC8],
			"PICMODE" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x28, 0xA1],
			"SNDMODE" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x2B, 0x9E],
			"CH_LIST" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x6B, 0x5E],
			"MORE" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x9C, 0x2D],
			"KEY_0" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x11, 0xB8],
			"KEY_1" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x04, 0xC5],
			"KEY_2" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x05, 0xC4],
			"KEY_3" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x06, 0xC3],
			"KEY_4" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x08, 0xC1],
			"KEY_5" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x09, 0xC0],
			"KEY_6" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x0A, 0xBF],
			"KEY_7" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x0C, 0xBD],
			"KEY_8" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x0D, 0xBC],
			"KEY_9" : [0x08, 0x22, 0x0d, 0x00, 0x00, 0x0E, 0xBB]
		}
		
		dev = indigo.devices[action.deviceId]
		button = action.props["Button"]
		if button not in buttons:
			self.logger.error(button+" is not a valid key")
			return

		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			try:
				self.logger.debug(u"sending button "+button)
				self.serialConns[dev.id].write(bytearray(buttons[button]))
				if self.waitForAck(dev):
					#status queries - volume, mute, channel, picture mode, sound mode, input
					#there's sometimes a delay before the new state is reflected in a query.
					#maybe sleep here, but it'd probably better to throw off an update thread
					if button == "VOLUP" or button == "VOLDOWN":
						self.updateVolume(dev)
					elif button == "MUTE":
						self.updateMute(dev)
					elif button == "CHUP" or button == "CHDOWN" or button == "PRECH" or button == "FAVCH":
						#Should we do an updateChannel every time a digit is pressed?  that seems too chatty.
						self.updateChannel(dev)
					elif button == "SOURCE":
						self.updateInput(dev)
					elif button == "PICMODE":
						self.updatePictureMode(dev)
					elif button == "SNDMODE":
						self.updateSoundMode(dev)
				else:
					self.logger.error(u"Button "+button+" not acknowledged")
			except:
				self.logger.error("Internal error sending "+button)
				pass					
		self.serialLocks[dev.id].release()

	########################################
	#This handles actions with any number of integer fields
	def integerAction(self, action):
		dev = indigo.devices[action.deviceId]
		for command in props:
			try:
				value = int(action.props[command])
				self.serialLocks[dev.id].acquire()
				self.sendIntegerCommand(dev, command, value)
				self.serialLocks[dev.id].release()
			except:
				self.logger.error("Internal error processing command "+command)
				pass

	########################################
	def enumAction(self, action):
		dev = indigo.devices[action.deviceId]
		command = action.props["Command"]
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			self.sendEnumCommand(dev, command)
		self.serialLocks[dev.id].release()

	########################################
	def oneshotAction(self, action):
		dev = indigo.devices[action.deviceId]
		self.serialLocks[dev.id].acquire()
		if self.checkSerial(dev):
			self.sendEnumCommand(dev, str(action.pluginTypeId))
		self.serialLocks[dev.id].release()
		
	########################################
	def compoundAction(self, action):
		dev = indigo.devices[action.deviceId]
		self.logger.debug(action)
		group = action.props.get("CommandGroup", "")
		if (action.props.get("Command", "") != ""):
 			self.serialLocks[dev.id].acquire()
			self.logger.debug("This is enum action "+action.props["Command"])
			try:
				self.sendEnumCommand(dev, action.props["Command"])
 			except:
 				self.logger.error("Internal error processing command "+action.props["Command"])
 				pass
 			self.serialLocks[dev.id].release()
			return

		for cmdGroup in self.commandGroups:
			if cmdGroup == group:
				self.serialLocks[dev.id].acquire()
				self.logger.debug("This is an integer group "+group)
				for element in self.commandGroups[cmdGroup]:
					self.logger.debug("Sending element "+element)
					try:
						value = int(action.props[element])
						self.sendIntegerCommand(dev, element, value)
					except:
						self.logger.error("Internal error processing command "+element)
						pass
				self.serialLocks[dev.id].release()
		
		for cmd in self.integerCommands:
			if cmd == group:
				self.serialLocks[dev.id].acquire()
				self.logger.debug("This is a single integer command "+group)
				try:
					value = int(action.props[cmd])
					self.sendIntegerCommand(dev, cmd, value)
				except:
					self.logger.error("Internal error processing command "+cmd)
					pass
				self.serialLocks[dev.id].release()

		for cmd in self.enumCommands:
			if cmd == group:
				self.serialLocks[dev.id].acquire()
				self.logger.debug("This is one-shot command "+group)
				try:
					self.sendEnumCommand(dev, cmd)
				except:
					self.logger.error("Internal error processing command "+cmd)
					pass
				self.serialLocks[dev.id].release()

	########################################
	def doNothingMethod(self, valuesDict, typeId="", devId=None):
		# This method doesn't do anything itself, but its existence
		# forces the commandGenerator method below to get called.
		#self.logger.debug("doNothingMethod called")
		return

	########################################
	def commandGenerator(self, filter="", valuesDict=None, typeId="", devId=None):
		self.debugLog("dynamicMenuGenerator called")
		self.logger.debug(valuesDict)
		group = valuesDict.get("CommandGroup", "")
		returnList = []

		if group == "":
			return returnList

		self.logger.debug("Looking up values for "+group)
		for command in self.enumCommands:
			if command.startswith(group):
				returnList.extend([(command, self.enumCommands[command]["name"])])
				
		return returnList
