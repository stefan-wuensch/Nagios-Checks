# check_JSON_status_URL.py

This script is a Nagios plugin which will query a web service for a JSON blob
of health indicators. This will iterate over all the key/value pairs in the JSON, 
and compare each value to the input arguments for Warning and OK.

