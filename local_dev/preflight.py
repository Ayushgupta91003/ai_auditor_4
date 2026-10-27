"""Bounded loopback probe: avoid asyncio socketpair hanging in restricted Windows sandboxes."""
import socket

def loopback_status():
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.settimeout(1)
            listener.bind(("127.0.0.1",0));listener.listen(1)
            with socket.create_connection(listener.getsockname(),timeout=1):
                connection,_=listener.accept();connection.close()
        return True,"Loopback sockets available"
    except OSError:
        return False,"This execution environment blocks localhost sockets. Run START_LOCAL.cmd in a normal laptop terminal. No administrator elevation is intended."
