import unittest

from ck3_to_md import CK3Lookup, CK3UltimateExport


MINIMAL_GAMESTATE = """
traits_lookup={ brave }
living={
 42={
  first_name=\"Alice\"
  dynasty_house=7
  culture=3
  faith=5
  skill={ 1 2 3 4 5 6 }
  traits={ 0 }
  family_data={}
 }
}
 7={
  name=\"dynn_capet\"
 }
culture_manager={
 cultures={
  3={
   name=\"french\"
  }
 }
}
religion={
 faiths={
  5={
   name=\"catholic\"
  }
 }
}
"""


class CK3UltimateExportTests(unittest.TestCase):
    def test_process_handles_missing_alive_data_block(self) -> None:
        parser = CK3UltimateExport("dummy.ck3")
        parser.gamestate = MINIMAL_GAMESTATE
        parser.lookups = CK3Lookup(MINIMAL_GAMESTATE)
        parser.player_id = "42"

        parser.process()

        self.assertEqual(parser.data["First Name"], "Alice")
        self.assertEqual(parser.data["House"], "Capet")
        self.assertEqual(parser.data["Culture"], "French")
        self.assertEqual(parser.data["Faith"], "Catholic")
        self.assertEqual(parser.data["Gold"], 0.0)
        self.assertEqual(parser.data["Piety"], 0.0)
        self.assertEqual(parser.data["Prestige"], 0.0)
        self.assertEqual(parser.data["Traits"], ["Brave"])
        self.assertEqual(parser.data["Perks"], [])
        self.assertEqual(parser.data["Flags"], [])


if __name__ == "__main__":
    unittest.main()
