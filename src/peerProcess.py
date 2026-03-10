import sys
import socket
import struct
import threading

from config import loadCommon, loadPeerInfo, findPeerById
from peer import Peer
from pathlib import Path

def startServer(port, myPeerId, expectedConnections):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", port))
    server.listen()

    print(f"Peer listening on port {port}...")

    for i in range(expectedConnections):
        conn, addr = server.accept()
        print(f"Connection received from {addr}")

        receivedPeerId = readHandshake(conn)
        print(f"Received handshake from peer {receivedPeerId}")

        handshake = createHandshake(myPeerId)
        conn.sendall(handshake)
        print(f"Sent handshake from peer {myPeerId}")

        conn.close()

    server.close()

def getPreviousPeers(peerList, peerId):
    previousPeers = []

    for peer in peerList:
        if peer["peerId"] == peerId:
            break
        previousPeers.append(peer)

    return previousPeers

def getLaterPeerCount(peerList, peerId):
    count = 0
    foundMe = False

    for peer in peerList:
        if foundMe:
            count += 1
        if peer["peerId"] == peerId:
            foundMe = True

    return count

def connectToPeer(host, port, myPeerId):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    print(f"Connecting to {host}:{port}...")
    client.connect((host, port))
    print("Connected successfully!")

    handshake = createHandshake(myPeerId)
    client.sendall(handshake)
    print(f"Sent handshake from peer {myPeerId}")

    receivedPeerId = readHandshake(client)
    print(f"Received handshake from peer {receivedPeerId}")

    client.close()

def createHandshake(peerId):
    header = b"P2PFILESHARINGPROJ"
    zeroBits = b'\x00' * 10
    peerIdBytes = struct.pack(">I", peerId)
    return header + zeroBits + peerIdBytes


def readHandshake(sock):
    data = sock.recv(32)

    if len(data) != 32:
        print("Error: handshake was not 32 bytes")
        return None

    header = data[:18]
    zeroBits = data[18:28]
    peerIdBytes = data[28:32]

    if header != b"P2PFILESHARINGPROJ":
        print("Error: invalid handshake header")
        return None

    if zeroBits != b'\x00' * 10:
        print("Error: invalid zero bits")
        return None

    peerId = struct.unpack(">I", peerIdBytes)[0]
    return peerId

def main():
    if len(sys.argv) != 2:
        print("Correct command format: python peerProcess.py <peerId>")
        sys.exit(1)

    try:
        peerId = int(sys.argv[1])
    except ValueError:
        print("Error: peerId must be an integer.")
        sys.exit(1)


    baseDir = Path(".")
    commonCfgPath = baseDir / "Common.cfg"
    peerInfoCfgPath = baseDir / "PeerInfo.cfg"

    try:
        commonConfig = loadCommon(commonCfgPath)
        peerList = loadPeerInfo(peerInfoCfgPath)
    except Exception as e:
        print(f"Error reading config files: {e}")
        sys.exit(1)

    myPeer = findPeerById(peerList, peerId)
    if myPeer is None:
        print(f"Error: peer ID {peerId} was not found in PeerInfo.cfg")
        sys.exit(1)

    numPieces = commonConfig["numPieces"]

    if myPeer["hasFile"] == 1:
        bitfield = [1] * numPieces
    else:
        bitfield = [0] * numPieces

    currentPeer = Peer(
        myPeer["peerId"], 
        myPeer["hostName"], 
        myPeer["port"], 
        myPeer["hasFile"], 
        bitfield)
    currentPeer.printInfo()

    print()

    laterPeerCount = getLaterPeerCount(peerList, peerId)

    serverThread = threading.Thread(
    target=startServer,
    args=(currentPeer.port, currentPeer.peerId, laterPeerCount)
    )
    serverThread.start()

    previousPeers = getPreviousPeers(peerList, peerId)

    for peer in previousPeers:
        connectToPeer(peer["hostName"], peer["port"], currentPeer.peerId)

    serverThread.join()


if __name__ == "__main__":
    main()