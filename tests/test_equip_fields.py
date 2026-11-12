# -*- coding: utf-8 -*-
"""装备字段读写往返：_read_equip_fields → _apply_equip_fields → _read_equip_fields 应稳定。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


ENGINE = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="engine_test_macro" class="engine">
    <properties>
      <boost duration="1.0" recharge="2.0" thrust="3.0" acceleration="4.0" attack="5.0" release="6.0" coast="7.0" />
      <travel charge="8.0" thrust="9.0" attack="10.0" release="11.0" />
      <thrust forward="12.0" reverse="13.0" strafe="14.0" pitch="15.0" yaw="16.0" roll="17.0" />
      <hull max="100" threshold="0.5" integrated="1" />
      <glow dynamic="1" />
      <effects>
        <boosting ref="fx_boost" />
        <traveling ref="fx_travel" />
      </effects>
      <sounds>
        <enginedetail ref="snd_engine" />
      </sounds>
      <decelerationcurve>
        <point position="0" value="1.0" />
        <point position="1" value="0.5" />
      </decelerationcurve>
      <strafecurve>
        <point position="0" value="2.0" />
      </strafecurve>
    </properties>
  </macro>
</macros>
"""

SHIELD = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="shield_test_macro" class="shield">
    <properties>
      <hull max="100" threshold="0.5" integrated="1" />
      <recharge max="200" rate="10" delay="1" disruptionstability="1" />
    </properties>
  </macro>
</macros>
"""

TURRET = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="turret_test_macro" class="turret">
    <properties>
      <bullet class="bullet_test_macro" />
      <rotationspeed max="1" />
      <rotationacceleration max="2" />
      <hull max="100" threshold="0.5" integrated="1" />
      <weapon angle="30" />
      <ammunition tags="missile" />
      <storage capacity="10" />
    </properties>
  </macro>
</macros>
"""

WEAPON = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="weapon_test_macro" class="weapon">
    <properties>
      <bullet class="bullet_test_macro" />
      <heat overheat="1" cooldelay="2" overheatcooldelay="3" coolrate="4" reenable="5" />
      <rotationspeed max="6" />
      <rotationacceleration max="7" />
      <hull max="100" integrated="1" hittable="1" />
      <weapon angle="8" shotangle="9" />
      <ammunition tags="missile" />
      <storage capacity="10" />
      <zoom delay="11" factor="12" time="13" />
    </properties>
  </macro>
</macros>
"""

MISSILE = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="missile_test_macro" class="missile">
    <properties>
      <missile amount="1" barrelamount="2" lifetime="3" range="4" guided="1" retarget="1"
               tags="missile" angle="5" icon="6" timediff="7" swarm="8" targetable="1"
               influencelist="9" />
      <ammunition value="10" reload="11" />
      <explosiondamage value="12" shield="13" shielddisruption="14" hull="15" />
      <reload time="16" />
      <hull max="17" />
      <weapon system="weapon_test" />
      <countermeasure resilience="18" />
      <lock time="19" range="20" />
      <accfactors forward="21" reverse="22" />
      <physics mass="23" />
      <inertia pitch="24" yaw="25" roll="26" />
      <drag forward="27" reverse="28" horizontal="29" vertical="30" pitch="31" yaw="32" roll="33" />
    </properties>
  </macro>
</macros>
"""

BULLET = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="bullet_test_macro" class="bullet">
    <properties>
      <bullet speed="1" lifetime="2" amount="3" barrelamount="3" delay="5" icon="6" angle="7"
              maxhits="8" ricochet="9" timediff="10" scale="11" attach="12" range="13"
              influencelist="14" restitution="15" mass="16" chargetime="17"
              firewhenfullcharge="0" requirefullcharge="0" heatwhilecharging="0"
              selfdestruct="0" plannedselfdestruct="0" selfdestructmintime="0"
              selfdestructtimediff="0" sticktime="0" />
      <ammunition value="18" reload="19" />
      <reload rate="20" time="21" />
      <heat value="22" initial="23" />
      <damage value="24" shielddisruption="25" shield="26" repair="27" hull="28" delay="29" />
      <areadamage shield="30" value="31" lifetime="32" />
      <multiplier traveldrive="33" mining="34" surfaceelement="35" />
      <weapon system="weapon_test" />
      <damagecurves>
        <time>
          <point position="0" value="1.0" />
          <point position="1" value="0.5" />
        </time>
      </damagecurves>
    </properties>
  </macro>
</macros>
"""

CASES = {"engine": ENGINE, "shield": SHIELD, "turret": TURRET,
         "weapon": WEAPON, "missile": MISSILE, "bullet": BULLET}


class EquipFieldsRoundTripTest(unittest.TestCase):
    def test_roundtrip_all_classes(self):
        for cls, txt in CASES.items():
            with self.subTest(cls=cls):
                f1 = server._read_equip_fields(cls, txt)
                self.assertTrue(f1, "%s 未读到任何字段" % cls)
                out = server._apply_equip_fields(cls, txt, f1)
                f2 = server._read_equip_fields(cls, out)
                self.assertEqual(f1, f2, "%s 字段往返后不一致" % cls)

    def test_apply_changes_values(self):
        f = server._read_equip_fields("shield", SHIELD)
        f["hull"] = "999"
        f["recharge_rate"] = "42"
        out = server._apply_equip_fields("shield", SHIELD, f)
        f2 = server._read_equip_fields("shield", out)
        self.assertEqual(f2["hull"], "999")
        self.assertEqual(f2["recharge_rate"], "42")

    def test_missing_field_does_not_touch_other_tags(self):
        f = server._read_equip_fields("turret", TURRET)
        f["weapon_angle"] = ""
        out = server._apply_equip_fields("turret", TURRET, f)
        f2 = server._read_equip_fields("turret", out)
        self.assertEqual(f2["weapon_angle"], "")
        self.assertEqual(f2["rot_speed"], "1")
        self.assertEqual(f2["hull"], "100")


if __name__ == "__main__":
    unittest.main()
