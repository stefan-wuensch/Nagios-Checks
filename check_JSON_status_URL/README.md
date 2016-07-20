# check_JSON_status_URL.py

This script is a Nagios plugin which will query a web service for a JSON blob
of health indicators. This will iterate over all the key/value pairs in the JSON,
and compare each value to the input arguments for Warning and OK.



```
Usage: check_JSON_status_URL.py [-h] [-v] -u URL -p OKSTRING [-w WARNSTRING]

Nagios check of a JSON app health object. Exit status 0 == OK, 1 == Warning,
2 == Critical, 3 == Unknown.

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         increase output verbosity
  -u URL, --url URL     URL to be checked - required
  -p OKSTRING, --okString OKSTRING
                        text string which indicates OK - required
  -w WARNSTRING, --warnString WARNSTRING
                        text string which indicates Warning


Exit status: 0, 1, 2, 3 as standard Nagios status codes. See EXIT_STATUS_DICT for mapping.
```

Note: If no WARNSTRING arg is given, the only non-OK state returned will be CRITICAL.
Program errors will return Nagios UNKNOWN.


## Example of usage


Sample JSON for this example:
```
{
    "Name Look up service": "WARN",
    "File Transfer": "PASS",
    "Database Connection": "FAIL",
    "Security Service": "PASS"
}
```

Sample command:
```
check_JSON_status_URL.py --url=https://myserver.mydomain.com/apphealth.cgi --warnString=WARN --okString=PASS
```


Output for this example:
```
Status of all attributes: OK: Security Service, File Transfer / WARNING: Name Look up service / CRITICAL: Database Connection / UNKNOWN: 0
```


This example would have exited *2*, for Nagios *CRITICAL*.

