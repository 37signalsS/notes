# Lua-скрипты в Wireshark — автоматизация и кастомизация

> **SSoT:** Базовые функции Wireshark — в **[Определения](./definitions.md)**. Использование tshark — в **[Использование tshark](./tshark_usage.md)**. Продвинутые функции — в **[Продвинутые функции](./advanced_features.md)**.

## Определения

**Dissector (Диссектор)** — программный модуль, обучающий Wireshark понимать структуру протокола. Более 3000 встроенных диссекторов (C). Lua позволяет писать пользовательские диссекторы без перекомпиляции.

**Lua Scripting** — встраиваемый язык программирования в Wireshark (Lua 5.4). Позволяет создавать: кастомные диссекторы, post-dissectors (модификация после диссекции), tap-обработчики (сбор статистики), корректировщики (rename fields), и listeners (реакция на пакеты).

**Tap** — механизм перехвата пакетов в Wireshark для построения статистики. Tap-функция вызывается для каждого пакета, проходящего фильтр, и может накапливать данные для вывода в окно статистики.

**Listener** — callback-функция Lua, вызываемая при определённых событиях (новый пакет, обновление дерева протоколов, завершение захвата).

## Quick-Start: Типы Lua-скриптов

| Тип | Назначение | Файл |
| :--- | :--- | :--- |
| **Dissector** | Декодирование нового протокола | `<protocol>.lua` |
| **Post-dissector** | Добавление полей после диссекции | `post_dissector.lua` |
| **Tap** | Построение статистики | `tap.lua` |
| **Listener** | Реакция на пакеты | `init.lua` |
| **_corr** | Переименование полей | `corr.lua` |

## Основные концепции

### Структура Lua-скрипта

```lua
-- Базовый шаблон диссектора
local my_proto = Proto("myproto", "My Custom Protocol")

-- Определение полей
local f_field1 = ProtoField.uint8("myproto.field1", "Field 1", base.HEX)
local f_field2 = ProtoField.string("myproto.field2", "Field 2")
local f_field3 = ProtoField.uint16("myproto.field3", "Field 3", base.DEC)

my_proto.fields = {f_field1, f_field2, f_field3}

-- Функция диссекции
function my_proto.dissector(buffer, pinfo, tree)
    local length = buffer:len()
    if length == 0 then return end

    pinfo.cols.protocol = my_proto.name

    local subtree = tree:add(my_proto, buffer(), "My Protocol")

    subtree:add(f_field1, buffer(0, 1))
    subtree:add(f_field2, buffer(1, 4))
    subtree:add(f_field3, buffer(5, 2))
end

-- Регистрация диссектора
local tcp_table = DissectorTable.get("tcp.port")
tcp_table:add(12345, my_proto)
```

### Post-dissector: Добавление вычисляемых полей

```lua
-- Post-dissector: добавляет вычисленное поле к каждому пакету
local my_post = Proto("mypost", "My Post Dissector")

function my_post.init()
    -- Инициализация (вызывается один раз)
end

function my_post.dissector(buffer, pinfo, tree)
    -- Добавляем вычисленное поле
    local length = buffer:len()
    tree:add(my_post, buffer(), "Payload Length: " .. length)

    -- Добавляем в колонку
    pinfo.cols.info = pinfo.cols.info .. " [Len=" .. length .. "]"
end

-- Регистрация как post-dissector
register_post_dissector(my_post)
```

### Tap для статистики

```lua
-- Tap: сбор статистики по IP-адресам
local mytap = Listener.new("ip")

local stats = {}

function mytap.packet()
    local ip_src = Field.new("ip.src")
    local ip_dst = Field.new("ip.dst")

    local src = ip_src()
    local dst = ip_dst()

    if src then
        stats[tostring(src)] = (stats[tostring(src)] or 0) + 1
    end
end

function mytap.reset()
    stats = {}
end

-- Вывод статистики (через меню Tools → Lua → ...)
function draw_stats()
    local win = TextWindow.new("IP Statistics")
    for ip, count in pairs(stats) do
        win:append(ip .. ": " .. count .. " packets\n")
    end
end

register_menu("IP Stats", draw_stats, MENU_TOOLS_UNSORTED)
```

### Корректировщик (Name Resolution)

```lua
-- Переименование полей Wireshark
local my_corr = Proto("mycorr", "My Correlator")

function my_corr.init()
    -- Добавляем значение к существующему полю
end

function my_corr.dissector(buffer, pinfo, tree)
    local tcp_dstport = Field.new("tcp.dstport")
    local dstport = tcp_dstport()

    if dstport == 80 then
        pinfo.cols.info = pinfo.cols.info .. " [HTTP]"
    elseif dstport == 443 then
        pinfo.cols.info = pinfo.cols.info .. " [HTTPS]"
    end
end

register_post_dissector(my_corr)
```

## Практические сценарии

### Сценарий 1: Диссектор для кастомного протокола

```lua
-- Диссектор для простого бинарного протокола:
-- [2 bytes: length][1 byte: command][N bytes: payload]

local my_proto = Proto("myproto", "My Custom Protocol")

local f_len = ProtoField.uint16("myproto.length", "Length", base.DEC)
local f_cmd = ProtoField.uint8("myproto.command", "Command", base.DEC, {
    [0x01] = "HEARTBEAT",
    [0x02] = "DATA",
    [0x03] = "ACK",
    [0x04] = "NACK"
})
local f_payload = ProtoField.bytes("myproto.payload", "Payload")

my_proto.fields = {f_len, f_cmd, f_payload}

function my_proto.dissector(buffer, pinfo, tree)
    if buffer:len() < 3 then return end

    pinfo.cols.protocol = "MYPROTO"
    local subtree = tree:add(my_proto, buffer(), "My Custom Protocol")

    local length = buffer(0, 2):uint()
    subtree:add(f_len, buffer(0, 2))
    subtree:add(f_cmd, buffer(2, 1))

    if buffer:len() > 3 then
        subtree:add(f_payload, buffer(3))
    end

    -- Переименование в Info column
    local cmd = buffer(2, 1):uint()
    local cmd_names = {[1]="HEARTBEAT", [2]="DATA", [3]="ACK", [4]="NACK"}
    pinfo.cols.info = cmd_names[cmd] or "UNKNOWN"
end

-- Регистрация на порту 12345
local tcp_table = DissectorTable.get("tcp.port")
tcp_table:add(12345, my_proto)
```

### Сценарий 2: Сбор статистики по DNS-запросам

```lua
-- Tap: подсчёт уникальных DNS-имен
local dns_tap = Listener.new("dns")

local dns_queries = {}
local dns_count = 0

function dns_tap.packet()
    local dns_qry_name = Field.new("dns.qry.name")
    local dns_flags_response = Field.new("dns.flags.response")

    local name = dns_qry_name()
    local is_response = dns_flags_response()

    if name and is_response == 0 then
        dns_queries[tostring(name)] = (dns_queries[tostring(name)] or 0) + 1
        dns_count = dns_count + 1
    end
end

function dns_tap.reset()
    dns_queries = {}
    dns_count = 0
end

function show_dns_stats()
    local win = TextWindow.new("DNS Query Statistics")
    win:append("Total queries: " .. dns_count .. "\n\n")
    win:append(string.format("%-50s %s\n", "Domain", "Count"))
    win:append(string.rep("-", 60) .. "\n")

    -- Сортировка по количеству
    local sorted = {}
    for domain, count in pairs(dns_queries) do
        table.insert(sorted, {domain=domain, count=count})
    end
    table.sort(sorted, function(a,b) return a.count > b.count end)

    for _, item in ipairs(sorted) do
        win:append(string.format("%-50s %d\n", item.domain, item.count))
    end
end

register_menu("DNS Statistics", show_dns_stats, MENU_TOOLS_UNSORTED)
```

### Сценарий 3: Автоматическая разметка проблем TCP

```lua
-- Post-dissector: помечает пакеты с проблемами TCP
local tcp_issues = Proto("tcpissues", "TCP Issues")

function tcp_issues.dissector(buffer, pinfo, tree)
    local retransmission = Field.new("tcp.analysis.retransmission")
    local zero_window = Field.new("tcp.analysis.zero_window")
    local duplicate_ack = Field.new("tcp.analysis.duplicate_ack")
    local out_of_order = Field.new("tcp.analysis.out_of_order")

    local issues = {}

    if retransmission() then table.insert(issues, "RETRANS") end
    if zero_window() then table.insert(issues, "ZERO_WINDOW") end
    if duplicate_ack() then table.insert(issues, "DUP_ACK") end
    if out_of_order() then table.insert(issues, "OUT_OF_ORDER") end

    if #issues > 0 then
        tree:add(tcp_issues, buffer(), "Issues: " .. table.concat(issues, ", "))
        pinfo.cols.info = pinfo.cols.info .. " [" .. table.concat(issues, ", ") .. "]"
    end
end

register_post_dissector(tcp_issues)
```

### Сценарий 4: Экспорт данных в CSV

```lua
-- Tap: экспорт HTTP-запросов в CSV
local http_tap = Listener.new("http")

local csv_data = {}

function http_tap.packet()
    local http_host = Field.new("http.host")
    local http_request_method = Field.new("http.request.method")
    local http_response_code = Field.new("http.response.code")
    local frame_time = Field.new("frame.time_relative")

    local host = http_host()
    local method = http_request_method()
    local code = http_response_code()
    local time = frame_time()

    if time then
        table.insert(csv_data, {
            time = tostring(time),
            host = tostring(host or ""),
            method = tostring(method or ""),
            code = tostring(code or "")
        })
    end
end

function export_csv()
    local file = io.open("/tmp/wireshark_export.csv", "w")
    file:write("Time,Host,Method,Code\n")
    for _, row in ipairs(csv_data) do
        file:write(row.time .. "," .. row.host .. "," .. row.method .. "," .. row.code .. "\n")
    end
    file:close()
    print("Exported " .. #csv_data .. " rows to /tmp/wireshark_export.csv")
end

register_menu("Export HTTP to CSV", export_csv, MENU_TOOLS_UNSORTED)
```

## Дополнительная информация

### Сравнение Lua и C-диссекторов

| Характеристика | Lua | C |
| :--- | :--- | :--- |
| **Производительность** | В 10-100 раз медленнее | Максимальная |
| **Простота написания** | Высокая | Средняя |
| **Перекомпиляция** | Не требуется | Требуется |
| **Доступ к API** | Полный (ProtoField, TreeItem, etc.) | Полный |
| **Использование** | Прототипы, кастомные протоколы | Высоконагруженные сети |

### Ограничения Lua в Wireshark

- **Производительность:** Lua-скрипт замедляет диссекцию на 10-100x. Не используйте для высокоскоростных сетей.
- **Потокобезопасность:** Lua не потокобезопасен. Нельзя использовать глобальные переменные в Stateless茅ках.
- **Память:** Lua-таблицы не автоматически очищаются. Используйте `reset()` в tap.
- **Отладка:** Используйте `print()` и `debug_print()` для вывода в консоль.

### Загрузка Lua-скриптов

```bash
# Способ 1: Через меню
# Analyze → Lua Scripts → (+) добавить файл

# Способ 2: Через tshark
tshark -r capture.pcap -X lua_script:my_dissector.lua

# Способ 3: Автозагрузка
# Файл ~/.local/lib/wireshark/plugins/init.lua
# Или /usr/lib/wireshark/plugins/init.lua

# Способ 4: Переменная окружения
export WIRESHARK_LUA_SCRIPTS=/path/to/scripts/
```

### Отладка Lua-скриптов

```lua
-- Вывод в консоль Wireshark
print("Debug: " .. tostring(variable))

-- Вывод в консоль tshark
-- tshark -r file.pcap -X lua_script:script.lua 2>&1

-- Проверка ошибок
-- Wireshark: Analyze → Reload Lua Plugins
-- Таблица ошибок отображается в консоли
```

### См. также
- **[Определения Wireshark](./definitions.md)** — диссекторы и базовые термины
- **[Использование tshark](./tshark_usage.md)** — CLI-анализ (включая `-X lua_script`)
- **[Продвинутые функции](./advanced_features.md)** — профили, Expert Info, статистика
- **[Основные концепции](./core_concepts.md)** — захват трафика
