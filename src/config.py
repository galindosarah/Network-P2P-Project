import math

def loadCommon(filename):
    common = {}

    with open(filename, "r") as file:
        for line in file:
            # line = line.strip()
            columns = line.split()
            key = columns[0]
            value = columns[1]

            common[key] = value

    # common = {
    #     "NumberOfPreferredNeighbors": int(config["NumberOfPreferredNeighbors"]),
    #     "UnchokingInterval": int(config["UnchokingInterval"]),
    #     "OptimisticUnchokingInterval": int(config["OptimisticUnchokingInterval"]),
    #     "FileName": config["FileName"],
    #     "FileSize": int(config["FileSize"]),
    #     "PieceSize": int(config["PieceSize"]),
    # }

    common["numPieces"] = math.ceil(common["FileSize"] / common["PieceSize"])
    print(common)
    return common


def loadPeerInfo(filename):
    peers = []

    with open(filename, "r") as file:
        for line in file:
            # line = line.strip()
            # if line == "":
            #     continue

            columns = line.split()

            peer = {
                "peerId": int(columns[0]),
                "hostName": columns[1],
                "port": int(columns[2]),
                "hasFile": int(columns[3]),
            }

            peers.append(peer)
    print(peers)
    return peers


def findPeerById(peerList, peerId):
    for peer in peerList:
        if peer["peerId"] == peerId:
            return peer
    return None