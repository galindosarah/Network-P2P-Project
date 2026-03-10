import sys
import socket

from config import loadCommon, loadPeerInfo, findPeerById
from peer import Peer
from pathlib import Path

def startServer(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", port))
    server.listen()

    print(f"Peer listening on port {port}...")

    conn, addr = server.accept()
    print(f"Connection received from {addr}")

    conn.close()
    server.close()


def connectToPeer(host, port):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    print(f"Connecting to {host}:{port}...")

    client.connect((host, port))

    print("Connected successfully!")

    client.close()

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

    if peerId == 1001:
        startServer(currentPeer.port)
    else:
        connectToPeer(currentPeer.hostName, currentPeer.port)


if __name__ == "__main__":
    main()