"""
Иконки процессов в «Диспетчере задач» и окне «Выбор процесса».

Настоящую иконку Windows отдаёт только по пути к .exe. get_running_processes
специально НЕ запрашивает exe (это вешало UI) — путь ищем точечно.
Если пути нет — в списке остаётся 🎮.

Запуск: python -m pytest tests/test_process_icons.py
"""

from __future__ import annotations

import os
import sys

import pytest

import process_monitor as pm


@pytest.fixture(autouse=True)
def _clear_exe_cache():
    pm.reset_exe_cache()
    yield
    pm.reset_exe_cache()


def test_get_running_processes_does_not_request_exe(monkeypatch):
    """Регресс: обход всех процессов с exe снова повесит UI."""
    seen = []

    def fake_iter(attrs):
        seen.append(list(attrs))
        return []

    monkeypatch.setattr(pm.psutil, "process_iter", fake_iter)
    pm._PROC_CACHE["ts"] = 0.0
    pm._PROC_CACHE["data"] = []
    pm.get_running_processes()
    assert seen, "process_iter должен быть вызван"
    for attrs in seen:
        assert "exe" not in attrs, f"get_running_processes запросил exe: {attrs}"


def test_resolve_empty_name():
    assert pm.resolve_process_exe("") is None
    assert pm.resolve_process_exe("   ") is None
    assert pm.resolve_process_exes(["", None, "  "]) == {}


def test_known_chrome_path(tmp_path, monkeypatch):
    appdir = tmp_path / "Google" / "Chrome" / "Application"
    appdir.mkdir(parents=True)
    exe = appdir / "chrome.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "nope"))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "nope"))
    path = pm.resolve_process_exe("chrome.exe")
    assert path == str(exe)
    # кэш
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert pm.resolve_process_exe("CHROME.EXE") == str(exe)


def test_discord_versioned_folder(tmp_path, monkeypatch):
    folder = tmp_path / "Discord" / "app-1.0.9000"
    folder.mkdir(parents=True)
    exe = folder / "Discord.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = pm.resolve_process_exe("discord.exe")
    assert path == str(exe)


def test_unknown_process_without_running_is_none(monkeypatch):
    monkeypatch.setattr(pm, "get_running_processes", lambda: [])
    assert pm.resolve_process_exe("definitely-not-installed-xyz.exe") is None


def test_resolve_from_running_pid(tmp_path, monkeypatch):
    exe = tmp_path / "foo.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(pm, "get_running_processes",
                        lambda: [{"pid": 4242, "name": "foo.exe"}])
    monkeypatch.setattr(pm, "_cheap_exe", lambda name: None)

    class _Proc:
        def exe(self):
            return str(exe)

    monkeypatch.setattr(pm.psutil, "Process", lambda pid: _Proc())
    assert pm.resolve_process_exe("foo.exe") == str(exe)


def test_resolve_skips_slow_lookup_on_negative_cache(monkeypatch):
    monkeypatch.setattr(pm, "get_running_processes", lambda: [{"pid": 1, "name": "bar.exe"}])
    monkeypatch.setattr(pm, "_cheap_exe", lambda name: None)
    calls = {"n": 0}

    class _Proc:
        def exe(self):
            calls["n"] += 1
            raise pm.psutil.AccessDenied(1)

    monkeypatch.setattr(pm.psutil, "Process", lambda pid: _Proc())
    assert pm.resolve_process_exe("bar.exe") is None
    assert pm.resolve_process_exe("bar.exe") is None
    assert calls["n"] == 1, "повторный промах не должен снова звать exe()"


def test_interrupt_stops_batch(monkeypatch):
    monkeypatch.setattr(pm, "_cheap_exe", lambda name: None)
    monkeypatch.setattr(pm, "get_running_processes", lambda: [])
    found = pm.resolve_process_exes(
        ["a.exe", "b.exe", "c.exe"], interrupt=lambda: True
    )
    assert found == {}


def test_adapter_wrappers_do_not_raise():
    import umbranet.engine_adapter as ea

    assert ea.resolve_process_exe("") is None
    assert ea.resolve_process_exes([]) == {}
    assert isinstance(ea.get_running_processes(), list)


def test_pixmap_for_missing_file():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from umbranet.process_icons import pixmap_for_exe, reset_icon_cache

    reset_icon_cache()
    assert pixmap_for_exe("/no/such/file.exe") is None
    assert pixmap_for_exe("") is None
    assert pixmap_for_exe(None) is None


def test_pixmap_for_existing_file(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from umbranet.process_icons import pixmap_for_exe, reset_icon_cache

    reset_icon_cache()
    fake = tmp_path / "app.exe"
    fake.write_bytes(b"MZ")
    pm_icon = pixmap_for_exe(str(fake))
    # на Linux без иконки темы провайдер может вернуть None — главное не упасть
    if pm_icon is not None:
        assert not pm_icon.isNull()


def test_gamepad_icon_not_null():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from umbranet.process_icons import gamepad_icon, reset_icon_cache

    reset_icon_cache()
    icon = gamepad_icon()
    assert icon is not None
    assert not icon.isNull()


def test_manual_canvas_paints_pixmap_and_fallback():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtGui = pytest.importorskip("PySide6.QtGui")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    from umbranet.widgets.manual_canvas import ManualCanvas

    canvas = ManualCanvas()
    canvas.resize(700, 200)
    pix = QtGui.QPixmap(16, 16)
    pix.fill(QtGui.QColor("red"))
    canvas.set_items([
        {"name": "chrome.exe", "key": "routed_processes", "icon": "🎮",
         "badge": "", "badge_color": "", "display": "chrome.exe",
         "protected": True, "pixmap": pix},
        {"name": "mystery.exe", "key": "routed_processes", "icon": "🎮",
         "badge": "", "badge_color": "", "display": "mystery.exe",
         "protected": False},
    ])
    grabbed = canvas.grab()
    assert not grabbed.isNull()
    canvas.deleteLater()
    app.processEvents()


def test_try_fill_process_icons(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtGui = pytest.importorskip("PySide6.QtGui")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    pix = QtGui.QPixmap(16, 16)
    pix.fill(QtGui.QColor("blue"))
    monkeypatch.setattr(
        "umbranet.process_icons.pixmap_for_process",
        lambda name, size=16: pix if name == "chrome.exe" else None,
    )
    from umbranet.widgets.manual_canvas import ManualCanvas

    canvas = ManualCanvas()
    canvas.set_items([
        {"name": "chrome.exe", "key": "routed_processes", "icon": "🎮",
         "badge": "", "badge_color": "", "display": "chrome.exe",
         "protected": True},
        {"name": "example.com", "key": "routed_domains", "icon": "🌐",
         "badge": "", "badge_color": "", "display": "example.com"},
    ])
    canvas.try_fill_process_icons()
    assert canvas._items[0].get("pixmap") is pix
    assert "pixmap" not in canvas._items[1]


def test_picker_rows_always_have_icon(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    monkeypatch.setattr(
        "umbranet.widgets.dialogs.ProcessPickerDialog._load", lambda self: None
    )
    from umbranet.widgets.dialogs import ProcessPickerDialog

    dlg = ProcessPickerDialog()
    dlg._all = ["chrome.exe", "foo.exe"]
    dlg._paths = {}
    dlg._show(["chrome.exe", "foo.exe"])
    assert dlg._list.count() == 2
    for i in range(dlg._list.count()):
        icon = dlg._list.item(i).icon()
        assert not icon.isNull(), "без настоящей иконки должна быть заглушка 🎮"
    dlg.close()
    dlg.deleteLater()


def test_picker_uses_real_icon_when_path_known(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    fake = tmp_path / "chrome.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setattr(
        "umbranet.widgets.dialogs.ProcessPickerDialog._load", lambda self: None
    )
    from umbranet.process_icons import reset_icon_cache
    from umbranet.widgets.dialogs import ProcessPickerDialog

    reset_icon_cache()
    dlg = ProcessPickerDialog()
    dlg._all = ["chrome.exe"]
    dlg._paths = {"chrome.exe": str(fake)}
    dlg._show(["chrome.exe"])
    assert dlg._list.count() == 1
    assert not dlg._list.item(0).icon().isNull()
    dlg.close()
    dlg.deleteLater()


def test_rebuild_attaches_pixmap_when_resolver_works(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtGui = pytest.importorskip("PySide6.QtGui")
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    pix = QtGui.QPixmap(16, 16)
    pix.fill(QtGui.QColor("green"))
    monkeypatch.setattr(
        "umbranet.views.routing.pixmap_for_process",
        lambda name: pix if str(name).lower() == "chrome.exe" else None,
    )

    from umbranet import engine_adapter as adapter
    from umbranet.views.routing import RoutingView

    engine = adapter.get_engine()
    old_procs = list(engine.config.get("routed_processes") or [])
    old_domains = list(engine.config.get("routed_domains") or [])
    old_subs = list(engine.config.get("routed_subscriptions") or [])
    view = RoutingView()
    try:
        engine.config["routed_processes"] = ["chrome.exe", "mystery.exe"]
        engine.config["routed_domains"] = []
        engine.config["routed_subscriptions"] = []
        view._manual_list_key = None
        view._rebuild_manual_list()
        items = view._manual_canvas._items
        procs = [it for it in items if it["key"] == "routed_processes"]
        by_name = {it["name"]: it for it in procs}
        assert "pixmap" in by_name["chrome.exe"]
        assert "pixmap" not in by_name["mystery.exe"]
        assert by_name["mystery.exe"]["icon"] == "🎮"
    finally:
        engine.config["routed_processes"] = old_procs
        engine.config["routed_domains"] = old_domains
        engine.config["routed_subscriptions"] = old_subs
        view.deleteLater()
