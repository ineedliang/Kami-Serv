"""Real VLC playback + Lua API smoke checks, using only generated WAV media.

The extension's widget rendering is stubbed; its code, Lua interpreter, HTTP
transport, XML reader and helper are real. This does not certify the Qt layout.
No normal VLC settings or extensions are modified.
"""
import ctypes
import hashlib
import math
import os
import pathlib
import re
import struct
import subprocess
import time
import urllib.request
import wave

from integration import Integration, ROOT


def eventually(predicate, message, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(message)


def playback(vlc_dir, url):
    dll_context = os.add_dll_directory(str(vlc_dir))
    lib = ctypes.CDLL(str(vlc_dir / "libvlc.dll"))
    def bind(name, result, *arguments):
        function = getattr(lib, name)
        function.restype = result
        function.argtypes = list(arguments)
        return function
    ptr, integer, time_type = ctypes.c_void_p, ctypes.c_int, ctypes.c_int64
    new = bind("libvlc_new", ptr, integer, ctypes.POINTER(ctypes.c_char_p))
    release = bind("libvlc_release", None, ptr)
    media_new = bind("libvlc_media_new_location", ptr, ptr, ctypes.c_char_p)
    media_release = bind("libvlc_media_release", None, ptr)
    player_new = bind("libvlc_media_player_new_from_media", ptr, ptr)
    player_release = bind("libvlc_media_player_release", None, ptr)
    play = bind("libvlc_media_player_play", integer, ptr)
    stop = bind("libvlc_media_player_stop", None, ptr)
    pause = bind("libvlc_media_player_set_pause", None, ptr, integer)
    get_time = bind("libvlc_media_player_get_time", time_type, ptr)
    set_time = bind("libvlc_media_player_set_time", None, ptr, time_type)
    state = bind("libvlc_media_player_get_state", integer, ptr)
    seekable = bind("libvlc_media_player_is_seekable", integer, ptr)
    arguments = [b"--ignore-config", b"--no-plugins-cache", b"--aout=dummy", b"--vout=dummy",
                 b"--no-metadata-network-access", b"--quiet"]
    instance = new(len(arguments), (ctypes.c_char_p * len(arguments))(*arguments))
    assert instance, "Could not initialize installed LibVLC"
    players = []
    try:
        for _ in range(4):
            media = media_new(instance, url.encode())
            assert media
            player = player_new(media)
            media_release(media)
            assert player
            players.append(player)
            assert play(player) == 0
        eventually(lambda: all(get_time(p) > 750 for p in players), "Four VLC players did not all start")
        assert all(seekable(p) for p in players), "VLC did not recognize streams as seekable"
        pause(players[0], 1)
        eventually(lambda: state(players[0]) == 4, "First VLC session did not pause")
        paused_at = get_time(players[0])
        other_at = get_time(players[1])
        time.sleep(1.1)
        assert abs(get_time(players[0]) - paused_at) < 150
        assert get_time(players[1]) > other_at + 500, "Pausing one session affected another"
        pause(players[0], 0)
        set_time(players[0], 30000)
        eventually(lambda: get_time(players[0]) >= 30000, "Forward seek failed")
        assert get_time(players[1]) < 10000, "Seeking one session changed another's position"
        set_time(players[0], 5000)
        eventually(lambda: 5000 <= get_time(players[0]) < 10000, "Backward seek failed")
        assert all(state(p) == 3 for p in players), "One of four sessions stopped unexpectedly"
        print("PASS: four real VLC players; independent pause, resume, forward and backward seeking")
    finally:
        for player in players:
            stop(player)
            player_release(player)
        release(instance)
        dll_context.close()


def lua_api(vlc_dir, test, executable=None, extension_path=None, bootstrap=False, picker_tests=False, firewall_tests=False, srt_tests=False):
    variant = "portable" if executable else "installed"
    profile = test.work / ("isolated-appdata-" + variant)
    interfaces = profile / "vlc/lua/intf"
    interfaces.mkdir(parents=True)
    marker = test.work / ("lua-result-" + variant + ".txt")
    # Long Lua strings avoid interpreting backslashes in Windows paths.
    extension = (extension_path or ROOT / "vlc/library_share.lua").as_posix()
    modules = (test.work / "extension/modules/?.lua").as_posix()
    media = test.media.as_posix()
    second_media_path = test.work / "Second library"
    second_media_path.mkdir(exist_ok=True)
    (second_media_path / "Second clip.mp4").write_bytes(b"second-folder-fixture")
    second_media = second_media_path.as_posix()
    marker_path = marker.as_posix()
    activity_check = ""
    if not bootstrap:
        # A tiny range finishes before VLC opens the panel. It must still appear
        # there as RECENT, proving that short TV requests cannot vanish unseen.
        fixture = next(test.media.glob("*.mp4"))
        identifier = hashlib.sha256(str(fixture.resolve()).upper().encode()).hexdigest()[:32].upper()
        module_text = (test.work / "extension/modules/library_share_config.lua").read_text()
        port = re.search(r"port = (\d+)", module_text)[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(f"http://127.0.0.1:{port}/media/{identifier}/fixture.mp4", headers={"Range": "bytes=0-31"}), timeout=5) as response:
            response.read()
        activity_check = '''
    local found_recent = false
    for _, text in pairs(lists[2].values) do
        if text:find("RECENT", 1, true) and text:find([[''' + fixture.name + ''']], 1, true) then found_recent = true end
    end
    assert(found_recent, "Completed short request was not rendered in the activity window")
    '''
    picker_library = '''
    inputs[1].text = "before browsing"
    inputs[2].text = "Keep my folder label"
    pick_folder()
    assert(inputs[1].text == [[''' + media + ''']], "Chosen folder did not automatically fill the input")
    assert(inputs[2].text == "Keep my folder label", "Browse erased the folder label")
    ''' if picker_tests else ""
    firewall_settings = '''
    inputs[settings_input].text = "Keep firewall name edits"
    inputs[settings_input+4].text = "39"
    check_firewall()
    assert(labels[#labels-1].text ~= nil)
    allow_firewall()
    assert(inputs[settings_input].text == "Keep firewall name edits", "Firewall operation erased server name")
    assert(inputs[settings_input+4].text == "39", "Firewall operation erased subtitle preferences")
    ''' if firewall_tests else ""
    picker_settings = '''
    inputs[settings_input].text = "Keep my unsaved server name"
    inputs[settings_input+4].text = "37"
    pick_icon()
    assert(inputs[settings_input].text == "Keep my unsaved server name", "Icon chooser erased the server name")
    assert(inputs[settings_input+4].text == "37", "Icon chooser erased subtitle preferences")
    assert(inputs[settings_input+1].text == [[''' + media + '''/icon & test.png]], "Chosen icon did not automatically fill the input")
    ''' if picker_tests else ""
    srt_prepare = '''
    local video_widget = lists[#lists]
    local selected_id, other_id
    for id, title in pairs(video_widget.values) do
        if title == "A & B.mp4" then selected_id = id else other_id = id end
    end
    assert(selected_id and other_id, "SRT test videos not listed")
    video_widget.get_selection = function() return {[selected_id] = true} end
    load_subtitles()
    local source_dropdown = dropdowns[#dropdowns]
    assert(source_dropdown.values[2] == "A & B.srt", "Matching SRT choices not populated")
    source_dropdown.selected = 2
    local original_stream = vlc.stream
    local submitted = nil
    vlc.stream = function(url)
        if url:find("action=prepare", 1, true) then
            submitted = url
            return vlc.memory_stream("<library><summary>Sharing: ON</summary></library>")
        end
        return original_stream(url)
    end
    prepare_preview()
    assert(submitted and submitted:find("sidecar=", 1, true), "SRT selection not submitted")
    assert(not submitted:find("sidecar=&", 1, true) and not submitted:match("sidecar=$"), "Empty SRT selection")
    video_widget.get_selection = function() return {[other_id] = true} end
    submitted = nil
    prepare_full()
    assert(not submitted, "SRT selection from a different video was submitted")
    vlc.stream = original_stream
    ''' if srt_tests else ""
    script = f'''
local function run()
    package.path = [[{modules}]] .. ";" .. package.path
    local labels, inputs, lists, dropdowns = {{}}, {{}}, {{}}, {{}}
    local function widget(text)
        return {{ text = text, values = {{}}, checked = false,
            set_text = function(self, value) self.text = value end,
            get_text = function(self) return self.text end,
            clear = function(self) self.values = {{}}; self.first = nil end,
            add_value = function(self, text, id) self.values[id] = text; self.first = self.first or id end,
            get_value = function(self) return self.selected or self.first end,
            set_checked = function(self, value) self.checked = value end,
            get_checked = function(self) return self.checked end,
            get_selection = function(self) return {{}} end }}
    end
    vlc.dialog = function(title)
        assert(title == "Share Library")
        return {{
            add_label = function(self, text, ...) local w = widget(text); labels[#labels+1] = w; return w end,
            add_button = function(self, text, callback, ...) assert(type(callback) == "function"); return widget(text) end,
            add_text_input = function(self, text, ...) local w = widget(text); inputs[#inputs+1] = w; return w end,
            add_list = function(self, ...) local w = widget(""); lists[#lists+1] = w; return w end,
            add_dropdown = function(self, ...) local w = widget(""); dropdowns[#dropdowns+1] = w; return w end,
            add_check_box = function(self, text, checked, ...) local w = widget(text); w.checked = checked; return w end,
            update = function() end, delete = function() end, del_widget = function() end
        }}
    end
    dofile([[{extension}]])
    assert(descriptor().title == "Share Library")
    activate()
    {"start_helper()" if bootstrap else ""}
    assert(labels[1].text:find("Sharing: ON", 1, true), labels[1].text)
    {activity_check}
    inputs[1].text = [[{media}]]
    add_folder()
    assert(lists[1].values[1], "Shared folders not parsed by actual VLC XML reader")
    local first_folder = lists[1].values[1]
    inputs[1].text = [[{second_media}]]
    inputs[2].text = "Second library"
    add_folder()
    assert(lists[1].values[1] == first_folder, "Adding a second folder changed the first")
    assert(lists[1].values[2] and lists[1].values[2]:find("Second library", 1, true), "Second folder was not appended")
    refresh_status()
    assert(lists[1].values[1] == first_folder and lists[1].values[2], "Refresh lost one of the folders")
    disable_sharing()
    assert(labels[1].text:find("Sharing: OFF", 1, true), labels[1].text)
    enable_sharing()
    rescan_library()
    assert(labels[1].text:find("Sharing: ON", 1, true), labels[1].text)
    {picker_library}
    local settings_input = #inputs+1
    show_page("settings")
    {picker_settings}
    {firewall_settings}
    save_playback()
    show_page("prepare")
    prepare_preview() -- No selection: must not launch a conversion.
    {srt_prepare}
    show_page("library")
    deactivate()
    -- Closing only the panel must leave sharing available while VLC is alive.
    local connection = require("library_share_config")
    local stream = assert(vlc.stream("http://127.0.0.1:" .. connection.port .. "/local?action=status&token=" .. connection.token))
    assert(stream:read(1048576):find("Sharing: ON", 1, true), "Panel closure stopped the helper")
end
local ok, message = pcall(run)
local result = assert(io.open([[{marker_path}]], "w"))
result:write(ok and "PASS" or tostring(message))
result:close()
vlc.misc.quit()
'''
    (interfaces / "share_smoke.lua").write_text(script, encoding="utf-8")
    environment = os.environ.copy()
    environment["APPDATA"] = str(profile)
    environment["LOCALAPPDATA"] = str(profile / "local")
    environment["VLC_DATA_PATH"] = str(profile / "vlc")
    environment["VLC_PLUGIN_PATH"] = str(vlc_dir / "plugins")
    log_path = test.work / ("vlc-lua-" + variant + ".log")
    arguments = [str(executable or vlc_dir / "vlc.exe"), "--ignore-config", "--no-one-instance", "--no-plugins-cache",
        "--no-media-library", f"--config={profile / 'vlcrc'}",
        "--intf=luaintf", "--lua-intf=share_smoke", "--no-metadata-network-access", "--aout=dummy", "--vout=dummy",
        "--file-logging", f"--logfile={log_path}", "--verbose=2"]
    process = subprocess.Popen(arguments, env=environment, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        process.wait(timeout=15)
        assert marker.exists(), "VLC Lua harness did not execute; inspect " + str(log_path)
        assert marker.read_text() == "PASS", marker.read_text()
        print("PASS: extension callbacks using installed VLC's Lua, HTTP transport and XML reader (widgets stubbed)")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def main():
    vlc_dir = pathlib.Path(os.environ.get("VLC_DIR", r"C:\Program Files\VideoLAN\VLC"))
    if not (vlc_dir / "libvlc.dll").exists():
        raise RuntimeError("Set VLC_DIR to a desktop VLC installation")
    Integration.setUpClass()
    test = Integration()
    try:
        wav_path = test.media / "Playback.wav"
        rate = 48000
        samples = b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(rate))
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(samples * 60)
        url = test.media_url("Playback.wav")
        playback(vlc_dir, url)
        lua_api(vlc_dir, test)
        preview = ROOT / "build/vlc-preview/vlc.exe"
        if preview.exists():
            lua_api(vlc_dir, test, executable=preview)
            print("PASS: portable preview executable loads the installed plugins and runs the Lua integration")
    finally:
        Integration.tearDownClass()


if __name__ == "__main__":
    main()
