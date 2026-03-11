import sys
import socket
import struct
import threading
import random

from config import loadCommon, loadPeerInfo, findPeerById
from peer import Peer
from pathlib import Path

# Start server function
def startServer(port, myPeerId, expectedConnections, myBitfield, filePath, pieceSize, fileSize):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", port))
    server.listen()

    print(f"Peer listening on port {port}...")

    for i in range(expectedConnections):
        connection, addr = server.accept()
        print(f"Connection received from {addr}")

        receivedPeerId = readHandshake(connection)
        print(f"Received handshake from peer {receivedPeerId}")

        handshake = createHandshake(myPeerId)
        connection.sendall(handshake)
        print(f"Sent handshake from peer {myPeerId}")

        messageType, payload = readMessage(connection)
        if messageType == 5:
            otherBitfield = payload.decode()
            print(f"Received bitfield from peer {receivedPeerId}: {otherBitfield}")

        sendBitfield(connection, myBitfield)

        if hasInterestingPieces(myBitfield, otherBitfield):
            sendSimpleMessage(connection, 2)
        else:
            sendSimpleMessage(connection, 3)

        messageType, payload = readMessage(connection)
        if messageType == 2:
            print(f"Received INTERESTED from peer {receivedPeerId}")
            sendSimpleMessage(connection, 1)

            messageType, payload = readMessage(connection)
            if messageType == 6:
                requestedPieceIndex = struct.unpack(">I", payload)[0]
                print(f"Received REQUEST for piece {requestedPieceIndex} from peer {receivedPeerId}")

                pieceData = getPieceData(myBitfield, filePath, requestedPieceIndex, pieceSize, fileSize)
                if pieceData is not None:
                    sendPiece(connection, requestedPieceIndex, pieceData)

                    messageType, payload = readMessage(connection)
                    if messageType == 4:
                        havePieceIndex = struct.unpack(">I", payload)[0]
                        print(f"Received HAVE for piece {havePieceIndex} from peer {receivedPeerId}")

                        otherBitfield = updateBitfieldWithHave(otherBitfield, havePieceIndex)
                        print(f"Updated bitfield for peer {receivedPeerId}: {otherBitfield}")

        elif messageType == 3:
            print(f"Received NOT INTERESTED from peer {receivedPeerId}")
            sendSimpleMessage(connection, 0)
        connection.close()

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

def connectToPeer(host, port, myPeerId, myBitfield, filePath, pieceSize):
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

        pieceToRequest = choosePieceToRequest(myBitfield, otherBitfield)

        if pieceToRequest is not None:
            sendRequest(client, pieceToRequest)

            messageType, payload = readMessage(client)
            if messageType == 7:
                pieceIndex = struct.unpack(">I", payload[:4])[0]
                pieceData = payload[4:]

                print(f"Received PIECE {pieceIndex} from peer {receivedPeerId}")
                savePiece(myBitfield, filePath, pieceIndex, pieceSize, pieceData)
                sendHave(client, pieceIndex)

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


# Request function
def sendRequest(sock, pieceIndex):
    messageType = 6
    payload = struct.pack(">I", pieceIndex)
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent REQUEST for piece {pieceIndex}")

# Piece functions

def sendPiece(sock, pieceIndex, pieceData):
    messageType = 7
    payload = struct.pack(">I", pieceIndex) + pieceData
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent PIECE {pieceIndex}")

def getPieceData(bitfield, filePath, pieceIndex, pieceSize, fileSize):
    if bitfield[pieceIndex] == 1:
        return readPieceFromFile(filePath, pieceIndex, pieceSize, fileSize)
    return None


def savePiece(bitfield, filePath, pieceIndex, pieceSize, pieceData):
    bitfield[pieceIndex] = 1
    writePieceToFile(filePath, pieceIndex, pieceSize, pieceData)
    print(f"Saved piece {pieceIndex} to {filePath}")
    
def choosePieceToRequest(myBitfield, otherBitfieldString):
    possiblePieces = []

    for i in range(len(myBitfield)):
        if myBitfield[i] == 0 and otherBitfieldString[i] == "1":
            possiblePieces.append(i)

    if len(possiblePieces) == 0:
        return None

    return random.choice(possiblePieces)

# Have functions
def sendHave(sock, pieceIndex):
    messageType = 4
    payload = struct.pack(">I", pieceIndex)
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent HAVE for piece {pieceIndex}")

def updateBitfieldWithHave(bitfieldString, pieceIndex):
    bitfieldList = list(bitfieldString)
    bitfieldList[pieceIndex] = "1"
    return "".join(bitfieldList)

# Peer folder functions
def createPeerDirectory(peerId):
    peerFolder = Path(str(peerId))
    peerFolder.mkdir(exist_ok=True)
    return peerFolder

def getPeerFilePath(peerId, fileName):
    peerFolder = createPeerDirectory(peerId)
    return peerFolder / fileName

def initializePeerFile(peerId, fileName, fileSize, hasFile):
    filePath = getPeerFilePath(peerId, fileName)

    if hasFile == 1:
        if not filePath.exists():
            print(f"Warning: peer {peerId} should start with the file, but {filePath} does not exist")
    else:
        if not filePath.exists():
            with open(filePath, "wb") as file:
                file.truncate(fileSize)

    return filePath


def getPieceOffset(pieceIndex, pieceSize):
    return pieceIndex * pieceSize


def getPieceLength(pieceIndex, pieceSize, fileSize):
    pieceOffset = getPieceOffset(pieceIndex, pieceSize)
    remainingBytes = fileSize - pieceOffset

    if remainingBytes >= pieceSize:
        return pieceSize
    else:
        return remainingBytes


def readPieceFromFile(filePath, pieceIndex, pieceSize, fileSize):
    pieceOffset = getPieceOffset(pieceIndex, pieceSize)
    pieceLength = getPieceLength(pieceIndex, pieceSize, fileSize)

    with open(filePath, "rb") as file:
        file.seek(pieceOffset)
        return file.read(pieceLength)


def writePieceToFile(filePath, pieceIndex, pieceSize, pieceData):
    pieceOffset = getPieceOffset(pieceIndex, pieceSize)

    with open(filePath, "r+b") as file:
        file.seek(pieceOffset)
        file.write(pieceData)

# Main function
def main():
    if len(sys.argv) != 2:
        print("Correct command format: python peerProcess.py <peerId>")
        sys.exit(1)

    try:
        peerId = int(sys.argv[1])
    except ValueError:
        print("Error: peerId must be an integer")
        sys.exit(1)


    baseDir = Path(".")
    commonCfgPath = baseDir / "Common.cfg"
    peerInfoCfgPath = baseDir / "PeerInfo.cfg"

    if not commonCfgPath.exists():
        print("Common.cfg not found")
        return

    if not peerInfoCfgPath.exists():
        print("PeerInfo.cfg not found")
        return

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

    fileName = commonConfig["FileName"]
    fileSize = commonConfig["FileSize"]
    pieceSize = commonConfig["PieceSize"]

    filePath = initializePeerFile(
        currentPeer.peerId,
        fileName,
        fileSize,
        currentPeer.hasFile
    )

    print(f"My file path: {filePath}")

    print()

    laterPeerCount = getLaterPeerCount(peerList, peerId)

    serverThread = threading.Thread(
        target=startServer,
        args=(
            currentPeer.port, 
            currentPeer.peerId, 
            laterPeerCount, 
            currentPeer.bitfield,
            filePath,
            pieceSize,
            fileSize
        )
    )
    serverThread.start()

    previousPeers = getPreviousPeers(peerList, peerId)

    for peer in previousPeers:
        connectToPeer(
            peer["hostName"], 
            peer["port"], 
            currentPeer.peerId, 
            currentPeer.bitfield,
            filePath,
            pieceSize
        )

    serverThread.join()


if __name__ == "__main__":
    main()