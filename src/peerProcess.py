import sys
from config import loadCommon, loadPeerInfo, findPeerById
from peer import Peer
from pathlib import Path


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

    currentPeer = Peer(peerId, myPeer["hostName"], myPeer["port"], myPeer["hasFile"], bitfield)
    currentPeer.printInfo()


if __name__ == "__main__":
    main()