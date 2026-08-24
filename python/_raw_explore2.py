import socket, time, sys
HOST, PORT = "127.0.0.1", 8791
def raw_post(action, steps=None, n=1):
    for i in range(n):
        body = {"action": action}
        if steps is not None: body["steps"] = steps
        import json
        data = json.dumps(body).encode()
        req = (f"POST / HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n"
               f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n"
               f"Connection: close\r\n\r\n").encode() + data
        s = socket.create_connection((HOST, PORT), timeout=5.0)
        s.settimeout(20.0)
        t0 = time.time()
        try:
            s.sendall(req)
            buf = b""
            while True:
                c = s.recv(65536)
                if not c: break
                buf += c
                if len(buf) > 3_000_000: break
            dt = time.time() - t0
            # show structure
            head_end = buf.find(b"\r\n\r\n")
            cl = buf.lower().find(b"content-length")
            te = buf.lower().find(b"transfer-encoding")
            has_term = b"0\r\n\r\n" in buf
            print(f"[{i}] {dt:.2f}s len={len(buf)} head_end={head_end} "
                  f"content-length@={cl} transfer-encoding@={te} has_0term={has_term}", flush=True)
            print("   first 160:", repr(buf[:160]), flush=True)
            print("   last 80:", repr(buf[-80:]), flush=True)
        except Exception as e:
            print(f"[{i}] EXC after {time.time()-t0:.2f}s {type(e).__name__}: {e}", flush=True)
        finally:
            s.close()
        time.sleep(0.3)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    raw_post("explore", 10, n)
