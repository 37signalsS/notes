# ISC DHCP Failover — отказоустойчивая пара серверов

> **Важно:** ISC (Internet Systems Consortium) DHCP устарел (EOL — End of Life). Для новых развёртываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)** с поддержкой **HA (High Availability — высокая доступность)** через hook-модули.
> См. также: [Защита от rogue DHCP](../../../../Networking/Protocols/DHCP/dhcp_security.md).

## Определения

**DHCP Failover** — протокол обеспечения высокой доступности, при котором два сервера **DHCP (Dynamic Host Configuration Protocol — протокол динамической настройки узла)** синхронизируют базу данных арендованных адресов и обеспечивают непрерывную работу при сбое одного из узлов.

**Primary / Secondary (Основной / Резервный)** — роли серверов в паре. Primary управляет распределением пула и задаёт параметры синхронизации. Secondary выполняет запросы и заменяет Primary при сбое.

**MCLT (Max Client Lead Time)** — максимальный интервал времени, на который один сервер может продлить аренду адреса клиенту без подтверждения от партнёра. Параметр настраивается только на Primary.

**Split** — алгоритм балансировки нагрузки (Hash-based), разделяющий пул адресов. Значение `128` означает разделение 50/50.

## Основные концепции

### Обязательные требования

Для корректной работы Failover необходимо выполнение следующих условий:
1. **Синхронизация времени:** Время на обоих серверах должно быть идентичным (рекомендуется использование **NTP (Network Time Protocol — протокол сетевого времени)** или **Chrony**). Разница более чем в несколько секунд приведёт к разрыву связи между узлами.
2. **Связанность по сети:** Серверы должны иметь доступ друг к другу по протоколу **TCP (Transmission Control Protocol — протокол управления передачей)** через порт **647**.
3. **Идентичность конфигураций:** Блоки `subnet` и `shared-network` должны быть полностью одинаковыми на обоих узлах.

### Принцип работы

1. **Синхронизация:** Обмен информацией о выданных адресах происходит по TCP/647.
2. **Балансировка:** Оба сервера могут одновременно отвечать клиентам, используя алгоритм хеширования (параметр `split`).
3. **Отказоустойчивость:** Если один сервер перестаёт отвечать, второй переходит в состояние `communications-interrupted`, а затем (при необходимости) в `partner-down`, принимая на себя обслуживание всего пула.

### Состояния отказоустойчивой пары

| Состояние | Описание |
| :--- | :--- |
| `normal` / `balanced` | Штатный режим, синхронизация активна, нагрузка распределена. |
| `communications-interrupted` | Потеря связи. Серверы продолжают выдавать адреса из своих частей пула. |
| `partner-down` | Один сервер официально признан нерабочим. Второй узел обслуживает 100% запросов. |
| `potentially-down` | Переходное состояние, когда один узел подозревает сбой партнёра. |
| `recover` | Узел запрашивает у партнёра обновление базы аренды после перезагрузки. |
| `shutdown` | Штатная остановка узла администратором. |

## Практические сценарии

### Настройка безопасности (HMAC-ключи)

Для защиты канала синхронизации рекомендуется использовать аутентификацию по ключу.

1. **Генерация ключа:**
    ```bash
    dnssec-keygen -a HMAC-MD5 -b 128 -n USER dhcp-key
    ```
2. **Добавление в конфиг:**
    ```bash
    key "dhcp-failover-key" {
        algorithm hmac-md5;
        secret "ВАШ_СЕКРЕТНЫЙ_КЛЮЧ==";
    };
    ```

### Конфигурация серверов

**Primary сервер (10.0.4.4):**
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
    split 128; # Настраивается только на Primary
    load balance max seconds 3;
}

include "/etc/dhcp/dhcpd.conf.d/subnets.conf";
```

**Secondary сервер (10.0.4.5):**
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

include "/etc/dhcp/dhcpd.conf.d/subnets.conf";
```

### Настройка межсетевого экрана

**Пример для `ufw` (Debian/Ubuntu):**
```bash
sudo ufw allow from 10.0.4.4 to any port 647 proto tcp
```

**Пример для `firewalld` (RHEL):**
```bash
sudo firewall-cmd --add-rich-rule='rule family="ipv4" source address="10.0.4.5" port port="647" protocol="tcp" accept' --permanent
sudo firewall-cmd --reload
```

## Решение проблем

### Ручное объявление партнёра нерабочим

Если основной сервер вышел из строя и не восстановится быстро, необходимо перевести резервный сервер в состояние `partner-down`. Это **не происходит автоматически** для предотвращения ситуации **Split-Brain** (разделения сознания).

**Способ 1: через `omshell`**
```bash
omshell
> server localhost
> port 7911
> key dhcp-failover-key "secret"
> connect
> new failover-state
> set name = "dhcp-failover"
> set local-state = 6 # 6 соответствует partner-down
> create
```

**Способ 2: правка файла аренды (lease file)**
Остановите службу, найдите блок `failover-state` в `/var/lib/dhcp/dhcpd.leases` и измените `my state communications-interrupted` на `my state partner-down`.

### Диагностика

* **Логи синхронизации:**
    ```bash
    sudo journalctl -u isc-dhcp-server -f | grep failover
    ```
* **Проверка портов:**
    ```bash
    ss -tnlp | grep :647
    ```

## Дополнительная информация

- [Обзор ISC DHCP и архитектура](./isc_dhcp_server_overview.md) — общие сведения и Kea.
- [Протокол DHCP: теория](../../../../Networking/Protocols/DHCP/dhcp_overview.md) — процесс DORA и опции.
- [Механизмы High Availability](../../../../Concepts/High_Availability/ha_failover_mechanisms.md) — теория Heartbeat и Split-Brain.
- [Диагностика DHCP](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md) — поиск проблем с арендой.
