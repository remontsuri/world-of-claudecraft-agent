import socket, json, time
CRLF=b"\r\n"
host,port="127.0.0.1",8791
for n in range(1, 11):
    data=json.dumps({"action":"explore","steps":5}).encode()
    req=("POST / HTTP/1.1"+CRLF.decode()+"Host: 127.0.0.1:8791"+CRLF.decode()+
         "Content-Type: application/json"+CRLF.decode()+"Content-Length: %d"%len(data)+CRLF.decode()+
         "Connection: close"+CRLF.decode()+CRLF.decode()).encode()+data
    s=socket.create_connection((host,port),timeout=5)
    s.settimeout(15)
    s.sendall(req)
    buf=b""
    try:
        while True:
            c=s.recv(65536)
            if not c: break
            buf+=c
    except socket.timeout:
        print(f"[{n}] TIMEOUT reading")
        s.close(); continue
    s.close()
    has_term = b"0"+CRLF+CRLF in buf
    # crude chunked decode
    out=b""; i=0
    while i < len(buf):
        crlf=buf.find(CRLF,i)
        if crlf==-1: break
        try: sz=int(buf[i:crlf].split(b";")[0].strip(),16)
        except ValueError: break
        if sz==0: break
        out+=buf[crlf+2:crlf+2+sz]; i=crlf+2+sz+2
    try:
        json.loads(out.decode("utf-8"))
        jok="JSON OK"
    except Exception as e:
        jok="JSON FAIL: %s" % type(e).__name__
    print(f"[{n}] len={len(buf)} term={has_term} decoded={len(out)} {jok}")
