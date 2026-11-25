import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import materials as m


TAIPEI = {"cci_tpe_總指數": 117.91, "cci_tpe_材料類": 119.54, "cci_tpe_勞務類": 115.17}
TAIPEI_FULL = "月份,指數/總指數,指數/材料類指數,指數/勞務類指數\n115年11月,118,120,116"
TAIPEI_PARTIAL = "月份,指數/總指數,指數/材料類指數\n115年11月,118,無資料"
TAICHUNG_URL = "https://example.test/taichung.json"


def previous_item(key, city, name, value):
    return m.make_item(id=key, name=f"{city} · {name}", group="cci_local", unit="指數",
                       history=[("2026-09", value - 1), ("2026-10", value)],
                       source=city, source_url="https://example.test/", region=city, freq="月")


class LocalCciRefreshTest(unittest.TestCase):
    def setUp(self):
        self.prev = {key: previous_item(key, "臺北市", key.split("_")[-1], value)
                     for key, value in TAIPEI.items()}
        for key, city, name in [
            ("cci_ntpc_total", "新北市", "總指數"),
            ("cci_txg_00", "臺中市", "總指數"),
            ("cci_txg_01", "臺中市", "材料類"),
        ]:
            self.prev[key] = previous_item(key, city, name, 100)

    def request(self, session, url, **kwargs):
        if url == m.TAIPEI_CCI_URL:
            if isinstance(self.taipei, Exception):
                raise self.taipei
            return SimpleNamespace(content=self.taipei.encode("utf-8"))
        if url == m.NTPC_CCI_URL:
            return SimpleNamespace(content="115年11月,120".encode())
        if url == m.TAICHUNG_DATASET_API:
            return SimpleNamespace(json=lambda: {"result": {"distribution": [
                {"resourceFormat": "JSON", "resourceDownloadUrl": TAICHUNG_URL}]}})
        if url == TAICHUNG_URL:
            if self.taichung_fails:
                raise TimeoutError("resource timeout")
            return SimpleNamespace(json=lambda: [
                {"項目": "營造工程物價指數-物價指數", "資料時間日期": "2026-11-01",
                 "欄位名稱": name, "數值": 110 + i} for i, name in enumerate(self.taichung)
            ])
        raise AssertionError(f"Unexpected fetch: {url}")

    def run_refresh(self, taipei, taichung=("材料類", "總指數"), *, fails=False, previous=None):
        self.taipei, self.taichung, self.taichung_fails = taipei, taichung, fails
        data = list(self.prev.values()) if previous is None else list(previous.values())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "materials.json"
            path.write_text(json.dumps({"items": data}), encoding="utf-8")
            with (patch.object(m, "MATERIALS_PATH", path), patch.object(m, "_get", self.request),
                  patch.object(m, "fetch_dgbas_cci", return_value=[]),
                  patch.object(m, "fetch_metaltrade", return_value=[]),
                  patch.object(m, "fetch_worldbank", return_value=[]),
                  patch.object(m, "fetch_twse", return_value=[]),
                  patch.object(m, "fetch_news_feed", return_value=[]),
                  patch.object(m, "log")):
                m.write_outputs(m.build_materials())
            result = json.loads(path.read_text(encoding="utf-8"))
        items = {i["id"]: i for i in result["items"]}
        self.assertEqual(len(items), len(result["items"]))
        return items, {s["source"]: s for s in result["sources_status"]}

    def test_taipei_failure_preserves_full_previous_rows_and_other_cities_update(self):
        items, status = self.run_refresh(TimeoutError("Taipei timeout"))
        for key in TAIPEI:
            self.assertEqual(items[key], dict(self.prev[key], stale=True))
        taipei = status["臺北市政府主計處"]
        self.assertFalse(taipei["ok"])
        self.assertEqual(taipei["stale_items"], 3)
        self.assertEqual(taipei["error"], "Taipei timeout")
        for key in ("cci_ntpc_total", "cci_txg_00", "cci_txg_01"):
            self.assertFalse(items[key]["stale"])
            self.assertEqual(items[key]["period"], "2026-11")
        self.assertEqual(items["cci_txg_00"]["name"], "臺中市 · 總指數")
        self.assertEqual(items["cci_txg_00"]["value"], 111)
        self.assertTrue(status["新北市政府主計處"]["ok"])
        self.assertTrue(status["臺中市政府主計處"]["ok"])

    def test_partial_taipei_preserves_missing_rows_and_recovers_on_next_run(self):
        items, status = self.run_refresh(TAIPEI_PARTIAL)
        self.assertEqual(items["cci_tpe_總指數"]["value"], 118)
        for key in ("cci_tpe_材料類", "cci_tpe_勞務類"):
            self.assertEqual(items[key], dict(self.prev[key], stale=True))
        self.assertFalse(status["臺北市政府主計處"]["ok"])
        self.assertEqual(status["臺北市政府主計處"]["fresh_items"], 1)
        recovered, status = self.run_refresh(TAIPEI_FULL, previous=items)
        self.assertTrue(status["臺北市政府主計處"]["ok"])
        for key in TAIPEI:
            self.assertFalse(recovered[key]["stale"])
            self.assertEqual(recovered[key]["period"], "2026-11")

    def test_partial_taichung_does_not_overwrite_a_different_series(self):
        items, status = self.run_refresh(TAIPEI_FULL, ("材料類", "新指數"))
        self.assertEqual(items["cci_txg_00"], dict(self.prev["cci_txg_00"], stale=True))
        self.assertEqual(items["cci_txg_01"]["name"], "臺中市 · 材料類")
        self.assertEqual(items["cci_txg_02"]["name"], "臺中市 · 新指數")
        self.assertFalse(status["臺中市政府主計處"]["ok"])

    def test_taichung_failure_leaves_taipei_fresh(self):
        items, status = self.run_refresh(TAIPEI_FULL, fails=True)
        self.assertFalse(status["臺中市政府主計處"]["ok"])
        self.assertEqual(items["cci_txg_01"], dict(self.prev["cci_txg_01"], stale=True))
        self.assertTrue(status["臺北市政府主計處"]["ok"])

    def test_unrecognized_taipei_response_without_backup_is_reported(self):
        items, status = self.run_refresh("<html>server error</html>", previous={})
        self.assertFalse(any(key.startswith("cci_tpe_") for key in items))
        self.assertFalse(status["臺北市政府主計處"]["ok"])
        self.assertEqual(status["臺北市政府主計處"]["missing_series"], sorted(TAIPEI))


if __name__ == "__main__":
    unittest.main()
