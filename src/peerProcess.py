import sys
from config import loadCommon, loadPeerInfo, findPeerById


def main():
    # Step 1: make sure a peer ID was given
    if len(sys.argv) != 2:
        print("Correct command format: python peerProcess.py <peerId>")
        sys.exit(1)

    # Step 2: convert the command-line argument to an integer
    try:
        peerId = int(sys.argv[1])
    except ValueError:
        print("Error: peerId must be an integer.")
        sys.exit(1)

    # Step 3: read the two config files
    try:
        commonConfig = loadCommon("Common.cfg")
        peerList = loadPeerInfo("PeerInfo.cfg")
    except Exception as e:
        print(f"Error reading config files: {e}")
        sys.exit(1)

    # Step 4: find this peer in PeerInfo.cfg
    myPeer = findPeerById(peerList, peerId)
    if myPeer is None:
        print(f"Error: peer ID {peerId} was not found in PeerInfo.cfg")
        sys.exit(1)

    # Step 5: set up a very basic bitfield
    numPieces = commonConfig["numPieces"]

    if myPeer["hasFile"] == 1:
        bitfield = [1] * numPieces
    else:
        bitfield = [0] * numPieces

    # Step 6: print what we loaded so we know it works
    print("===== peerProcess started =====")
    print(f"My peer ID: {peerId}")
    print(f"My host: {myPeer['hostName']}")
    print(f"My port: {myPeer['port']}")
    print(f"Has complete file: {myPeer['hasFile']}")
    print()
    print("Common.cfg values:")
    print(commonConfig)
    print()
    print("All peers from PeerInfo.cfg:")
    for peer in peerList:
        print(peer)
    print()
    print(f"Number of pieces: {numPieces}")
    print(f"Initial bitfield: {bitfield}")


if __name__ == "__main__":
    main()