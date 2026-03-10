class Peer: 
    def __init__(self, peerId, hostName, port, hasFile, bitfield): 
        self.peerId = peerId
        self.hostName = hostName
        self.port = port
        self.hasFile = hasFile
        self.bitfield = bitfield
        
    def printInfo(self):
        print(f"Peer ID: {self.peerId}")
        print(f"Host Name: {self.hostName}")
        print(f"Port: {self.port}")
        print(f"Has File: {self.hasFile}")
        print(f"Bitfield: {self.bitfield}")