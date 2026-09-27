# Аудит и журналирование сессий VPN

## Определения

**Аудит VPN** — сбор и хранение фактов о подключениях: кто, когда, с какого адреса, как долго и сколько трафика прошло по туннелю. **NFLOG (netfilter LOG)** — механизм ядра, перенаправляющий пакеты, попавшие под правило netfilter, в userspace (в отличие от устаревшего LOG, который пишет в dmesg). **RADIUS Accounting** — учётная часть протокола RADIUS: сервер отправляет на RADIUS-сервер записи Start/Stop сессии (время, объём, адрес). **Retention** — политика хранения логов и срока их доступности для разбора инцидента. **SIEM** — централизованная система сбора и корреляции событий безопасности (пайплайн Vector → Loki/ELK выступает его упрощённой заменой).

## Основные концепции

### Проблема: WireGuard не ведёт логов подключений

WireGuard как модуль ядра по замыслу не журналирует сессии: нет файла лога, нет понятия «пользователь». Единственная наблюдаемость «изнутри» — снимок состояния `wg show` (возраст handshake, transfer по пиру). Это ограничение регулярно всплывает на собеседованиях: «как обеспечить audit при use of WireGuard?». Ответ — третий уровень за пределами самого протокола: снимки состояния, журнал через NFLOG, RADIUS Accounting, логи контроллера (Headscale и аналоги).

### Что именно фиксировать

| Событие | Ключевые поля | Источник |
|---------|---------------|----------|
| Подключение/переподключение пира | публичный ключ, source IP:port, время, возраст handshake | снимки `wg show dump` (NxN по времени) |
| Пакеты нового handshake | pubkey, source IP:port, action | NFLOG-правило на UDP 51820 |
| Сессия пользователя | username, Start/Stop, duration, rx/tx, NAS IP | RADIUS Accounting (OpenVPN/IPsec) |
| Вход через контроллер | user (OIDC), узел, время, причина удаления | Headscale/Netbird/Netmaker логи |

Три уровня аудита — от дешёвого к детальному:

1. **Снимки состояния** — периодический dump `wg show dump` в Prometheus/JSONL. Дешево, отвечает «кто был подключён в момент времени».
2. **NFLOG/периметровый журнал** — логирование событий нового соединения на firewall. Детально, но без привязки к пользователю (только ключ).
3. **RADIUS Accounting / контроллер** — полный учёт пользовательских сессий для OpenVPN/IPsec и mesh-решений с OIDC.

## Практические сценарии

### 1. Снимки состояния пиров (дешёвый аудит WAN)

Штатный приём мониторинга из [vpn-monitoring.md](./vpn-monitoring.md) превращается в аудит, если хранить **историю** снимков, а не только текущее значение:

```bash
#!/bin/bash
# /usr/local/bin/wg_audit_snapshot.sh — пишет JSONL всех подключённых пиров
IFACE=wg0
OUT=/var/log/vpn/connections.jsonl
mkdir -p /var/log/vpn
# Формат dump: pubkey preshared endpoint allowed-ips latest-handshake rx tx
wg show wg0 dump | awk -v ts="$(date -u +%FT%TZ)" -v iface="$IFACE" '
    $1 != "off" { next }
    $5 > 0 {
        printf "{\"ts\":\"%s\",\"iface\":\"%s\",\"pubkey\":\"%s\",\"endpoint\":\"%s\",\"handshake_ts\":%d}\n",
               ts, iface, $1, $3, $5
    }' | tee -a "$OUT"
```

Запуск по cron каждые 60 c, отправка в центральный лог через Vector (см. [Vector — обзор](../Vector/vector_overview.md)) вместо локального файла. Хранить с retention ≥90 дней для соответствия типовым локальным регламентам.

### 2. Журналирование новых соединений через NFLOG

Правило на входе ловит только первичный handshake от роуминговых клиентов (для site-to-site лучше allowlist, см. [wireguard-security.md](./wireguard-security.md)). `iptables`:

```bash
# Цепочка логирования до DROP/ACCEPT
iptables -I INPUT 1 -p udp --dport 51820 -m conntrack --ctstate NEW \
  -j NFLOG --nflog-group 5 --nflog-prefix "WG:HANDSHAKE:"
# Приёмник: nflog → rsyslog/syslog-ng → central log
sudo ulogd2 -d -o DB 2>/dev/null || ulogd2 -d
```

Аналог на `nftables` + приём через `nflog`:

```bash
nft add rule inet filter input udp dport 51820 ct state new \
  log group 5 prefix "WG:HANDSHAKE:"
```

Факт появления записи с новым `source IP` для уже известного пира = событие роуминга или подозрительного входа; корреляция с инвентарём ключей (см. [wireguard-key-management.md](./wireguard-key-management.md)) даёт ответ «кто».

### 3. RADIUS Accounting для OpenVPN/IPsec

Если периметр на OpenVPN/IPsec с RADIUS (настройка сервера — [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md)), включается учётная часть:

```text
# /etc/openvpn/server.conf — дополнение к RADIUS-плагину
plugin /usr/lib/openvpn/openvpn-plugin-radius.so /etc/openvpn/radius/radius.cnf
```

```text
# /etc/openvpn/radius/radius.cnf
NAS-Identifier=vpn-gw1
Authserver  10.20.0.10:1812  testing123
Acctserver  10.20.0.10:1813  testing123
```

На FreeRADIUS-сервере обязателен слушающий порт acct 1813 (в конфигурации `sites-available/default` это `acct {}` — см. [LDAP/ldap_vpn_radius.md](../LDAP/ldap_vpn_radius.md#свободный-радиус)). Каждая сессия получает записи `Accounting-Request (Start)` и `(Stop)` с полями `Acct-Session-Time`, `Acct-Input-Octets`, `Acct-Output-Octets` и `Calling-Station-Id` — это готовый источник данных для биллинга, quota-контроля и аудита.

### 4. Аудит через контроллер mesh-VPN

Для Tailscale/Headscale полный аудит входов ведёт координатор: OIDC-login пользователя + регистрация узла + время жизни ключа (см. [tailscale.md](./tailscale.md)). Retain логов `headscale` на период комплаенса:

```bash
sudo journalctl -u headscale --since "2026-01-01" > /var/log/vpn/headscale.log
```

Отзыв доступа («кто и когда удалён») фиксируется теми же логами — обязательная строка для разборок с compliance.

### 5. Compliance-позиции для продакшена

- Лог событий подключения хранится централизованно (Vector → Loki/ELK, см. [Loki — обзор](../Loki/loki_overview.md)), не на шлюзе.
- Привязка «публичный ключ → владелец» ведётся в инвентаре (см. [wireguard-key-management.md](./wireguard-key-management.md)); без неё лог бесполезен.
- Права на архив: только для службы безопасности/ответственных, rotate и retention задаются явно.
- Алерт на «новый пир с неизвестного source IP» — минимум для раннего обнаружения компрометации ключа.

## Дополнительная информация

- **[vpn-monitoring.md](./vpn-monitoring.md)** — метрики и алертинг (снимки `wg show`, Blackbox Exporter)
- **[wireguard-key-management.md](./wireguard-key-management.md)** — инвентарь ключей, без которого аудит не имеет смысла
- **[LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md)** — FreeRADIUS + LDAP, аккаунт-сервер, чек-лист интеграции