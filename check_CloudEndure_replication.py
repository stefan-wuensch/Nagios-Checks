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
# Exit status: 0, 1, 2, 3 as standard Nagios status codes. See EXITSTATUSDICT for mapping.
# 
# =================================================================================================


import urllib, httplib, json, re, sys, argparse, time

# Dictionary for exit status codes
EXITSTATUSDICT = { 
	"OK": 0,
	"WARNING": 1,
	"CRITICAL": 2,
	"UNKNOWN": 3
}

# Dictionary for looking up the status string from the value
EXITSTATUSDICTREVERSE = { 
	0: "OK",
	1: "WARNING",
	2: "CRITICAL",
	3: "UNKNOWN"
}

TIMENOW = int( time.time() )
WARNINGSYNCDELAY  = 15		# number of seconds over which it's a Warning - we will forgive any sync delay up to 15 sec.
CRITICALSYNCDELAY = 900		# number of seconds (equals 15 minutes) over which it's Critical



###################################################################################################
def exitWithMessage( message = "Something not defined", exitCode = EXITSTATUSDICT[ 'UNKNOWN' ] ):

# Output a message and exit
# 
# Usage: exitWithMessage( string, int )
# 	'string' is printed to STDOUT
# 	'int' is used for the exit status
# 
# Returns: nothing - will always exit
# 
# Note the default values.

	prefix = ""
	if exitCode == EXITSTATUSDICT[ 'UNKNOWN' ]: prefix = "Error: "		# Add additional info at beginning
	print "{0}{1}".format( prefix, message )
	response = sendRequest( 'logout', {}, { 'Cookie': session_cookie } )	# Send a logout because they want that
	sys.exit( exitCode )



###################################################################################################
def lastSyncTimeTest( instance ):

# This function is the heart of the health check logic. 
# 
# Usage: lastSyncTimeTest( dictionary )
# 	'dictionary' is from JSON, containing details of one specific host
# 
# Returns: tuple of ( string, int ) where 'string' is a status message and 'int' is a status code

	if args.verbose: print "replicationState:", instance[ 'replicationState' ]
	if args.verbose: print "lastConsistencyTime:", instance[ 'lastConsistencyTime' ]

	# First thing to check is the text string of the state
	if instance[ 'replicationState' ] == "Not Replicated":
		message = instance[ 'name' ] + " (" + instance[ 'id' ] + ") is Not Replicated!"
		return ( message, EXITSTATUSDICT[ 'CRITICAL' ] )

	# Dummy check the timestamp, because if the host isn't replicating the timestamp will be null
	# This shouldn't be a real indication of replication failure, because the 'replicationState' being
	# checked above should catch it.
	if not isinstance( instance[ 'lastConsistencyTime' ], ( int, long ) ):
		message = instance[ 'name' ] + " lastConsistencyTime is not an integer!"
		return ( message, EXITSTATUSDICT[ 'UNKNOWN' ] )

	lastSyncTimeStr = time.strftime( '%Y-%m-%d %H:%M:%S', time.localtime( instance[ 'lastConsistencyTime' ] ) )
	timeDelta = TIMENOW - instance[ 'lastConsistencyTime' ]

	if ( timeDelta > CRITICALSYNCDELAY ):		# This is the first test, because the longest delay value is Critical
		message = instance[ 'name' ] + " has not had an update since " + lastSyncTimeStr
		return ( message, EXITSTATUSDICT[ 'CRITICAL' ] )

	if ( timeDelta > WARNINGSYNCDELAY ):
		message = instance[ 'name' ] + " has not had an update since " + lastSyncTimeStr
		return ( message, EXITSTATUSDICT[ 'WARNING' ] )

	if ( timeDelta <= WARNINGSYNCDELAY ):		# If the delay since last sync is less than our tolerance for Warning, it's good!!
		message = instance[ 'name' ] + " last update " + lastSyncTimeStr
		return ( message, EXITSTATUSDICT[ 'OK' ] )

	message = "Could not analyze the sync state for " + instance[ 'name' ]
	return ( message, EXITSTATUSDICT[ 'UNKNOWN' ] )		# If we get to this point something went wrong!



###################################################################################################
def sendRequest( func, params, headers ):

# This function makes the HTTPS call out to the CloudEndure API and makes sure we get a '200' HTTP status
# before returning the JSON
# 
# Usage: sendRequest( string, dict1, dict2 )
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
		exitWithMessage( "login call returned HTTP code {0} {1}".format( response.status, response.reason ), EXITSTATUSDICT[ 'UNKNOWN' ] )
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
	print "Time now", TIMENOW
	print "username", args.username
# 	print "password", args.password		# echoing the password is probably not a good idea, but it comes in on the command line anyway.
	print "hostname", args.hostname


# Do the login
response = sendRequest( 'login', { 'username': args.username, 'password': args.password }, {} )


# Extract the session cookie from the login
session_cookie = [ header[ 1 ] for header in response.getheaders() if header[ 0 ] == 'set-cookie' ][ 0 ]
cookies = re.split( '; |, ', session_cookie )
session_cookie = [ cookie for cookie in cookies if cookie.startswith( 'session' ) ][ 0 ].strip()


# Get the replica location from the user info
response = sendRequest( 'getUserDetails', {}, { 'Cookie': session_cookie } )
result = json.loads( response.read() )[ 'result' ]
if args.verbose: print "\ngetUserDetails:", json.dumps( result, sort_keys = True, indent = 4 )
location = result[ 'mirrorLocation' ]


# This is from some sample code I incorporated into this script. Since the 'for' loop
# looks useful for future things, I'm including it here for reference. This builds and prints
# a one-line comma-separated list of machine IDs. This is not needed in this script.
# response = sendRequest( 'listMachines', { 'location': location }, { 'Cookie': session_cookie } )
# machineIds = [ machine[ 'id' ] for machine in json.loads( response.read() )[ 'result' ] ]
# print ', '.join(machineIds)


# Now that we have the location, we list all machines. This gets us all info about everything!
response = sendRequest( 'listMachines', { 'location': location }, { 'Cookie': session_cookie } )
instances = json.loads( response.read() )[ 'result' ]
if args.verbose: print "\nlistMachines:", json.dumps( instances, sort_keys = True, indent = 4 )



################################################################
# Special overrides for testing / debugging / development.
# This manipulates the timestamp and status text for evaluating
# the logic in lastSyncTimeTest()
# 
# for x in instances:
# 	timetest = int( TIMENOW - 901 )
# 	print "\n*** Setting lastConsistencyTime to " + str( timetest ) + " for testing"
# 	x[ 'lastConsistencyTime' ] = timetest
# 	print "\n*** Setting replicationState to \"foo\" for testing"
# 	x[ 'replicationState' ] = "foo"
################################################################



if args.hostname == "all":		# "all" means we're going to check all of them (duh)

	summaryMessage = ""		# init to null because we are going to be appending text
	highestError = 0		# track the worst status for the final return code
	statusDict = {}			# a dictionary to track all the instances' status for later use

	for severity in ( EXITSTATUSDICT[ 'OK' ], EXITSTATUSDICT[ 'WARNING' ], EXITSTATUSDICT[ 'CRITICAL' ], EXITSTATUSDICT[ 'UNKNOWN' ] ):
		statusDict[ severity ] = []		# initialize the structure - each severity level will hold names of instances

	for instance in instances:
		if args.verbose: print "\nname:", instance[ 'name' ]

		message, exitCode = lastSyncTimeTest( instance )		# This is the heart of the analysis of health.
		statusDict[ instance[ 'name' ] ] = {}				# Init the structure for each host
		statusDict[ instance[ 'name' ] ][ 'message' ] = message		# Store the message for each host
		statusDict[ instance[ 'name' ] ][ 'exitCode' ] = exitCode	# Store the status code for each host
		statusDict[ exitCode ].append( instance[ 'name' ] )		# push the name of this instance into the array for its severity
		statusDict[ exitCode ].sort

		if args.verbose: print "\nstatusDict:", json.dumps( statusDict, sort_keys = True, indent = 4 )
		if exitCode > highestError: highestError = exitCode	# Capture the "worst" error state

	# Now we build up the 'summaryMessage' by iterating across all the different statuses. (or stati? My Latin sucks.)
	# For each level of severity we'll build a comma-separated list of hostnames with that status. 
	# If a severity level doesn't have any hosts in that state, we'll output '0' (zero).
	for severity in ( EXITSTATUSDICT[ 'OK' ], EXITSTATUSDICT[ 'WARNING' ], EXITSTATUSDICT[ 'CRITICAL' ], EXITSTATUSDICT[ 'UNKNOWN' ] ):
		if len( statusDict[ severity ] ) > 0:		# is there a host with this severity level?
			for name in statusDict[ severity ]:	# if so, add it to the list
				if len( summaryMessage ) > 0: summaryMessage = summaryMessage + ", "
				summaryMessage = summaryMessage + EXITSTATUSDICTREVERSE[ severity ] + ": " + name
		else:						# if there wasn't any host in this severity, show zero
			if len( summaryMessage ) > 0: summaryMessage = summaryMessage + ", "
			summaryMessage = summaryMessage + EXITSTATUSDICTREVERSE[ severity ] + ": 0"

	summaryMessage = "Status of all: " + summaryMessage
	exitWithMessage( summaryMessage, highestError )

else:		# this means we were given a specific host name to check
	foundTheHostname = False
	for instance in instances:	# here we are looking for one in particular out of all of them, so iterate
		if instance[ 'name' ] == args.hostname:
			foundTheHostname = True
			if args.verbose: print "\nI found %s" % args.hostname
			message, exitCode = lastSyncTimeTest( instance )
			exitWithMessage( message, exitCode )

	# Not finding the host name that was specified is a big problem!!!
	if foundTheHostname == False: exitWithMessage( "Could not find the specified hostname \"" + args.hostname 
							+ "\" in account \"" + args.username + "\" !!", EXITSTATUSDICT[ 'CRITICAL' ] )


# Bail out fail-safe (but in this case "safe" is to notify us of the problem!)
exitWithMessage( "Something went wrong - this should not happen.", EXITSTATUSDICT[ 'UNKNOWN' ] )

