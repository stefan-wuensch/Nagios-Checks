#!/usr/bin/env python

# =================================================================================================
# check_CloudEndure_replication.py
# 
# By Stefan Wuensch, Jan. 2016
# 
# This script is a Nagios plugin which will query the CloudEndure API for the 
# replication / sync status of a host. 
# 
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
# https://confluence.huit.harvard.edu/pages/viewpage.action?pageId=12133075
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


import urllib, httplib, json, re, sys, argparse, time, calendar
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

WARNING_SYNC_DELAY  = 300	# Number of seconds over which it's a Warning - we will forgive any sync delay up to 5 min.
CRITICAL_SYNC_DELAY = 900	# Number of seconds (equals 15 minutes) over which it's Critical



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
	response = send_request( 'logout', {}, { 'Cookie': session_cookie } )	# Send a logout because they want that
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
	try:
		instance[ 'lastConsistencyTime' ] = calendar.timegm( datetime.strptime( instance[ 'lastConsistencyTime' ], '%Y-%m-%dT%H:%M:%S.%fZ' ).timetuple() )
	except ValueError:
		instance[ 'lastConsistencyTime' ] = calendar.timegm( datetime.strptime( instance[ 'lastConsistencyTime' ], '%Y-%m-%dT%H:%M:%S.%f+00:00' ).timetuple() )
	if args.verbose: print "lastConsistencyTime UNIX epoch seconds:", instance[ 'lastConsistencyTime' ]

	# Now for the ultimate in being careful, make sure it really is an integer!
	if not isinstance( instance[ 'lastConsistencyTime' ], ( int, long ) ):
		message = instance[ 'name' ] + " lastConsistencyTime is not an integer!"
		return ( message, EXIT_STATUS_DICT[ 'UNKNOWN' ] )

	# Make a string that's human-readable for printing in output
	lastSyncTimeStr = time.strftime( '%Y-%m-%d %H:%M:%S', time.localtime( instance[ 'lastConsistencyTime' ] ) )

	# Finally calculate how far back was the last sync
	timeDelta = int( time.time() ) - instance[ 'lastConsistencyTime' ]

	if ( timeDelta > CRITICAL_SYNC_DELAY ):		# This is the first test, because the longest delay value is Critical
		message = instance[ 'name' ] + " has not had an update since " + lastSyncTimeStr + ", " + str( timeDelta ) + " seconds ago"
		return ( message, EXIT_STATUS_DICT[ 'CRITICAL' ] )

	if ( timeDelta > WARNING_SYNC_DELAY ):
		message = instance[ 'name' ] + " has not had an update since " + lastSyncTimeStr + ", " + str( timeDelta ) + " seconds ago"
		return ( message, EXIT_STATUS_DICT[ 'WARNING' ] )

	if ( timeDelta <= WARNING_SYNC_DELAY ):		# If the delay since last sync is less than our tolerance for Warning, it's good!!
		message = instance[ 'name' ] + " last update " + lastSyncTimeStr + ", " + str( timeDelta ) + " seconds ago"
		return ( message, EXIT_STATUS_DICT[ 'OK' ] )

	message = "Could not analyze the sync state for " + instance[ 'name' ]
	return ( message, EXIT_STATUS_DICT[ 'UNKNOWN' ] )		# If we get to this point something went wrong!



###################################################################################################
def send_request( func, params, headers ):

# This function makes the HTTPS call out to the CloudEndure API and makes sure we get a '200' HTTP status
# before returning the JSON
# 
# Usage: send_request( string, dict1, dict2 )
# 	'string' is the API function call
# 	'dict1' is a dictionary of parameters for the API call
# 	'dict2' is a dictionary of HTTP headers - currently only used for the session auth cookie
# 
# Returns: JSON blob

	conn = httplib.HTTPSConnection( 'dashboard.cloudendure.com', 443 )
	conn.connect()
	headers.update( { 'Content-Type': 'application/json' } )

	# For debugging it's helpful to include the 'params' in verbose output, but
	# that exposes the password when calling the 'login' API function - so it's not
	# a great idea. Instead just show the function name and headers. That's safe.
	## if args.verbose: print "\nCalling {0} with {1} and {2}".format( func, params, headers )
	if args.verbose: print "\nCalling {0} with {1}".format( func, headers )

	conn.request( 'POST', '/latest/' + func, json.dumps( params ), headers )
	response = conn.getresponse()
	if response.status != 200:
		exit_with_message( "login call returned HTTP code {0} {1}".format( response.status, response.reason ), EXIT_STATUS_DICT[ 'UNKNOWN' ] )
	return response

###################################################################################################



# Set up our inputs from the command line. This also handles the "-h" and error usage output for free!
parser = argparse.ArgumentParser( description = "Nagios check of the sync status of CloudEndure replication. Exit status 0 == OK, 1 == Warning, 2 == Critical, 3 == Unknown.",
				  epilog = "https://confluence.huit.harvard.edu/pages/viewpage.action?pageId=12133075" )
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
response = send_request( 'login', { 'username': args.username, 'password': args.password }, {} )


# Extract the session cookie from the login
session_cookie = [ header[ 1 ] for header in response.getheaders() if header[ 0 ] == 'set-cookie' ][ 0 ]
cookies = re.split( '; |, ', session_cookie )
session_cookie = [ cookie for cookie in cookies if cookie.startswith( 'session' ) ][ 0 ].strip()


# Get the replica location from the user info
response = send_request( 'getUserDetails', {}, { 'Cookie': session_cookie } )
result = json.loads( response.read() )[ 'result' ]
if args.verbose: print "\ngetUserDetails:", json.dumps( result, sort_keys = True, indent = 4 )
location = result[ 'originalLocation' ]


# This is from some sample code I incorporated into this script. Since the 'for' loop
# looks useful for future things, I'm including it here for reference. This builds and prints
# a one-line comma-separated list of machine IDs. This is not needed in this script.
# response = send_request( 'listMachines', { 'location': location }, { 'Cookie': session_cookie } )
# machineIds = [ machine[ 'id' ] for machine in json.loads( response.read() )[ 'result' ] ]
# print ', '.join(machineIds)


# Now that we have the location, we list all machines. This gets us all info about everything!
response = send_request( 'listMachines', { 'location': location }, { 'Cookie': session_cookie } )
instances = json.loads( response.read() )[ 'result' ]
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
	# Each of the severity levels will be slash-separated
	# Example:
	# OK: server12.harvard.edu / WARNING: 0 / CRITICAL: server1.harvard.edu, server8.harvard.edu / UNKNOWN: 0
	for severity in ( EXIT_STATUS_DICT[ 'OK' ], EXIT_STATUS_DICT[ 'WARNING' ], EXIT_STATUS_DICT[ 'CRITICAL' ], EXIT_STATUS_DICT[ 'UNKNOWN' ] ):

		wasPreviousCountZero = True			# Track what the previous number was, so we know when to use a slash vs. comma
		if len( statusDict[ severity ] ) > 0:		# Is there one or more host(s) with this severity level?
			isFirstHostName = True
			for name in statusDict[ severity ]:	# If there are hosts this time, add each one to the summary message by iterating over the list
				if len( summaryMessage ) > 0:	# Only add punctuation if we're not starting off for the very first time
					if wasPreviousCountZero == True:
						summaryMessage = summaryMessage + " / "
					else:
						summaryMessage = summaryMessage + ", "
				if isFirstHostName: 		# Only add the name of the severity level if it's the first host with this level
					summaryMessage = summaryMessage + EXIT_STATUS_DICT_REVERSE[ severity ] + ": "
					isFirstHostName = False
				summaryMessage = summaryMessage + name
				wasPreviousCountZero = False

		else:						# If there wasn't any host in this severity, show zero
			if len( summaryMessage ) > 0: 		# Don't add a comma if we're just starting off for the first round
				summaryMessage = summaryMessage + " / "
			summaryMessage = summaryMessage + EXIT_STATUS_DICT_REVERSE[ severity ] + ": 0"
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

