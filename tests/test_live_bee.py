"""Live Bee integration: the whole story on a real network, once.

Everything else in this suite runs against FakeSwarmClient, whose refs are
sha256 stand-ins. This test is the one place both halves go live at the
same time: file bytes uploaded to a real Bee node (real BMT references as
object identities), classifications in an OntoDAG persisted on the same
node, and the filesystem browsing and reading it all back — including a
range read and a fresh-process rehydration where the only bridge is the
committed root.

Skips unless BEE_API **and** BEE_BATCH are set (house convention: pass a
real purchased batch so nothing auto-buys):

    BEE_API=http://localhost:1633 BEE_BATCH=<batchID> \
        python3 -m pytest tests/test_live_bee.py -v
"""

import os
import unittest

BEE_API = os.environ.get("BEE_API")
BEE_BATCH = os.environ.get("BEE_BATCH")


@unittest.skipUnless(
    BEE_API and BEE_BATCH,
    "set BEE_API and BEE_BATCH to run the live Bee integration test",
)
class TestFilesystemOnLiveBee(unittest.TestCase):
    def test_file_browse_and_read_back_on_real_swarm(self):
        from ontodag.eager import EagerOntoDAG
        from recordstore import BeeBytesStore, RecordStore
        from swarmfs import SwarmClient, SwarmFileSystem

        from ontodag_fs import OntoDAGFileSystem, OntoDAGIndex

        blobs = BeeBytesStore(BEE_API, BEE_BATCH)

        # Real content, real BMT refs — these refs ARE the object identities.
        rex = blobs.put(b"rex the dog, on swarm")
        note_bytes = b"a note about weights " * 40      # multi-hundred bytes
        note = blobs.put(note_bytes)

        # Classifications in an OntoDAG persisted on the same node,
        # dimensions included.
        dag = EagerOntoDAG(RecordStore(BeeBytesStore(BEE_API, BEE_BATCH)))
        index = OntoDAGIndex(dag)
        for name, parents in [("animal", []), ("dog", ["animal"]),
                              ("document", []), ("dimension", []),
                              ("linear-dimension", ["dimension"]),
                              ("weight", ["linear-dimension"])]:
            index.add_attribute(name, parents)
        index.add_object(rex, "rex.txt", {"dog", "weight(12kg)"})
        index.add_object(note, "weights.md", {"document"})
        root = dag.commit()
        self.assertTrue(root)

        fs = OntoDAGFileSystem(
            index=index,
            swarm=SwarmFileSystem(client=SwarmClient(BEE_API),
                                  skip_instance_cache=True))

        # Browse: subsumption and a VIRTUAL typed-value directory.
        names = {e.rsplit("/", 1)[-1] for e in fs.ls("/animal/.all")}
        self.assertEqual(names, {"rex.txt"})
        self.assertTrue(fs.isdir("/dog/weight(..20kg)"))
        virtual = {e.rsplit("/", 1)[-1]
                   for e in fs.ls("/dog/weight(..20kg)/.all")}
        self.assertEqual(virtual, {"rex.txt"})

        # Read the bytes back from the network, whole and by range.
        self.assertEqual(fs.cat_file("/dog/rex.txt"),
                         b"rex the dog, on swarm")
        self.assertEqual(fs.cat_file("/dog/rex.txt", start=0, end=3), b"rex")
        self.assertEqual(fs.cat_file("/document/weights.md"), note_bytes)

        # Scorched-earth rehydration: a fresh graph from the committed root
        # (records read back from Bee), a fresh index, a fresh filesystem —
        # the same knowledge, browsable again.
        again = OntoDAGFileSystem(
            index=OntoDAGIndex(
                EagerOntoDAG(RecordStore.at(
                    root, BeeBytesStore(BEE_API, BEE_BATCH)))),
            swarm=SwarmFileSystem(client=SwarmClient(BEE_API),
                                  skip_instance_cache=True))
        self.assertEqual(
            {e.rsplit("/", 1)[-1]
             for e in again.ls("/dog/weight(..20kg)/.all")},
            {"rex.txt"})
        self.assertEqual(again.cat_file("/animal/rex.txt"),
                         b"rex the dog, on swarm")


if __name__ == "__main__":
    unittest.main()
