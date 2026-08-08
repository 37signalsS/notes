# ISC DHCP Failover — отказоустойчивая пара серверов

> **Важно:** ISC DHCP официально признан устаревшим (EOL). Для новых развёртываний рекомендуется использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)** с нативной поддержкой HA.

---

## Определения

**DHCP Failover** — протокол обеспечения высокой доступности, при котором два сервера синхронизируют базу данных арендованных адресов (leases) и обеспечивают непрерывное обслуживание клиентов при сбое одного из узлов.

**Primary / Secondary (Основной / Резервный)** — роли серверов. Primary инициирует соединения и управляет балансировкой. Secondary принимает соединения и берет на себя нагрузку при отсутствии Primary.

**MCLT (Max Client Lead Time)** — максимальное время, на которое сервер может выдать или продлить аренду адреса клиенту без подтверждения от партнера. Это критический параметр для предотвращения выдачи одного IP разным клиентам при сбое связи.

**OMAPI (Object Management API)** — программный интерфейс для управления `dhcpd` «на лету» без перезагрузки, используемый утилитой `omshell`.

---

## Основные концепции

### Обязательные требования

1.  **Синхронизация времени:** Разница во времени между серверами более 60 секунд приведет к остановке Failover-процесса. Рекомендуется использовать **Chrony** или **NTP**.
2.  **Сетевая доступность:** Серверы обмениваются данными по протоколу **TCP** через порт **647**.
3.  **Идентичность конфигурации:** Все блоки `subnet` и `pool` должны быть идентичны на обоих серверах.

### Принцип работы и Балансировка (Split)

Для распределения нагрузки используется параметр `split 128` (настраивается только на Primary).
- Значение `128` делит пул 50/50.
- Алгоритм хеширования (на базе MAC-адреса клиента) определяет, какой сервер должен ответить. Если «ответственный» сервер молчит более `load balance max seconds`, второй сервер отвечает вместо него.

### Состояния Failover

| Состояние | Описание |
| :--- | :--- |
| `normal` | Штатный режим работы и синхронизации. |
| `communications-interrupted` | Потеря связи между серверами. Каждый узел обслуживает только свою часть пула. |
| `partner-down` | Узел считает партнера нерабочим и берет на себя 100% нагрузки после истечения MCLT. |
| `recover` | Узел запрашивает полную копию базы аренды у партнера после перезагрузки. |

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

---

## Дополнительная информация

- **[Обзор ISC DHCP](./isc_dhcp_server_overview.md)** — архитектура и компоненты.
- **[Протокол DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — основы функционирования.
- **[Механизмы High Availability](../../../../Concepts/High_Availability/ha_failover_mechanisms.md)** — теория отказоустойчивости.
- **[Безопасность DHCP](../../../../Networking/Protocols/DHCP/dhcp_security.md)** — защита от Rogue DHCP.
- **[Диагностика DHCP](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)** — методы анализа трафика.
