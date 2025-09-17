# In a terminal where pythonnet can see .NET (Windows), and TC_BIN is set

set TC_BIN=C:\Siemens\Teamcenter\soa_client\bin
python hello_teamcenter.py -host http://your-tc-server:7001/tc -user yourid -password yourpwd

# Or if your environment is defined in TCCS:

python hello_teamcenter.py -host tccs://MY_ENV
