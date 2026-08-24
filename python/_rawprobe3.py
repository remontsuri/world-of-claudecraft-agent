import socket, json
CRLF=b"\r\n"
host,port="127.0.0.1",8791
data=json.dumps({"action":"snapshot"}).encode()
req=("POST / HTTP/1.1"+CRLF.decode()+"Host: 127.0.0.1:8791"+CRLF.decode()+
     "Content-Type: application/json"+CRLF.decode()+"Content-Length: %d"%len(data)+CRLF.decode()+
     "Connection: close"+CRLF.decode()+CRLF.decode()).encode()+data
s=socket.create_connection((host,port),timeout=5)
s.settimeout(10)
s.sendall(req)
buf=b""
while True:
    try: c=s.recv(65536)
    except socket.timeout: break
    if not c: break
    buf+=c
    if len(buf)>20000: break
s.close()
print("TOTAL:",len(buf))
print("ENDS WITH:",repr(buf[-20:]))
print("HAS 0CRLFCRLF:", b"0"+CRLF+CRLF in buf)
