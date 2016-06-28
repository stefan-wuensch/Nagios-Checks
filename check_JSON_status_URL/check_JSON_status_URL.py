#!/usr/bin/env python2

# =================================================================================================
# check_JSON_status_URL.py
# 
# version 2016-06-28
# 
# By Stefan Wuensch, June 2016
# https://github.com/stefan-wuensch/Nagios-Checks
# 
# 
# This script is a Nagios plugin which will query a web service for a JSON blob
# of health indicators. This will iterate over all the key/value pairs in the JSON, 
# and compare each value to the input arguments for Warning and OK.
# If any Critical state attributes are found, this script will exit as Nagios CRITICAL.
# If no Critical states are found but any Warning states are found, this will exit with Nagios WARNING.
# If no Critical and no Warning are found, this will exit with Nagios OK.
# 
# A state is determined to be Critical if it does _not_ match the string OKSTRING and 
# also does _not_ match the string WARNSTRING (if given).
# 
# 
# Usage: check_JSON_status_URL.py [-h] [-v] -u URL -p OKSTRING [-w WARNSTRING]
# 
# Nagios check of a JSON app health object. Exit status 0 == OK, 1 == Warning, 
# 2 == Critical, 3 == Unknown.
# 
# optional arguments:
#   -h, --help            show this help message and exit
#   -v, --verbose         increase output verbosity
#   -u URL, --url URL     URL to be checked - required
#   -p OKSTRING, --okString OKSTRING
#                         text string which indicates OK - required
#   -w WARNSTRING, --warnString WARNSTRING
#                         text string which indicates Warning
# 
# 
# Exit status: 0, 1, 2, 3 as standard Nagios status codes. See EXIT_STATUS_DICT for mapping.
# 
# Note: If no WARNSTRING arg is given, the only non-OK state returned will be CRITICAL.
# Program errors will return Nagios UNKNOWN.
# 
# 
# 
# 
# =================================================================================================
# 
# Example usage:
# 
# check_JSON_status_URL.py --url=https://myserver.mydomain.com/apphealth.cgi --warnString=WARN --okString=PASS
# 
# Sample JSON for this example:
# {
#     "Name Look up service": "WARN", 
#     "File Transfer": "PASS", 
#     "Database Connection": "FAIL", 
#     "Security Service": "PASS"
# } 
# 
# Output for this example:
# Status of all attributes: OK: Security Service, File Transfer / WARNING: Name Look up service / CRITICAL: Database Connection / UNKNOWN: 0
# 
# This example would have exited 2, for Nagios CRITICAL.
# 
# 
# =================================================================================================
# 
# The MIT License (MIT)
# 
# Copyright (c) 2016 Stefan Wuensch
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# 
# =================================================================================================


import argparse, time, sys, httplib, json, socket
from urlparse import urlparse

###################################################################################################
# Dictionary for exit status codes
EXIT_STATUS_DICT = {
	"OK": 0,
	"WARNING": 1,
	"CRITICAL": 2,
	"UNKNOWN": 3
}


###################################################################################################
# Dictionary for looking up the status string from the value
EXIT_STATUS_DICT_REVERSE = {
	0: "OK",
	1: "WARNING",
	2: "CRITICAL",
	3: "UNKNOWN"
}


###################################################################################################
# Map a protocol / scheme default to the standard ports
def portmapping( scheme ):
	return {
		'http':  80,
		'https': 443
	}.get( scheme, 80 )	# Return 80 if there's no scheme given



###################################################################################################
def exit_with_message( message = "Something not defined", exitCode = EXIT_STATUS_DICT[ 'UNKNOWN' ] ):

# Output a message and exit
# 
# Usage: exit_with_message( string, int )
# 	'string' is printed to STDOUT
# 	'int' is used for the exit status
# 
# Returns: nothing - will always exit
# 
# Note the default values.

	prefix = ""
	if exitCode == EXIT_STATUS_DICT[ 'UNKNOWN' ]: prefix = "Error: "		# Add additional info at beginning

	print "{0}{1}".format( prefix, message )

	sys.exit( exitCode )



###################################################################################################



# Set up our inputs from the command line. This also handles the "-h" and error usage output for free!
parser = argparse.ArgumentParser( description = "Nagios check of a JSON app health object. Exit status 0 == OK, 1 == Warning, 2 == Critical, 3 == Unknown.",
				  epilog = "https://github.com/stefan-wuensch/Nagios-Checks" )
parser.add_argument( "-v", "--verbose",  help = "increase output verbosity", action = "store_true" )
parser.add_argument( "-u", "--url", help = "URL to be checked - required", required = True )
parser.add_argument( "-p", "--okString", help = "text string which indicates OK - required",  required = True )
parser.add_argument( "-w", "--warnString", help = "text string which indicates Warning" )
args = parser.parse_args()

if args.verbose:
	print "Time now", int( time.time() )
	print "url", args.url
	print "okString", args.okString
	print "warnString", args.warnString



# If the URL given doesn't have a proper method / scheme, add one. 
# Otherwise the 'urlparse' gets all weird. Default to HTTP.
if "http" in args.url:
	url = args.url
else:
	url = "http://" + args.url
if args.verbose: print "url " + url


urlObject = urlparse( url )
scheme = urlObject.scheme
if args.verbose: print "scheme " + scheme

# If there's a port number given in the URL (like server:8080) then use that.
# Otherwise look up the port in our dict.
if urlObject.port:
	port = urlObject.port
else:
	port = portmapping( scheme )
if args.verbose: print "port: ", port, " hostname: ", urlObject.hostname

# exit_with_message( "Debugging - bail out early.", EXIT_STATUS_DICT[ 'UNKNOWN' ] )	# For testing


# Now do the connection setup
# First look up the IP address from the hostname
try:
	ip, port = socket.getaddrinfo( urlObject.hostname, port )[ 0 ][ -1 ]
except Exception:
	exit_with_message( "Problem performing DNS name lookup on " + urlObject.hostname, EXIT_STATUS_DICT[ 'UNKNOWN' ] )
if args.verbose: print "ip: ", ip
if scheme == "http":
	connection = httplib.HTTPConnection( ip, port, timeout=10 )
else:
	connection = httplib.HTTPSConnection( urlObject.hostname, port, timeout=10 )
# Note: in the above connection setup, apparently the 'timeout' behavior is not optimal if you
# use the hostname - because the name resolution can make the timeout wonky.
# Instead, it's preferred to use the IP address in the connection setup (as the first arg)
# but the SSL negotiation appears to fail without using the hostname - which makes sense.


try:
	connection.connect()
except Exception:
	exit_with_message( "Problem setting up the " + scheme + " connection to \"" + urlObject.hostname + ":" + str( port ) + "\" !!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )


# If we needed to supply some parameters in JSON form, this is an example of how that would work:
# connection.request( 'POST', '/some-form.cgi', json.dumps( params ), { 'Content-Type': 'application/json' } )

connection.request( 'GET', urlObject.path )
try:
	connectionResponse = connection.getresponse()
except Exception:
	exit_with_message( "Problem performing getresponse() on connection", EXIT_STATUS_DICT[ 'UNKNOWN' ] )

if connectionResponse.status != 200:
	exit_with_message( "call returned HTTP code {0} {1}".format( connectionResponse.status, connectionResponse.reason ), EXIT_STATUS_DICT[ 'UNKNOWN' ] )

try:
	appHealthJSON = json.loads( connectionResponse.read() )
except Exception:
	exit_with_message( "Could not get objects from the transaction!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )

connection.close()
if args.verbose: print "Connection closed"
if args.verbose: print "\nJSON:", json.dumps( appHealthJSON, sort_keys = True, indent = 4 ), "\n"



summaryMessage = ""		# Init to null because we are going to be appending text
highestError = 0		# Track the worst status for the final return code (0 is no error, higher is worse)
statusDict = {}			# Init a dictionary to track all the instances' status for later use

for severity in ( EXIT_STATUS_DICT[ 'OK' ], EXIT_STATUS_DICT[ 'WARNING' ], EXIT_STATUS_DICT[ 'CRITICAL' ], EXIT_STATUS_DICT[ 'UNKNOWN' ] ):
	statusDict[ severity ] = []		# Initialize the structure - each severity level will hold names of instances

# Now we loop through everything we got back and populate the statusDict
for healthCheck in appHealthJSON:
	if args.verbose: print healthCheck, " is ", appHealthJSON[ healthCheck ]

	if appHealthJSON[ healthCheck ] == args.okString:
		statusDict[ healthCheck ] = EXIT_STATUS_DICT[ 'OK' ]
		statusDict[ EXIT_STATUS_DICT[ 'OK' ] ].append( healthCheck )

	elif appHealthJSON[ healthCheck ] == args.warnString:
		statusDict[ healthCheck ] = EXIT_STATUS_DICT[ 'WARNING' ]
		statusDict[ EXIT_STATUS_DICT[ 'WARNING' ] ].append( healthCheck )
		if highestError == EXIT_STATUS_DICT[ 'OK' ]:	# Only track this Warning if there's not already been something worse - like Critical
			highestError = EXIT_STATUS_DICT[ 'WARNING' ]

	else:
		statusDict[ healthCheck ] = EXIT_STATUS_DICT[ 'CRITICAL' ]
		statusDict[ EXIT_STATUS_DICT[ 'CRITICAL' ] ].append( healthCheck )
		highestError = EXIT_STATUS_DICT[ 'CRITICAL' ]

# Note: We are not handling "UNKNOWN" but that's a future enhancement. For now we assume that only
# the status attributes found in the JSON are the ones to check. To-do: Add a JSON input parameter list
# which would contain all the expected attributes and anything not found would be 'UNKNOWN'.

if args.verbose: print "\n", statusDict, "\n"


# Now we build up the 'summaryMessage' by iterating across all the different statuses. (or stati? My Latin sucks.)
# For each level of severity we'll build a comma-separated list of attributes with that status.
# If a severity level doesn't have any attributes in that state, we'll output '0' (zero).
# Each of the severity levels will be slash-separated.
# Example:
# OK: Database Connection, Name Lookup / WARNING: 0 / CRITICAL: Auth Service / UNKNOWN: 0
for severity in ( EXIT_STATUS_DICT[ 'OK' ], EXIT_STATUS_DICT[ 'WARNING' ], EXIT_STATUS_DICT[ 'CRITICAL' ], EXIT_STATUS_DICT[ 'UNKNOWN' ] ):

	wasPreviousCountZero = True			# Track what the previous number was, so we know when to use a slash vs. comma
	if len( statusDict[ severity ] ) > 0:		# Is there one or more attributes(s) with this severity level?
		isFirstAttrName = True
		for name in statusDict[ severity ]:	# If there are attributes this time, add each one to the summary message by iterating over the list
			if len( summaryMessage ) > 0:	# Only add punctuation if we're not starting off for the very first time
				if wasPreviousCountZero == True:
					summaryMessage += " / "
				else:
					summaryMessage += ", "
			if isFirstAttrName: 		# Only add the name of the severity level if it's the first attribute with this level
				summaryMessage += EXIT_STATUS_DICT_REVERSE[ severity ] + ": "
				isFirstAttrName = False
			summaryMessage += name
			wasPreviousCountZero = False

	else:						# If there wasn't any attribute in this severity, show zero
		if len( summaryMessage ) > 0: 		# Don't add a comma if we're just starting off for the first round
			summaryMessage += " / "
		summaryMessage += EXIT_STATUS_DICT_REVERSE[ severity ] + ": 0"
		wasPreviousCountZero = True

summaryMessage = "Status of all attributes: " + summaryMessage
exit_with_message( summaryMessage, highestError )



# Bail out fail-safe (but in this case "safe" is to notify us of the problem!)
exit_with_message( "Something went wrong - this should not happen.", EXIT_STATUS_DICT[ 'UNKNOWN' ] )

