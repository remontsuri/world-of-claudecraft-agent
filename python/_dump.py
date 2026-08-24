import socket, json
CRLF=b"\r\n"
host,port="127.0.0.1",8791
data=json.dumps({"action":"snapshot"}).encode()
req=("POST / HTTP/1.1"+CRLF.decode()+"Host: 127.0.0.1:8791"+CRLF.decode()+
     "Content-Type: application/json"+CRLF.decode()+"Content-Length: %d"%len(data)+CRLF.decode()+
     "Connection: close"+CRLF.decode()+CRLF.decode()).encode()+data
s=socket.create_connection((host,port),timeout=5)
s.settimeout(15); s.sendall(req)
buf=b""
while True:
    c=s.recv(65536)
    if not c: break
    buf+=c
s.close()
# show first 120 bytes as repr to see chunk structure
print("FIRST 160:", repr(buf[:160]))
print("HAS 0CRLFCRLF:", b"0"+CRLF+CRLF in buf)
# find first chunk size line
h_end = buf.find(CRLF+CRLF)
body = buf[h_end+4:]
print("BODY FIRST 80:", repr(body[:80]))
