from clientx_session import Session

# Either a direct TC URL...
sess = Session("http://your-tc-web/soa", "", "")

# ...or via TCCS environment
arg_map = Session.GetConfigurationFromTCCS(["-host", "tccs://MyEnv"])
sess = Session(arg_map["-host"], arg_map.get("-sso-url",""), arg_map.get("-appid",""))

user = sess.login()
print("Logged in as:", getattr(user, "User_name", "<user>"))
# ... call services here ...
sess.logout()
