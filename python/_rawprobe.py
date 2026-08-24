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
    try:
        c=s.recv(65536)
    except socket.timeout:
        break
    if not c: break
    buf+=c
    if len(buf)>20000: break
s.close()
print("TOTAL BYTES:",len(buf))
print("FIRST 600:",repr(buf[:600]))
# find header/body split
i=buf.find(CRLF+CRLF)
print("HEADER/BODY SPLIT AT:",i)
print("BODY FIRST 300:",repr(buf[i+4:i+4+300]))
