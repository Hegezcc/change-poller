#!/usr/bin/env python3
# -*- encoding: UTF-8 -*-

from selenium import webdriver
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from gettext import ngettext
from json.decoder import JSONDecodeError

import os
import sys
import json
import re
import time
import subprocess
import argparse
import logging
import logging.handlers

__program_name__ = 'change-poller'
__version__ = 0.1
_valid_notification_events = ['notify', 'log', 'print']
_default_browser = 'Firefox'
_debug = False

conf = {}

# Convert verbosity to logger format
_verbosityToLevel = {
	-1: logging.CRITICAL,
	0: logging.WARNING,
	1: logging.INFO,
	2: logging.DEBUG
}

def main():
	"""Load configuration, parse args and do required things"""

	argConf, whatToDo, setParams = parseArgs()

	# The logging library makes sure we don't need to save an instance of logger as we can just get it from the cache
	setupLogger(argConf)

	conf, addedPageUrls = getConfig(argConf, setParams)

	if _debug: _log('debug', 'Starting up {} v{}'.format(__program_name__, __version__), argConf)

	# Do things to be done
	if 'print-config' in whatToDo:
		_log('info', 'Printing out configuration')

		print(formatJSON(conf), file=sys.stderr)

	if 'save-config' in whatToDo:
		_log('info', 'Saving configuration to {}'.format(conf['config_file']))

		with open(conf['config_file'], 'w') as f:
			f.write(formatJSON(conf))

	if 'run' in whatToDo:
		changes, tryAgain = run(conf, addedPageUrls)

		# Wrap following code in try-finally to ensure no error will hinder the tryAgain saving

		try:
			if len(changes) == 0:
				_log('info', 'No changes detected')
			else:
				# Run summary events
				change_data = {
				 'timestamp': int(time.time()),
				 'changed_count': len(changes),
				 'change_data': changes
				}

				_log(
					'info',
					'Changes detected at {} (UNIX timestamp {}). Change count: {}'.format(
						time.ctime(change_data['timestamp']),
						change_data['timestamp'],
						change_data['changed_count']
					), conf)

				if len(conf['event_list']) == 0:
					if _debug: _log('debug', 'No notification events to run')
				else:
					if _debug: _log('debug', 'Running notification events ({})'.format(', '.join(conf['event_list'])))

				if 'log' in conf['event_list']:
					if _debug: _log('debug', 'Appending change data to log file ({})'.format(conf['log_path']))

					with open(conf['log_path'], 'a') as f:
						bytes = f.write(formatJSON(change_data))

						_log('info', 'Change data saved to log file, size changed by {} bytes'.format(bytes))

				if 'print' in conf['event_list']:
					# TODO: is this too obvious and over-logging?
					if _debug: _log('debug', 'Printing change data into stdout in json')
					print(formatJSON(change_data), file=sys.stdout)

					_log('info', 'Printed change data into stdout')
				
				if 'notify' in conf['event_list']:

					# Check that we have the notify-send command
					if not any(os.access(os.path.join(path, 'notify-send'), os.X_OK) for path in os.environ['PATH'].split(os.pathsep)):
						_log('warning', 'Cannot find "notify-send" in system! Please install it (or symlink somehow if not possible).')
					else:
						if _debug: _log('debug', 'Notifying user')
						# Make the command to notify-send
						cmd = ['notify-send', str(change_data['changed_count']) + ngettext(' change', ' changes', change_data['changed_count']) + ' in followed sites']

						# Also get sites
						sites = []

						m = min(change_data['changed_count'], 3)
						i = 0

						while len(sites) < m:
							if changes[i]['domain'] not in sites:
								sites.append(changes[i]['domain'])

							i += 1

							if change_data['changed_count'] <= i:
								break
					
						if len(sites) < change_data['changed_count']:
							sites.append('...')

						cmd.append("\n".join(sites))
					
						# Finally call it
						subprocess.call(cmd)

						_log('info', 'Sent a notification about changes to user')
						if _debug: _log('debug', 'The command: {}'.format(' '.join(cmd)))

		finally:
			if len(tryAgain) > 0:
				_log('info', 'Now trying to save unsaved changes ({}) again'.format(len(tryAgain)))

				for data_file in tryAgain:
					if _debug: _log('debug', 'Trying to save {}'.format(data_file))

					try:
						with open(data_file, 'w') as f:
							f.write(tryAgain[data_file])
							_log('info', 'Previously errored file ({}) saved now happily.'.format(data_file))
					except OSError as err:
						_log('warning', 'Cannot save data file ({})! {}: {}'.format(data_file, type(err).__name__, str(err)))

def parseArgs():
	"""Parses arguments given at command line."""


	global conf
	global _debug

	parser = argparse.ArgumentParser(description='Poll web pages for updates. Give this program the urls, CSS selectors and regexes to watch for content changes.')

	verbos = parser.add_mutually_exclusive_group()

	parser.add_argument('-p', '--page', action='append', nargs='+', metavar='URL SELECTOR [REGEX]', help='add an url to fetch, CSS selector and optionally a regex for inner text. May give multiple.')
	parser.add_argument('-b', '--browser',			action='store',				help='use custom browser for Selenium. Default: ' + _default_browser)
	parser.add_argument('-x', '--use-xvfb',			action='store_true',	help='use a headless X server, Xvfb to run the browser')
	parser.add_argument('-e', '--event-list',		action='append',			help='events to do for notification, valid args: ' + ', '.join(_valid_notification_events) + '. May give multiple.')
	parser.add_argument('-l', '--log-path',			action='store',				help='set the page change log path')
	parser.add_argument('-S', '--save-config',	action='store_true',	help="save configuration to given path, don't run main program")
	parser.add_argument('-P', '--print-config',	action='store_true',	help="print out configuration, don't run main program")
	parser.add_argument('-c', '--config-file',	action='store',				help='set the configuration file')
	parser.add_argument('-d', '--data-dir',			action='store',				help='set the data directory to store page contents')
	parser.add_argument('-n', '--no-run',				action='store_true',	help="don't run the poller")
	verbos.add_argument('-v', '--verbose', 			action='count',				help='be verbose (add multiple to be more verbose)', default=0)
	verbos.add_argument('-q', '--quiet',				action='store_true',	help='print no output')
	parser.add_argument('-V', '--version',			action='version',	version='%(prog)s ' + str(__version__), help='print out version')

	args = parser.parse_args()

	argConf = {
		'pages': []
	}
	whatToDo = []
	setParams = []

	# Define verbosity first just after argparse lefts the wheel
	if args.quiet:
		argConf['verbosity'] = -1
	elif args.verbose:
		argConf['verbosity'] = args.verbose

		# Change _debug to True if we are verbose enough
		if args.verbose >= 2:
			_debug = True
	else:
		argConf['verbosity'] = 0

	if _debug: _log('debug', 'Initializing {} v{}'.format(__program_name__, __version__), argConf)

	# The {} is for count of arguments. min() is used so if sys.argv is empty, the count will not be -1
	if _debug: _log('debug', 'Started parsing command line arguments (count {})'.format(max(0, len(sys.argv)-1)), argConf)

	if args.page:

		setParams.append('pages')

		page_help = 'You must give an url, CSS selector for it and optionally a regex for its inner text. So in total 2 or 3 args for each --page.'

		# This regex tries to be pretty liberal about parsing an url.
		# And also save some processor time by compiling the regex first so it's parsed in the memory already
		url_regex = re.compile('https?://[-a-zA-Z0-9@:%._\+~#=]{2,256}\.[a-z]{2,63}/?[-a-zA-Z0-9@:%_\+.~#?&//=]*')

		for p in args.page:

			setParams.append('pages')
			# Do syntax check for the page argument
			# Check that the page argument count actually is between 2 and 3
			if len(p) < 2:
				parser.error('Too few page arguments for "' + p[0] + '"! ' + page_help)
			if len(p) > 3:
				parser.error('Too much page arguments for "' + p[0] + '"! ' + page_help)

			# Validate it's an url
			if url_regex.match(p[0]) == None:
				parser.error('Malformed url "' + p[0] + '" given! ' + page_help)

			# Validate the url is unique
			if any([True for i in argConf['pages'] if i['url'] == p[0]]):
				parser.error('Duplicate page arguments for "' + p[0] + '"! Please make sure the urls are unique. Maybe add an unique #hash to the end of url if you really want to circumvent this?')

			# Sadly it's hard to validate CSS selector (at least without additional libraries) :/
			# But we can check if the regex is valid
			if len(p) == 3:
				try:
					re.compile(p[2])
				except re.error:
					# Invalid regex!
					parser.error('Malformed regex for "' + p[0] + '"! ' + page_help)

			# Now everything should be fine
			if _debug: _log('debug', 'Adding a new page: {}'.format(p[0]), argConf)

			argConf['pages'].append({
				'url': p[0],
				'selector': p[1]
			})

			# Save regex only if given
			if (len(p) == 3):
				argConf['pages'][-1]['regex'] = p[2]

	if args.browser:
		if _debug: _log('debug', 'Setting browser used by Selenium webdriver to {}'.format(args.browser), argConf)
		setParams.append('browser')
		argConf['browser'] = args.browser
	else:
		argConf['browser'] = _default_browser

	if args.use_xvfb:
		if _debug: _log('debug', 'Setting the Xvfb usage flag to true', argConf)
		setParams.append('use_xvfb')

	argConf['use_xvfb'] = args.use_xvfb

	if args.event_list:
		setParams.append('event_list')

		argConf['event_list'] = []
		for e in args.event_list:
			if e in _valid_notification_events:
				if _debug: _log('debug', 'Adding the {} event to be run in notification stage'.format(e), argConf)

				argConf['event_list'].append(e)
			else:
				parser.error(e + ' not found in valid notification events. The next ones are supported: ' + ', '.join(_valid_notification_events))
	else:
		# Just do them all as a default
		argConf['event_list'] = _valid_notification_events

	if args.log_path:
		if _debug: _log('debug', 'Setting log path to {}'.format(args.log_path), argConf)

		setParams.append('log_path')
		argConf['log_path'] = args.log_path
	else:
		argConf['log_path'] = os.path.expanduser('~') + os.path.sep + '.change-poller.log'

	if args.save_config:
		if _debug: _log('debug', 'Making a note to save the config after processing', argConf)
		whatToDo.append('save-config')

	if args.print_config:
		if _debug: _log('debug', 'Making a note to print the config after processing', argConf)
		whatToDo.append('print-config')

	if args.config_file:
		if _debug: _log('debug', 'Setting config file path to {}'.format(args.config_file), argConf)

		setParams.append('config_file')
		argConf['data_dir'] = args.config_file

	if args.data_dir:
		if _debug: _log('debug', 'Setting data path to {}'.format(args.data_dir), argConf)

		setParams.append('data_dir')
		argConf['data_dir'] = args.data_dir

	if len(whatToDo) == 0 and not args.no_run:
		if _debug: _log('debug', 'No other notes made about what to do, so making a note to run the main program', argConf)
		whatToDo.append('run')

	if 'run' in whatToDo:
		# Do also check for browser existence, but only if it's really required
		if not hasattr(webdriver, argConf['browser']):
			parser.error(argConf['browser'] + ' is not supported by Selenium webdriver.')
		else:
			if _debug: _log('debug', 'Looks like Selenium webdriver may support {} (at this point we cannot still be sure if it really works)'.format(argConf['browser']), argConf)

	if _debug: _log('debug', 'Ended parsing command line arguments', argConf)

	return argConf, whatToDo, setParams

def getConfig(conf, setParams):
	"""Returns the configuration"""

	if _debug: _log('debug', 'Started parsing the configuration')

	addedPageUrls = []
	home = os.path.expanduser('~')

	if _debug: _log('debug', 'Home path: {}'.format(home))

	if 'config_file' in conf:
		if _debug: _log('debug', 'Configuration file path already set')
	else:
		# Guess the config file
		config_dir = os.environ.get('XDG_CONFIG_HOME')

		if config_dir == None:
			# If no env var found, get the default in most systems
			config_dir = os.path.sep.join([home, '.config'])

			if _debug: _log('debug', 'This system doesn\'t seem to obey XDG directory standard, falling back to just setting configuration at ~/.config')
		else:
			if _debug: _log('debug', 'Configuration path got from environment variable XDG_CONFIG_HOME')

		conf['config_file'] = os.path.sep.join([config_dir, 'change-poller', 'config'])

	if _debug: _log('debug', 'Config file path is now {}'.format(conf['config_file']))

	config_dir = os.path.dirname(conf['config_file'])

	# Make the config dir if not exists already
	if not os.path.isdir(config_dir):
		if _debug: _log('debug', 'Configuration path does not exist yet, creating it')
		os.makedirs(config_dir, mode=0o700)

	try:
		with open(conf['config_file']) as f:
			fileConf = json.load(f)

			if _debug: _log('debug', 'Successfully read configuration file, starting to merge cli and file configurations')

			# Merge configs from commandline and savefile
			for k in fileConf:
				if k not in conf or k not in setParams:
					if _debug: _log('debug', 'Setting "{}" to "{}"'.format(k, fileConf[k]))
					conf[k] = fileConf[k]

				elif type(fileConf[k]) == list:
					# Lists must be merged with a bit of iteration work
					for i in conf[k]:
						# Do it this way to preserve order (oldest first)
						if i not in fileConf[k]:
							if _debug: _log('debug', 'Adding "{}" to "{}" list'.format(i, k))

							if k == 'pages':
								# Also add it to addedPageUrls
								addedPageUrls.append(i['url'])

							fileConf[k].append(i)

					# Then mirror the configs
					conf[k] = fileConf[k]
		
		# No config save needed
		save_default_config = False

	except (OSError, JSONDecodeError) as err:
		_log('warning', 'Failed to load config file, is this first time running? Using defaults and trying to save afterwards. {}: {}'.format(type(err).__name__, str(err)))
		if _debug: _log('debug', 'Marking the default config to be saved (different thing from --save-config)')

		# Start with default config, so also save it
		# Also make a flag to store it
		save_default_config = True

	# Get data path if not set already
	if 'data_dir' in conf:
		if _debug: _log('debug', 'Data path already set')
	else:
		data_dir = os.environ.get('XDG_DATA_HOME')

		if data_dir == None:
			if _debug: _log('debug', 'This system doesn\'t seem to obey XDG directory standard, falling back to just setting data path at ~/.local/share')
			data_dir = os.path.sep.join([home, '.local', 'share'])
		else:
			if _debug: _log('debug', 'Data path got from environment variable XDG_DATA_HOME')

		conf['data_dir'] = data_dir + os.path.sep + 'change-poller'

	if _debug: _log('debug', 'Data path is now {}'.format(conf['data_dir']))

	# Make the config dir if not exists already
	if not os.path.isdir(conf['data_dir']):
		if _debug: _log('debug', 'Data path does not exist yet, creating it')
		os.makedirs(conf['data_dir'], mode=0o700)

	# Save config if needed
	if save_default_config:
		if _debug: _log('debug', 'Saving the default configuration as ẃe couldn\'t write to it before')

		with open(conf['config_file'], 'w') as f:
			f.write(formatJSON(conf))

	if _debug: _log('debug', 'Ended parsing the configuration')

	return conf, addedPageUrls

def run(conf, addedPageUrls):
	"""Runs modification checks for sites given in conf and saves changes"""

	if _debug: _log('debug', 'Started polling procedure');

	allChanges = []
	tryAgain = {}

	domain_regex = re.compile('://(.[^/]+)')

	# Run only if pages are specified
	if len(conf['pages']) == 0:
		_log('warning', 'No pages specified!')
	else:
		browser = getBrowser(conf)

		for page in conf['pages']:
			if _debug: _log('debug', 'Page poll starts for {}'.format(page['url']))

			# Get the current timestamp
			timestamp = int(time.time())

			# Read the previous data first
			data_file = conf['data_dir'] + os.path.sep + getSafeFilename(page['url'], conf)

			if _debug: _log('debug', 'Data file path: {}'.format(data_file))

			try:
				with open(data_file) as f:
					file_data = json.load(f)

					if _debug: _log('debug', 'Data file loaded successfully')

			except (OSError, JSONDecodeError) as err:
				if page['url'] in addedPageUrls:
					# This is usual
					if _debug: _log('debug', 'Data file does not exist yet when adding page first time, using defaults')
				else:
					_log('warning', 'Data file ({}) load failed, please fix your configuration! Using defaults. {}: {}'.format(data_file, err.__class__.__name__, err.__str__()))

				# No previous data file found, use defaults
				file_data = {
					'last_content_change': 0,
					'last_check': 0,
					'title': '',
					'url': page['url'],
					'domain': domain_regex.search(page['url']).group(1),
					'content': [],
					'error': False
				}

			# React to url change
			if 'new_url' in file_data:
				_log('debug' 'Updating url to {}'.format(file_data['new_url']))

				file_data['url'] = file_data['new_url']
				del(file_data['new_url'])

				# Update also domain
				file_data['domain'] = domain_regex.search(page['url']).group(1)

				# Make a new filename and save the old one for deletion after save
				old_data_file = data_file
				data_file = conf['data_dir'] + os.path.sep + getSafeFilename(page['url'], conf)

			# Then let's get to load the page
			try:
				if _debug: _log('debug', 'Loading the page...')

				browser.get(page['url'])

				if _debug: _log('debug', 'Gotcha, finding element by CSS selector: {}'.format(page['selector']))

				# Get content by CSS selector
				content = browser.find_element_by_css_selector(page['selector']).text

				# If regex is given, match content more precisely (in a tuple)
				if 'regex' in page:
					if _debug: _log('debug', 'Found, doing final finding with regex: {}'.format(page['regex']))

					content = re.search(page['regex'], content)
					
					if content == None:
						raise LookupError()
					else:
						content = content.groups()
				else:
					if content == '':
						# That's how we react to big changes at pages, because they may be 404
						raise LookupError()

					if _debug: _log('debug', 'Found, no regex given for this url so the CSS selector marks the final content')
					
					# Change content to match the regex return format
					content = (content,)

			except (WebDriverException, NoSuchElementException, LookupError) as err:
				# Thing not found
				err_type = type(err)

				if err_type == WebDriverException:
					description = 'server cannot be contacted'
				elif err_type == NoSuchElementException:
					description = 'element cannot be found'
				elif err_type == LookupError:
					description = 'couldn\'t find what we were looking for'
				else:
					description = '???'
				
				if not file_data['error']:
					_log('warning', 'Query erroring out! {}: {}, {}'.format(err_type.__name__, str(err), description))
					file_data['error'] = True
				else:
					_log('info', 'Query is still erroring out. {}: {}, {}'.format(err_type.__name__, str(err), description))

				file_data['error_description'] = description

			else:
				# Got data successfully, let's diff it
				if _debug: _log('debug', 'Got page data successfully')

				# Firstly, get rid of error if we previously had one
				if file_data['error']:
					_log('info', 'Server is now responding, previously it was not')
					file_data['error'] = False
					del(file_data['error_description'])
				
				# Secondly, check if we have any changes in content
				old = set(file_data['content'])
				new = set(content)

				if old == new:
					if _debug: _log('debug', 'No changes in content')
				else:
					if _debug: _log('debug', 'Changes in content detected, let\'s update page data')
					file_data['content'] = content
					file_data['title'] = browser.title
					file_data['last_content_change'] = timestamp

					# Get what precisely has changed to notify user
					allChanges.append({
						'added': [i for i in new if i not in old],
						'removed': [i for i in old if i not in new],
						'title': browser.title,
						'url': file_data['url'],
						'domain': file_data['domain']
					})
			
			# Did we find the data or not, update check timestamp
			file_data['last_check'] = timestamp

			try:
				# Update data file
				with open(data_file, 'w') as f:
					# Use pretty print with indent of 2 spaces
					f.write(formatJSON(file_data))

					if _debug: _log('debug', 'Data file updated successfully')
				
				# If we had an url update, remove the old file now
				# (raises an exception if there was no old file)
				os.remove(old_data_file)

				if _debug: _log('debug', 'Also removed old data file as url was changed')
			except NameError:
				# No url update
				pass
			except OSError as err:
				# Couldn't update the needed data file! Let's query save for later time, there might have been file access tries
				_log('info', "Couldn't update data file for {}! Trying again later. {}: {}".format(file_data['domain'], type(err).__name__, str(err)), file=sys.stderr)
				tryAgain[data_file] = formatJSON(change_data)

	# Return changes after loop (if we even were there)
	return allChanges, tryAgain

def setupLogger(conf):
	"""Configure and return logger instance"""

	if _debug: _log('debug', 'Setting up logger')

	logger = logging.getLogger(__name__)

	# The logger may have been configured already, no need to add any (more) handlers then
	if logger.hasHandlers():
		if _debug: _log('debug', 'Logger already configured')
	else:
		if _debug: _log('debug', 'Configuring logger for first time')

		if conf['verbosity'] not in _verbosityToLevel:
			# Invalid level
			sys.exit('Invalid log verbosity level, try fewer -v')
		else:
			severity = _verbosityToLevel[conf['verbosity']]

		if _debug: _log('debug', 'Log severity set to {}'.format(logging._levelToName[_verbosityToLevel[conf['verbosity']]]))

		# Log formats
		cfmt = '[{levelname}] {message}'
		ffmt = '{asctime} ' + cfmt

		if _debug: _log('debug', 'Console log format: {}'.format(cfmt))
		if _debug: _log('debug', 'File log format: {}'.format(ffmt))

		# Add handlers
		# TODO: should the hard-coded rotation params be allowed to change in config?
		ch = logging.StreamHandler()
		fh = logging.handlers.RotatingFileHandler(conf['log_path'], maxBytes=32768, backupCount=5)

		ch.setLevel(severity)
		fh.setLevel(logging.INFO)

		ch.setFormatter(logging.Formatter(cfmt, style='{'))
		fh.setFormatter(logging.Formatter(ffmt, style='{'))

		logger.addHandler(ch)
		logger.addHandler(fh)

		if _debug: _log('debug', 'Logger configured, two handlers added (console and rotating file)')

	if _debug: _log('debug', 'Logger set up')

def getBrowser(conf):
	"""Get the browser instance for retriving pages"""

	if _debug: _log('debug', 'Getting the browser instance')

	if conf['use_xvfb']:
		if _debug: _log('debug', 'Using Xvfb')

		# Make the browser headless by starting a Xvfb display server (if not running already)
		if os.path.isfile('/tmp/.X99-lock'):
			if _debug: _log('debug', 'Looks like the Xvfb display server is already running as the lockfile exists')
		else:
			if _debug: _log('debug', 'Looks like the Xvfb display server is not running, starting it daemonized')
			subprocess.Popen(['Xvfb', ':99', '-ac'])
	
		if _debug: _log('debug', 'Setting the DISPLAY environment variable to :99, the Xvfb display')

		os.environ['DISPLAY'] = ':99'

	else:
		if _debug: _log('debug', 'Not using Xvfb')

	if _debug: _log('debug', 'Finally calling the Selenium webdriver browser, using {} for it'.format(conf['browser']))

	# Get the browser from the webdriver object
	browser = getattr(webdriver, conf['browser'])()

	if _debug: _log('debug', 'Finalized initializing the browser instance')

	return browser

def getSafeFilename(string, conf):
	"""Remove the protocol from url and change suspicious chars to underscores"""

	if _debug: _log('debug', 'Getting a safe filename for "{}"'.format(string))

	remove_protocol = re.compile('://(.*)$')

	filename = re.sub('[^\w\-_\. ]', '_', remove_protocol.search(string).group(1)).strip('_')

	if _debug: _log('debug', 'Ended up with "{}"'.format(filename))

	return filename

def formatJSON(data, _seenData={}):
	"""Returns pretty-printed JSON (caches already JSON'd data)"""

	try:
		key = hash(data)

		# We can hash it, so we can cache it
		cacheable = True
	except TypeError:
		cacheable = False

	if cacheable and key in _seenData:
		formatted = _seenData[key]
	else:
		formatted = json.dumps(data, indent=2, sort_keys=True)
		
		if cacheable:
			_seenData[key] = formatted
	
	return formatted + '\n'

def _log(levelName, msg, *args, **kwargs):
	"""Instantiate temp logger mimicing logging.StreamHandler, writing to stderr if verbosity is enough"""

	global conf

	levelName = levelName.upper()

	# We have a very early stage of program here if conf is not defined yet
	if not 'verbosity' in conf:
		conf['verbosity'] = 0

	# This makes sure we don't use invalid log levels even in the fallback logger
	if levelName not in logging._nameToLevel:
		raise KeyError('Invalid log level: {}'.format(level))

	# Also make sure the log level is supported
	if levelName not in [logging._levelToName[l] for l in _verbosityToLevel.values()]:
		raise KeyError('Log level not supported: {}'.format(levelName))

	# Use the already init'd logger if we already have one
	logger = logging.getLogger(__name__)

	if logger.hasHandlers():
		# Yup we haz one
		logger._log(logging._nameToLevel[levelName], msg, args, **kwargs)
	else:
		# Fallback logger
		if logging._nameToLevel[levelName] >= _verbosityToLevel[conf['verbosity']]:
			print('[{0}] {1}'.format(levelName, msg), file=sys.stderr)

# Get to mainloop
if __name__ == '__main__':
	main()
