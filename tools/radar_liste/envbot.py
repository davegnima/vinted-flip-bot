import os as _os; _QUI=_os.path.dirname(_os.path.abspath(__file__)); _REPO=_os.path.abspath(_os.path.join(_QUI,'..','..'))
import os,sys,tempfile
t=tempfile.mkdtemp()
os.environ.update({"TELEGRAM_API_ID":"1","TELEGRAM_API_HASH":"x","TELEGRAM_SESSION_STRING":"","TELEGRAM_GROUP_ID":"-100","TELEGRAM_BOT_TOKEN":"1:x","TELEGRAM_OWNER_CHAT_ID":"1","GEMINI_API_KEY":"k","DB_FILE":t+"/d.sqlite3","TRACCIAMENTO_FILE":t+"/t.jsonl","FAIR_VALUE_LOG_FILE":t+"/f.jsonl","FAIR_VALUE_APPRESO_FILE":t+"/a.json","CATALOGO_CATEGORIE_FILE":t+"/c.json"})
sys.path.insert(0,_REPO)
