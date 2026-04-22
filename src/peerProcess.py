import sys
import socket
import struct
import threading
import random

from config import loadCommon, loadPeerInfo, findPeerById
from peer import Peer
from pathlib import Path
from datetime import datetime

# Global dictionary
neighborBitfields = {}
neighborBitfieldsLock = threading.Lock()

completedPeers = set()
completedPeersLock = threading.Lock()
shutdownEvent = threading.Event()

preferredNeighbors = set()
preferredNeighborsLock = threading.Lock()
connectedPeers = set()
connectedPeersLock = threading.Lock()

peerSockets = {}
peerSocketsLock = threading.Lock()

peerChokeStatus = {}
peerChokeStatusLock = threading.Lock()

# Start server function
def startServer(port, myPeerId, expectedConnections, myBitfield, filePath, pieceSize, fileSize, totalPeerCount, peerList):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", port))
    server.listen()

    print(f"Peer listening on port {port}...")

    for i in range(expectedConnections):
        if shutdownEvent.is_set():
            break

        connection, addr = server.accept()
        print(f"Connection received from {addr}")

        receivedPeerId = readHandshake(connection)
        print(f"Received handshake from peer {receivedPeerId}")
        writeLog(myPeerId, f"is connected from Peer {receivedPeerId}.")

        addConnectedPeer(receivedPeerId)
        storePeerSocket(receivedPeerId, connection)
        setPeerChokeStatus(receivedPeerId, True)
        applyPreferredNeighborChoking(myPeerId)

        handshake = createHandshake(myPeerId)
        connection.sendall(handshake)
        print(f"Sent handshake from peer {myPeerId}")

        # Receive neighbor bitfield
        messageType, payload = readMessage(connection)
        if messageType != 5:
            print("Expected BITFIELD message")
            cleanupPeerConnection(receivedPeerId)
            connection.close()
            continue

        otherBitfield = payload.decode()
        storeNeighborBitfield(receivedPeerId, otherBitfield)
        print(f"Received bitfield from peer {receivedPeerId}: {otherBitfield}")

        if "0" not in otherBitfield and not isPeerCompleted(receivedPeerId):
            markPeerCompleted(receivedPeerId)

        if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
            cleanupPeerConnection(receivedPeerId)
            connection.close()
            return

        sendBitfield(connection, myBitfield)

        # Send interested / not interested
        if hasInterestingPieces(myBitfield, otherBitfield):
            sendSimpleMessage(connection, 2)
        else:
            sendSimpleMessage(connection, 3)

        # Receive neighbor interested / not interested
        messageType, payload = readMessage(connection)
        if messageType == 2:
            print(f"Received INTERESTED from peer {receivedPeerId}")
            writeLog(myPeerId, f"received the 'interested' message from Peer {receivedPeerId}.")

            currentPreferred = getPreferredNeighbors()

            if receivedPeerId in currentPreferred or len(currentPreferred) == 0:
                sendSimpleMessage(connection, 1)
                setPeerChokeStatus(receivedPeerId, False)
            else:
                sendSimpleMessage(connection, 0)
                setPeerChokeStatus(receivedPeerId, True)
                cleanupPeerConnection(receivedPeerId)
                connection.close()
                continue
        elif messageType == 3:
            print(f"Received NOT INTERESTED from peer {receivedPeerId}")
            writeLog(myPeerId, f"received the 'not interested' message from Peer {receivedPeerId}.")            
            sendSimpleMessage(connection, 0)
            cleanupPeerConnection(receivedPeerId)
            connection.close()
            continue
        else:
            print("Expected INTERESTED or NOT INTERESTED message")
            cleanupPeerConnection(receivedPeerId)
            connection.close()
            continue

        # Keep serving requests on this same connection
        while True:
            if shutdownEvent.is_set():
                break

            messageType, payload = readMessage(connection)

            if messageType is None:
                break

            if messageType == 6:
                requestedPieceIndex = struct.unpack(">I", payload)[0]
                print(f"Received REQUEST for piece {requestedPieceIndex} from peer {receivedPeerId}")

                pieceData = getPieceData(myBitfield, filePath, requestedPieceIndex, pieceSize, fileSize)
                if pieceData is not None:
                    sendPiece(connection, requestedPieceIndex, pieceData)

            elif messageType == 4:
                havePieceIndex = struct.unpack(">I", payload)[0]
                print(f"Received HAVE for piece {havePieceIndex} from peer {receivedPeerId}")
                writeLog(myPeerId, f"received the 'have' message from Peer {receivedPeerId} for the piece {havePieceIndex}.")

                updatedBitfield = updateNeighborBitfieldWithHave(receivedPeerId, havePieceIndex)
                print(f"Updated bitfield for peer {receivedPeerId}: {updatedBitfield}")

                if updatedBitfield is not None and "0" not in updatedBitfield:
                    if not isPeerCompleted(receivedPeerId):
                        markPeerCompleted(receivedPeerId)
                        print(f"Peer {receivedPeerId} has completed the file.")

                if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
                    break

            elif messageType == 3:
                print(f"Received NOT INTERESTED from peer {receivedPeerId}")
                writeLog(myPeerId, f"received the 'not interested' message from Peer {receivedPeerId}.")

                if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
                    break

                break

            else:
                print(f"Received unexpected message type {messageType} from peer {receivedPeerId}")
                break

        cleanupPeerConnection(receivedPeerId)           
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

def connectToPeer(host, port, myPeerId, myBitfield, filePath, pieceSize, totalPeerCount, peerList):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    print(f"Connecting to {host}:{port}...")
    client.connect((host, port))
    print("Connected successfully!")

    handshake = createHandshake(myPeerId)
    client.sendall(handshake)
    print(f"Sent handshake from peer {myPeerId}")

    receivedPeerId = readHandshake(client)
    print(f"Received handshake from peer {receivedPeerId}")
    writeLog(myPeerId, f"makes a connection to Peer {receivedPeerId}.")

    addConnectedPeer(receivedPeerId)
    storePeerSocket(receivedPeerId, client)
    setPeerChokeStatus(receivedPeerId, True)
    
    sendBitfield(client, myBitfield)

    # Receive neighbor bitfield
    messageType, payload = readMessage(client)
    if messageType != 5:
        print("Expected BITFIELD message")
        client.close()
        return

    otherBitfield = payload.decode()
    storeNeighborBitfield(receivedPeerId, otherBitfield)
    print(f"Received bitfield from peer {receivedPeerId}: {otherBitfield}")

    if "0" not in otherBitfield and not isPeerCompleted(receivedPeerId):
        markPeerCompleted(receivedPeerId)
        print(f"Completed peers: {getCompletedPeerCount()} / {totalPeerCount}")

    if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
        cleanupPeerConnection(receivedPeerId)
        client.close()
        return

    # Send interested / not interested
    if hasInterestingPieces(myBitfield, otherBitfield):
        sendSimpleMessage(client, 2)
    else:
        sendSimpleMessage(client, 3)

    # Receive neighbor interested / not interested
    messageType, payload = readMessage(client)
    if messageType == 2:
        print(f"Received INTERESTED from peer {receivedPeerId}")
        writeLog(myPeerId, f"received the 'interested' message from Peer {receivedPeerId}.")
    elif messageType == 3:
        print(f"Received NOT INTERESTED from peer {receivedPeerId}")
        writeLog(myPeerId, f"received the 'not interested' message from Peer {receivedPeerId}.")
    
    # Receive choke / unchoke
    messageType, payload = readMessage(client)
    if messageType == 0:
        print(f"Received CHOKE from peer {receivedPeerId}")
        writeLog(myPeerId, f"is choked by Peer {receivedPeerId}.")
        setPeerChokeStatus(receivedPeerId, True)
        cleanupPeerConnection(receivedPeerId)
        client.close()
        return
    elif messageType != 1:
        print("Expected CHOKE or UNCHOKE message")
        cleanupPeerConnection(receivedPeerId)
        client.close()
        return

    print(f"Received UNCHOKE from peer {receivedPeerId}")
    writeLog(myPeerId, f"is unchoked by Peer {receivedPeerId}.")
    setPeerChokeStatus(receivedPeerId, False)

    # Keep requesting pieces until this neighbor has nothing else useful
    while True:
        if shutdownEvent.is_set():
            break

        otherBitfield = getNeighborBitfield(receivedPeerId)
        if otherBitfield is None:
            print(f"No stored bitfield for peer {receivedPeerId}")
            break

        pieceToRequest = choosePieceToRequest(myBitfield, otherBitfield)

        if pieceToRequest is None:
            print(f"No more interesting pieces from peer {receivedPeerId}")
            sendSimpleMessage(client, 3)
            break

        sendRequest(client, pieceToRequest)

        messageType, payload = readMessage(client)
        if messageType != 7:
            print("Expected PIECE message")
            break

        pieceIndex = struct.unpack(">I", payload[:4])[0]
        pieceData = payload[4:]

        print(f"Received PIECE {pieceIndex} from peer {receivedPeerId}")
        savePiece(myBitfield, filePath, pieceIndex, pieceSize, pieceData)

        pieceCount = sum(myBitfield)
        writeLog(
            myPeerId,
            f"has downloaded the piece {pieceIndex} from Peer {receivedPeerId}. "
            f"Now the number of pieces it has is {pieceCount}."
        )

        sendHave(client, pieceIndex)

        if all(myBitfield) and not isPeerCompleted(myPeerId):
            markPeerCompleted(myPeerId)
            writeLog(myPeerId, "has downloaded the complete file.")

            if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
                break

        if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
            break

        if not hasInterestingPieces(myBitfield, otherBitfield):
            sendSimpleMessage(client, 3)
            break

    cleanupPeerConnection(receivedPeerId)
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

def storeNeighborBitfield(peerId, bitfieldString):
    with neighborBitfieldsLock:
        neighborBitfields[peerId] = bitfieldString


def getNeighborBitfield(peerId):
    with neighborBitfieldsLock:
        return neighborBitfields.get(peerId)


def updateNeighborBitfieldWithHave(peerId, pieceIndex):
    with neighborBitfieldsLock:
        if peerId in neighborBitfields:
            bitfieldList = list(neighborBitfields[peerId])
            bitfieldList[pieceIndex] = "1"
            neighborBitfields[peerId] = "".join(bitfieldList)
            return neighborBitfields[peerId]
        return None

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

# def updateBitfieldWithHave(bitfieldString, pieceIndex):
#     bitfieldList = list(bitfieldString)
#     bitfieldList[pieceIndex] = "1"
#     return "".join(bitfieldList)

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

def getLogFilePath(peerId):
    return Path(f"log_peer_{peerId}.log")

def writeLog(peerId, message):
    logFilePath = getLogFilePath(peerId)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logLine = f"[{timestamp}] Peer {peerId} {message}\n"

    with open(logFilePath, "a") as logFile:
        logFile.write(logLine)

def clearLogFile(peerId):
    logFilePath = getLogFilePath(peerId)
    with open(logFilePath, "w") as logFile:
        pass

def markPeerCompleted(peerId):
    with completedPeersLock:
        completedPeers.add(peerId)

def isPeerCompleted(peerId):
    with completedPeersLock:
        return peerId in completedPeers

def getCompletedPeerCount():
    with completedPeersLock:
        return len(completedPeers)

def allPeersCompleted(totalPeerCount):
    with completedPeersLock:
        return len(completedPeers) == totalPeerCount
    
def addConnectedPeer(peerId):
    with connectedPeersLock:
        connectedPeers.add(peerId)

def getConnectedPeers():
    with connectedPeersLock:
        return list(connectedPeers)
    
def removeConnectedPeer(peerId):
    with connectedPeersLock:
        connectedPeers.discard(peerId)

def cleanupPeerConnection(peerId):
    removePeerSocket(peerId)
    removeConnectedPeer(peerId)

    with peerChokeStatusLock:
        if peerId in peerChokeStatus:
            del peerChokeStatus[peerId]

def setPreferredNeighbors(peerIds):
    with preferredNeighborsLock:
        preferredNeighbors.clear()
        preferredNeighbors.update(peerIds)

def getPreferredNeighbors():
    with preferredNeighborsLock:
        return set(preferredNeighbors)

def runPreferredNeighborSelection(myPeerId, numberOfPreferredNeighbors, unchokingInterval):
    while not shutdownEvent.is_set():
        shutdownEvent.wait(unchokingInterval)
        if shutdownEvent.is_set():
            break

        connected = getConnectedPeers()

        if len(connected) == 0:
            continue

        if len(connected) <= numberOfPreferredNeighbors:
            chosenNeighbors = connected
        else:
            chosenNeighbors = random.sample(connected, numberOfPreferredNeighbors)

        setPreferredNeighbors(chosenNeighbors)

        neighborListString = ", ".join(str(peerId) for peerId in sorted(chosenNeighbors))
        print(f"Preferred neighbors for peer {myPeerId}: {neighborListString}")
        writeLog(myPeerId, f"has the preferred neighbors {neighborListString}.")

        applyPreferredNeighborChoking(myPeerId)

def storePeerSocket(peerId, sock):
    with peerSocketsLock:
        peerSockets[peerId] = sock


def removePeerSocket(peerId):
    with peerSocketsLock:
        if peerId in peerSockets:
            del peerSockets[peerId]


def getPeerSocket(peerId):
    with peerSocketsLock:
        return peerSockets.get(peerId)


def setPeerChokeStatus(peerId, isChoked):
    with peerChokeStatusLock:
        peerChokeStatus[peerId] = isChoked


def getPeerChokeStatus(peerId):
    with peerChokeStatusLock:
        return peerChokeStatus.get(peerId, True)

def applyPreferredNeighborChoking(myPeerId):
    currentPreferred = getPreferredNeighbors()
    connected = getConnectedPeers()

    for peerId in connected:
        sock = getPeerSocket(peerId)
        if sock is None:
            continue

        try:
            currentlyChoked = getPeerChokeStatus(peerId)

            if peerId in currentPreferred:
                if currentlyChoked:
                    sendSimpleMessage(sock, 1)
                    setPeerChokeStatus(peerId, False)
                    print(f"Sent UNCHOKE to peer {peerId}")
                    writeLog(myPeerId, f"has unchoked Peer {peerId}.")
            else:
                if not currentlyChoked:
                    sendSimpleMessage(sock, 0)
                    setPeerChokeStatus(peerId, True)
                    print(f"Sent CHOKE to peer {peerId}")
                    writeLog(myPeerId, f"has choked Peer {peerId}.")
        except OSError:
            cleanupPeerConnection(peerId)
        except Exception as e:
            print(f"Error updating choke status for peer {peerId}: {e}")
            cleanupPeerConnection(peerId)

def allKnownPeersCompleted(myPeerId, myBitfield, peerList):
    if not all(myBitfield):
        return False

    for peer in peerList:
        peerId = peer["peerId"]

        if peerId == myPeerId:
            continue

        otherBitfield = getNeighborBitfield(peerId)
        if otherBitfield is None:
            return False

        if "0" in otherBitfield:
            return False

    return True

def checkForGlobalCompletion(myPeerId, myBitfield, peerList):
    if allKnownPeersCompleted(myPeerId, myBitfield, peerList):
        print("All peers have completed the file. Shutting down.")
        shutdownEvent.set()
        return True
    return False

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
    
    clearLogFile(currentPeer.peerId)

    setPreferredNeighbors([])

    totalPeerCount = len(peerList)

    if all(currentPeer.bitfield):
        markPeerCompleted(currentPeer.peerId)

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

    numberOfPreferredNeighbors = commonConfig["NumberOfPreferredNeighbors"]
    unchokingInterval = commonConfig["UnchokingInterval"]

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
            fileSize,
            totalPeerCount,
            peerList
        )
    )

    serverThread.start()

    preferredNeighborThread = threading.Thread(
        target=runPreferredNeighborSelection,
        args=(
            currentPeer.peerId,
            numberOfPreferredNeighbors,
            unchokingInterval
        )
    )
    preferredNeighborThread.start()

    previousPeers = getPreviousPeers(peerList, peerId)

    for peer in previousPeers:
        connectToPeer(
            peer["hostName"],
            peer["port"],
            currentPeer.peerId,
            currentPeer.bitfield,
            filePath,
            pieceSize,
            totalPeerCount,
            peerList
        )

    serverThread.join()
    preferredNeighborThread.join()


if __name__ == "__main__":
    main()