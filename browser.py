import gzip
import socket
import ssl
import tkinter
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import font as tk_font

type Cache = dict[str, tuple[str, datetime]]
cache: Cache = {}

HSTEP, VSTEP = 13, 18
MIN_WIDTH = HSTEP * 2
SCROLL_STEP = 100

class URL:
    MAX_REDIRECTS = 10

    def __init__(self, url: str, redirects=0):
        self.redirects = redirects
        self.url = url
        if "data" in url or "about" in url:
            self.scheme, url = url.split(":", 1)
        else:
            self.scheme, url = url.split("://", 1)
        if self.scheme not in ["http", "https", "file", "data", "view-source", "about"]:
            self.scheme, self.url = "about", "blank"

        if self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443
        elif self.scheme == "data":
            self.media_type, self.data = url.split(",", 1)
            return
        elif self.scheme == "about":
            self.data = ""
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
        if self.scheme == "data" or self.scheme == "about":
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
        request += "Accept-Encoding: gzip\r\n"
        request += "\r\n"
        s.send(request.encode("utf8"))

        response = s.makefile("rb")
        statusline = response.readline().decode("utf-8")
        version, status, explanation = statusline.split(" ", 2)

        response_headers = {}
        while True:
            line = response.readline().decode("utf-8")
            if line == "\r\n": break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

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

        if response_headers.get("transfer-encoding") == "chunked":
            content = b""
            while True:
                chunk_size_line = response.readline().strip()
                chunk_size = int(chunk_size_line, 16)
                if chunk_size == 0: break
                chunk_data = response.read(chunk_size)
                content += chunk_data
                response.read(2)
        else:
            content = response.read(int(response_headers["content-length"]))

        if response_headers.get("content-encoding") == "gzip":
            content = gzip.decompress(content)

        if "cache-control" in response_headers and "no-store" not in response_headers["cache-control"]:
            exp_date = datetime.max
            cache_control = response_headers["cache-control"].split(",")

            for directive in cache_control:
                if "max-age" in directive:
                    max_age = int(directive.split("=", 1)[1])
                    exp_date = datetime.now() + timedelta(seconds=max_age) - timedelta(seconds=int(response_headers["age"]))
                    break
            cache[self.url] = (str(content), exp_date)

        return content.decode("utf-8")

class Browser:
    def __init__(self, width=800, height=600):
        self.width, self.height = width, height
        self.window = tkinter.Tk()
        self.window.title("Bowser Browser")
        self.canvas = tkinter.Canvas(
            self.window,
            width=self.width,
            height=self.height,
            scrollregion=(0, 0, self.width, self.height)
        )
        self.v_scrollbar = tkinter.Scrollbar(
            self.window,
            command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)
        self.v_scrollbar.pack(fill="y", side="right")
        self.canvas.pack(fill="both", expand=True)
        self.window.protocol("WM_DELETE_WINDOW", self.window.quit)
        self.window.bind("<Up>", lambda e: self.scroll_canvas(delta=-1))
        self.window.bind("<Down>", lambda e: self.scroll_canvas(delta=1))
        self.window.bind("<MouseWheel>", lambda e: self.scroll_canvas(delta=-1 if e.delta > 0 else 1))
        self.window.bind("<Configure>", self.resize)

    def draw(self) -> None:
        self.canvas.delete("all")
        scroll_top = int(self.canvas.yview()[0] * self.max_y)
        for x, y, c in self.display_list:
            if y < scroll_top - VSTEP: continue
            if y > scroll_top + self.height + VSTEP: continue
            self.canvas.create_text(x, y, text=c, anchor="nw")

    def load(self, url: URL) -> None:
        if url.url in cache and cache[url.url][1] > datetime.now():
            text = lex(cache[url.url][0])
        else:
            body = url.request()
            if url.scheme == "view-source":
                self.text = body
            else:
                self.text = lex(body)
        self.layout()
        self.draw()

    def scroll_canvas(self, event=None, delta=0):
        self.canvas.yview_scroll(delta, "units")
        self.draw()

    def resize(self, e: tkinter.Event):
        self.width, self.height = e.width, e.height
        self.canvas.config(width=self.width, height=self.height)
        self.layout()
        self.draw()

    def layout(self):
        font = tk_font.Font()
        self.display_list: list[tuple[float, float, str]] = []
        cursor_x, cursor_y = HSTEP, VSTEP
        effective_width = max(self.width - 2 * HSTEP, MIN_WIDTH)
        for word in self.text.split():
            w = font.measure(word)
            if cursor_x + w >= effective_width - HSTEP:
                cursor_y += font.metrics("linespace") * 1.25
                cursor_x = HSTEP
            self.display_list.append((cursor_x, cursor_y, word))
            cursor_x += w + font.measure(" ")
        self.max_y = cursor_y
        self.canvas.configure(scrollregion=(0,0,self.width,self.max_y))


def lex(body: str) -> str:
    text = ""
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
            text += "<"
            i += 4
        elif not in_tag and body[i:i+4] == "&gt;":
            text += ">"
            i += 4
        elif not in_tag:
            text += body[i]
            i += 1
        else:
            i += 1
    return text

if __name__ == "__main__":
    import sys
    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()
