--[[----------------------------------------------------------------------------------------
ItemBrowser -- getting the item to the player.

A 3.3.5a addon cannot create items. The only lever it has is issuing a GM command, so this
file is where the whole feature can quietly do the wrong thing, and every decision in it was
read out of the core source rather than guessed. Paths below are relative to
.work/ac-src (the pinned AzerothCore clone).

WHICH COMMAND, AND DOES IT HIT THE SELECTION?
---------------------------------------------
'.additem' targets the SELECTED player, and falls back to the caster.

    src/server/scripts/Commands/cs_misc.cpp:1724
        static bool HandleAddItemCommand(ChatHandler* handler,
                                         Optional<PlayerIdentifier> player,
                                         ItemTemplate const* itemTemplate,
                                         Optional<int32> _count)
    cs_misc.cpp:1741-1742
        if (!player)
            player = PlayerIdentifier::FromTargetOrSelf(handler);

    src/server/game/Chat/ChatCommands/ChatCommandTags.h:189   FromTargetOrSelf
    src/server/game/Chat/ChatCommands/ChatCommandTags.cpp:141
        if (Player* target = player->GetSelectedPlayer())   return { *target };

So no separate "give to target" command is needed -- and '.send items' (cs_send.cpp:40) is
the wrong tool here: it mails the item instead of putting it in the bags.

BUT THE NAME IS ALWAYS PASSED EXPLICITLY. Here is why.
The first parameter is Optional<PlayerIdentifier>, and the optional-argument parser is
greedy with backtracking (src/server/game/Chat/ChatCommands/ChatCommand.h:72-99): it FIRST
tries to consume the next token as a player, and only retries without it if the rest of the
line then fails to parse. PlayerIdentifier::TryConsume accepts a bare number as a character
LOW GUID (ChatCommandTags.cpp:92-99). So '.additem 2589 20' is first attempted as
"give item 20 to the character whose guid is 2589". Today that reparses correctly because
item 20 does not exist -- it is saved by a lookup failure, not by design. Send the recipient
name and the ambiguity is gone: a name is never a number, so it can only parse one way.

    .additem Grishnak 49623 1        <- what this addon sends

The recipient must be online: HandleAddItemCommand bails on
GetConnectedPlayer() == nullptr (cs_misc.cpp:1747-1750). A selected player always is.

HOW THE COMMAND IS SENT
-----------------------
Two transports, probed at login, never both:

  1. ADDON CHANNEL (preferred). AzerothCore accepts commands over addon whispers and answers
     with a machine-readable ack/ok/fail, so the UI can say "server refused that" instead of
     leaving the user to read chat.
         src/server/game/Handlers/ChatHandler.cpp:302  -- lang == LANG_ADDON dispatches to
         src/server/game/Chat/Chat.cpp:1063            -- AddonChannelCommandHandler::ParseCommands
     Wire format, from that function:
         bytes  0..11  "AzerothCore\t"     (the addon message prefix plus the client's tab)
         byte      12  opcode: 'p' ping, 'i' issue command, 'h' issue human-readable
         bytes 13..16  a four-character echo counter, all bytes non-zero
         bytes 17..    the command, WITHOUT a leading dot -- it goes to _ParseCommands(),
                       not ParseCommands(), so the dot stripping has already happened
     Replies arrive as LANG_ADDON whispers from yourself: 'a'+echo ack, 'o'+echo ok,
     'f'+echo failed, 'm'+echo+text a message line.

  2. CHAT FALLBACK. SendChatMessage(".additem ...", "SAY"). The server intercepts any message
     beginning with '.' before it is broadcast (Chat.cpp:250-270 ParseCommands), so nothing is
     said out loud, but there is no structured reply -- output only lands in the chat frame.

The probe exists so the addon never has to guess. It also means a failed command is never
retried on the other transport: a lost acknowledgement is annoying, handing someone two
Shadowmournes is worse.
------------------------------------------------------------------------------------------]]

ItemBrowserTransport = {}

local T = ItemBrowserTransport

local PREFIX = "AzerothCore"
local PROBE_ECHO = "0000"
local PROBE_TIMEOUT = 5      -- seconds to wait for the ping ack before falling back
local REPLY_TIMEOUT = 8      -- seconds before a sent command is declared unanswered

T.mode = "probing"           -- "probing" | "addon" | "chat"
T.pending = {}               -- echo -> { onDone = function(ok, text), sent = GetTime() }

local nextEcho = 0
local probeSentAt = nil
-- Parented, not free-floating: a frame with a parent is reliably shown, and only a shown
-- frame runs OnUpdate, which is where the probe timeout and the reply deadline live.
local listener = CreateFrame("Frame", "ItemBrowserTransportFrame", UIParent)

--- Four printable digits. Must be exactly four bytes and none of them may be NUL:
--- Chat.cpp:1070-1071 drops the whole message if str[13]..str[16] are not all non-zero.
local function NextEcho()
    nextEcho = nextEcho + 1
    if nextEcho > 9999 then nextEcho = 1 end
    return string.format("%04d", nextEcho)
end

--- Names that could smuggle extra command arguments are refused, not escaped.
-- WoW character names cannot contain spaces or punctuation, so anything that does is either
-- a bug in the caller or an attempt to append arguments to the command line.
local function IsSafeName(name)
    return type(name) == "string" and name ~= "" and #name <= 24
        and string.find(name, "^[^%s%p%d]+$") ~= nil
end

function T:Describe()
    if self.mode == "addon" then
        return "addon channel (replies are read back from the server)"
    elseif self.mode == "chat" then
        return "chat command (output appears in your chat frame)"
    end
    return "probing..."
end

function T:Probe()
    self.mode = "probing"
    probeSentAt = GetTime()
    -- Opcode 'p': Chat.cpp:1076-1078 answers with an ack and nothing else. Harmless even
    -- to a server that has never heard of the protocol -- an unknown addon whisper to
    -- yourself is silently dropped.
    SendAddonMessage(PREFIX, "p" .. PROBE_ECHO, "WHISPER", UnitName("player"))
end

--- Ask the server to put `count` of `itemId` into `targetName`'s bags.
-- @param onDone  function(ok, text) -- ok is nil while unresolved on the chat transport
function T:AddItem(targetName, itemId, count, onDone)
    if not IsSafeName(targetName) then
        onDone(false, "Refusing to send a command for the name \"" ..
                      tostring(targetName) .. "\".")
        return
    end
    itemId = tonumber(itemId)
    count = tonumber(count)
    if not itemId or itemId < 1 or itemId ~= math.floor(itemId) then
        onDone(false, "Bad item id.")
        return
    end
    if not count or count < 1 or count ~= math.floor(count) then
        onDone(false, "Bad quantity.")
        return
    end

    local command = string.format("additem %s %d %d", targetName, itemId, count)

    if self.mode == "addon" then
        local echo = NextEcho()
        self.pending[echo] = { onDone = onDone, sent = GetTime(), acked = false }
        -- 'h' rather than 'i': human-readable output, so any 'm' line the server sends back
        -- (e.g. "inventory is full") is worth showing the user verbatim.
        SendAddonMessage(PREFIX, "h" .. echo .. command, "WHISPER", UnitName("player"))
    else
        -- No reply channel. Say so rather than claiming success.
        SendChatMessage("." .. command, "SAY")
        onDone(nil, "Sent. Watch your chat frame for the server's reply.")
    end
end

local function HandleReply(message)
    local opcode = string.sub(message, 1, 1)
    local echo = string.sub(message, 2, 5)
    local body = string.sub(message, 6)

    if echo == PROBE_ECHO then
        if T.mode == "probing" then
            T.mode = "addon"
        end
        return
    end

    local entry = T.pending[echo]
    if not entry then return end

    if opcode == "a" then                     -- acknowledged, still running
        entry.acked = true
    elseif opcode == "m" then                 -- a line of command output
        entry.text = (entry.text and (entry.text .. "\n") or "") .. body
    elseif opcode == "o" then                 -- succeeded
        T.pending[echo] = nil
        entry.onDone(true, entry.text)
    elseif opcode == "f" then                 -- refused or failed
        T.pending[echo] = nil
        entry.onDone(false, entry.text or "The server refused the command.")
    end
end

listener:RegisterEvent("CHAT_MSG_ADDON")
listener:RegisterEvent("PLAYER_ENTERING_WORLD")
listener:SetScript("OnEvent", function(self, event, prefix, message)
    if event == "PLAYER_ENTERING_WORLD" then
        if T.mode ~= "addon" then T:Probe() end
    elseif event == "CHAT_MSG_ADDON" and prefix == PREFIX then
        HandleReply(message)
    end
end)

listener:SetScript("OnUpdate", function()
    local now = GetTime()
    if T.mode == "probing" and probeSentAt and now - probeSentAt > PROBE_TIMEOUT then
        T.mode = "chat"
        probeSentAt = nil
    end
    for echo, entry in pairs(T.pending) do
        if now - entry.sent > REPLY_TIMEOUT then
            T.pending[echo] = nil
            -- Deliberately NOT resent on the other transport. An acknowledged command was
            -- definitely received and may well have run to completion; resending it would
            -- hand someone the item twice.
            entry.onDone(nil, entry.acked
                and ("The server took the command but never reported back. Check " ..
                     "the player's bags before trying again.")
                or ("No reply after " .. REPLY_TIMEOUT .. "s. Check the player's bags " ..
                    "before trying again, or /ib chat to use the chat transport."))
        end
    end
end)
