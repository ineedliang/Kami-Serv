-- VLC 3 desktop extension. The helper keeps TV playback independent of VLC's playlist.
function descriptor()
    return { title = "Share Library", version = "0.3.0-alpha.1", author = "Library Share Project",
        shortdesc = "Share your library with TVs", description = "Manage your media server, folders and TV playback preferences.", capabilities = {} }
end

local dialog, status_label, firewall_label, connection, page
local folder_input, label_input, type_input, folder_list, transfer_list, video_list
local name_input, icon_input, audio_input, position_input, offset_input, font_input, size_input, bold_input, color_input, outline_input
local burn_input, subtitle_input
local state, folders, videos = {}, {}, {}
local media_types = {"all", "video", "audio", "image"}
local media_labels = {"All media", "Video", "Music", "Photos"}
local audio_types = {"dolby", "default", "aac"}
local audio_labels = {"English Dolby when available", "File default", "English AAC when available"}
local positions = {"bottom", "file", "top"}
local position_labels = {"Bottom edge (all cues)", "File position + offset", "Top edge (all cues)"}

local function escape(text) return (text:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")) end
local function show_message(text) if status_label then status_label:set_text((escape(text):gsub("\n", "<br/>"))) end end
local function dropdown(widget, values, labels, selected, column, row, span)
    -- Recreate on a programmatic selection change. Qt's VLC 3 dropdown update
    -- only appends missing texts, even if clear()+add_value() happen together.
    if widget then dialog:del_widget(widget) end
    widget = dialog:add_dropdown(column, row, span or 1, 1)
    -- VLC's dropdown API selects its first value; there is no set_value method.
    for i, value in ipairs(values) do if value == selected then widget:add_value(labels[i], i) end end
    for i, value in ipairs(values) do if value ~= selected then widget:add_value(labels[i], i) end end
    return widget
end
local function update_fields()
    show_message(state.summary or "Start the helper, then refresh.")
    if page == "library" then
        folder_list:clear()
        for i, folder in ipairs(folders) do folder_list:add_value(folder.display or folder.path, i) end
        transfer_list:clear()
        for i, text in ipairs(state.transfers or {}) do transfer_list:add_value(text, i) end
    elseif page == "settings" then
        firewall_label:set_text(escape(state.firewallMessage or "Check or allow Windows Firewall access below."))
        name_input:set_text(state.serverName or "VLC Shared Library")
        audio_input = dropdown(audio_input, audio_types, audio_labels, state.audioPreference or "dolby", 2, 7, 3)
        position_input = dropdown(position_input, positions, position_labels, state.subtitlePosition or "bottom", 2, 8, 2)
        offset_input:set_text(state.subtitleOffset or "0"); font_input:set_text(state.font or "Arial")
        size_input:set_text(state.fontSize or "26"); bold_input:set_checked(state.bold == "true")
        color_input:set_text(state.color or "FFFFFF"); outline_input:set_text(state.outline or "2")
    elseif page == "prepare" then
        video_list:clear()
        for i, video in ipairs(videos) do video_list:add_value(video.title, i) end
    end
end

local function request(action, parameters, preserve_fields)
    if not connection then show_message("Run install-vlc-plugin.cmd first, then reopen VLC."); return false end
    local url = "http://127.0.0.1:" .. connection.port .. "/local?token=" .. connection.token .. "&action=" .. action
    for key, value in pairs(parameters or {}) do url = url .. "&" .. key .. "=" .. vlc.strings.encode_uri_component(tostring(value)) end
    local ok, response = pcall(function()
        local stream = vlc.stream(url)
        if not stream then error("Cannot reach helper") end
        return stream:read(1048576)
    end)
    if not ok or not response then show_message("Helper is stopped. Click Start helper, then Refresh status."); return false end
    local xml_stream = vlc.memory_stream(response)
    local reader = vlc.xml():create_reader(xml_stream)
    local tag, error_message = "", nil
    local new_state, new_folders, new_videos = {transfers = {}}, {}, {}
    local folder, video
    while true do
        local kind, value = reader:next_node()
        if not kind or kind <= 0 then break end
        if kind == 1 then tag = value
        elseif kind == 2 then tag = ""
        elseif kind == 3 then
            if tag == "error" then error_message = value
            elseif tag == "folder" then folder = {path = value}; new_folders[#new_folders+1] = folder
            elseif tag == "folderLabel" and folder then folder.label = value
            elseif tag == "folderType" and folder then folder.kind = value
            elseif tag == "folderDisplay" and folder then folder.display = value
            elseif tag == "videoId" then video = {id = value}; new_videos[#new_videos+1] = video
            elseif tag == "videoTitle" and video then video.title = value
            elseif tag == "transfer" or tag == "recentTransfer" or tag == "warning" then new_state.transfers[#new_state.transfers+1] = value
            else new_state[tag] = value end
        end
    end
    if error_message then show_message(error_message); return false end
    state, folders, videos = new_state, new_folders, new_videos
    if preserve_fields == "firewall" then
        show_message(state.firewallMessage or "Checking Windows Firewall...")
        if firewall_label then firewall_label:set_text(escape(state.firewallMessage or "")) end
    elseif preserve_fields then show_message(state.pickerMessage or "Opening chooser...")
    else update_fields() end
    if state.pickedFolder and folder_input then folder_input:set_text(state.pickedFolder) end
    if state.pickedIcon and icon_input then icon_input:set_text(state.pickedIcon) end
    dialog:update()
    return true
end

function refresh_status() request("status") end
function start_helper()
    if connection and connection.start_command then
        show_message("Starting helper..."); dialog:update()
        os.execute(connection.start_command)
        refresh_status()
    else show_message("Reinstall the plugin to add the helper launcher.") end
end
function enable_sharing() request("enable") end
function disable_sharing() request("disable") end
function rescan_library() request("rescan") end
function add_folder()
    request("add", {folder = folder_input:get_text(), label = label_input:get_text(), mediaType = media_types[type_input:get_value()] or "all"})
end
function edit_folder()
    for id, _ in pairs(folder_list:get_selection()) do
        local folder = folders[id]
        if folder then
            folder_input:set_text(folder.path); label_input:set_text(folder.label or "")
            type_input = dropdown(type_input, media_types, media_labels, folder.kind or "all", 3, 5)
            show_message("Edit the label or media type, then click Add / update folder.")
            break
        end
    end
end
function remove_folders()
    local paths = {}
    for id, _ in pairs(folder_list:get_selection()) do if folders[id] then paths[#paths+1] = folders[id].path end end
    for _, path in ipairs(paths) do request("remove", {folder = path}) end
end
local function pick(kind)
    -- Do not refresh fields here: users may have typed a label/server name or
    -- changed playback settings before clicking Browse.
    if not request("pick-" .. kind, nil, true) then return end
    while state.pickerActive == "true" do
        if vlc.keep_alive then vlc.keep_alive() end
        if not request("picker-wait", nil, true) then return end
    end
end
function pick_folder() pick("folder") end
function pick_icon() pick("icon") end
local function firewall_setup(allow)
    if not request(allow and "firewall-allow" or "firewall-check", nil, "firewall") then return end
    while state.firewallActive == "true" do
        if vlc.keep_alive then vlc.keep_alive() end
        if not request("firewall-wait", nil, "firewall") then return end
    end
end
function allow_firewall() firewall_setup(true) end
function check_firewall() firewall_setup(false) end
function save_identity()
    if request("identity", {name = name_input:get_text(), icon = icon_input:get_text()}) then icon_input:set_text("") end
end
function clear_icon() request("identity", {name = name_input:get_text(), clearIcon = "true"}) end
function save_playback()
    request("settings", {audio = audio_types[audio_input:get_value()] or "dolby", position = positions[position_input:get_value()] or "bottom",
        offset = offset_input:get_text(), font = font_input:get_text(), size = size_input:get_text(), bold = tostring(bold_input:get_checked()),
        color = color_input:get_text(), outline = outline_input:get_text()})
end
local function prepare(full)
    local selected = nil
    for id, _ in pairs(video_list:get_selection()) do
        if selected then show_message("Choose one video at a time."); return end
        selected = videos[id]
    end
    if not selected then show_message("Select a video first."); return end
    request("prepare", {id = selected.id, burn = tostring(burn_input:get_checked()), subtitle = subtitle_input:get_text(), full = tostring(full)})
end
function prepare_preview() prepare(false) end
function prepare_full() prepare(true) end

function show_page(selected)
    if dialog then dialog:delete() end
    page = selected
    folder_input, label_input, type_input, folder_list, transfer_list, video_list = nil, nil, nil, nil, nil, nil
    icon_input = nil
    firewall_label = nil
    dialog = vlc.dialog("Share Library")
    status_label = dialog:add_label("Connecting...", 1, 1, 4, 1)
    dialog:add_button("Library folders", function() show_page("library") end, 1, 2)
    dialog:add_button("Server & playback", function() show_page("settings") end, 2, 2)
    dialog:add_button("Prepare for TV", function() show_page("prepare") end, 3, 2)
    dialog:add_button("Start helper", start_helper, 4, 2)
    dialog:add_button("Enable sharing", enable_sharing, 1, 3)
    dialog:add_button("Stop sharing", disable_sharing, 2, 3)
    dialog:add_button("Refresh status", refresh_status, 3, 3)
    dialog:add_button("Rescan files", rescan_library, 4, 3)
    if page == "library" then
        dialog:add_label("Folder path:", 1, 4)
        folder_input = dialog:add_text_input("", 2, 4, 2, 1)
        dialog:add_button("Browse...", pick_folder, 4, 4)
        dialog:add_label("Label on TV:", 1, 5)
        label_input = dialog:add_text_input("", 2, 5)
        type_input = dialog:add_dropdown(3, 5)
        type_input = dropdown(type_input, media_types, media_labels, "all", 3, 5)
        dialog:add_button("Add / update folder", add_folder, 4, 5)
        folder_list = dialog:add_list(1, 6, 4, 3)
        dialog:add_button("Edit selected", edit_folder, 1, 9, 2, 1)
        dialog:add_button("Remove selected", remove_folders, 3, 9, 2, 1)
        dialog:add_label("Active + recent requests (last 10 minutes) / scan warnings:", 1, 10, 3, 1)
        dialog:add_button("Refresh activity", refresh_status, 4, 10)
        transfer_list = dialog:add_list(1, 11, 4, 3)
        dialog:add_label("Activity updates when refreshed. RECENT means a past request; it does not indicate play/pause state.", 1, 14, 4, 1)
    elseif page == "settings" then
        dialog:add_label("Server name:", 1, 4)
        name_input = dialog:add_text_input("", 2, 4, 3, 1)
        dialog:add_label("New icon image:", 1, 5)
        icon_input = dialog:add_text_input("", 2, 5, 2, 1)
        dialog:add_button("Browse icon...", pick_icon, 4, 5)
        dialog:add_button("Save server identity", save_identity, 1, 6, 2, 1)
        dialog:add_button("Remove custom icon", clear_icon, 3, 6, 2, 1)
        dialog:add_label("Audio preference:", 1, 7)
        audio_input = dialog:add_dropdown(2, 7, 3, 1)
        dialog:add_label("Subtitle position:", 1, 8)
        position_input = dialog:add_dropdown(2, 8, 2, 1)
        offset_input = dialog:add_text_input("0", 4, 8)
        dialog:add_label("Offset applies to File position: positive = up, negative = down (pixels).", 1, 9, 4, 1)
        dialog:add_label("Text font / size (px):", 1, 10)
        font_input = dialog:add_text_input("Arial", 2, 10)
        size_input = dialog:add_text_input("26", 3, 10)
        bold_input = dialog:add_check_box("Bold", false, 4, 10)
        dialog:add_label("Text color (RRGGBB):", 1, 11)
        color_input = dialog:add_text_input("FFFFFF", 2, 11)
        dialog:add_label("Outline (0-10):", 3, 11)
        outline_input = dialog:add_text_input("2", 4, 11)
        dialog:add_label("Font styling: plain text subtitles. DVD/image captions keep their original lettering.<br/>Preferences apply to newly prepared files. Existing files stay as they are.", 1, 12, 4, 1)
        dialog:add_button("Save playback preferences", save_playback, 1, 13, 4, 1)
        firewall_label = dialog:add_label("", 1, 14, 4, 1)
        dialog:add_button("Check firewall", check_firewall, 1, 15, 2, 1)
        dialog:add_button("Allow / repair firewall access", allow_firewall, 3, 15, 2, 1)
        dialog:add_label("Private networks and local subnet only. Allow / repair requests Windows administrator permission.", 1, 16, 4, 1)
    else
        dialog:add_label("Shared videos (first 500): select one to prepare a separate MKV for TV.", 1, 4, 4, 1)
        video_list = dialog:add_list(1, 5, 4, 4)
        burn_input = dialog:add_check_box("Burn subtitles into video", false, 1, 9, 2, 1)
        dialog:add_label("Subtitle track (0 = first):", 3, 9)
        subtitle_input = dialog:add_text_input("0", 4, 9)
        dialog:add_button("Prepare & share 2 min preview", prepare_preview, 1, 10, 2, 1)
        dialog:add_button("Prepare & share full file", prepare_full, 3, 10, 2, 1)
        dialog:add_label("Refresh to see completion. Finished files appear under Prepared for TV.<br/>Audio preference uses existing English tracks; it does not change channel count.<br/>Burn-in re-encodes video. Original files are kept intact.", 1, 11, 4, 1)
    end
    update_fields()
    refresh_status()
end
function activate()
    local ok, settings = pcall(require, "library_share_config")
    connection = ok and settings or nil
    show_page("library")
    if connection and connection.manage_lifetime then start_helper() end
end
function close() vlc.deactivate() end
function deactivate()
    if dialog then dialog:delete() end
    dialog = nil
end
