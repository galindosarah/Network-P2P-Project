# config.py

import math


def load_common_cfg(filename):
    config = {}

    with open(filename, "r") as file:
        for line in file:
            line = line.strip()
            if line == "":
                continue

            parts = line.split()
            key = parts[0]
            value = parts[1]

            config[key] = value

    common = {
        "NumberOfPreferredNeighbors": int(config["NumberOfPreferredNeighbors"]),
        "UnchokingInterval": int(config["UnchokingInterval"]),
        "OptimisticUnchokingInterval": int(config["OptimisticUnchokingInterval"]),
        "FileName": config["FileName"],
        "FileSize": int(config["FileSize"]),
        "PieceSize": int(config["PieceSize"]),
    }

    common["num_pieces"] = math.ceil(common["FileSize"] / common["PieceSize"])

    return common


def load_peer_info_cfg(filename):
    peers = []

    with open(filename, "r") as file:
        for line in file:
            line = line.strip()
            if line == "":
                continue

            parts = line.split()

            peer = {
                "peer_id": int(parts[0]),
                "host_name": parts[1],
                "port": int(parts[2]),
                "has_file": int(parts[3]),
            }

            peers.append(peer)

    return peers


def find_peer_by_id(peer_list, peer_id):
    for peer in peer_list:
        if peer["peer_id"] == peer_id:
            return peer
    return None