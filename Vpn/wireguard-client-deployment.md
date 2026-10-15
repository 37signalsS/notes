# WireGuard: массовое развёртывание клиентов (Windows, macOS, iOS)

**Актуально для:** WireGuard for Windows 1.1.x (MSI + `wireguard.exe` CLI) / официальные клиенты macOS и iOS (App Store, `.mobileconfig`)

## Определения

**Tunnel Service** — служба Windows `WireGuardTunnel$<имя>`, создаваемая командой `wireguard /installtunnelservice`; обслуживает один конфиг `wg-quick`-формата. Управляется стандартными средствами (`services.msc`, `sc`).

**Manager Service** — служба `WireGuardManager`, управляющая UI и следящая за каталогом конфигов; для тихой установки ставится отдельно (`/installmanagerservice`).

**`.conf.dpapi`** — вариант конфига, зашифрованный средством Windows DPAPI (`CryptProtectData`) при генерации; расшифровывается только на той машине/под тем пользователем, где шифровался.

**`.mobileconfig`** — профиль конфигурации Apple (plist/XML) с payload `com.apple.vpn.managed`, устанавливаемый вручную или каналом MDM; переносит туннель WireGuard в системные настройки VPN.

**MDM (Mobile Device Management)** — сервер управления корпоративными устройствами (Jamf, Intune, Mosyle и др.); доставляет профили и приложения на macOS/iOS.

**GPO (Group Policy Object)** — механизм Active Directory для пакетной установки ПО (Software Installation) и запуска скриптов (Startup/Logon Scripts) на компьютерах домена.

## Основные концепции

Модели доставки конфигурации клиенту:

| Модель | Платформа | Что ставим | Плюсы | Минусы |
|---|---|---|---|---|
| GPO: MSI + Startup Script | Windows-домен | `wireguard.exe` + per-machine `.conf` из SYSVOL | Централизованно, без участия пользователя | Нужен SYSVOL и ACL; обновление конфига = повтор скрипта |
| SCCM/Intune/Ansible | Windows без домена | То же, дистрибутивом | Работает в гибридных средах | Нужен агент управления |
| MDM-профиль | macOS / iOS | `.mobileconfig` | Нет root, ключ в профиле, удалённый отзыв профиля | Платформа Apple; приватный ключ внутри профиля |
| Self-service панель | Любая | Пользователь сам берёт конфиг/QR | Минимум ручной работы на сервере | Требует панель ([wg-easy и др.](./wireguard-key-management.md)) |

Ключевые свойства Windows-клиента, используемые ниже (официальный enterprise-документ WireGuard):

- MSI можно разворачивать GPO/SCCM; свойство MSI `DO_NOT_LAUNCH` подавляет автозапуск UI после установки.
- `wireguard /installtunnelservice <путь\к\конфиг.conf>` создаёт службу `WireGuardTunnel$<имя>` (имя = имя файла без расширения).
- `wireguard /uninstalltunnelservice <имя>` — удаление; при уже запущенной службе установка поверх завершается ошибкой `Tunnel already installed and running` — сначала остановите/удалите службу.
- `wireguard /installmanagerservice` — тихая установка менеджера; менеджер следит за `%ProgramFiles%\WireGuard\Data\Configurations\` и уведомляет UI о новых `.conf`.
- `wireguard /update` — автообновление клиента (можно по расписанию через Task Scheduler).
- Статус туннеля — штатный `wg.exe show` (утилита `wg(8)` поставляется с клиентом).

На Apple-платформах приватный ключ и вся `wg-quick`-секция размещаются в payload профиля; ключи `FwMark`, `Table`, `PreUp`, `PostUp`, `PreDown`, `PostDown`, `SaveConfig` в `WgQuickConfig` **не поддерживаются**. При повторной установке профиля с тем же `PayloadIdentifier` новый профиль перезаписывает старый — это штатный механизм ротации.

Генерация ключей и инвентарь флота — [wireguard-key-management.md](./wireguard-key-management.md); серверные Ansible-роли также описаны в [VPN Automation](../Networking/Tunnels/vpn_automation.md).

## Практические сценарии

### 1. Windows: тихая установка MSI

```powershell
# Запуск от имени администратора; имя MSI — из каталога https://www.wireguard.com/install (Browse MSIs)
msiexec /i wireguard-x64-1.1.0.0.msi /qn DO_NOT_LAUNCH=1
# → код возврата 0 — установлено, UI не запущен
```

### 2. Windows: раздача конфигов через GPO Startup Script

Скрипт (например, `deploy-wg.cmd`) размещается в SYSVOL; включается для компьютеров (GPO → Computer Configuration → Policies → Windows Settings → Scripts → Startup). Каждому компьютеру — свой `.conf` (имя файла = имя туннеля = `$env:COMPUTERNAME`):

```bat
@echo off
set WGDIR=%ProgramFiles%\WireGuard
set CFGDIR=C:\ProgramData\WireGuard
set SRC=\\example.local\SYSVOL\example.local\scripts\wireguard

if not exist "%WGDIR%\wireguard.exe" (
    msiexec /i "%SRC%\wireguard-x64-1.1.0.0.msi" /qn DO_NOT_LAUNCH=1
)

if exist "%SRC%\%COMPUTERNAME%.conf" (
    if not exist "%CFGDIR%" mkdir "%CFGDIR%"
    copy /Y "%SRC%\%COMPUTERNAME%.conf" "%CFGDIR%\%COMPUTERNAME%.conf"
    "%WGDIR%\wireguard.exe" /uninstalltunnelservice %COMPUTERNAME% >nul 2>&1
    "%WGDIR%\wireguard.exe" /installtunnelservice "%CFGDIR%\%COMPUTERNAME%.conf"
)
```

**Безопасность SYSVOL:** по умолчанию конфиги читают все члены домена. Не складывайте в общий каталог приватные ключи всех сотрудников разом. Варианты: (1) ACL на папку — читает только целевой компьютер/группа; (2) шифрование DPAPI — файл `.conf.dpapi` (расшифровывается лишь на той машине, где был зашифрован); (3) раздача через management-канал (SCCM/Ansible) вместо шары.

### 3. Windows: ротация конфига (смена серверного ключа)

```powershell
# На клиенте (SYSTEM): сначала убрать старую службу — иначе ошибка "Tunnel already installed and running"
& "$env:ProgramFiles\WireGuard\wireguard.exe" /uninstalltunnelservice office
Copy-Item .\office.conf.new "C:\ProgramData\WireGuard\office.conf" -Force
& "$env:ProgramFiles\WireGuard\wireguard.exe" /installtunnelservice "C:\ProgramData\WireGuard\office.conf"
sc.exe query WireGuardTunnel$office
# → STATE: 4 RUNNING
```

Порядок действий при ротации серверного ключа целиком (выпуск новых клиентских конфигов, контрольное окно) — в [wireguard-key-management.md](./wireguard-key-management.md).

### 4. Windows: Ansible

```yaml
- name: Deploy WireGuard client config
  ansible.windows.win_copy:
    src: "files/wg/{{ inventory_hostname }}.conf"
    dest: 'C:\ProgramData\WireGuard\office.conf'

- name: Install (restart) WireGuard tunnel service
  ansible.windows.win_shell: |
    $wg = "$env:ProgramFiles\WireGuard\wireguard.exe"
    & $wg /uninstalltunnelservice office 2>$null
    & $wg /installtunnelservice 'C:\ProgramData\WireGuard\office.conf'
    (Get-Service WireGuardTunnel$office).Status
  # → Running
```

Установка самого MSI через Ansible — модулем `chocolatey.chocolatey.win_chocolatey` (`package: wireguard`) либо копией MSI и `win_command: msiexec /i ... /qn DO_NOT_LAUNCH=1`.

### 5. macOS / iOS: профиль `.mobileconfig`

Минимальный профиль (структура по [официальной спецификации wireguard-apple](https://git.zx2c4.com/wireguard-apple/tree/MOBILECONFIG.md); UUID сгенерируйте свои):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadDisplayName</key>
  <string>Corporate WireGuard</string>
  <key>PayloadType</key>
  <string>Configuration</string>
  <key>PayloadVersion</key>
  <integer>1</integer>
  <key>PayloadIdentifier</key>
  <string>com.example.wireguard.corp</string>
  <key>PayloadUUID</key>
  <string>44CDFE9F-4DC7-472A-956F-61C68055117C</string>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>PayloadDisplayName</key>
      <string>VPN</string>
      <key>PayloadType</key>
      <string>com.apple.vpn.managed</string>
      <key>PayloadVersion</key>
      <integer>1</integer>
      <key>PayloadIdentifier</key>
      <string>com.example.wireguard.corp.tunnel</string>
      <key>PayloadUUID</key>
      <string>6A7B8C9D-0E1F-4A5B-8C6D-7E8F9A0B1C2D</string>
      <key>UserDefinedName</key>
      <string>corp-vpn</string>
      <key>VPNType</key>
      <string>VPN</string>
      <key>VPNSubType</key>
      <string>com.wireguard.macos</string>
      <!-- для iOS: com.wireguard.ios -->
      <key>VendorConfig</key>
      <dict>
        <key>WgQuickConfig</key>
        <string>[Interface]
PrivateKey = &lt;CLIENT_PRIVATE_KEY&gt;
Address = 10.0.0.5/32
DNS = 10.0.0.1

[Peer]
PublicKey = &lt;SERVER_PUBLIC_KEY&gt;
AllowedIPs = 10.0.0.0/24, 192.168.1.0/24
Endpoint = vpn.example.com:51820
PersistentKeepalive = 25</string>
      </dict>
      <key>VPN</key>
      <dict>
        <key>RemoteAddress</key>
        <string>vpn.example.com:51820</string>
        <key>AuthenticationMethod</key>
        <string>Password</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
```

Установка:

- **Ручная:** отправить пользователю профиль, открыть на устройстве → Установить профиль (на macOS — Системные настройки → Профили; на iOS — Настройки → Основные → VPN и управление устройством). Туннель появляется в системных настройках VPN, включается переключателем.
- **MDM:** загрузить профиль в сервер MDM (Jamf Pro / Intune / Mosyle) и назначить группе устройств; при повторном назначении с тем же `PayloadIdentifier` профиль заменяется целиком — так разносится ротация конфигов.

`WgQuickConfig` — обычный текст `wg0.conf`; `Address`/`DNS`/секция `[Peer]` — как на Linux. Запрещённые ключи: `FwMark`, `Table`, `PreUp`, `PostUp`, `PreDown`, `PostDown`, `SaveConfig`.

### 6. Android: QR-код

Панель (wg-easy, Netbird dashboard и т.п.) либо скрипт генерации показывают QR с готовым конфигом; в приложении WireGuard → `+` → Scan from QR. Генерация серверных ключей и панели — [wireguard-key-management.md](./wireguard-key-management.md).

### 7. Контроль состояния флота

```powershell
# Windows: статус туннеля на конкретной машине
& "$env:ProgramFiles\WireGuard\wg.exe" show
# → interface: office
# →   public key: <client_pub>
# →   peer: <server_pub>
# →   endpoint: 203.0.113.10:51820
# →   latest handshake: 1 minute, 2 seconds ago
sc.exe query WireGuardTunnel$office
# → STATE: 4 RUNNING
```

На сервере принадлежность конфига машине сверяется по инвентарю pubkey → владелец/устройство ([wireguard-key-management.md](./wireguard-key-management.md)); сессии — [vpn-session-audit.md](./vpn-session-audit.md).

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| `Tunnel already installed and running` | Служба туннеля активна | `/uninstalltunnelservice <имя>` (или остановить службу) перед переустановкой |
| Служба есть, трафика нет | В конфиге нет `DNS`/`AllowedIPs` не покрывают нужные сети | Проверить `wg.exe show`; поправить конфиг, переустановить службу |
| Профиль не устанавливается на macOS | Ошибки в plist/UUID | `plutil -lint профиль.mobileconfig`; сверить PayloadIdentifier |
| Туннель в профиле есть, но выключается | MDM не назначил профиль / конфликт с ручным профилем того же идентификатора | Проверить установку профиля на устройстве; одинаковый PayloadIdentifier перезаписывает |
| После ротации серверного ключа клиенты молчат | Не разосланы новые конфиги | Порядок ротации: [wireguard-key-management.md](./wireguard-key-management.md) |

## Лучшие практики

- Именуйте `.conf` стабильно (имя машины/сотрудника из инвентаря) — имя файла = имя службы Windows.
- `DO_NOT_LAUNCH=1` в домене обязателен: без него при каждой загрузке у пользователя всплывает UI.
- Ротацию конфигов планируйте окнами: `uninstall → copy → install`, иначе служба отклонит установку.
- Приватные ключи в MDM/SYSVOL — только с ACL или в DPAPI-шите; ротируйте ключ при подозрении на компрометацию шары.
- После массового выката проверьте выборку клиентов и мониторинг рукопожатий — [vpn-acceptance-checklist.md](./vpn-acceptance-checklist.md), [vpn-monitoring.md](./vpn-monitoring.md).

## Дополнительная информация

- **[WireGuard — управление ключами и флотом](./wireguard-key-management.md)** — генерация конфигов, инвентарь, ротация, панели
- **[WireGuard](./wireguard.md)** — § «Развёртывание клиентов на десктопах и мобильных устройствах»
- **[VPN Automation — Ansible и Terraform](../Networking/Tunnels/vpn_automation.md)** — серверная автоматизация
- **[VPN: мониторинг](./vpn-monitoring.md)** — отслеживание рукопожатий флота
- Источники: [Enterprise Usage (wireguard-windows)](https://git.zx2c4.com/wireguard-windows/about/docs/enterprise.md), [MOBILECONFIG.md (wireguard-apple)](https://git.zx2c4.com/wireguard-apple/about/MOBILECONFIG.md)
