import os
import socket
from app import app

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    local_ip = get_local_ip()

    print("=" * 65)
    print(" CLASSROOM ASSIGNMENT TRACKER SERVER STARTED")
    print("=" * 65)
    print(f" Local Machine URL : http://localhost:{port}")
    print(f" Mobile / LAN URL  : http://{local_ip}:{port}")
    print(" (Classmates on Android, iOS, Windows, Mac on same Wi-Fi")
    print(f"  can open http://{local_ip}:{port} on their browser!)")
    print("=" * 65)
    print(" Default Admin Account:")
    print(" Username: admin")
    print(" Password: admin123")
    print("=" * 65)

    use_waitress = os.environ.get('USE_WAITRESS', 'true').lower() == 'true'

    if use_waitress:
        try:
            from waitress import serve
            print("Running high-performance production WSGI server (Waitress)...")
            serve(app, host='0.0.0.0', port=port, threads=8)
        except ImportError:
            app.run(host='0.0.0.0', port=port, debug=True)
    else:
        app.run(host='0.0.0.0', port=port, debug=True)
