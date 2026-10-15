# Аудит и журналирование сессий VPN

**Актуально для:** WireGuard (wireguard-tools 1.0.x) / OpenVPN 2.6.x / FreeRADIUS 3.x

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

## Практические сценарии

### 1. Снимки состояния WireGuard (`wg show dump`)

Самый дешёвый уровень: периодически снимать состояние интерфейса и накапливать историю. Формат строки пира в дампе (поля через табуляцию): `pubkey`, `preshared-key`, `endpoint`, `allowed-ips`, `latest-handshake`, `transfer-rx`, `transfer-tx`, `persistent-keepalive`. Незаданные значения `wg` печатает как `(none)`, а `fwmark`/`persistent-keepalive` — как `off` (см. исходник `dump_print` в [wireguard-tools](https://git.zx2c4.com/wireguard-tools/tree/src/show.c)). Первая строка дампа описывает сам интерфейс (ключи, порт, fwmark), а не пира.

**Скрипт `/usr/local/bin/wg_audit_snapshot.sh`:**

```bash
#!/bin/bash
# wg_audit_snapshot.sh <iface> — снимок состояния пиров в JSONL для аудита
set -euo pipefail
IFACE="${1:-wg0}"
OUT="${WG_AUDIT_LOG:-/var/log/vpn/connections.jsonl}"
TS="$(date -u +%FT%TZ)"          # единое время в UTC

install -d -m 0750 /var/log/vpn
umask 027

# Поля пира в dump: pubkey, preshared, endpoint, allowed-ips, latest-handshake, rx, tx, keepalive
wg show "$IFACE" dump | awk -v ts="$TS" -v iface="$IFACE" '
BEGIN { FS = "\t" }
NR == 1 { next }                 # пропустить строку интерфейса
{
  printf("{\"ts\":\"%s\",\"iface\":\"%s\",\"pubkey\":\"%s\",\"endpoint\":\"%s\",\"allowed_ips\":\"%s\",\"handshake_ts\":%s,\"rx\":%s,\"tx\":%s}\n",
    ts, iface, $1, $3, $4, $5, $6, $7)
}' >> "$OUT"
```

**Пример записи** (`endpoint` и `allowed_ips` — из документационной сети TEST-NET-3):

```json
{"ts":"2026-01-15T09:00:00Z","iface":"wg0","pubkey":"xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=","endpoint":"203.0.113.7:51820","allowed_ips":"10.8.0.10/32","handshake_ts":1768467600,"rx":1048576,"tx":524288}
```

**systemd timer** (опрос каждые 5 минут):

```ini
# /etc/systemd/system/wg-audit-snapshot.service
[Unit]
Description=WireGuard audit snapshot (state dump)
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wg_audit_snapshot.sh wg0
```

```ini
# /etc/systemd/system/wg-audit-snapshot.timer
[Unit]
Description=Periodic WireGuard audit snapshot

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now wg-audit-snapshot.timer
systemctl list-timers wg-audit-snapshot.timer
# → NEXT  LEFT  LAST  PASSED  UNIT  ACTIVATES
```

**Ротация и хранение** (retention локального архива задаётся здесь):

```text
# /etc/logrotate.d/wg-audit
/var/log/vpn/connections.jsonl {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
}
```

**Что даёт и чего не даёт.** Уровень фиксирует «кто был подключён в момент T» и появление новых `endpoint`. Он не даёт точного времени входа/выхода: разрыв между двумя снапшотами маскирует реальное событие. Для точных Start/Stop нужны события периметра (п.2) или RADIUS Accounting (п.3). Привязка `pubkey` к владельцу — только через инвентарь (п.5).

### 2. События периметра: NFLOG для WireGuard

WireGuard не логирует подключения, но факт нового UDP-потока к его порту виден файрволу. Логируя через **NFLOG** только новые соединения (`ct state NEW`), получаем события периметра: с какого IP:порта пришёл новый хэндшейк (роуминг, смена сети) и когда. Механизм NFLOG/ulogd2 (стек, бэкенды, запуск) подробно разобран в [nftables: логирование через nflog](../Linux/Networking/Settings/tools/nftables/monitoring_and_alerting.md); базовая теория целей и таблиц — в [iptables: основы](../Linux/Networking/Settings/tools/iptables_basics.md). Ниже — специфика WireGuard.

Порт берётся из конфига узла (`ListenPort`). Протокольного порта по умолчанию у WireGuard нет: если `ListenPort` не задан, выбирается случайный порт; в примерах и по соглашению используется `51820`. Группа NFLOG — произвольный номер (здесь `5`); он должен совпадать в правиле файрвола и в приёмнике ulogd2.

**iptables:**

```bash
# Отдельная цепочка только для аудита: логирует и возвращает управление в INPUT
sudo iptables -N WG_AUDIT 2>/dev/null || sudo iptables -F WG_AUDIT
sudo iptables -A WG_AUDIT -p udp --dport 51820 -m conntrack --ctstate NEW \
     -j NFLOG --nflog-group 5 --nflog-prefix "WG:NEW:"
sudo iptables -A WG_AUDIT -j RETURN

sudo iptables -I INPUT -p udp --dport 51820 -j WG_AUDIT
```

**nftables:**

```text
table inet wg_audit {
    chain input {
        type filter hook input priority filter; policy accept;
        udp dport 51820 ct state new log prefix "WG:NEW: " group 5
    }
}
```

Цель `NFLOG` и оператор `log` — не завершающие: правило лишь дублирует пакет в userspace, вердикт остаётся за остальными правилами.

**Приёмник (ulogd2), фрагмент `/etc/ulogd.conf`:**

```ini
[wg_log]
group=5
nflog_uid=0
buffer_size=32768

[wg_json]
group=5
json=1
file=/var/log/vpn/wg-nflog.json
```

Полный стек `plugin=` (загружаемые модули, вывод в файл/БД/Kafka) и запуск — в статье по nftables выше.

**Валидация:**

```bash
sudo tcpdump -i any -n port 51820    # видеть входящий UDP-хэндшейк
tail -f /var/log/vpn/wg-nflog.json   # должна появиться запись с префиксом "WG:NEW:"
```

**Ограничения.** conntrack считает UDP-поток «новым» по таймауту: `nf_conntrack_udp_timeout` — 30 с, `nf_conntrack_udp_timeout_stream` — 120 с ([ядро](https://docs.kernel.org/networking/nf_conntrack-sysctl.html)). Поэтому одно физическое подключение после паузы дольше таймаута породит повторное событие — это нормально для фиксации роуминга, но не годится как точный счётчик сессий. Логирование всех пакетов (без `ct state NEW`) при активном туннеле перегружает диск и netlink — не включайте его постоянно.

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


### 4. Аудит через контроллер mesh-VPN (Headscale/Tailscale, Netbird, Netmaker)

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

**Netbird** (combined-развёртывание, v0.65.0+). Журнал аудита (**Audit Events**) включён по умолчанию и хранится в отдельном хранилище рядом с management: он доступен в UI на вкладке Audit Events и через API management-сервера (`GET /api/events/audit`). Серверные логи контейнера:

```bash
docker compose logs netbird-server --since 24h        # или: docker logs netbird-server
# выгрузка журнала аудита через API
curl -s https://netbird.example.com/api/events/audit \
     -H "Authorization: Token <TOKEN>" | jq .
```

Netbird умеет стримить audit events в SIEM (см. интеграции в [документации](https://docs.netbird.io/manage/activity)). Предупреждение admin CLI `Warning: audit events will not be recorded` означает, что хранилище событий не открылось — проверьте ключ шифрования activity store.

**Netmaker.** Сервер работает в Docker (логи — `docker compose logs`), удалённая выгрузка серверных логов — `nmctl logs`. Агент `netclient` на узле пишет в journald:

```bash
sudo journalctl -u netclient@<network> -f
```

Доп. детали по контроллеру и OIDC — см. [tailscale.md](./tailscale.md), архитектура Netbird/Netmaker — [mesh-vpn-overview.md](./mesh-vpn-overview.md).


### 5. Инвентаризация pubkey→владелец (обязательна)

Без сопоставления публичного ключа с владельцем события из п.1–2 **бесполезны** для расследования. Ведите инвентарь в защищённом месте с минимальным доступом. Канонический формат выдачи/ротации ключей — в [wireguard-key-management.md](./wireguard-key-management.md) §2; для целей аудита его расширяют полями владельца, команды и отметкой об отзыве.

**Расширенный формат для аудита (CSV):**

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
| Журнал аудита Netbird | UI `Audit Events` или `curl <mgmt>/api/events/audit` | Combined-развёртывание v0.65.0+ |
| Логи агента Netmaker | `journalctl -u netclient@<network> -f` | События узла |
| Ротация логов (audit) | см. Troubleshooting/Best Practices | Обязательно с retention |


## Troubleshooting

### Снимки не пишутся

- Проверить наличие скрипта и прав: `ls -la /usr/local/bin/wg_audit_snapshot.sh`, `cat` содержимое.
- Проверить таймер: `systemctl status wg-audit-snapshot.timer`, `journalctl -u wg-audit-snapshot.service -n 15`.
- Убедиться, что интерфейс существует: `ip link show wg0`.
- Проверить awk/jq: `wg show wg0 dump | head -1`.

### NFLOG не ловит события

- Проверить правило: `iptables -S INPUT | grep NFLOG` или `nft list ruleset | grep WG:NEW`.
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

## Очистка

Откат аудита не должен затрагивать сам VPN: удаляются только правила сбора и артефакты. Сохраняйте источник событий до окончания срока retention — удаление раньше срока делает расследование невозможным.

**Снять правила аудита:**

```bash
# iptables: сначала ссылку из INPUT, затем саму цепочку
sudo iptables -D INPUT -p udp --dport 51820 -j WG_AUDIT
sudo iptables -F WG_AUDIT && sudo iptables -X WG_AUDIT
```

```bash
# nftables: удалить таблицу целиком
sudo nft delete table inet wg_audit
```

**Остановить сбор:**

```bash
sudo systemctl disable --now wg-audit-snapshot.timer
sudo rm /etc/systemd/system/wg-audit-snapshot.{timer,service}
sudo systemctl daemon-reload
sudo rm /usr/local/bin/wg_audit_snapshot.sh
```

**Очистить приёмник и локальные данные:**

```bash
sudo systemctl stop ulogd2                 # только если ulogd2 использовался исключительно для этого
sudo rm /var/log/vpn/connections.jsonl /var/log/vpn/wg-nflog.json
# централизованное хранилище (Loki/ELK/ClickHouse) чистится по политике retention, а не вручную
```

Убедитесь, что удаляете именно своё правило: сверьтесь с `iptables -S INPUT` и `nft list ruleset` перед удалением.

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

