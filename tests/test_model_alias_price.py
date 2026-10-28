#!/usr/bin/env python3
"""模型清单的价格必须每次从源重算，不能继承上一版 alias map。

回归背景（2026-10-28）：`expand_hops()` 曾把 alias map 里 chain 的 price
原样带回，`family_entries()` 又优先用 `item["price"]`，于是上游改价永远不生效。
WorkBuddy 的 Step-5-Pre 限免在 10-25 结束后实际已按 x0.33 计费，配置里却一直
挂在「免费 @0.00」，直到有人手点模型才发现。

跑法：`python -m unittest discover -s tests -v`
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import model_alias as M  # noqa: E402


def wb_record(list_rate: float, eff_rate: float | None = None) -> dict:
    return {
        "list": list_rate,
        "eff": list_rate if eff_rate is None else eff_rate,
        "label": "",
    }


def chain_item(*hops: tuple[str, str, float]) -> dict:
    """构造一条已存在的 alias 链路（带旧价格）。"""
    base = {"WB": M.WB_BASE, "OC": M.OC_BASE, "QD": M.QD_BASE}
    upstream = hops[0][1]
    return {
        "channel": hops[0][0],
        "upstream": upstream,
        "base_model": upstream.split(":", 1)[-1],
        "original": upstream,
        "protocol": "chat",
        "fallbacks": [],
        "legacy_ids": [upstream],
        "chain": [
            {
                "channel": channel,
                "upstream": up,
                "base": base[channel],
                "price": old_price,
                "original": up,
                "base_model": up.split(":", 1)[-1],
            }
            for channel, up, old_price in hops
        ],
    }


class PriceIsDerivedTest(unittest.TestCase):
    def test_chain_price_is_not_inherited(self):
        """存着 0.0，源里是 0.33 —— 结果必须是 0.33。"""
        item = chain_item(("WB", "cn:step-5-preview", 0.0))
        hops = M.expand_hops(item)
        self.assertTrue(all(h["price"] is None for h in hops))

        entries = M.family_entries(hops, {"cn:step-5-preview": wb_record(0.33)}, {}, "auto")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["price"], 0.33)
        self.assertEqual(entries[0]["chain"][0]["price"], 0.33)

    def test_price_drop_is_picked_up(self):
        """涨价要跟上，降价也要跟上（MiMo-2.6-Pro 0.18 -> 0.13）。"""
        item = chain_item(
            ("WB", "cn:mimo-v2.6-pro", 0.18),
            ("OC", "mimo-v2.6-pro", 0.18),
        )
        entries = M.family_entries(
            M.expand_hops(item), {"cn:mimo-v2.6-pro": wb_record(0.13)}, {}, "auto",
        )
        self.assertEqual(entries[0]["price"], 0.13)
        self.assertEqual([h["upstream"] for h in entries[0]["chain"]],
                         ["cn:mimo-v2.6-pro", "mimo-v2.6-pro"])

    def test_dead_hop_is_dropped(self):
        """源里已经没有这个上游（下架/账号封禁）→ 该跳消失，不靠旧价赖着。"""
        item = chain_item(
            ("WB", "cn:step-5-preview", 0.0),
            ("OC", "step-5-preview", 0.0),
        )
        entries = M.family_entries(
            M.expand_hops(item), {"cn:step-5-preview": wb_record(0.33)}, {}, "auto"
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual([h["upstream"] for h in entries[0]["chain"]],
                         ["cn:step-5-preview"])

    def test_fully_dead_chain_is_skipped(self):
        item = chain_item(("WB", "cn:gone-model", 0.0))
        self.assertEqual(M.family_entries(M.expand_hops(item), {}, {}, "auto"), [])

    def test_free_promo_expiry_moves_group(self):
        """限免到期：价格从 0 变 0.33，分组必须从免费挪到高耗。"""
        item = chain_item(("WB", "cn:step-5-preview", 0.0))
        entries = M.family_entries(
            M.expand_hops(item), {"cn:step-5-preview": wb_record(0.33)}, {}, "auto"
        )
        self.assertEqual(M.entry_group(entries[0], {}), ("high", ""))


class DriftCheckTest(unittest.TestCase):
    def _grouped(self, price: float) -> dict:
        entry = M.family_entries(
            M.expand_hops(chain_item(("WB", "cn:step-5-preview", 0.0))),
            {"cn:step-5-preview": wb_record(price)}, {}, "auto",
        )[0]
        entry = dict(entry)
        entry["new_id"] = "Step-5-Pre"
        entry["price"] = price
        return {"high": [entry]}

    def test_price_drift_is_reported(self):
        existing = {
            "Step-5-Pre": {
                "group": "免费",
                "price": 0.0,
                "chain": [{"channel": "WB", "upstream": "cn:step-5-preview", "price": 0.0}],
            }
        }
        drift = M.drift_report(self._grouped(0.33), existing)
        self.assertEqual(drift["price_changed"], [("Step-5-Pre", 0.0, 0.33)])
        self.assertEqual(drift["group_changed"], [("Step-5-Pre", "免费", "高耗")])

    def test_no_drift_after_apply(self):
        existing = {
            "Step-5-Pre": {
                "group": "高耗",
                "price": 0.33,
                "chain": [{"channel": "WB", "upstream": "cn:step-5-preview", "price": 0.33}],
            }
        }
        drift = M.drift_report(self._grouped(0.33), existing)
        self.assertFalse(any(drift.values()), drift)


class ProbeFreshnessTest(unittest.TestCase):
    def test_stale_probe_entries_are_dropped(self):
        fresh_at = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        stale_at = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S")
        probe = {
            "cn:fresh": {"status": "ok", "checked_at": fresh_at},
            "cn:stale": {"status": "unavailable", "checked_at": stale_at},
            "cn:no-stamp": {"status": "ok"},
        }
        fresh, stale = M._fresh_probe(probe, 72)
        self.assertEqual(sorted(fresh), ["cn:fresh"])
        self.assertEqual(sorted(stale), ["cn:no-stamp", "cn:stale"])

    def test_ttl_zero_disables_filtering(self):
        probe = {"cn:old": {"status": "ok", "checked_at": "2020-01-01T00:00:00"}}
        fresh, stale = M._fresh_probe(probe, 0)
        self.assertEqual(fresh, probe)
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
