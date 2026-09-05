#!/usr/bin/env python3
"""Seed dashboard.html with the current data and write dashboard_build.html.

The published page subscribes to the artifact database for live updates, but a
first paint -- and any viewer whose grant does not resolve -- renders from the
data baked in here, so the dashboard is never a blank shell.
"""
import json

tpl = open("dashboard.html").read()
out = (tpl.replace("__CURRENT__", json.dumps(json.load(open("dashboard_current.json")), separators=(",", ":")))
          .replace("__HISTORY__", json.dumps(json.load(open("dashboard_history.json")), separators=(",", ":"))))
if "__CURRENT__" in out or "__HISTORY__" in out:
    raise SystemExit("placeholder not substituted -- refusing to write a broken page")
open("dashboard_build.html", "w").write(out)
print("dashboard_build.html: %.1f KB" % (len(out) / 1024))
