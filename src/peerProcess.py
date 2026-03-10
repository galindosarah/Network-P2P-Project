# peerProcess.py

import sys
from config import load_common_cfg, load_peer_info_cfg, find_peer_by_id


def main():
    # Step 1: make sure a peer ID was given
    if len(sys.argv) != 2:
        print("Usage: python peerProcess.py <peer_id>")
        sys.exit(1)

    # Step 2: convert the command-line argument to an integer
    try:
        peer_id = int(sys.argv[1])
    except ValueError:
        print("Error: peer_id must be an integer.")
        sys.exit(1)

    # Step 3: read the two config files
    try:
        common_config = load_common_cfg("Common.cfg")
        peer_list = load_peer_info_cfg("PeerInfo.cfg")
    except Exception as e:
        print(f"Error reading config files: {e}")
        sys.exit(1)

    # Step 4: find this peer in PeerInfo.cfg
    my_peer = find_peer_by_id(peer_list, peer_id)
    if my_peer is None:
        print(f"Error: peer ID {peer_id} was not found in PeerInfo.cfg")
        sys.exit(1)

    # Step 5: set up a very basic bitfield
    num_pieces = common_config["num_pieces"]

    if my_peer["has_file"] == 1:
        bitfield = [1] * num_pieces
    else:
        bitfield = [0] * num_pieces

    # Step 6: print what we loaded so we know it works
    print("===== peerProcess started =====")
    print(f"My peer ID: {peer_id}")
    print(f"My host: {my_peer['host_name']}")
    print(f"My port: {my_peer['port']}")
    print(f"Has complete file: {my_peer['has_file']}")
    print()
    print("Common.cfg values:")
    print(common_config)
    print()
    print("All peers from PeerInfo.cfg:")
    for peer in peer_list:
        print(peer)
    print()
    print(f"Number of pieces: {num_pieces}")
    print(f"Initial bitfield: {bitfield}")


if __name__ == "__main__":
    main()