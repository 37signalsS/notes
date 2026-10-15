# Аудит и журналирование сессий VPN

## Определения

**Аудит VPN** — сбор, хранение и сопоставление фактов о подключениях: кто (пользователь/владелец пира), когда подключился/отключился, с какого публичного адреса, через какой шлюз, как долго длилась сессия, какой объём трафика прошёл по туннелю.

**NFLOG (netfilter LOG)** — механизм ядра netfilter для перенаправления пакетов, попавших под правило, в userspace-приёмник (ulogd2/nflogd/rsyslog с модулем imnflog). В отличие от устаревшего LOG, NFLOG не пишет в dmesg и позволяет централизованно собирать события.

**RADIUS Accounting** — учётная часть протокола RADIUS (порт 1813/UDP по умолчанию). Шлюз (NAS) отправляет записи `Accounting-Request (Start)`, `Interim-Update`, `Stop` с временем, объёмом трафика (`Acct-Input-Octets`/`Acct-Output-Octets`), `Acct-Session-Id`, `Calling-Station-Id`, `NAS-IP-Address` и др.

**Retention** — явно заданный срок хранения событий аудита (минимум достаточный для расследований инцидентов; задаётся на центральном хранилище и при ротации локальных файлов).

**SIEM/центральный лог** — приём, хранение, поиск и корреляция событий (упрощённый вариант в рамках этой базы: Vector → Loki/ClickHouse/ELK или rsyslog/journald + централизованный приём).

**Пир (peer)** — узел WireGuard, однозначно идентифицируемый публичным ключом.

**Handshake** — криптографический обмен WireGuard, по которому косвенно фиксируется «живость» пира.

## Основные концепции

### Почему WireGuard сам по себе не ведёт аудит

WireGuard спроектирован минималистично: в нём нет встроенного логирования подключений/пользователей. Единственный оперативный снимок состояния — вывод `wg show`/`wg show dump` (наличие пира, endpoint, `latest-handshake`, `transfer`). По нему нельзя достоверно восстановить полную историю входов/выходов без периодического снятия снапшотов и сопоставления с событиями периметра.

### Уровни аудита (от минимального к полному)

| Уровень | Достоверность | Привязка к пользователю | Источник | Комментарий |
|---------|---------------|-------------------------|----------|-------------|
| 1. Снимки состояния | Базовая («кто присутствовал в момент T») | Нет напрямую (только pubkey) | `wg show dump` по таймеру | Дешёвый, необходимый минимум. Требует инвентаря pubkey→владелец. |
| 2. События периметра (NFLOG) | Средняя (факт попытки/нового соединения с endpoint) | Нет напрямую | netfilter NFLOG на UDP 51820 + приёмник (ulogd2/nflog) | Помогает зафиксировать роуминг (смена IP/порта), подозрительную активность. |
| 3. Пользовательский учёт | Максимальная (Start/Stop/Interim) | Да (username) | RADIUS Accounting (OpenVPN/IPsec) | Классика для корпоративного remote-access с доменной аутентификацией. |
| 4. Контроллер mesh-VPN | Максимальная + управление доступом | Да (OIDC/локальный пользователь) | логи Headscale/Netbird/Netmaker (journald/syslog) | Централизованный аудит входов/регистрации узлов/отзыва ключей. |

### Что обязательно фиксировать

| Поле | Назначение | Источник |
|------|------------|----------|
| `timestamp` (UTC) | Единое время события | система (NTP/chrony). Критично для корреляции. |
| `iface` | Шлюз/интерфейс WG | `wg show`/контекст правила |
| `pubkey` | Идентификатор пира | `wg show dump`/NFLOG-контекст |
| `owner` | ФИО/логин владельца пира | инвентарь (см. [wireguard-key-management.md](./wireguard-key-management.md)) |
| `endpoint` (src_ip:src_port) | Откуда подключается пир | `wg show dump`, NFLOG |
| `handshake_ts`/`latest-handshake` | Время последнего handshake | `wg show dump` |
| `rx/tx bytes` | Объём трафика (на момент снапшота) | `wg show dump` |
| `session_start/stop/duration` | Длительность пользовательской сессии | RADIUS Accounting |
| `nas_ip`/`nas_id` | Какой шлюз обслужил сессию | RADIUS Accounting |
| `reason` (disconnect/revoke) | Причина завершения/отзыва | контроллер/админ-действие |

### Архитектура сбора

1. **Источник**: WireGuard state (`wg show dump`), netfilter (NFLOG), RADIUS Accounting, контроллер (Headscale).
2. **Сбор**: systemd-timer + скрипт, ulogd2/nflog, rsyslog/syslog-ng, journald.
3. **Транспорт**: локальный лог-файл (jsonl/syslog) → Vector/rsyslog → центральное хранилище.
4. **Хранение**: централизованный лог (Loki/ELK) с доступом по ролям + локальный архив на шлюзе (rotate+retention).
5. **Корреляция**: pubkey↔owner из инвентаря + временные ряды снапшотов + события периметра.

### 3. RADIUS Accounting для OpenVPN/IPsec (пользовательский аудит)

Если используется OpenVPN/IPsec с RADIUS-аутентификацией, включается учётная часть (Accounting). Конфигурация RADIUS-сервера/клиента описана в [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md).

**OpenVPN + radius plugin (пример):**

```text
# /etc/openvpn/server.conf
plugin /usr/lib/openvpn/openvpn-plugin-radius.so /etc/openvpn/radius/radius.cnf
```

```text
# /etc/openvpn/radius/radius.cnf
NAS-Identifier=vpn-gw1
Authserver  10.20.0.10:1812  testing123
Acctserver  10.20.0.10:1813  testing123
```

На FreeRADIUS должен быть включён `acct` блок (`sites-available/default`, `acct { ... }`) и открыт 1813/UDP. В записях Start/Stop присутствуют: `Acct-Session-Id`, `User-Name`, `Calling-Station-Id`, `NAS-IP-Address`, `Acct-Session-Time`, `Acct-Input-Octets`, `Acct-Output-Octets`. Именно эти поля формируют полный пользовательский аудит.

**Валидация:** проверить, что FreeRADIUS принимает Accounting-запросы:

```bash
sudo tcpdump -i any port 1813 -n
# с клиента OpenVPN должен идти Accounting-Request
```

```bash
sudo radtest username password 127.0.0.1:1813 0 testing123 acct
```


### 4. Аудит через контроллер mesh-VPN (Headscale/Tailscale и аналоги)

Контроллер фиксирует события аутентификации (OIDC/login), регистрации/удаления узлов, отзыв ключей, изменения ACL. Это основной источник пользовательского аудита в mesh-сетях.

**Headscale (journald):**

```bash
sudo journalctl -u headscale --since "2026-01-01" --output=short-iso
```

**Экспорт в файл с явным временным окном (retention-архив):**

```bash
sudo journalctl -u headscale --since "2026-01-01T00:00:00Z" --until "2026-12-31T23:59:59Z" > /var/log/vpn/headscale-2026.log
chmod 600 /var/log/vpn/headscale-2026.log
```

**Фильтрация ключевых событий:**

```bash
sudo journalctl -u headscale -g "login\|node\|register\|delete\|revoke" --since -7d
```

Доп. детали по контроллеру и OIDC — см. [tailscale.md](./tailscale.md), обзор mesh-VPN — [mesh-vpn-overview.md](./mesh-vpn-overview.md).


### 5. Инвентаризация pubkey→владелец (обязательна)

Без сопоставления публичного ключа с владельцем события из п.1–2 **бесполезны** для расследования. Ведите инвентарь в защищённом месте с минимальным доступом.

**Минимальный формат (CSV):**

```csv
name,owner,team,email,pubkey,ip,iface,issued_at,rotation_due,revoked,revoked_at,note
alice-vpn,Иванов Иван,infra,ivanov@corp.local,ABCDEF...,10.8.0.10,wg0,2026-01-15,2027-01-15,false,,laptop
```

**Проверка соответствия снапшота инвентарю:**

```bash
# Сопоставить pubkey из последнего снапшота с инвентарём
jq -r '.pubkey' /var/log/vpn/connections.jsonl | tail -5 | while read pk; do
grep -i "$pk" /etc/wireguard/inventory.csv || echo "UNKNOWN:$pk"
done
```

Подробнее — [wireguard-key-management.md](./wireguard-key-management.md).


## Операции и команды (краткая сводка)

| Операция | Команда | Комментарий |
|----------|---------|-------------|
| Снимок текущих пиров | `wg show wg0` | Оперативный, без истории |
| Полный дамп | `wg show wg0 dump` | Поля: pubkey, preshared, endpoint, allowed-ips, latest-handshake, rx, tx |
| JSONL-снимок (аудит) | `wg_audit_snapshot.sh wg0` | Пишет историю в `/var/log/vpn/connections.jsonl` |
| NFLOG NEW (iptables) | см. п.2 | Фиксирует новые подключения |
| NFLOG NEW (nftables) | см. п.2 | Аналог для nftables |
| Проверка RADIUS Accounting | `tcpdump -i any port 1813 -n` | Должны идти Accounting-Request Start/Stop |
| Логи Headscale | `journalctl -u headscale -g "node\|login\|delete" --since -7d` | Фильтр ключевых событий |
| Ротация логов (audit) | см. Troubleshooting/Best Practices | Обязательно с retention |


## Troubleshooting

### Снимки не пишутся

- Проверить наличие скрипта и прав: `ls -la /usr/local/bin/wg_audit_snapshot.sh`, `cat` содержимое.
- Проверить таймер: `systemctl status wg-audit-snapshot.timer`, `journalctl -u wg-audit-snapshot.service -n 15`.
- Убедиться, что интерфейс существует: `ip link show wg0`.
- Проверить awk/jq: `wg show wg0 dump | head -1`.

### NFLOG не ловит события

- Проверить правило: `iptables -S INPUT | grep NFLOG` или `nft list ruleset | grep WG:HANDSHAKE`.
- Проверить, что порт правильный: `ss -lunp | grep 51820`.
- ulogd2 запущен: `systemctl status ulogd2`, логи в `/var/log/ulogd/`.
- Альтернатива: включить логирование в rsyslog с модулем imnflog (зависит от дистрибутива).

### RADIUS Accounting не приходит

- Свободные порты: `nc -vzu 10.20.0.10 1813` (с NAS) или `tcpdump port 1813`.
- FreeRADIUS: `systemctl status freeradius`, логи `/var/log/freeradius/radius.log` или `journalctl -u freeradius`.
- Включён acct-секшен в site-конфиге FreeRADIUS.
- `secret` совпадает между NAS и FreeRADIUS.

### Headscale-логи пустые/неполные

- Юнит: `systemctl status headscale`, `journalctl -u headscale -n 20`.
- Фильтры по уровню/формату: `journalctl -u headscale --since -1h -o json-pretty | head -5`.
- Убедиться, что OIDC и роутинг настроены корректно (см. [tailscale.md](./tailscale.md)).


## Лучшие практики (Best Practices)

- **Единое время:** синхронизация через NTP/chrony на всех шлюзах и центральном логе (критично для корреляции).
- **UTC в логах:** хранить таймстампы в UTC; при отображении конвертировать в локаль.
- **Обязательный инвентарь:** любая ссылка на `pubkey` без владельца должна триггерить алерт. См. [wireguard-key-management.md](./wireguard-key-management.md).
- **Централизация:** не хранить аудит только локально на шлюзе — отправлять в централизованное хранилище (Vector/rsyslog). Локальный архив — как страховка.
- **Ротация и retention:** явно задать ротацию логов (logrotate) и retention на центральном хранилище. Минимум покрывать окно расследования по регламенту.
- **Минимум привилегий:** доступ к audit-логам и инвентарю — только службе безопасности/ответственным. Файлы с ключами/инвентарём — `chmod 600/700`.
- **Алертинг на аномалии:** новый endpoint для известного `pubkey` (роуминг) — на рассмотрение; `pubkey` из снапшота отсутствует в инвентаре — критичный алерт.
- **Защита от потери:** периодически проверять, что таймер запущен, диск не переполнен (`df -h /var/log`), есть место под JSONL/NFLOG.
- **Согласованность версий:** при изменении WireGuard/OpenVPN/FreeRADIUS сверять поля Accounting и формат дампа (разные сборки редко ломают формат, но стоит проверить).
- **Mesh-контроллер:** фиксировать отзыв узлов/ключей в тех же журналах, что и логины (Headscale) — см. [tailscale.md](./tailscale.md).
- **Site-to-site:** для статичных site-to-site пиров NFLOG по NEW часто избыточен; акцент на снапшотах + мониторинге (см. [vpn-monitoring.md](./vpn-monitoring.md), [wireguard-ha.md](./wireguard-ha.md)).

## Дополнительная информация

- **[vpn-monitoring.md](./vpn-monitoring.md)** — метрики и алертинг по WireGuard (`wg show`, алерты), интеграция с Prometheus
- **[wireguard-key-management.md](./wireguard-key-management.md)** — инвентаризация pubkey→владелец, ротация, хранение ключей
- **[wireguard.md](./wireguard.md)** — базовая настройка WireGuard, команды, конфиги
- **[wireguard-security.md](./wireguard-security.md)** — hardening, ограничения доступа, firewall
- **[wireguard-ha.md](./wireguard-ha.md)** — HA-концентратор, синхронизация состояния, аудит кластера
- **[tailscale.md](./tailscale.md)** — Headscale: OIDC, ACL, аудит логов координатора
- **[mesh-vpn-overview.md](./mesh-vpn-overview.md)** — обзор mesh-VPN, сравнительная таблица
- **[LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md)** — FreeRADIUS + LDAP, RADIUS Accounting (acct), чек-лист
- **[Vector — обзор](../Vector/vector_overview.md)** — транспортировка логов с шлюзов в централизованное хранилище
- **[Loki — обзор](../Loki/loki_overview.md)** — хранение и поиск VPN-аудита

