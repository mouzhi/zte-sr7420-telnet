"""Invented minimal XML, NOT an export from a real router."""
def synthetic_xml():
    tables = {
        "TelnetCfg": [{"TS_Enable": "0", "Lan_Enable": "0", "Wan_Enable": "0", "TS_Port": "23",
                       "TS_UName": "root", "TS_UPwd": "synthetic-old-value"}],
        "PortControl": [{"ServName": "TELNET", "PortValue": "23", "ServIPMode": "0",
                         "PortEnable": "0", "PortLANEnable": "1"}],
        "FWLevel": [{"Enable": "1", "Ipv4Enable": "1", "Ipv6Enable": "1",
                     "Ipv4Level": "High", "Ipv6Level": "High"}],
        "UnrelatedExample": [{"Example": "KEEP_THIS_SYNTHETIC_VALUE"}],
    }
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<Config>"]
    for name, rows in tables.items():
        parts.append(f'<Tbl name="{name}" RowCount="{len(rows)}">')
        for i, fields in enumerate(rows):
            parts.append(f'<Row No="{i}">')
            parts.extend(f'<DM name="{k}" val="{v}"/>' for k, v in fields.items())
            parts.append("</Row>")
        parts.append("</Tbl>")
    parts.append("</Config>")
    return "\n".join(parts).encode()
