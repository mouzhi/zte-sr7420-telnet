"""Documented-by-inspection admin login and read-only backup flow. No restore API."""
import hashlib
import http.client
from http.cookies import SimpleCookie
import ipaddress
import json
import secrets
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from .codec import LIMIT, require
from .config import parse


def lan_host(host):
    address = ipaddress.ip_address(host)
    private = address.version == 4 and any(address in ipaddress.ip_network(net)
                for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"))
    require(private
            and not address.is_unspecified and not address.is_multicast,
            "Only a numeric LAN IPv4 address is supported")
    return str(address)


class Router:
    def __init__(self, host, port=80):
        self.host = lan_host(host)
        self.connection = http.client.HTTPConnection(self.host, port, timeout=15)
        self.origin = "http://" + self.host + (f":{port}" if port != 80 else "")
        self.cookies = {}
        self.token = None

    def close(self):
        self.connection.close()

    def request(self, path, form=None, body=None, content_type=None):
        require(path.startswith("/?") or path == "/", "Unexpected request path")
        headers = {"User-Agent": "Mozilla/5.0", "Origin": self.origin,
                   "Referer": self.origin + "/", "Connection": "keep-alive"}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in self.cookies.items())
        if form is not None:
            form = dict(form)
            if self.token:
                form.setdefault("_sessionTOKEN", self.token)
            body = urlencode(form).encode()
            content_type = "application/x-www-form-urlencoded"
        if content_type:
            headers["Content-Type"] = content_type
        self.connection.request("POST" if body is not None else "GET", path, body=body, headers=headers)
        response = self.connection.getresponse()
        require(response.status == 200, f"Router returned HTTP {response.status}; no automatic retry")
        length = response.getheader("Content-Length")
        require(length is not None and length.isdigit() and int(length) <= LIMIT, "Invalid response length")
        data = response.read(int(length) + 1)
        require(len(data) == int(length), "Incomplete router response; discard this backup")
        for name, value in response.getheaders():
            if name.lower() == "set-cookie":
                cookie = SimpleCookie(value)
                self.cookies.update({key: item.value for key, item in cookie.items()})
            elif name.lower() == "x_xsrf_token":
                self.token = value
        require(b"<IF_ERRORSTR>SessionTimeout</IF_ERRORSTR>" not in data, "Router session expired")
        return data

    def login(self, password):
        self.request("/")
        info = json.loads(self.request("/?_type=loginsceneData&_tag=login_token_json"))
        self.token = info["_sessionToken"]
        digest = hashlib.sha256((password + info["logintoken"]).encode()).hexdigest()
        reply = json.loads(self.request("/?_type=loginData&_tag=login_entry", form={
            "Username": "admin", "Password": digest, "action": "login",
            "Frm_Logintoken": "", "captchaCode": ""}))
        require(reply.get("login_need_refresh") is True, "Admin login not confirmed; no automatic retries")
        self.token = reply["sess_token"]

    def identity(self):
        tree = parse(self.request("/?_type=vueData&_tag=security_globalctl_data"))
        fields = {}
        for obj in tree.iter("OBJ_GLOBAL_ENV"):
            for row in obj.iter("Instance"):
                fields.update(zip([n.text for n in row.findall("ParaName")],
                                  [n.text for n in row.findall("ParaValue")]))
        return {"model": fields.get("WEBTitle"), "firmware": fields.get("SoftwareVer")}

    def backup(self):
        # This POST prepares an export; it is not a configuration restore.
        tree = ET.fromstring(self.request("/?_type=vueData&_tag=vue_loadprevent_data",
                                        form={"sessToken": self.token}))
        require(any(n.text == "SUCC" for n in tree.iter("IF_ERRORSTR")), "Backup preparation failed")
        boundary = "----OwnerRouterBackup" + secrets.token_hex(8)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="config"\r\n\r\n'
                f'\r\n--{boundary}--\r\n').encode()
        return self.request("/?_type=vueData&_tag=do_download_usercfg", body=body,
                            content_type="multipart/form-data; boundary=" + boundary)
