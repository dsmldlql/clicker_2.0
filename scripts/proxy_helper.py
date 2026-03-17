#!/usr/bin/env python3
"""
Local HTTP proxy server that handles proxy authentication transparently.
Chromium connects to this proxy without auth, and this proxy forwards
requests to the real proxy with authentication.
"""
import socket
import threading
import base64
import sys
import select

class ProxyConnection:
    def __init__(self, proxy_host, proxy_port, proxy_login, proxy_password):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.proxy_login = proxy_login
        self.proxy_password = proxy_password
        self.auth_header = f'Basic {base64.b64encode(f"{proxy_login}:{proxy_password}".encode()).decode()}'
    
    def forward_to_proxy(self, client_socket):
        """Forward client request to upstream proxy with authentication"""
        try:
            # Read request from client
            request = client_socket.recv(8192)
            if not request:
                return
            
            # Connect to upstream proxy
            proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            proxy_sock.settimeout(10)
            proxy_sock.connect((self.proxy_host, self.proxy_port))
            
            # Check if this is a CONNECT request (for HTTPS)
            if request.startswith(b'CONNECT'):
                # Add Proxy-Authorization header to CONNECT request
                lines = request.split(b'\r\n')
                new_request = b'\r\n'.join(lines[:-1])  # Remove empty last line
                new_request += f'\r\nProxy-Authorization: {self.auth_header}'.encode()
                new_request += b'\r\n\r\n'
                
                # Send CONNECT to proxy
                proxy_sock.sendall(new_request)
                
                # Read proxy response
                response = b''
                while b'\r\n\r\n' not in response:
                    chunk = proxy_sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                
                # Check if connection established
                if b'200' in response.split(b'\r\n')[0]:
                    client_socket.sendall(response)
                    # Now relay data bidirectionally
                    self.relay(client_socket, proxy_sock)
                else:
                    client_socket.sendall(response)
                
                proxy_sock.close()
                client_socket.close()
            else:
                # HTTP request - add Proxy-Authorization header
                lines = request.split(b'\r\n')
                new_request = b'\r\n'.join(lines[:-1])
                new_request += f'\r\nProxy-Authorization: {self.auth_header}'.encode()
                new_request += b'\r\n\r\n'
                
                # Send to proxy
                proxy_sock.sendall(new_request)
                
                # Forward response
                while True:
                    response = proxy_sock.recv(4096)
                    if not response:
                        break
                    client_socket.sendall(response)
                
                proxy_sock.close()
                client_socket.close()
                
        except Exception as e:
            print(f"Error: {e}")
            try:
                client_socket.close()
            except:
                pass
    
    def relay(self, client, proxy):
        """Relay data between client and proxy"""
        try:
            while True:
                readable, _, _ = select.select([client, proxy], [], [], 5)
                if not readable:
                    break
                
                for sock in readable:
                    other = proxy if sock is client else client
                    data = sock.recv(4096)
                    if not data:
                        return
                    other.sendall(data)
        except Exception as e:
            print(f"Relay error: {e}")

def run_proxy(local_port, upstream_proxy_host, upstream_proxy_port, login, password):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', local_port))
    server.listen(10)
    
    print(f"[*] Local proxy listening on 127.0.0.1:{local_port}")
    print(f"[*] Forwarding to {upstream_proxy_host}:{upstream_proxy_port}")
    print(f"[*] Using authentication: {login}:***")
    
    conn = ProxyConnection(upstream_proxy_host, upstream_proxy_port, login, password)
    
    while True:
        try:
            client, addr = server.accept()
            thread = threading.Thread(target=conn.forward_to_proxy, args=(client,))
            thread.daemon = True
            thread.start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Accept error: {e}")
    
    server.close()

if __name__ == "__main__":
    if len(sys.argv) != 6:
        print("Usage: python proxy_helper.py <local_port> <proxy_host> <proxy_port> <login> <password>")
        sys.exit(1)
    
    local_port = int(sys.argv[1])
    proxy_host = sys.argv[2]
    proxy_port = int(sys.argv[3])
    login = sys.argv[4]
    password = sys.argv[5]
    
    run_proxy(local_port, proxy_host, proxy_port, login, password)
