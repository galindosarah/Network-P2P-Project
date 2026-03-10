import sys
import socket
import struct
import threading

from config import loadCommon, loadPeerInfo, findPeerById
from peer import Peer
from pathlib import Path

# Start server function
def startServer(port, myPeerId, expectedConnections, myBitfield):
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

        messageType, payload = readMessage(conn)
        if messageType == 5:
            otherBitfield = payload.decode()
            print(f"Received bitfield from peer {receivedPeerId}: {otherBitfield}")

        sendBitfield(conn, myBitfield)

        if hasInterestingPieces(myBitfield, otherBitfield):
            sendSimpleMessage(conn, 2)
        else:
            sendSimpleMessage(conn, 3)

        messageType, payload = readMessage(conn)
        if messageType == 2:
            print(f"Received INTERESTED from peer {receivedPeerId}")
            sendUnchoke(conn)
        elif messageType == 3:
            print(f"Received NOT INTERESTED from peer {receivedPeerId}")
            sendChoke(conn)

        conn.close()

    server.close()


# Peer connection functions
def getPreviousPeers(peerList, peerId):
    previousPeers = []

    for peer in peerList:
        if peer["peerId"] == peerId:
            break
        previousPeers.append(peer)

    return previousPeers

def getLaterPeerCount(peerList, peerId):
    count = 0
    found = False

    for peer in peerList:
        if found:
            count += 1
        if peer["peerId"] == peerId:
            found = True

    return count

def connectToPeer(host, port, myPeerId, myBitfield):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    print(f"Connecting to {host}:{port}...")
    client.connect((host, port))
    print("Connected successfully!")

    handshake = createHandshake(myPeerId)
    client.sendall(handshake)
    print(f"Sent handshake from peer {myPeerId}")

    receivedPeerId = readHandshake(client)
    print(f"Received handshake from peer {receivedPeerId}")

    sendBitfield(client, myBitfield)

    # bitfield messaging
    messageType, payload = readMessage(client)
    if messageType == 5:
        otherBitfield = payload.decode()
        print(f"Received bitfield from peer {receivedPeerId}: {otherBitfield}")

    if hasInterestingPieces(myBitfield, otherBitfield):
        sendSimpleMessage(client, 2)
    else:
        sendSimpleMessage(client, 3)

    # interested/not interested messaging
    messageType, payload = readMessage(client)
    if messageType == 2:
        print(f"Received INTERESTED from peer {receivedPeerId}")
    elif messageType == 3:
        print(f"Received NOT INTERESTED from peer {receivedPeerId}")

    # choke/unchoke messaging 
    messageType, payload = readMessage(client)
    if messageType == 0:
        print(f"Received CHOKE from peer {receivedPeerId}")
    elif messageType == 1:
        print(f"Received UNCHOKE from peer {receivedPeerId}")


    client.close()

# Handshake functions
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

# Bitfield functions
def sendBitfield(sock, bitfield):
    bitfieldString = "".join(str(bit) for bit in bitfield)
    payload = bitfieldString.encode()

    messageType = 5
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent bitfield: {bitfieldString}")


def readMessage(sock):
    messageLengthBytes = sock.recv(4)
    if len(messageLengthBytes) != 4:
        print("Error: could not read message length")
        return None, None

    messageLength = struct.unpack(">I", messageLengthBytes)[0]

    messageTypeBytes = sock.recv(1)
    if len(messageTypeBytes) != 1:
        print("Error: could not read message type")
        return None, None

    messageType = struct.unpack(">B", messageTypeBytes)[0]

    payloadLength = messageLength - 1
    payload = sock.recv(payloadLength)

    if len(payload) != payloadLength:
        print("Error: could not read full payload")
        return None, None

    return messageType, payload


# Interested/Not Interested functions
def hasInterestingPieces(myBitfield, otherBitfieldString):
    for i in range(len(myBitfield)):
        if myBitfield[i] == 0 and otherBitfieldString[i] == "1":
            return True
    return False


def sendSimpleMessage(sock, messageType):
    messageLength = 1
    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    sock.sendall(message)

    if messageType == 0:
        print("Sent CHOKE message")
    elif messageType == 1:
        print("Sent UNCHOKE message")
    elif messageType == 2:
        print("Sent INTERESTED message")
    elif messageType == 3:
        print("Sent NOT INTERESTED message")


# Choke/Unchoke functions
def sendChoke(sock):
    messageLength = 1
    messageType = 0

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)

    sock.sendall(message)
    print("Sent CHOKE message")


def sendUnchoke(sock):
    messageLength = 1
    messageType = 1

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)

    sock.sendall(message)
    print("Sent UNCHOKE message")

# Main function
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
        bitfield
    )
    
    currentPeer.printInfo()

    print()

    laterPeerCount = getLaterPeerCount(peerList, peerId)

    serverThread = threading.Thread(
        target=startServer,
        args=(
            currentPeer.port, 
            currentPeer.peerId, 
            laterPeerCount, 
            currentPeer.bitfield
        )
    )
    serverThread.start()

    previousPeers = getPreviousPeers(peerList, peerId)

    for peer in previousPeers:
        connectToPeer(
            peer["hostName"], 
            peer["port"], 
            currentPeer.peerId, 
            currentPeer.bitfield
        )

    serverThread.join()


if __name__ == "__main__":
    main()