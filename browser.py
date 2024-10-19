import socket
import ssl
import tkinter
from datetime import datetime, timedelta

cache: dict[str, tuple[str, datetime]] = {}

WIDTH, HEIGHT = 800, 600


class URL:
    MAX_REDIRECTS = 10

    def __init__(self, url: str, redirects=0):
        self.redirects = redirects
        self.url = url
        if "data" in url:
            self.scheme, url = url.split(":", 1)
        else:
            self.scheme, url = url.split("://", 1)
        assert self.scheme in ["http", "https", "file", "data", "view-source"]

        if self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443
        elif self.scheme == "data":
            self.media_type, self.data = url.split(",", 1)
            return

        if "/" not in url:
            url += "/"
        self.host, url = url.split("/", 1)

        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            self.port = int(port)

        self.path = "/" + url

    def request(self) -> str:
        if self.scheme == "file":
            return open(self.path).read()
        if self.scheme == "data":
            return self.data

        s = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP
        )
        s.connect((self.host, self.port))

        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)
        
        request = f"GET {self.path} HTTP/1.1\r\n"
        request += f"Host: {self.host}\r\n"
        request += "Connection: keep-alive\r\n"
        request += "User-Agent: Bowser\r\n"
        request += "\r\n"
        s.send(request.encode("utf8"))

        response = s.makefile("r", encoding="utf8", newline="\r\n")
        statusline = response.readline()
        version, status, explanation = statusline.split(" ", 2)

        response_headers = {}
        while True:
            line = response.readline()
            if line == "\r\n": break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        assert "content-encoding" not in response_headers
        assert "transfer-encoding" not in response_headers

        if int(status) in range(300, 400) and self.redirects < URL.MAX_REDIRECTS and "://" in response_headers["location"]:
            self.redirects += 1
            self.__init__(response_headers["location"], redirects=self.redirects)
            return self.request()
        elif int(status) in range(300, 400) and self.redirects < URL.MAX_REDIRECTS:
            self.redirects += 1
            self.path = response_headers["location"]
            return self.request()
        elif int(status) in range(300, 400):
            return "ERROR: Maximum redirects exceeded"
        else:
            self.redirects = 0
        
        content = response.read(int(response_headers["content-length"]))

        if "cache-control" in response_headers and "no-store" not in response_headers["cache-control"]:
            exp_date = datetime.max
            cache_control = response_headers["cache-control"].split(",")

            for directive in cache_control:
                if "max-age" in directive:
                    max_age = int(directive.split("=", 1)[1])
                    exp_date = datetime.now() + timedelta(seconds=max_age) - timedelta(seconds=int(response_headers["age"]))
                    break
            cache[self.url] = (content, exp_date)

        return content
    
class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window,
            width=WIDTH,
            height=HEIGHT
        )
        self.canvas.pack()

    def load(self, url: URL) -> None:
        if url.url in cache and cache[url.url][1] > datetime.now():
            show(cache[url.url][0])
            return
        body = url.request()
        if url.scheme == "view-source":
            print(body, end="")
        else:
            show(body)
        self.canvas.create_rectangle(10, 20, 400, 300)
        self.canvas.create_oval(100, 100, 150, 150)
        self.canvas.create_text(200, 150, text="Hi!")

def show(body: str) -> None:
    in_tag = False
    i = 0
    while i < len(body):
        if body[i] == "<":
            in_tag = True
            i += 1
        elif body[i] == ">":
            in_tag = False
            i += 1
        elif not in_tag and body[i:i+4] == "&lt;":
            print("<", end="")
            i += 4
        elif not in_tag and body[i:i+4] == "&gt;":
            print(">", end="")
            i += 4
        elif not in_tag:
            print(body[i], end="")
            i += 1
        else:
            i += 1


if __name__ == "__main__":
    import sys
    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()