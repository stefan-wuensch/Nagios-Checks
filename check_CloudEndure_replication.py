#!/usr/bin/env python

# =================================================================================================
# check_CloudEndure_replication.py
# 
# Version 2016-02-02
# 
# By Stefan Wuensch, Jan. 2016
# 
# This script is a Nagios plugin which will query the CloudEndure API for the 
# replication / sync status of a host. (CloudEndure is a server-replication
# provider, allowing migration and/or DR.) https://www.cloudendure.com/
# Disclaimer: I have no affiliation with CloudEndure; my employer is a customer of CloudEndure.
# 
# 
# usage: check_CloudEndure_replication.py [-h] [-v] -u USERNAME -p PASSWORD
#                                         [-n HOSTNAME]
# 
# Nagios check of the sync status of CloudEndure replication. Exit status 0 ==
# OK, 1 == Warning, 2 == Critical, 3 == Unknown.
# 
# optional arguments:
#   -h, --help            show this help message and exit
#   -v, --verbose         increase output verbosity
#   -u USERNAME, --username USERNAME
#                         user name for the CloudEndure account - required
#   -p PASSWORD, --password PASSWORD
#                         password for the CloudEndure account - required
#   -n HOSTNAME, --hostname HOSTNAME
#                         hostname of instance to check, or "all" (defaults to
#                         "all" if not specified)
# 
# 
# 
# Required inputs: CloudEndure username and password. 
# Optional inputs: A host name (expected to be FQDN, but not manditory) to check
# 
# Outputs: One line of text containing the explanation of the replication status. Note that 
# 	this will be one line no matter how many hosts are found (in the case of "all")
# 
# Exit status: 0, 1, 2, 3 as standard Nagios status codes. See EXIT_STATUS_DICT for mapping.
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
# 
# To Do:
# - turn the Warning and Critical constants into optional arguments
# - make the Location an optional argument, instead of hard-coded "originalLocation".
# 	(The two Locations we might want to watch are "originalLocation" and "mirrorLocation".)
# 
# =================================================================================================



import httplib, json, re, sys, argparse, time, calendar
from datetime import datetime

# Dictionary for exit status codes
EXIT_STATUS_DICT = {
	"OK": 0,
	"WARNING": 1,
	"CRITICAL": 2,
	"UNKNOWN": 3
}

# Dictionary for looking up the status string from the value
EXIT_STATUS_DICT_REVERSE = {
	0: "OK",
	1: "WARNING",
	2: "CRITICAL",
	3: "UNKNOWN"
}

# To do: make these optional args
WARNING_SYNC_DELAY  = 1800	# Number of seconds over which it's a Warning - we will forgive any sync delay up to 30 min.
CRITICAL_SYNC_DELAY = 3600	# Number of seconds (equals 1 hour) beyond which it's Critical

CLOUDENDURE_API_HOST = "dashboard.cloudendure.com"



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

	# Try and do a proper logout (because they want that) but NOT if we got here because of 
	# an 'Unknown' state! If we tried to do a 'logout' call on 'Unknown' we'd be risking an 
	# endless loop of send_request() fail bringing us back here again. Ugly.
	# (Nagios would eventually time out this script, but let's not even risk it.)
	if exitCode != EXIT_STATUS_DICT[ 'UNKNOWN' ]:
		try:
			response, connection = send_request( 'logout', {}, { 'Cookie': session_cookie } )	# Here we don't care what is the response.
			connection.close()
			if args.verbose: print "Connection closed"
		except Exception:
			sys.exit( exitCode )	# If we get an error trying to log out, just bail.

	sys.exit( exitCode )



###################################################################################################
def last_sync_time_test( instance ):

# This function is the heart of the health check logic.
# 
# Usage: last_sync_time_test( dictionary )
# 	'dictionary' is from JSON, containing details of one specific host
# 
# Returns: tuple of ( string, int ) where 'string' is a status message and 'int' is a status code

	if args.verbose: print "replicationState:", instance[ 'replicationState' ]
	if args.verbose: print "lastConsistencyTime ISO-8601:", instance[ 'lastConsistencyTime' ]

	# First thing to check is the text string of the state
	if instance[ 'replicationState' ] != "Replicated":
		message = instance[ 'name' ] + " (" + instance[ 'id' ] + ") in account \"" + args.username + "\" is \"" + instance[ 'replicationState' ] + "\" not \"Replicated\" !!"
		return ( message, EXIT_STATUS_DICT[ 'CRITICAL' ] )

	# Dummy check the timestamp, because if the host isn't replicating the timestamp will be null
	# This shouldn't be a real indication of replication failure, because the 'replicationState' being
	# checked above should catch it.
	if instance[ 'lastConsistencyTime' ] is None:
		message = instance[ 'name' ] + " lastConsistencyTime is empty! There should be something there if it is replicating properly!"
		return ( message, EXIT_STATUS_DICT[ 'UNKNOWN' ] )

	# Convert ISO-8601 format to UNIX epoch (integer seconds since Jan 1 1970) since that makes the math easy :-)
	# We will try several different ISO-8601 formats before giving up.
	# https://en.wikipedia.org/wiki/ISO_8601
	# See format codes at https://docs.python.org/2/library/datetime.html
	originalTimeValue = instance[ 'lastConsistencyTime' ]		# Save it for later. We will be trying to replace it with the integer value.
	for format in ( '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f+00:00', '%Y-%m-%dT%H:%M:%S+00:00', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y%m%dT%H%M%SZ' ):
		if args.verbose: print "Trying ISO-8601 format ", format
		try:
			instance[ 'lastConsistencyTime' ] = calendar.timegm( datetime.strptime( instance[ 'lastConsistencyTime' ], format ).timetuple() )
			if isinstance( instance[ 'lastConsistencyTime' ], ( int, long ) ):
				break		# If we managed to get a numeric value, we're done.
		except ValueError:
			continue		# Try again with the next format if this one didn't work.

	# If we still have the same time value & format as before, we failed to find a matching ISO-8601 pattern.
	if instance[ 'lastConsistencyTime' ] == originalTimeValue:
		message = instance[ 'name' ] + " lastConsistencyTime " + str( instance[ 'lastConsistencyTime' ] ) + " doesn't appear to be a date / time in a recognized ISO-8601 format!"
		return ( message, EXIT_STATUS_DICT[ 'UNKNOWN' ] )

	# Now for the ultimate in being careful, make sure it really is an integer!
	if not isinstance( instance[ 'lastConsistencyTime' ], ( int, long ) ):
		message = instance[ 'name' ] + " lastConsistencyTime is not an integer!"
		return ( message, EXIT_STATUS_DICT[ 'UNKNOWN' ] )
	if args.verbose: print "lastConsistencyTime UNIX epoch seconds:", instance[ 'lastConsistencyTime' ]


	# Make a string that's human-readable for printing in output
	lastSyncTimeStr = time.strftime( '%Y-%m-%d %H:%M:%S', time.localtime( instance[ 'lastConsistencyTime' ] ) )

	# Finally calculate how far back was the last sync
	if args.verbose: print "Time now", int( time.time() )
	timeDelta = int( time.time() ) - instance[ 'lastConsistencyTime' ]
	if args.verbose: print "lastConsistencyTime seconds ago:", timeDelta

	if ( timeDelta > CRITICAL_SYNC_DELAY ):		# This is the first test, because the longest delay value is Critical
		message = instance[ 'name' ] + " has not had an update since " + lastSyncTimeStr + ", " + str( seconds_to_time_text( timeDelta ) )
		return ( message, EXIT_STATUS_DICT[ 'CRITICAL' ] )

	if ( timeDelta > WARNING_SYNC_DELAY ):
		message = instance[ 'name' ] + " has not had an update since " + lastSyncTimeStr + ", " + str( seconds_to_time_text( timeDelta ) )
		return ( message, EXIT_STATUS_DICT[ 'WARNING' ] )

	if ( timeDelta <= WARNING_SYNC_DELAY ):		# If the delay since last sync is less than our tolerance for Warning, it's good!!
		message = instance[ 'name' ] + " last update " + lastSyncTimeStr + ", " + str( seconds_to_time_text( timeDelta ) )
		return ( message, EXIT_STATUS_DICT[ 'OK' ] )

	message = "Could not analyze the sync state for " + instance[ 'name' ]
	return ( message, EXIT_STATUS_DICT[ 'UNKNOWN' ] )		# If we get to this point something went wrong!



###################################################################################################
def send_request( function, params, headers ):

# This function makes the HTTPS call out to the CloudEndure API and makes sure we get a '200' HTTP status
# before returning the JSON
# 
# Usage: send_request( string, dict1, dict2 )
# 	'string' is the API function call
# 	'dict1' is a dictionary of parameters for the API call
# 	'dict2' is a dictionary of HTTP headers - currently only used for the session auth cookie
# 
# Returns: tuple of HTTPSConnection.getresponse(), and the connection object itself (to allow closing outside this function)

	connection = httplib.HTTPSConnection( CLOUDENDURE_API_HOST, 443 )
	try:
		connection.connect()
	except HTTPException:
		exit_with_message( "Problem setting up the HTTPS connection to \"" + CLOUDENDURE_API_HOST + "\" !!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )
	headers.update( { 'Content-Type': 'application/json' } )

	# For debugging it's helpful to include the 'params' in verbose output, but
	# that exposes the password when calling the 'login' API function - so it's not
	# a great idea. Instead just show the function name and headers. That's safe.
	## if args.verbose: print "\nCalling {0} with {1} and {2}".format( function, params, headers )
	if args.verbose: print "\nCalling {0} with {1}".format( function, headers )

	connection.request( 'POST', '/latest/' + function, json.dumps( params ), headers )
	connectionResponse = connection.getresponse()

	if connectionResponse.status != 200:
		exit_with_message( "{0} call returned HTTP code {1} {2}".format( function, connectionResponse.status, connectionResponse.reason ), EXIT_STATUS_DICT[ 'UNKNOWN' ] )
	return connectionResponse, connection



###################################################################################################
def seconds_to_time_text( inputSeconds ):

# This function converts a number of seconds into a human-readable string of 
# seconds / minutes / hours / days.
# 
# Usage: seconds_to_time_text( seconds )
# 	'seconds' is an int, or string representation of an int
# 
# Returns: string of the time in words, such as "4 hours, 1 minute, 22 seconds"
# 	or "1 day, 18 minutes"
# 	or "12 days, 1 hour, 59 seconds"
# 
# Note: Due to variations in clock synchronization, it's possible for the CloudEndure
# last sync time to come back as a timestamp in the future relative to where this
# script is running. We will handle that gracefully.

	try:
		inputSeconds = int( inputSeconds )	# In case it's a string
	except:
		return "{} does not appear to be a whole number of seconds!".format( inputSeconds )

	if inputSeconds == 0: return "0 seconds ago (just now)"
	if inputSeconds < 0:
		trailingText = " in the future!"
	else:
		trailingText = " ago"
	inputSeconds = abs( inputSeconds )	# In case it's negative, meaning in the future

	results = []
	periods = (
		( "days",    86400 ),
		( "hours",   3600 ),
		( "minutes", 60 ),
		( "seconds", 1 )
	)

	for interval, number in periods:
		timePart = inputSeconds // number		# Modulus / floor divide
		if timePart:
			inputSeconds -= timePart * number	# Take away the part so far
			if timePart == 1: interval = interval.rstrip( "s" )	# Handle singular case
			results.append( "{0} {1}".format( timePart, interval ) )
	output = ", ".join( results )
	return output + trailingText


###################################################################################################



# Set up our inputs from the command line. This also handles the "-h" and error usage output for free!
parser = argparse.ArgumentParser( description = "Nagios check of the sync status of CloudEndure replication. Exit status 0 == OK, 1 == Warning, 2 == Critical, 3 == Unknown.",
				  epilog = "https://github.com/stefan-wuensch/Nagios-Checks" )
parser.add_argument( "-v", "--verbose",  help = "increase output verbosity", action = "store_true" )
parser.add_argument( "-u", "--username", help = "user name for the CloudEndure account - required", required = True )
parser.add_argument( "-p", "--password", help = "password for the CloudEndure account - required",  required = True )
parser.add_argument( "-n", "--hostname", help = "hostname of instance to check, or \"all\" (defaults to \"all\" if not specified)", default = "all" )
args = parser.parse_args()

if args.verbose:
	print "Time now", int( time.time() )
	print "username", args.username
# 	print "password", args.password		# Echoing the password is probably not a good idea, but it comes in on the command line anyway.
	print "hostname", args.hostname


# Do the login
try:
	response, connection = send_request( 'login', { 'username': args.username, 'password': args.password }, {} )
except Exception:
	exit_with_message( "Could not get a response on the login transaction!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )


# Extract the session cookie from the login
try:
	session_cookie = [ header[ 1 ] for header in response.getheaders() if header[ 0 ] == 'set-cookie' ][ 0 ]
	connection.close()
	if args.verbose: print "Connection closed"
except Exception:
	session_cookie = ""		# Set it to null in case we get all the way to the 'logout' call - we at least need it initialized.
	exit_with_message( "Could not get a session cookie from the login transaction!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )
cookies = re.split( '; |, ', session_cookie )
session_cookie = [ cookie for cookie in cookies if cookie.startswith( 'session' ) ][ 0 ].strip()


# Get the replica location from the user info
response, connection = send_request( 'getUserDetails', {}, { 'Cookie': session_cookie } )
try:
	result = json.loads( response.read() )[ 'result' ]
	connection.close()
	if args.verbose: print "Connection closed"
except Exception:
	exit_with_message( "Could not get a \"result\" object from the \"getUserDetails\" transaction!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )

if args.verbose: print "\ngetUserDetails:", json.dumps( result, sort_keys = True, indent = 4 )

try:
	location = result[ 'originalLocation' ]
except Exception:
	exit_with_message( "Could not get a value for \"originalLocation\" from the \"getUserDetails\" transaction!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )


# This is from some sample code I incorporated into this script. Since the 'for' loop
# looks useful for future things, I'm including it here for reference. This builds and prints
# a one-line comma-separated list of machine IDs. This is not needed in this script.
# response, connection = send_request( 'listMachines', { 'location': location }, { 'Cookie': session_cookie } )
# machineIds = [ machine[ 'id' ] for machine in json.loads( response.read() )[ 'result' ] ]
# print ', '.join(machineIds)


# Now that we have the location, we list all machines. This gets us all info about everything!
response, connection = send_request( 'listMachines', { 'location': location }, { 'Cookie': session_cookie } )
try:
	instances = json.loads( response.read() )[ 'result' ]
	connection.close()
	if args.verbose: print "Connection closed"
except Exception:
	exit_with_message( "Could not get a \"result\" object from the \"listMachines\" transaction!", EXIT_STATUS_DICT[ 'UNKNOWN' ] )
if args.verbose: print "\nlistMachines:", json.dumps( instances, sort_keys = True, indent = 4 )



################################################################
# Special overrides for testing / debugging / development.
# This manipulates the timestamp and status text for evaluating
# the logic in last_sync_time_test()
# 
# for x in instances:
# 	timetest = "2016-01-01T22:08:15.803212+00:00"
# 	print "\n*** Setting lastConsistencyTime to " + timetest + " for testing"
# 	x[ 'lastConsistencyTime' ] = timetest
# 	print "\n*** Setting replicationState to \"foo\" for testing"
# 	x[ 'replicationState' ] = "foo"
################################################################



if args.hostname == "all":		# "all" means we're going to check all of them (duh)

	summaryMessage = ""		# Init to null because we are going to be appending text
	highestError = 0		# Track the worst status for the final return code
	statusDict = {}			# Init a dictionary to track all the instances' status for later use

	for severity in ( EXIT_STATUS_DICT[ 'OK' ], EXIT_STATUS_DICT[ 'WARNING' ], EXIT_STATUS_DICT[ 'CRITICAL' ], EXIT_STATUS_DICT[ 'UNKNOWN' ] ):
		statusDict[ severity ] = []		# Initialize the structure - each severity level will hold names of instances

	for instance in instances:
		if args.verbose: print "\nname:", instance[ 'name' ]

		message, exitCode = last_sync_time_test( instance )		# This is the heart of the analysis of health.
		statusDict[ instance[ 'name' ] ] = {}				# Init the structure for each host
		statusDict[ instance[ 'name' ] ][ 'message' ] = message		# Store the message for each host
		statusDict[ instance[ 'name' ] ][ 'exitCode' ] = exitCode	# Store the status code for each host
		statusDict[ exitCode ].append( instance[ 'name' ] )		# Push the name of this instance into the array for its severity
		statusDict[ exitCode ].sort

		if args.verbose: print "\nstatusDict:", json.dumps( statusDict, sort_keys = True, indent = 4 )
		if exitCode > highestError: highestError = exitCode	# Capture the "worst" error state

	# Now we build up the 'summaryMessage' by iterating across all the different statuses. (or stati? My Latin sucks.)
	# For each level of severity we'll build a comma-separated list of hostnames with that status.
	# If a severity level doesn't have any hosts in that state, we'll output '0' (zero).
	# Each of the severity levels will be slash-separated.
	# Example:
	# OK: server12.blah.com / WARNING: 0 / CRITICAL: server1.blah.com, server8.blah.com / UNKNOWN: 0
	for severity in ( EXIT_STATUS_DICT[ 'OK' ], EXIT_STATUS_DICT[ 'WARNING' ], EXIT_STATUS_DICT[ 'CRITICAL' ], EXIT_STATUS_DICT[ 'UNKNOWN' ] ):

		wasPreviousCountZero = True			# Track what the previous number was, so we know when to use a slash vs. comma
		if len( statusDict[ severity ] ) > 0:		# Is there one or more host(s) with this severity level?
			isFirstHostName = True
			for name in statusDict[ severity ]:	# If there are hosts this time, add each one to the summary message by iterating over the list
				if len( summaryMessage ) > 0:	# Only add punctuation if we're not starting off for the very first time
					if wasPreviousCountZero == True:
						summaryMessage += " / "
					else:
						summaryMessage += ", "
				if isFirstHostName: 		# Only add the name of the severity level if it's the first host with this level
					summaryMessage += EXIT_STATUS_DICT_REVERSE[ severity ] + ": "
					isFirstHostName = False
				summaryMessage += name
				wasPreviousCountZero = False

		else:						# If there wasn't any host in this severity, show zero
			if len( summaryMessage ) > 0: 		# Don't add a comma if we're just starting off for the first round
				summaryMessage += " / "
			summaryMessage += EXIT_STATUS_DICT_REVERSE[ severity ] + ": 0"
			wasPreviousCountZero = True

	summaryMessage = "Status of all hosts in account \"" + args.username + "\": " + summaryMessage
	exit_with_message( summaryMessage, highestError )

else:		# This means we were given a specific host name to check
	foundTheHostname = False
	for instance in instances:	# Here we are looking for one in particular out of all of them, so iterate
		if instance[ 'name' ] == args.hostname:
			foundTheHostname = True
			if args.verbose: print "\nI found %s" % args.hostname
			message, exitCode = last_sync_time_test( instance )
			exit_with_message( message, exitCode )

	# Not finding the host name that was specified is a big problem!!!
	if foundTheHostname == False: exit_with_message( "Could not find the specified hostname \"" + args.hostname
							+ "\" in account \"" + args.username + "\" !!", EXIT_STATUS_DICT[ 'CRITICAL' ] )


# Bail out fail-safe (but in this case "safe" is to notify us of the problem!)
exit_with_message( "Something went wrong - this should not happen.", EXIT_STATUS_DICT[ 'UNKNOWN' ] )

