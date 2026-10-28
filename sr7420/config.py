"""Change exactly four fields, retaining the original XML text elsewhere."""
import re
import xml.etree.ElementTree as ET

from .codec import require

MODEL = "ZXSLC SR7420"
FIRMWARE = "V1.0.0.2B4.8000"


def parse(xml):
    require(b"<!DOCTYPE" not in xml.upper() and b"<!ENTITY" not in xml.upper(), "XML entities are not supported")
    return ET.fromstring(xml)


def table(tree, name):
    matches = [t for t in tree.iter("Tbl") if t.get("name") == name]
    require(len(matches) == 1, "Expected one configuration table: " + name)
    return matches[0]


def fields(row):
    nodes = list(row)
    result = {n.get("name"): n.get("val") for n in nodes}
    require(len(nodes) == len(result), "Duplicate configuration field")
    return result


def one_row(tree, name):
    rows = table(tree, name).findall("Row")
    require(len(rows) == 1, "Expected one row in " + name)
    return fields(rows[0])


def patch(xml, password):
    require(re.fullmatch(r"[A-Za-z0-9_-]{24,64}", password) is not None, "Unsupported password format")
    original = parse(xml)
    telnet = one_row(original, "TelnetCfg")
    require(telnet.get("TS_UName") == "root" and telnet.get("TS_Port") == "23", "Unexpected Telnet account/port")
    require(all(telnet.get(k) == "0" for k in ("TS_Enable", "Lan_Enable", "Wan_Enable")),
            "Expected disabled LAN/WAN Telnet; refusing to overwrite an existing setup")
    firewall = one_row(original, "FWLevel")
    require(all(firewall.get(k) == "1" for k in ("Enable", "Ipv4Enable", "Ipv6Enable"))
            and firewall.get("Ipv4Level") == firewall.get("Ipv6Level") == "High",
            "Keep both IPv4/IPv6 firewalls enabled at High before preparing this candidate")
    ports = [r for r in table(original, "PortControl").findall("Row") if fields(r).get("ServName") == "TELNET"]
    require(len(ports) == 1, "Expected one TELNET port-control row")
    port = fields(ports[0])
    require(port.get("PortValue") == "23" and port.get("ServIPMode") == "0"
            and port.get("PortEnable") == "0" and port.get("PortLANEnable") == "1",
            "Unexpected TELNET port policy; review manually")
    text = xml.decode("utf-8")

    def change(text, table_name, updates, selector=None):
        pattern = r'(<Tbl\b[^>]*\bname="' + re.escape(table_name) + r'"[^>]*>)(.*?)(</Tbl>)'
        matches = list(re.finditer(pattern, text, re.S))
        require(len(matches) == 1, "Unsupported XML table formatting")
        match = matches[0]
        block = match.group(2)
        if selector:
            candidates = [r for r in re.finditer(r"<Row\b[^>]*>.*?</Row>", block, re.S) if selector in r.group()]
            require(len(candidates) == 1, "Cannot identify TELNET row")
            selected = candidates[0]
            work = selected.group()
        else:
            work = block
        for field, value in updates.items():
            field_pattern = r'(<DM\b[^>]*\bname="' + re.escape(field) + r'"[^>]*\bval=")[^"]*(")'
            work, count = re.subn(field_pattern, lambda m: m.group(1) + value + m.group(2), work)
            require(count == 1, "Unsupported XML field formatting: " + field)
        if selector:
            block = block[:selected.start()] + work + block[selected.end():]
        else:
            block = work
        return text[:match.start(2)] + block + text[match.end(2):]

    text = change(text, "TelnetCfg", {"TS_Enable": "1", "Lan_Enable": "1", "TS_UPwd": password})
    text = change(text, "PortControl", {"ServIPMode": "1"}, 'name="ServName" val="TELNET"')
    result = text.encode("utf-8")
    updated = parse(result)
    expected = {("TelnetCfg", "TS_Enable"), ("TelnetCfg", "Lan_Enable"),
                ("TelnetCfg", "TS_UPwd"), ("PortControl", "ServIPMode")}
    actual = []
    original_tables, updated_tables = list(original.iter("Tbl")), list(updated.iter("Tbl"))
    require(len(original_tables) == len(updated_tables), "Table count changed")
    for a, b in zip(original_tables, updated_tables):
        require(a.attrib == b.attrib, "Table metadata changed")
        old_rows, new_rows = a.findall("Row"), b.findall("Row")
        require(len(old_rows) == len(new_rows), "Row count changed")
        for row_number, (old_row, new_row) in enumerate(zip(old_rows, new_rows)):
            require(old_row.attrib == new_row.attrib, "Row metadata changed")
            old, new = fields(old_row), fields(new_row)
            require(old.keys() == new.keys(), "Field set changed")
            for name, value in old.items():
                if value != new[name]:
                    actual.append({"table": a.get("name"), "row": row_number, "field": name})
    require(len(actual) == 4 and {(x["table"], x["field"]) for x in actual} == expected, "Unexpected configuration changes")
    require(one_row(updated, "TelnetCfg")["Wan_Enable"] == "0", "WAN Telnet must remain disabled")
    return result, actual
