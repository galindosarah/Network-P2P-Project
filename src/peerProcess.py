import sys
import socket
import struct
import threading
import random
import time

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

interestedPeers = set()
interestedPeersLock = threading.Lock()

downloadCounts = {}
downloadCountsLock = threading.Lock()

optimisticallyUnchokedNeighbor = None
optimisticNeighborLock = threading.Lock()

downloadingFromPeers = set()
downloadingFromPeersLock = threading.Lock()

requestedPieces = set()
requestedPiecesLock = threading.Lock()

peerRemoteChokeStatus = {}
peerRemoteChokeStatusLock = threading.Lock()

peerPendingRequests = {}
peerPendingRequestsLock = threading.Lock()

peerInterestStatus = {}
peerInterestStatusLock = threading.Lock()


def startServer(port, myPeerId, expectedConnections, myBitfield, filePath, pieceSize, fileSize, peerList):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", port))
    server.listen()
    server.settimeout(1.0)

    print(f"Peer listening on port {port}...")

    acceptedConnections = 0
    handlerThreads = []

    while acceptedConnections < expectedConnections:
        if shutdownEvent.is_set():
            break

        try:
            connection, addr = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        acceptedConnections += 1
        print(f"Connection received from {addr}")

        def handleIncoming(conn):
            receivedPeerId = readHandshake(conn)
            print(f"Received handshake from peer {receivedPeerId}")
            writeLog(myPeerId, f"is connected from Peer {receivedPeerId}.")

            addConnectedPeer(receivedPeerId)
            storePeerSocket(receivedPeerId, conn)

            setPeerChokeStatus(receivedPeerId, True)

            setPeerRemoteChokeStatus(receivedPeerId, True)

            handshake = createHandshake(myPeerId)
            conn.sendall(handshake)
            print(f"Sent handshake from peer {myPeerId}")

            messageType, payload = readMessage(conn)
            if messageType != 5:
                print("Expected BITFIELD message")
                cleanupPeerConnection(receivedPeerId)
                conn.close()
                return

            otherBitfieldList = unpackBitfield(payload, len(myBitfield))
            otherBitfield = bitfieldToString(otherBitfieldList)

            storeNeighborBitfield(receivedPeerId, otherBitfield)
            print(f"Received bitfield from peer {receivedPeerId}: {otherBitfield}")

            if "0" not in otherBitfield and not isPeerCompleted(receivedPeerId):
                markPeerCompleted(receivedPeerId)

            sendBitfield(conn, myBitfield)

            updateInterestState(conn, receivedPeerId, myBitfield, otherBitfield)

            messageType, payload = readMessage(conn)
            if messageType == 2:
                print(f"Received INTERESTED from peer {receivedPeerId}")
                writeLog(myPeerId, f"received the 'interested' message from Peer {receivedPeerId}.")
                addInterestedPeer(receivedPeerId)
            elif messageType == 3:
                print(f"Received NOT INTERESTED from peer {receivedPeerId}")
                writeLog(myPeerId, f"received the 'not interested' message from Peer {receivedPeerId}.")
                removeInterestedPeer(receivedPeerId)
            else:
                print("Expected INTERESTED or NOT INTERESTED message")
                cleanupPeerConnection(receivedPeerId)
                conn.close()
                return

            currentPreferred = getPreferredNeighbors()
            currentOptimistic = getOptimisticallyUnchokedNeighbor()

            if receivedPeerId in currentPreferred or receivedPeerId == currentOptimistic:
                sendSimpleMessage(conn, 1)
                setPeerChokeStatus(receivedPeerId, False)
            else:
                sendSimpleMessage(conn, 0)
                setPeerChokeStatus(receivedPeerId, True)

            peerMessageLoop(conn, myPeerId, receivedPeerId, myBitfield, filePath, pieceSize, fileSize, peerList)

        handlerThread = threading.Thread(target=handleIncoming, args=(connection,))
        handlerThread.start()
        handlerThreads.append(handlerThread)

    for t in handlerThreads:
        t.join()
    server.close()

def connectToPeer(host, port, myPeerId, myBitfield, filePath, pieceSize, fileSize, peerList):
    print(f"Connecting to {host}:{port}...")

    client = None
    connected = False

    for attempt in range(120):
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect((host, port))
            connected = True
            break
        except ConnectionRefusedError:
            print(f"Connection to {host}:{port} refused, retrying...")
            if client is not None:
                client.close()
                client = None
            time.sleep(1)
        except OSError as e:
            print(f"Connection to {host}:{port} failed: {e}")
            if client is not None:
                client.close()
                client = None
            time.sleep(1)

    if not connected or client is None:
        print(f"Could not connect to {host}:{port}")
        return

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

    setPeerRemoteChokeStatus(receivedPeerId, True)

    sendBitfield(client, myBitfield)

    messageType, payload = readMessage(client)
    if messageType != 5:
        print("Expected BITFIELD message")
        cleanupPeerConnection(receivedPeerId)
        client.close()
        maybeShutdownCompletedPeer(myPeerId, myBitfield)
        return

    otherBitfieldList = unpackBitfield(payload, len(myBitfield))
    otherBitfield = bitfieldToString(otherBitfieldList)

    storeNeighborBitfield(receivedPeerId, otherBitfield)
    print(f"Received bitfield from peer {receivedPeerId}: {otherBitfield}")

    if "0" not in otherBitfield and not isPeerCompleted(receivedPeerId):
        markPeerCompleted(receivedPeerId)

    updateInterestState(client, receivedPeerId, myBitfield, otherBitfield)

    messageType, payload = readMessage(client)
    if messageType == 2:
        print(f"Received INTERESTED from peer {receivedPeerId}")
        writeLog(myPeerId, f"received the 'interested' message from Peer {receivedPeerId}.")
        addInterestedPeer(receivedPeerId)
    elif messageType == 3:
        print(f"Received NOT INTERESTED from peer {receivedPeerId}")
        writeLog(myPeerId, f"received the 'not interested' message from Peer {receivedPeerId}.")
        removeInterestedPeer(receivedPeerId)
    else:
        print("Expected INTERESTED or NOT INTERESTED message")
        cleanupPeerConnection(receivedPeerId)
        client.close()
        maybeShutdownCompletedPeer(myPeerId, myBitfield)
        return

    messageType, payload = readMessage(client)
    if messageType == 0:
        print(f"Received CHOKE from peer {receivedPeerId}")
        writeLog(myPeerId, f"is choked by Peer {receivedPeerId}.")
        setPeerRemoteChokeStatus(receivedPeerId, True)
    elif messageType == 1:
        print(f"Received UNCHOKE from peer {receivedPeerId}")
        writeLog(myPeerId, f"is unchoked by Peer {receivedPeerId}.")
        setPeerRemoteChokeStatus(receivedPeerId, False)
        addDownloadingFromPeer(receivedPeerId)

        requested = maybeRequestNextPiece(client, receivedPeerId, myBitfield)
        if not requested and all(myBitfield):
            cleanupPeerConnection(receivedPeerId)
            client.close()
            maybeShutdownCompletedPeer(myPeerId, myBitfield)
            return
    else:
        print("Expected CHOKE or UNCHOKE message")
        cleanupPeerConnection(receivedPeerId)
        client.close()
        maybeShutdownCompletedPeer(myPeerId, myBitfield)
        return

    peerMessageLoop(client, myPeerId, receivedPeerId, myBitfield, filePath, pieceSize, fileSize, peerList)

# Handshake / Message Parsing Functions
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

def packBitfield(bitfield):
    numBytes = (len(bitfield) + 7) // 8
    packed = bytearray(numBytes)

    for i, bit in enumerate(bitfield):
        if bit == 1:
            byteIndex = i // 8
            bitIndex = 7 - (i % 8)
            packed[byteIndex] |= (1 << bitIndex)

    return bytes(packed)

def unpackBitfield(payload, numPieces):
    bitfield = []

    for byte in payload:
        for bitIndex in range(7, -1, -1):
            bit = (byte >> bitIndex) & 1
            bitfield.append(bit)

    return bitfield[:numPieces]

def bitfieldToString(bitfield):
    return "".join(str(bit) for bit in bitfield)

def sendBitfield(sock, bitfield):
    payload = packBitfield(bitfield)

    messageType = 5
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent bitfield: {bitfieldToString(bitfield)}")

def readMessage(sock):
    try:
        messageLengthBytes = sock.recv(4)
    except (ConnectionResetError, OSError):
        return None, None

    if len(messageLengthBytes) != 4:
        return None, None

    messageLength = struct.unpack(">I", messageLengthBytes)[0]

    try:
        messageTypeBytes = sock.recv(1)
    except (ConnectionResetError, OSError):
        return None, None

    if len(messageTypeBytes) != 1:
        return None, None

    messageType = struct.unpack(">B", messageTypeBytes)[0]

    payloadLength = messageLength - 1
    payload = b""

    while len(payload) < payloadLength:
        try:
            chunk = sock.recv(payloadLength - len(payload))
        except (ConnectionResetError, OSError):
            return None, None

        if not chunk:
            return None, None

        payload += chunk

    return messageType, payload

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

def sendRequest(sock, pieceIndex):
    messageType = 6
    payload = struct.pack(">I", pieceIndex)
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent REQUEST for piece {pieceIndex}")


def sendPiece(sock, pieceIndex, pieceData):
    messageType = 7
    payload = struct.pack(">I", pieceIndex) + pieceData
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent PIECE {pieceIndex}")

def sendHave(sock, pieceIndex):
    messageType = 4
    payload = struct.pack(">I", pieceIndex)
    messageLength = 1 + len(payload)

    message = struct.pack(">I", messageLength)
    message += struct.pack(">B", messageType)
    message += payload

    sock.sendall(message)
    print(f"Sent HAVE for piece {pieceIndex}")

# Bitfield / Interest State Functions
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

def hasInterestingPieces(myBitfield, otherBitfieldString):
    for i in range(len(myBitfield)):
        if myBitfield[i] == 0 and otherBitfieldString[i] == "1":
            return True
    return False

def choosePieceToRequest(myBitfield, otherBitfieldString):
    possiblePieces = []

    for i in range(len(myBitfield)):
        if myBitfield[i] == 0 and otherBitfieldString[i] == "1":
            possiblePieces.append(i)

    random.shuffle(possiblePieces)

    for pieceIndex in possiblePieces:
        if reservePiece(pieceIndex):
            return pieceIndex

    return None

def broadcastHave(pieceIndex):
    for otherPeerId in getConnectedPeers():
        otherSock = getPeerSocket(otherPeerId)
        if otherSock is None:
            continue
        try:
            sendHave(otherSock, pieceIndex)
        except OSError:
            cleanupPeerConnection(otherPeerId)

def updateInterestState(sock, peerId, myBitfield, otherBitfieldString):
    shouldBeInterested = hasInterestingPieces(myBitfield, otherBitfieldString)
    previousState = getPeerInterestStatus(peerId)

    if previousState is None or previousState != shouldBeInterested:
        if shouldBeInterested:
            sendSimpleMessage(sock, 2)
        else:
            sendSimpleMessage(sock, 3)

        setPeerInterestStatus(peerId, shouldBeInterested)

    return shouldBeInterested

def reevaluateInterestForAllNeighbors(myBitfield):
    for otherPeerId in getConnectedPeers():
        otherSock = getPeerSocket(otherPeerId)
        if otherSock is None:
            continue

        otherBitfield = getNeighborBitfield(otherPeerId)
        if otherBitfield is None:
            continue

        try:
            updateInterestState(otherSock, otherPeerId, myBitfield, otherBitfield)
        except OSError:
            cleanupPeerConnection(otherPeerId)

# File Handling Functions
def getPieceData(bitfield, filePath, pieceIndex, pieceSize, fileSize):
    if bitfield[pieceIndex] == 1:
        return readPieceFromFile(filePath, pieceIndex, pieceSize, fileSize)
    return None

def savePiece(bitfield, filePath, pieceIndex, pieceSize, pieceData):
    bitfield[pieceIndex] = 1
    writePieceToFile(filePath, pieceIndex, pieceSize, pieceData)
    print(f"Saved piece {pieceIndex} to {filePath}")

def createPeerDirectory(peerId):
    peerFolder = Path(f"peer_{peerId}")
    peerFolder.mkdir(exist_ok=True)
    return peerFolder

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

# Logging / Completion Tracking Functions
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
        closeAllPeerSockets()
        return True
    return False

def maybeShutdownCompletedPeer(myPeerId, myBitfield):
    if all(myBitfield):
        connected = getConnectedPeers()
        if len(connected) == 0:
            print(f"Peer {myPeerId} has completed the file. Shutting down.")
            shutdownEvent.set()
            return True
    return False

def closeAllPeerSockets():
    with peerSocketsLock:
        sockets = list(peerSockets.items())

    for peerId, sock in sockets:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


def getPeerFilePath(peerId, fileName):
    peerFolder = createPeerDirectory(peerId)
    return peerFolder / fileName

# Connection / Peer State Functions
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

def storePeerSocket(peerId, sock):
    with peerSocketsLock:
        peerSockets[peerId] = sock


def removePeerSocket(peerId):
    with peerSocketsLock:
        if peerId in peerSockets:
            del peerSockets[peerId]


def getPeerSocket(peerId):
    with peerSocketsLock:
        sock = peerSockets.get(peerId)

    if sock is None:
        return None

    try:
        sock.fileno()
    except OSError:
        return None

    return sock

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
    pendingPiece = getPendingRequest(peerId)
    if pendingPiece is not None:
        releasePiece(pendingPiece)
        clearPendingRequest(peerId)

    removePeerSocket(peerId)
    removeConnectedPeer(peerId)
    removeInterestedPeer(peerId)
    removeDownloadingFromPeer(peerId)
    clearPeerRemoteChokeStatus(peerId)
    clearPeerInterestStatus(peerId)

    with peerChokeStatusLock:
        if peerId in peerChokeStatus:
            del peerChokeStatus[peerId]

    with downloadCountsLock:
        if peerId in downloadCounts:
            del downloadCounts[peerId]

    currentOptimistic = getOptimisticallyUnchokedNeighbor()
    if currentOptimistic == peerId:
        setOptimisticallyUnchokedNeighbor(None)

# Choke / Request State Functions
def setPreferredNeighbors(peerIds):
    with preferredNeighborsLock:
        preferredNeighbors.clear()
        preferredNeighbors.update(peerIds)

def getPreferredNeighbors():
    with preferredNeighborsLock:
        return set(preferredNeighbors)

def runPreferredNeighborSelection(myPeerId, myBitfield, numberOfPreferredNeighbors, unchokingInterval):
    while not shutdownEvent.is_set():
        shutdownEvent.wait(unchokingInterval)
        if shutdownEvent.is_set():
            break

        chosenNeighbors = choosePreferredNeighbors(myBitfield, numberOfPreferredNeighbors)
        setPreferredNeighbors(chosenNeighbors)

        neighborListString = ", ".join(str(peerId) for peerId in sorted(chosenNeighbors))
        print(f"Preferred neighbors for peer {myPeerId}: {neighborListString}")
        writeLog(myPeerId, f"has the preferred neighbors {neighborListString}.")

        applyPreferredNeighborChoking(myPeerId)

        resetDownloadCounts()

def setPeerChokeStatus(peerId, isChoked):
    with peerChokeStatusLock:
        peerChokeStatus[peerId] = isChoked


def getPeerChokeStatus(peerId):
    with peerChokeStatusLock:
        return peerChokeStatus.get(peerId, True)

def applyPreferredNeighborChoking(myPeerId):
    currentPreferred = getPreferredNeighbors()
    currentOptimistic = getOptimisticallyUnchokedNeighbor()
    interested = getInterestedPeers()

    for peerId in interested:
        sock = getPeerSocket(peerId)
        if sock is None:
            cleanupPeerConnection(peerId)
            continue

        try:
            currentlyChoked = getPeerChokeStatus(peerId)
            shouldBeUnchoked = (peerId in currentPreferred) or (peerId == currentOptimistic)

            if shouldBeUnchoked:
                if currentlyChoked:
                    sendSimpleMessage(sock, 1)
                    setPeerChokeStatus(peerId, False)
                    print(f"Sent UNCHOKE to peer {peerId}")
                    writeLog(myPeerId, f"has unchoked Peer {peerId}.")
            else:
                if isDownloadingFromPeer(peerId):
                    continue

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


def addInterestedPeer(peerId):
    with interestedPeersLock:
        interestedPeers.add(peerId)


def removeInterestedPeer(peerId):
    with interestedPeersLock:
        interestedPeers.discard(peerId)


def getInterestedPeers():
    with interestedPeersLock:
        return set(interestedPeers)


def recordDownloadFromPeer(peerId):
    with downloadCountsLock:
        downloadCounts[peerId] = downloadCounts.get(peerId, 0) + 1


def getDownloadCountsSnapshot():
    with downloadCountsLock:
        return dict(downloadCounts)


def resetDownloadCounts():
    with downloadCountsLock:
        downloadCounts.clear()


def setOptimisticallyUnchokedNeighbor(peerId):
    global optimisticallyUnchokedNeighbor
    with optimisticNeighborLock:
        optimisticallyUnchokedNeighbor = peerId


def getOptimisticallyUnchokedNeighbor():
    with optimisticNeighborLock:
        return optimisticallyUnchokedNeighbor
    
def choosePreferredNeighbors(myBitfield, numberOfPreferredNeighbors):
    interested = list(getInterestedPeers())

    if len(interested) == 0:
        return []

    if len(interested) <= numberOfPreferredNeighbors:
        return interested

    if all(myBitfield):
        return random.sample(interested, numberOfPreferredNeighbors)

    counts = getDownloadCountsSnapshot()
    scoredPeers = []

    for peerId in interested:
        scoredPeers.append((peerId, counts.get(peerId, 0)))

    random.shuffle(scoredPeers)
    scoredPeers.sort(key=lambda item: item[1], reverse=True)

    chosen = []
    for peerId, rate in scoredPeers[:numberOfPreferredNeighbors]:
        chosen.append(peerId)

    return chosen
    
def runOptimisticUnchoking(myPeerId, optimisticUnchokingInterval):
    while not shutdownEvent.is_set():
        shutdownEvent.wait(optimisticUnchokingInterval)
        if shutdownEvent.is_set():
            break

        interested = getInterestedPeers()
        preferred = getPreferredNeighbors()

        candidates = []
        for peerId in interested:
            if peerId not in preferred and getPeerChokeStatus(peerId):
                candidates.append(peerId)

        if len(candidates) == 0:
            setOptimisticallyUnchokedNeighbor(None)
            applyPreferredNeighborChoking(myPeerId)
            continue

        chosenPeer = random.choice(candidates)
        previousOptimistic = getOptimisticallyUnchokedNeighbor()

        setOptimisticallyUnchokedNeighbor(chosenPeer)

        if previousOptimistic != chosenPeer:
            print(f"Optimistically unchoked neighbor for peer {myPeerId}: {chosenPeer}")
            writeLog(myPeerId, f"has the optimistically unchoked neighbor {chosenPeer}.")

        applyPreferredNeighborChoking(myPeerId)

def addDownloadingFromPeer(peerId):
    with downloadingFromPeersLock:
        downloadingFromPeers.add(peerId)


def removeDownloadingFromPeer(peerId):
    with downloadingFromPeersLock:
        downloadingFromPeers.discard(peerId)


def isDownloadingFromPeer(peerId):
    with downloadingFromPeersLock:
        return peerId in downloadingFromPeers

def setPeerRemoteChokeStatus(peerId, isChoked):
    with peerRemoteChokeStatusLock:
        peerRemoteChokeStatus[peerId] = isChoked


def getPeerRemoteChokeStatus(peerId):
    with peerRemoteChokeStatusLock:
        return peerRemoteChokeStatus.get(peerId, True)


def clearPeerRemoteChokeStatus(peerId):
    with peerRemoteChokeStatusLock:
        if peerId in peerRemoteChokeStatus:
            del peerRemoteChokeStatus[peerId]


def setPendingRequest(peerId, pieceIndex):
    with peerPendingRequestsLock:
        peerPendingRequests[peerId] = pieceIndex


def getPendingRequest(peerId):
    with peerPendingRequestsLock:
        return peerPendingRequests.get(peerId)


def clearPendingRequest(peerId):
    with peerPendingRequestsLock:
        if peerId in peerPendingRequests:
            del peerPendingRequests[peerId]


def reservePiece(pieceIndex):
    with requestedPiecesLock:
        if pieceIndex in requestedPieces:
            return False
        requestedPieces.add(pieceIndex)
        return True


def releasePiece(pieceIndex):
    with requestedPiecesLock:
        requestedPieces.discard(pieceIndex)

def maybeRequestNextPiece(sock, peerId, myBitfield):
    if getPeerRemoteChokeStatus(peerId):
        return False

    if getPendingRequest(peerId) is not None:
        return True

    otherBitfield = getNeighborBitfield(peerId)
    if otherBitfield is None:
        return False

    pieceToRequest = choosePieceToRequest(myBitfield, otherBitfield)
    if pieceToRequest is None:
        try:
            sendSimpleMessage(sock, 3)
        except OSError:
            pass
        return False

    setPendingRequest(peerId, pieceToRequest)
    sendRequest(sock, pieceToRequest)
    return True

def peerMessageLoop(sock, myPeerId, peerId, myBitfield, filePath, pieceSize, fileSize, peerList):
    while not shutdownEvent.is_set():
        messageType, payload = readMessage(sock)

        if messageType is None:
            print(f"Connection to peer {peerId} closed.")
            break

        if messageType == 0:
            print(f"Received CHOKE from peer {peerId}")
            writeLog(myPeerId, f"is choked by Peer {peerId}.")
            setPeerRemoteChokeStatus(peerId, True)

            pendingPiece = getPendingRequest(peerId)
            if pendingPiece is not None:
                releasePiece(pendingPiece)
                clearPendingRequest(peerId)

        elif messageType == 1:
            print(f"Received UNCHOKE from peer {peerId}")
            writeLog(myPeerId, f"is unchoked by Peer {peerId}.")
            setPeerRemoteChokeStatus(peerId, False)
            addDownloadingFromPeer(peerId)

            requested = maybeRequestNextPiece(sock, peerId, myBitfield)
            if not requested and all(myBitfield):
                break

        elif messageType == 2:
            print(f"Received INTERESTED from peer {peerId}")
            writeLog(myPeerId, f"received the 'interested' message from Peer {peerId}.")
            addInterestedPeer(peerId)

        elif messageType == 3:
            print(f"Received NOT INTERESTED from peer {peerId}")
            writeLog(myPeerId, f"received the 'not interested' message from Peer {peerId}.")
            removeInterestedPeer(peerId)

        elif messageType == 4:
            havePieceIndex = struct.unpack(">I", payload)[0]
            print(f"Received HAVE for piece {havePieceIndex} from peer {peerId}")
            writeLog(myPeerId, f"received the 'have' message from Peer {peerId} for the piece {havePieceIndex}.")

            updatedBitfield = updateNeighborBitfieldWithHave(peerId, havePieceIndex)

            if updatedBitfield is not None and "0" not in updatedBitfield:
                if not isPeerCompleted(peerId):
                    markPeerCompleted(peerId)

            shouldBeInterested = False
            if updatedBitfield is not None:
                try:
                    shouldBeInterested = updateInterestState(sock, peerId, myBitfield, updatedBitfield)
                except OSError:
                    break

            if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
                break

            if shouldBeInterested and not getPeerRemoteChokeStatus(peerId):
                requested = maybeRequestNextPiece(sock, peerId, myBitfield)
                if not requested and all(myBitfield):
                    break

        elif messageType == 6:
            requestedPieceIndex = struct.unpack(">I", payload)[0]
            print(f"Received REQUEST for piece {requestedPieceIndex} from peer {peerId}")

            if not getPeerChokeStatus(peerId):
                pieceData = getPieceData(myBitfield, filePath, requestedPieceIndex, pieceSize, fileSize)
                if pieceData is not None:
                    sendPiece(sock, requestedPieceIndex, pieceData)

        elif messageType == 7:
            pieceIndex = struct.unpack(">I", payload[:4])[0]
            pieceData = payload[4:]

            print(f"Received PIECE {pieceIndex} from peer {peerId}")
            savePiece(myBitfield, filePath, pieceIndex, pieceSize, pieceData)
            recordDownloadFromPeer(peerId)

            pendingPiece = getPendingRequest(peerId)
            if pendingPiece is not None:
                releasePiece(pendingPiece)
                clearPendingRequest(peerId)

            pieceCount = sum(myBitfield)
            writeLog(
                myPeerId,
                f"has downloaded the piece {pieceIndex} from Peer {peerId}. "
                f"Now the number of pieces it has is {pieceCount}."
            )

            broadcastHave(pieceIndex)
            reevaluateInterestForAllNeighbors(myBitfield)

            if all(myBitfield) and not isPeerCompleted(myPeerId):
                markPeerCompleted(myPeerId)
                writeLog(myPeerId, "has downloaded the complete file.")

            if checkForGlobalCompletion(myPeerId, myBitfield, peerList):
                break

            maybeRequestNextPiece(sock, peerId, myBitfield)

        else:
            print(f"Received unexpected message type {messageType} from peer {peerId}")

    cleanupPeerConnection(peerId)
    try:
        sock.close()
    except OSError:
        pass

    maybeShutdownCompletedPeer(myPeerId, myBitfield)

def setPeerInterestStatus(peerId, isInterested):
    with peerInterestStatusLock:
        peerInterestStatus[peerId] = isInterested


def getPeerInterestStatus(peerId):
    with peerInterestStatusLock:
        return peerInterestStatus.get(peerId)


def clearPeerInterestStatus(peerId):
    with peerInterestStatusLock:
        if peerId in peerInterestStatus:
            del peerInterestStatus[peerId]

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

    # totalPeerCount = len(peerList)

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
    optimisticUnchokingInterval = commonConfig["OptimisticUnchokingInterval"]
    
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
            # totalPeerCount,
            peerList
        )
    )

    serverThread.start()

    preferredNeighborThread = threading.Thread(
        target=runPreferredNeighborSelection,
        args=(
            currentPeer.peerId,
            currentPeer.bitfield,
            numberOfPreferredNeighbors,
            unchokingInterval
        ),
        daemon=True
    )
    preferredNeighborThread.start()
    optimisticUnchokeThread = threading.Thread(
        target=runOptimisticUnchoking,
        args=(
            currentPeer.peerId,
            optimisticUnchokingInterval
        ),
        daemon=True
    )
    optimisticUnchokeThread.start()

    previousPeers = getPreviousPeers(peerList, peerId)

    outgoingThreads = []

    for peer in previousPeers:
        t = threading.Thread(
            target=connectToPeer,
            args=(
                peer["hostName"],
                peer["port"],
                currentPeer.peerId,
                currentPeer.bitfield,
                filePath,
                pieceSize,
                fileSize,
                # totalPeerCount,
                peerList
            )
        )
        t.start()
        outgoingThreads.append(t)

    serverThread.join()

    for t in outgoingThreads:
        t.join()


if __name__ == "__main__":
    main()