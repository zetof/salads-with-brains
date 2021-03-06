#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import logging.config
import time
import serial
from i18n import I18N
from alarms import Alarms
from lcd import LCDDisplay
from alarmpanel import AlarmPanel
from usb import USBDaemon
from httpservices import HttpServices

# Classe permettant de piloter tout type de communication dans l'unité VERT-X à savoir:
#		* Le panneau des alarmes lumineuses et visuelles
#		* L'écran LCD de l'unité
#		* L'écriture dans les logs applicatifs
#		* La communication avec les Arduinos
#
class Talk:

	# Liste des états hérités de la classe de logging
	#
	DEBUG = logging.DEBUG				# Message de type DEBUG
	INFO = logging.INFO					#	Message de type INFO
	WARNING = logging.WARNING		# Message de type WARNING
	ERROR = logging.ERROR				# Message de type ERROR
	CRITICAL = logging.CRITICAL	# Message de type CRITICAL

	# Paramètres de connexion à l'ARDUINO en cas de problème
	CONNECT_MAX_TRIALS = 3	# Nombre de tentatives de connection à un Arduino avant la levée d'une alarme
	CONNECT_WAIT_TIME = 10	# Temps d'attente entre deux essais de connexion

	# Méthode permettant de logger un message dans les fichiers de log
	# Le type est l'un des types défini par la classe logging
	# Le message est un tableau à une dimension []
	#		- le premier élément contient le label du message à afficher après traduction par l'i18n
	#		- les éléemnts suivants sont les éléments à substituer dans la phrase si nécessaire
	#
	def log(self, mType, message):

		# Traduction du message
		i18nMessage = self.i18n.t(message[0], message[1:])

		# Log au niveau requis
		if mType == self.DEBUG:
			self.logger.debug(i18nMessage)
		elif mType == self.INFO:
			self.logger.info(i18nMessage)
		elif mType == self.WARNING:
			self.logger.warning(i18nMessage)
		elif mType == self.ERROR:
			self.logger.error(i18nMessage)
		elif mType == self.CRITICAL:
			self.logger.critical(i18nMessage)

	# Méthode permettant l'ajout d'une alarme dans la liste des alarmes
	#
	def setAlarm(self, aType, aMessage, aAction = None):

		# Au début, on n'a pas de clé d'alarme
		aKey = None

		# Dans tous les cas, si le message passé n'est pas égal à False, on enregistre le message dans les logs
		if aMessage != False:
			self.log(aType, aMessage)

		# Pour le panneau des alarmes, on ajoute une alarme dans la liste
		# et on envoie une demande de notification au panneau des alarmes
		if aType == self.WARNING:
			self.alarmPanel.setWarning()
		elif aType == self.ERROR or aType == self.CRITICAL:
			self.alarmPanel.setAlert()
		aKey = self.alarms.addAlarm(aType, aMessage, aAction) 

		# On retourne la référence de l'alarme enregistrée
		return aKey

	# Méthode permettant la suppression d'une alarme dans la liste des alarmes
	# La suppression se fait par la clé précédemment enregistrée
	# A la suppression, on vérifie si on doit mettre à jour les flags d'alarme dans le panneau des alarmes
	#
	def resetAlarm(self, aMessage, aKey = None, aAction = None):

		# Si le message est différent de False on l'enregistre dans les logs sous forme d'une INFO
		if aMessage != False:
			self.log(self.INFO, aMessage)

		# On supprime l'alarme de la liste des alarmes suiant le type de données passée en paramètre
		if aKey != None:
			self.alarms.clearAlarmFromKey(aKey)
		if aAction != None:
			self.alarms.clearAlarmFromAction(aAction)

		# On vérifie si le panneau des alarmes doit être mis à jour
		if not self.alarms.anyWarning():
			self.alarmPanel.resetWarning()
		if not self.alarms.anyAlert():
			self.alarmPanel.resetAlert()

	# Méthode ajoutant un Arduino dans la liste des Arduinos à contacter
	#
	def addArduino(self, aName, aPort, aSpeed, callback):
		
		# On initialise les paramètres de connexion
		alarm = None
		arduino = None
		nbrOfTrials = 0

		# Tant qu'on n'a pas réussi une connection vers l'Arduino, on réessaie
		while arduino == None:

			# On tente une connection vers l'Arduino
			try:
				arduino = USBDaemon(aName, aPort, aSpeed, callback)
				self.arduinos.append(arduino)

				# A ce stade, la connexion est réussie
				# Si nous avions une erreur de connexion auparavent, on la supprime
				if alarm != None:
					self.resetAlarm(['info.usb.arduino.connect.ok', aName], aKey = alarm)

			# Si on y arrive pas, on rapporte l'erreur et on boucle
			except serial.SerialException as e:
				
				# On incrémente le nombre d'essais infructueux à la connexion
				# Si on a dépassé le nombre maximum d'essais, on continue d'essayer mais on envoie une ALARM
				nbrOfTrials += 1
				if nbrOfTrials == self.CONNECT_MAX_TRIALS:
					alarm = self.setAlarm(self.ERROR, ['alert.usb.arduino.connect.ko', aName])

				# On attend un instant avant de retenter
				time.sleep(self.CONNECT_WAIT_TIME)

	# Méthode permettant d'envoyer une commande à un des Arduinos
	#
	def sendArduino(self,machineName, command, data):

		# Formatte la commande à envoyer suivant les données passées en paramètres
		string2Send = command + ':'
		string2Send += ':'.join(str(val) for val in data) + '\n'

		# On recherche l'Arduino demandé afin de lui envoyer la commande
		for index, arduino in enumerate(self.arduinos):

			# Si on a trouvé l'Arduino, on essaie d'envoyer la commande
			if arduino.machineName == machineName:
				try:
					arduino.sendCommand(string2Send)

				# Si on y arrive pas, on enregistre le problème et on remonte l'exception
				except serial.SerialException as e:
					raise e

	# Méthode à appeler à l'arrêt général du programme afin de quitter tous les processus de façon contrôlée
	#
	def stop(self):

		# On arrête les processus tournant sur le panneau des alarmes, l'écran LCD et tous les Arduinos
		self.alarmPanel.stop()
		self.lcd.stop()
		for arduino in self.arduinos:
			arduino.stop()

	# Constructeur de la classe
	#
	def __init__(self, loggerName, locale, wsURL, wsUser, wsPwd, callback):

		# Initialisation du logging
		logging.config.fileConfig('logging.conf')
		self.logger = logging.getLogger(loggerName)

		# Initialisation du langage
		self.i18n = I18N(locale)

		# Liste des alarmes en cours
		self.alarms = Alarms()

		# Initialisation du panneau des alarmes
		self.alarmPanel = AlarmPanel(8, 7, 11, 9, 600, True);

		# Initialisation de l'écran LCD
		self.lcd = LCDDisplay(27, 22, 25, 24, 23, 18, 16, 2, 4)

		# Liste des Arduinos à contacter
		self.arduinos = []

		# Démarrage du serveur de commande et de la communication vers internet
		self.httpServices = HttpServices(wsURL, wsUser, wsPwd, callback)
