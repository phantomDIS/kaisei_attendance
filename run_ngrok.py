from pyngrok import ngrok
from pyngrok.conf import PyngrokConfig
import subprocess, time

LOCAL_NGROK = r"C:\ngrok\ngrok.exe"   # ← ここを固定
conf = PyngrokConfig(ngrok_path=LOCAL_NGROK)

flask_process = subprocess.Popen(["python", "app.py"])
time.sleep(2)
public_url = ngrok.connect(5000, pyngrok_config=conf)
print("🌐 公開URL:", public_url)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    ngrok.kill()
    flask_process.terminate()
