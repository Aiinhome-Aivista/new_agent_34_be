import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from backend.app import create_app
from backend.app.models.source_domain import User, Order, Payment
from backend.app.config import Config
from arango import ArangoClient

def seed_arango_graph():
    print(f"Connecting to ArangoDB at {Config.ARANGO_HOST}...")
    client = ArangoClient(hosts=Config.ARANGO_HOST)
    db = client.db(Config.ARANGO_DB, username=Config.ARANGO_USER, password=Config.ARANGO_PASSWORD)

    # 1. Ensure Named Graph
    graph_name = "FraudNetworkGraph"
    if not db.has_graph(graph_name):
        graph = db.create_graph(graph_name)
    else:
        graph = db.graph(graph_name)

    # 2. Ensure Collections
    v_cols = ["graph_users", "graph_devices", "graph_ips", "graph_merchants"]
    for vc in v_cols:
        if not db.has_collection(vc):
            db.create_collection(vc)

    e_cols = ["used_device", "used_ip", "transacted_with"]
    for ec in e_cols:
        if not db.has_collection(ec):
            db.create_collection(ec, edge=True)

    # 3. Ensure Edge Definitions in Graph
    existing_edges = [e["edge_collection"] for e in graph.edge_definitions()]
    if "used_device" not in existing_edges:
        graph.create_edge_definition(
            edge_collection="used_device",
            from_vertex_collections=["graph_users"],
            to_vertex_collections=["graph_devices"]
        )
    if "used_ip" not in existing_edges:
        graph.create_edge_definition(
            edge_collection="used_ip",
            from_vertex_collections=["graph_users"],
            to_vertex_collections=["graph_ips"]
        )
    if "transacted_with" not in existing_edges:
        graph.create_edge_definition(
            edge_collection="transacted_with",
            from_vertex_collections=["graph_users"],
            to_vertex_collections=["graph_merchants"]
        )

    users_col = db.collection("graph_users")
    devices_col = db.collection("graph_devices")
    ips_col = db.collection("graph_ips")
    merchants_col = db.collection("graph_merchants")
    used_device_col = db.collection("used_device")
    used_ip_col = db.collection("used_ip")
    transacted_with_col = db.collection("transacted_with")

    # 4. Insert Fraud Ring & Cluster Nodes
    users = [
        {"_key": "USR_SYBIL_01", "name": "Rakesh Verma", "risk": "HIGH", "status": "SUSPICIOUS", "label": "Sybil Node 1"},
        {"_key": "USR_SYBIL_02", "name": "Amit Kumar", "risk": "HIGH", "status": "SUSPICIOUS", "label": "Sybil Node 2"},
        {"_key": "USR_SYBIL_03", "name": "Kunal Sen", "risk": "HIGH", "status": "SUSPICIOUS", "label": "Sybil Node 3"},
        {"_key": "USR_LEGIT_01", "name": "Vikram Mehra", "risk": "LOW", "status": "VERIFIED", "label": "Legitimate User"},
        {"_key": "USR_LEGIT_02", "name": "Pooja Banerjee", "risk": "LOW", "status": "VERIFIED", "label": "Legitimate User"},
    ]
    for u in users:
        users_col.insert(u, overwrite=True)

    devices = [
        {"_key": "DEV_EMULATOR_RING_99", "device_type": "Android Emulator Farm", "os": "Android 14", "is_emulator": True},
        {"_key": "DEV_IPHONE_SECURE_12", "device_type": "Apple iPhone 15 Pro", "os": "iOS 17.4", "is_emulator": False},
        {"_key": "DEV_WIN_CHROME_88", "device_type": "Dell XPS Windows 11", "os": "WinNT 10.0", "is_emulator": False},
    ]
    for d in devices:
        devices_col.insert(d, overwrite=True)

    ips = [
        {"_key": "IP_TOR_EXIT_01", "ip": "185.220.101.5", "type": "TOR_EXIT_NODE", "country": "RU", "risk": "CRITICAL"},
        {"_key": "IP_DATACENTER_VPN", "ip": "45.142.120.8", "type": "HOSTING_VPN", "country": "DE", "risk": "HIGH"},
        {"_key": "IP_HOME_BROADBAND", "ip": "103.21.244.12", "type": "RESIDENTIAL", "country": "IN", "risk": "LOW"},
    ]
    for ip in ips:
        ips_col.insert(ip, overwrite=True)

    merchants = [
        {"_key": "MERCH_GIFT_CARDS_99", "name": "Crypto Gift Vouchers Ltd", "category": "HIGH_RISK_DIGITAL", "chargeback_rate": "4.8%"},
        {"_key": "MERCH_GLOBAL_TECH_01", "name": "Global Tech Gadgets", "category": "ELECTRONICS", "chargeback_rate": "0.3%"},
    ]
    for m in merchants:
        merchants_col.insert(m, overwrite=True)

    # 5. Insert Edges (Network Relationship Graph)
    # The 3 Sybil users all share the same Emulator Device and Tor IP -> classic multi-account fraud ring!
    edges_dev = [
        {"_key": "edge_dev_1", "_from": "graph_users/USR_SYBIL_01", "_to": "graph_devices/DEV_EMULATOR_RING_99", "relation": "SHARED_HARDWARE_FINGERPRINT"},
        {"_key": "edge_dev_2", "_from": "graph_users/USR_SYBIL_02", "_to": "graph_devices/DEV_EMULATOR_RING_99", "relation": "SHARED_HARDWARE_FINGERPRINT"},
        {"_key": "edge_dev_3", "_from": "graph_users/USR_SYBIL_03", "_to": "graph_devices/DEV_EMULATOR_RING_99", "relation": "SHARED_HARDWARE_FINGERPRINT"},
        {"_key": "edge_dev_4", "_from": "graph_users/USR_LEGIT_01", "_to": "graph_devices/DEV_IPHONE_SECURE_12", "relation": "PRIMARY_DEVICE"},
        {"_key": "edge_dev_5", "_from": "graph_users/USR_LEGIT_02", "_to": "graph_devices/DEV_WIN_CHROME_88", "relation": "PRIMARY_DEVICE"},
    ]
    for ed in edges_dev:
        used_device_col.insert(ed, overwrite=True)

    edges_ip = [
        {"_key": "edge_ip_1", "_from": "graph_users/USR_SYBIL_01", "_to": "graph_ips/IP_TOR_EXIT_01", "relation": "CONNECTED_VIA"},
        {"_key": "edge_ip_2", "_from": "graph_users/USR_SYBIL_02", "_to": "graph_ips/IP_TOR_EXIT_01", "relation": "CONNECTED_VIA"},
        {"_key": "edge_ip_3", "_from": "graph_users/USR_SYBIL_03", "_to": "graph_ips/IP_DATACENTER_VPN", "relation": "CONNECTED_VIA"},
        {"_key": "edge_ip_4", "_from": "graph_users/USR_LEGIT_01", "_to": "graph_ips/IP_HOME_BROADBAND", "relation": "CONNECTED_VIA"},
    ]
    for ei in edges_ip:
        used_ip_col.insert(ei, overwrite=True)

    edges_mch = [
        {"_key": "edge_mch_1", "_from": "graph_users/USR_SYBIL_01", "_to": "graph_merchants/MERCH_GIFT_CARDS_99", "relation": "HIGH_VELOCITY_PURCHASE", "amount": 45000},
        {"_key": "edge_mch_2", "_from": "graph_users/USR_SYBIL_02", "_to": "graph_merchants/MERCH_GIFT_CARDS_99", "relation": "HIGH_VELOCITY_PURCHASE", "amount": 48500},
        {"_key": "edge_mch_3", "_from": "graph_users/USR_SYBIL_03", "_to": "graph_merchants/MERCH_GIFT_CARDS_99", "relation": "HIGH_VELOCITY_PURCHASE", "amount": 42000},
        {"_key": "edge_mch_4", "_from": "graph_users/USR_LEGIT_01", "_to": "graph_merchants/MERCH_GLOBAL_TECH_01", "relation": "NORMAL_CHECKOUT", "amount": 2500},
    ]
    for em in edges_mch:
        transacted_with_col.insert(em, overwrite=True)

    print("✔ Successfully populated ArangoDB Named Graph 'FraudNetworkGraph'!")
    print(f"  - Users: {users_col.count()} vertices")
    print(f"  - Devices: {devices_col.count()} vertices")
    print(f"  - IP Addresses: {ips_col.count()} vertices")
    print(f"  - Merchants: {merchants_col.count()} vertices")
    print(f"  - Device Edges: {used_device_col.count()}")
    print(f"  - IP Edges: {used_ip_col.count()}")
    print(f"  - Merchant Edges: {transacted_with_col.count()}")

if __name__ == "__main__":
    seed_arango_graph()
