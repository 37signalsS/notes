# ISC DHCP-сервер: Настройка отказоустойчивости (Failover)

Для обеспечения высокой доступности (High Availability) службы DHCP настраивают два сервера в режиме failover. Они синхронизируют между собой информацию о выданных адресах и могут подменять друг друга в случае сбоя.

## Принцип работы
1.  **Два сервера:** Один настраивается как `primary`, другой как `secondary`.
2.  **Синхронизация:** Серверы обмениваются информацией о выданных арендах по TCP-порту 647.
3.  **Разделение нагрузки:** Пул адресов делится между серверами (`split`), что позволяет распределять нагрузку.

## Шаг 1: Организация конфигурационных файлов
Конфигурация для failover-пары почти идентична, за исключением нескольких параметров. Рекомендуется вынести общие части в отдельные файлы и подключать их через `include`.

Структура может быть такой:
- `/etc/dhcp/dhcpd.conf`: Содержит уникальные для каждого сервера failover-параметры.
- `/etc/dhcp/dhcpd.conf.d/subnets.conf`: Общие определения `subnet`.
- `/etc/dhcp/dhcpd.conf.d/reservations.conf`: Общие определения `host` (резервации).

## Шаг 2: Настройка `dhcpd.conf`

**Конфигурация для `primary` сервера (например, 10.0.4.4):**
```ini
# /etc/dhcp/dhcpd.conf на PRIMARY сервере

# Определение failover-пары
failover peer "dhcp-failover" {
    primary; # Этот сервер - основной
    address 10.0.4.4; # Его собственный IP для обмена
    port 647;
    peer address 10.0.4.5; # IP второго сервера
    peer port 647;
    
    max-response-delay 60; # Ждать 60 сек, прежде чем считать партнера "упавшим"
    max-unacked-updates 10; # Кол-во обновлений без подтверждения
    
    # Обязательные параметры для primary
    mclt 3600; # Max Client Lead Time. Время, на которое один сервер может продлить аренду без ведома другого
    split 128; # Распределение адресов 50/50 (256 - все на primary, 0 - все на secondary)
    load balance max seconds 3;
}

# Подключение общих файлов конфигурации
include "/etc/dhcp/dhcpd.conf.d/subnets.conf";
include "/etc/dhcp/dhcpd.conf.d/reservations.conf";
```

**Конфигурация для `secondary` сервера (например, 10.0.4.5):**
```ini
# /etc/dhcp/dhcpd.conf на SECONDARY сервере

failover peer "dhcp-failover" {
    secondary; # Этот сервер - вторичный
    address 10.0.4.5; # Его собственный IP
    port 647;
    peer address 10.0.4.4; # IP первого сервера
    peer port 647;
    
    max-response-delay 60;
    max-unacked-updates 10;
    load balance max seconds 3;
}

# Подключение общих файлов конфигурации
include "/etc/dhcp/dhcpd.conf.d/subnets.conf";
include "/etc/dhcp/dhcpd.conf.d/reservations.conf";
```

## Шаг 3: Модификация `subnets.conf`
В каждой подсети, которая должна быть отказоустойчивой, необходимо указать имя failover-пары. Диапазон адресов (`range`) заключается в блок `pool`.

```ini
# /etc/dhcp/dhcpd.conf.d/subnets.conf

subnet 10.0.10.0 netmask 255.255.255.0 {
    option routers 10.0.10.1;
    
    pool {
        failover peer "dhcp-failover"; # Указываем нашу failover-пару
        range 10.0.10.100 10.0.10.200;
    }
}
```

## Шаг 4: Настройка файрвола
На обоих DHCP-серверах необходимо разрешить входящие подключения на порт **TCP/647** для обмена failover-сообщениями.

---
*   **Далее:** [Настройка DHCP Relay](./isc_dhcp_server_relay.md)
*   **Назад:** [Резервирование IP и маршруты](./isc_dhcp_server_reservations.md)
