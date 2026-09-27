# ISC DHCP Failover — отказоустойчивая пара серверов

> **Важно:** ISC DHCP официально признан устаревшим (EOL). Для новых развёртываний рекомендуется использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)** с нативной поддержкой HA.

---

## Определения

**DHCP Failover** — протокол обеспечения высокой доступности, при котором два сервера синхронизируют базу данных арендованных адресов (leases) и обеспечивают непрерывное обслуживание клиентов при сбое одного из узлов.

**Primary / Secondary (Основной / Резервный)** — роли серверов. Primary инициирует соединения и управляет балансировкой. Secondary принимает соединения и берет на себя нагрузку при отсутствии Primary.

**MCLT (Max Client Lead Time)** — максимальное время, на которое сервер может выдать или продлить аренду адреса клиенту без подтверждения от партнера. Это критический параметр для предотвращения выдачи одного IP разным клиентам при сбои связи.

**OMAPI (Object Management API)** — программный интерфейс для управления `dhcpd` «на лету» без перезагрузки, используемый утилитой `omshell`.

**Split-Brain** — катастрофическое состояние, при котором оба сервера считают партнера нерабочим и пытаются выдать 100% пула. ISC DHCP предотвращает это через MCLT и обязательную синхронизацию состояния.

**Commit-before-ACK в паре** — перед отправкой `DHCPACK` клиенту, сервер обязан записать изменение в локальный файл аренды **и** дождаться подтверждения синхронизации от партнера. Это гарантирует, что при внезапном сбое партнер не выдаст тот же IP другому клиенту.

**Hot Standby** — режим работы, при котором Secondary полностью бездействует, пока Primary не выйдет из строя. Активируется параметром `split 0` на Secondary и отключением балансировки.

---

## Основные концепции

### Обязательные требования

1.  **Синхронизация времени:** Разница во времени между серверами более 60 секунд приведет к остановке Failover-процесса. Рекомендуется использовать **Chrony** или **NTP**.
2.  **Сетевая доступность:** Серверы обмениваются данными по протоколу **TCP** через порт **647**.
3.  **Идентичность конфигурации:** Все блоки `subnet` и `pool` должны быть идентичны на обоих серверах.

### Защита от Split-Brain и синхронизация

ISC DHCP использует несколько механизмов для предотвращения потери данных при разделении сети:

- **MCLT-ограничение:** Даже если связь потеряна, сервер не может выдать аренду, превышающую MCLT, без подтверждения партнера. При `partner-down` выживший узел ждет истечения MCLT перед тем, как взять на себя 100% пула.
- **Таймаут `max-response-delay`:** Если партнер не ответил в течение указанного времени, узел считает связь потерянной и переходит в `communications-interrupted`.
- **Очередь неподтвержденных обновлений (`max-unacked-updates`):** Ограничивает количество изменений, отправленных партнеру, но не подтвержденных. При превышении отправка приостанавливается до получения ACK.

### Принцип работы и Балансировка (Split)

Для распределения нагрузки используется параметр `split` (настраивается только на Primary). Значение `128` делит пул 50/50 по алгоритму хеширования MAC-адреса клиента. Secondary всегда имеет `split 0` (или не указывает параметр).

Алгоритм работает так:
1.  Клиент отправляет `DHCPDISCOVER`.
2.  Сервер вычисляет хеш от MAC-адреса и определяет, «свой» ли это клиент.
3.  Если ответственный сервер не отвечает в течение `load balance max seconds`, второй сервер отвечает вместо него.

**Важно:** Балансировка работает только при состоянии `normal`. В `communications-interrupted` каждый узел обслуживает только свою часть пула, определенную `split`.

#### Hot Standby: отключение балансировки

Для режима горячего резерва (Primary активен, Secondary ждет):
- На Primary: `split 128` (или любое значение > 0).
- На Secondary: `split 0`.
- На Secondary можно добавить `auto;` для автоматического перехода в `partner-down` при потере Primary.

### Состояния Failover

| Состояние | Описание |
| :--- | :--- |
| `normal` | Штатный режим работы и синхронизации. |
| `communications-interrupted` | Потеря связи между серверами. Каждый узел обслуживает только свою часть пула. |
| `partner-down` | Узел считает партнера нерабочим и берет на себя 100% нагрузки после истечения MCLT. |
| `recover` | Узел запрашивает полную копию базы аренды у партнера после перезагрузки. |

#### Детализация переходов состояний

- `normal` → `communications-interrupted`: Таймаут `max-response-delay` без ответа от партнера.
- `communications-interrupted` → `partner-down`: Ручной переход через `omshell` или автоматический после истечения MCLT.
- `partner-down` → `normal`: Партнер снова доступен, начинается синхронизация.
- `recover` → `normal`: Синхронизация завершена, базы аренды идентичны.

### Параметры конфигурации: справочник

| Параметр | Настроен на | Тип | Описание |
| :--- | :--- | :--- | :--- |
| `primary` / `secondary` | Оба | role | Роль узла. Только один primary в паре. |
| `address` | Оба | IP | Локальный IP-адрес для канала синхронизации. |
| `port` | Оба | число | Порт TCP для failover-трафика (по умолчанию 647). |
| `peer address` | Оба | IP | IP-адрес партнера. |
| `peer port` | Оба | число | Порт партнера (по умолчанию 647). |
| `mclt` | Только primary | секунды | Max Client Lead Time. Рекомендуемое значение: 1 час (3600). |
| `split` | Только primary | 0–255 | Доля пула для Primary (128 = 50%). |
| `load balance max seconds` | Оба | секунды | Таймаут для ответа партнера. Если партнер не ответил, узел берет на себя запрос. |
| `max-response-delay` | Оба | секунды | Время ожидания ответа от партнера перед переходом в `communications-interrupted`. |
| `max-unacked-updates` | Оба | число | Максимум неподтвержденных обновлений в очереди. |

---

## Практические сценарии

### 1. Настройка безопасности (TSIG/HMAC)

Создайте общий ключ для защиты канала синхронизации.

```bash
tsig-keygen -a HMAC-MD5 dhcp-failover-key
# → key "dhcp-failover-key" { algorithm hmac-md5; secret "..."; };
```

### 2. Конфигурация узлов

**На стороне Primary (10.0.4.4):**
```bash
failover peer "dhcp-failover" {
    primary;
    address 10.0.4.4;
    port 647;
    peer address 10.0.4.5;
    peer port 647;
    max-response-delay 60;
    max-unacked-updates 10;
    mclt 3600;
    split 128;
    load balance max seconds 3;
}
```

**На стороне Secondary (10.0.4.5):**
```bash
failover peer "dhcp-failover" {
    secondary;
    address 10.0.4.5;
    port 647;
    peer address 10.0.4.4;
    peer port 647;
    max-response-delay 60;
    max-unacked-updates 10;
    load balance max seconds 3;
}
```

### 3. Применение в пулах

В файле `dhcpd.conf` необходимо явно указать использование failover для конкретного пула:
```bash
subnet 192.168.1.0 netmask 255.255.255.0 {
    pool {
        failover peer "dhcp-failover";
        range 192.168.1.100 192.168.1.200;
    }
}
```

**Важно:** Failover работает на уровне `pool`, а не `subnet`. Если в одной подсети несколько пулов, failover можно применить selectively.

### 4. Брандмауэр и открытые порты

На обоих серверах должны быть открыты следующие порты:

```bash
# Debian/Ubuntu (ufw)
ufw allow in on eth0 to any port 647 proto tcp comment 'DHCP Failover'
ufw allow in on eth0 to any port 67 proto udp comment 'DHCP Server'
ufw allow in on eth0 to any port 68 proto udp comment 'DHCP Client'
ufw allow in on eth0 to any port 7911 proto tcp comment 'OMAPI'

# RHEL/Rocky (firewalld)
firewall-cmd --add-service=dhcp --permanent
firewall-cmd --add-port=647/tcp --permanent
firewall-cmd --add-port=7911/tcp --permanent
firewall-cmd --reload

# nftables (диапазон подсети серверов)
nft add rule ip dhcp_filter input ip saddr 10.0.4.0/24 tcp dport 647 accept
nft add rule ip dhcp_filter input udp dport 67 accept
nft add rule ip dhcp_filter input udp dport 68 accept
```

**Рекомендация:** Ограничьте порт 647 только IP-адресом партнера. Failover-канал не должен быть доступен из всей подсети.

### 5. Systemd-юнит и привязка к интерфейсам

На Debian/Ubuntu интерфейсы указываются в `/etc/default/isc-dhcp-server`:
```bash
INTERFACESv4="eth0"
INTERFACESv6=""
```

На RHEL/Rocky параметры передаются через `/etc/sysconfig/dhcpd`:
```bash
DHCPDARGS="eth0"
```

Для принудительного запуска на конкретном интерфейсе и предотвращения запуска на неправильном:
```bash
# systemd drop-in override (Debian/Ubuntu)
sudo systemctl edit isc-dhcp-server
# → [Service]
# → ExecStart=
# → ExecStart=/usr/sbin/dhcpd -q -cf /etc/dhcp/dhcpd.conf eth0
```

### 6. Отказоустойчивость на уровне VIP (VRRP/Keepalived)

Клиенты обычно указывают IP-адрес DHCP-сервера как `dhcp-server-identifier`. При отказе Primary клиенты, получившие адрес от Secondary, могут попытаться продлить аренду через упавший Primary (T1 = 50% lease time).

Для прозрачного переключения используйте плавающий IP через **Keepalived**:

```keepalived
vrrp_instance VI_DHCP {
    state MASTER
    interface eth0
    virtual_router_id 52
    priority 150
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass dhcp_vrrp_key
    }

    virtual_ipaddress {
        192.168.1.10/24
    }

    track_script {
        check_dhcpd
    }
}

vrrp_script check_dhcpd {
    script "/usr/bin/pgrep dhcpd || exit 1"
    interval 2
    fall 2
    rise 2
}
```

**Внимание:** Keepalived управляет VIP, но не синхронизирует базу аренд. При переключении Secondary берет на себя 100% пула только после истечения MCLT.

### 7. Управление базой аренд в парах

Файл аренды на каждом узле содержит **только те записи, которые этот сервер выдал или подтвердил**. При синхронизации партнер получает только изменения.

**Бэкап:**
```bash
# Остановите сервис перед копированием
sudo systemctl stop isc-dhcp-server

# Резервная копия с отметкой времени
cp /var/lib/dhcp/dhcpd.leases /backup/dhcpd.leases.$(date +%Y%m%d_%H%M%S)

# Создайте бэкап и конфигурации
tar czf /backup/dhcp-failover-backup.tar.gz \
    /etc/dhcp/dhcpd.conf \
    /var/lib/dhcp/dhcpd.leases
```

**Восстановление:**
```bash
sudo systemctl stop isc-dhcp-server
cp /backup/dhcpd.leases.20260912 /var/lib/dhcp/dhcpd.leases
sudo systemctl start isc-dhcp-server
```

**Контроль целостности:**
```bash
# Проверка синтаксиса leases-файла
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf

# Подсчет активных аренд
grep -c "binding state active" /var/lib/dhcp/dhcpd.leases
```

### 8. Мониторинг состояния Failover

**Проверка через journalctl:**
```bash
# Мониторинг в реальном времени
sudo journalctl -u isc-dhcp-server -f | grep -E "failover|partner"

# Последние 50 строк с состоянием failover
sudo journalctl -u isc-dhcp-server --since "1 hour ago" | grep failover

# Пример вывода:
# failover: peer dhcp-failover: I move from normal to communications-interrupted
```

**Проверка через omshell:**
```bash
omshell <<EOF
server localhost
port 7911
key omapi-key "secret"
connect
new failover-state
open name="dhcp-failover"
# → local-state = 00:00:00:01 (normal)
# → partner-state = 00:00:00:01 (normal)
EOF
```

**Мониторинг через Prometheus (dhcpd-leases-exporter):**
```bash
# Установка экспортера
wget https://github.com/cspectian/dhcpd-leases-exporter/releases/latest/download/dhcpd-leases-exporter-linux-amd64
chmod +x dhcpd-leases-exporter-linux-amd64
sudo mv dhcpd-leases-exporter-linux-amd64 /usr/local/bin/dhcpd-leases-exporter

# Systemd unit
sudo tee /etc/systemd/system/dhcpd-leases-exporter.service << 'EOF'
[Unit]
Description=DHCPD Leases Exporter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/dhcpd-leases-exporter \
  --dhcpd.leasesfile=/var/lib/dhcp/dhcpd.leases \
  --web.listen-address=:9153
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now dhcpd-leases-exporter
```

**Alerting Rules (Prometheus):**
```yaml
# /etc/prometheus/rules/dhcp_alerts.yml
groups:
  - name: dhcp_alerts
    rules:
      # Failover не в normal
      - alert: DhcpFailoverDegraded
        expr: dhcp_failover_state != 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "DHCP failover state != normal ({{ $labels.instance }})"
          description: "Current state: {{ $value }}"
```

### 9. Плавное переключение (Switchover)

Для планового переключения ролей (обслуживание Primary):

1.  **Остановите dhcpd на Primary:**
    ```bash
    sudo systemctl stop isc-dhcp-server
    ```
    Secondary автоматически перейдет в `partner-down` после истечения `max-response-delay` (60 сек по умолчанию) и возьмет на себя 100% пула.

2.  **Или принудительно переведите Secondary в partner-down:**
    ```bash
    omshell <<EOF
    server localhost
    port 7911
    key omapi-key "secret"
    connect
    new failover-state
    set name = "dhcp-failover"
    set local-state = 6  # 6 = partner-down
    create
    EOF
    ```

3.  **Выполните работы на Primary.**

4.  **Запустите Primary и дождитесь перехода в `normal`:**
    ```bash
    sudo systemctl start isc-dhcp-server
    sudo journalctl -u isc-dhcp-server -f | grep failover
    # → failover: peer dhcp-failover: I move from partner-down to normal
    ```

### 10. Производительность и нюансы

- **fsync на каждый ACK:** ISC DHCP выполняет `fsync()` при каждой записи аренды. Это обеспечивает целостность, но снижает производительность на SSD (~500 аренд/сек).
- **Влияние задержки сети:** Failover-канал чувствителен к задержкам. При RTT > 100 мс увеличьте `max-response-delay` до 120–180 секунд, чтобы избежать ложных переходов в `communications-interrupted`.
- **Однопоточность:** `dhcpd` однопоточный. На узле с failover оба сервера работают независимо, но каждый обрабатывает только свою долю пула.
- **Ограничение масштаба:** ISC DHCP масштабируется до ~5 000 активных аренд на узел. Для больших сред используйте Kea DHCP с MySQL backend.

### 11. Безопасность канала синхронизации

- **TSIG/HMAC:** Всегда защищайте канал синхронизации общим ключом. Без защиты любой узел в сети может impersonate партнера.
- **Ограничение по IP:** На уровне брандмауэра разрешите порт 647 только с IP-адреса партнера.
- **Сеть управления:** Рекомендуется использовать выделенную сеть или VLAN для failover-трафика, отделенную от пользовательских подсетей.
- **Аудит доступа:** OMAPI-порт (7911) должен быть доступен только с адресов администрирования.

---

## Решение проблем

### Ручной переход в `partner-down`

Если сервер перешел в `communications-interrupted` и вы уверены, что партнер «мертв», необходимо вручную перевести выживший узел в `partner-down`, иначе он не сможет выдавать адреса из части пула партнера.

**Через `omshell`:**
```bash
omshell
> port 7911
> key omapi-key "secret"
> connect
> new failover-state
> set name = "dhcp-failover"
> set local-state = 6  # 6 = partner-down
> create
# → obj: failover-state ... local-state = 00:00:00:06
```

### Диагностика

1.  **Проверка логов:**
    ```bash
    sudo journalctl -u isc-dhcp-server -f | grep failover
    # → failover: peer dhcp-failover: I move from normal to communications-interrupted
    ```
2.  **Проверка файла аренды:**
    Проверьте текущее состояние узла в конце файла `/var/lib/dhcp/dhcpd.leases`.
3.  **Проверка связности:**
    ```bash
    # TCP-соединение на порт 647
    nc -zv 10.0.4.5 647
    # → Connection succeeded

    # Разрешение DNS (если используете имена)
    dig +short dhcp-secondary.internal
    ```

### Типичные ошибки и решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Failover не переходит в `normal`** | Разница времени > 60 сек | Проверьте NTP/Chrony: `chronyc tracking` |
| **Оба сервера в `communications-interrupted`** | Брандмауэр блокирует TCP/647 | Откройте порт 647 в обоих направлениях |
| **Secondary не отвечает** | `split 0` не настроен на Secondary | Добавьте `split 0;` или уберите `split` на Secondary |
| **Одинаковый IP разным клиентам (дубликат)** | MCLT слишком большое значение при высокой нагрузке | Уменьшите MCLT до 1800–2700 секунд |
| **`partner-down` не включается автоматически** | `max-response-delay` слишком мал для среды с высокой задержкой | Увеличьте `max-response-delay` до 120–180 сек |
| **Потеря аренд после перезагрузки** | Файл `dhcpd.leases` поврежден или не записан | Проверьте права: `ls -la /var/lib/dhcp/dhcpd.leases` |
| **Клиенты не получают адрес от Secondary** | Secondary не в `normal` | Проверьте `journalctl` и состояние failover |
| **Синхронизация зависает** | Несовпадение `subnet` на Primary и Secondary | Проверьте конфиги: `diff /etc/dhcp/dhcpd.conf` |

---

## Миграция на Kea DHCP

Для новых развертываний в 2026 году рекомендуется Kea DHCP. Миграция Failover-конфигурации требует ручного перехода на HA hooks с общим MySQL/PostgreSQL backend.

Подробное руководство: **[Kea DHCP: Миграция с ISC](./kea_dhcp_migration.md)**

---

## Дополнительная информация

- **[Обзор ISC DHCP](./isc_dhcp_server_overview.md)** — архитектура и компоненты.
- **[Механизмы High Availability](../../../../Concepts/High_Availability/ha_failover_mechanisms.md)** — теория отказоустойчивости.
