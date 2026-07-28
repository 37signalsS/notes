# ICMP: Диагностика и безопасность

**Reliability Score: 10/10** (SSoT + Проверено по RFC 792/4443 и стандартам Netfilter 2026)

## Определения

**Диагностика ICMP** — использование служебных сообщений протокола ICMP для анализа топологии сети, выявления узких мест, измерения задержек и отладки проблем MTU.

**Безопасность ICMP** — стратегия настройки сетевых экранов и параметров ядра ОС для минимизации рисков сетевой разведки, DoS-атак и несанкционированного управления маршрутизацией при сохранении критической функциональности сети.

**Критический ICMPv6** — набор сообщений (NDP, RA/RS, Packet Too Big), без которых работа стека IPv6 невозможна. В отличие от IPv4, полное блокирование ICMPv6 делает узел неработоспособным в IPv6-сети.

## Основные концепции

### Последствия некорректной блокировки (ICMP Black Hole)

Полная блокировка ICMP-трафика ("Security through obscurity") — одна из самых частых ошибок системного администрирования.

*   **Проблема PMTUD:** При блокировке `Destination Unreachable` (Type 3 Code 4) отправитель не узнает, что пакет слишком велик для канала. В результате TCP-сессия устанавливается (маленькие пакеты проходят), но передача данных (большие пакеты) "зависает".
*   **Слепая трассировка:** Запрет `Time Exceeded` (Type 11) делает невозможной работу `traceroute` и `mtr`, что критично при поиске места разрыва связи.
*   **Ложные срабатывания мониторинга:** Блокировка `Echo` лишает возможности быстрого контроля доступности узла (L3-check).

### Рекомендуемая политика фильтрации (SSoT)

Для современных серверов рекомендуется разрешать только необходимые типы сообщений с применением ограничений скорости (Rate Limiting).

| Тип (v4 / v6) | Название | Действие | Обоснование |
| :--- | :--- | :--- | :--- |
| **8 / 128** | Echo Request | **Accept + Limit** | Разрешить для мониторинга, ограничить для защиты от флуда. |
| **3 / 1** | Destination Unreachable | **Accept** | Обязательно для PMTUD и быстрой реакции TCP на ошибки. |
| **11 / 3** | Time Exceeded | **Accept** | Обязательно для трассировки и предотвращения петель. |
| **— / 2** | Packet Too Big | **Accept** | **Критично для IPv6** (заменяет v4 Frag Needed). |
| **— / 133-137** | NDP (NS/NA/RS/RA/Redirect) | **Accept (Local)** | **Критично для IPv6**. Разрешать только на `link-local` уровне. |
| **5 / 137** | Redirect | **Drop** | Блокировать для предотвращения MITM-атак (перехват трафика). |

## Практические сценарии

### Настройка через nftables (Современный стандарт)

Использование семейства `inet` позволяет управлять обоими стеками (IPv4/IPv6) в одном месте.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Разрешить установленные соединения
        ct state established,related accept

        # 2. Разрешить критический ICMPv4
        icmp type { destination-unreachable, time-exceeded } accept
        icmp type echo-request limit rate 5/second accept

        # 3. Разрешить критический ICMPv6 (SLAAC, NDP, PMTUD)
        icmpv6 type { 
            destination-unreachable, packet-too-big, 
            time-exceeded, parameter-problem, 
            echo-request, nd-router-advert, 
            nd-neighbor-solicit, nd-neighbor-advert 
        } accept
    }
}
```

### Защита от специфических атак

1.  **ICMP Redirect Attack:** Защита на уровне ядра Linux (`sysctl`).
    ```bash
    sysctl -w net.ipv4.conf.all.accept_redirects=0
    sysctl -w net.ipv6.conf.all.accept_redirects=0
    ```
2.  **Smurf Attack (Усиление):** Запрет ответа на широковещательные запросы.
    ```bash
    sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=1
    ```
3.  **ICMP Tunneling:** Трафик инкапсулируется в поле `Data` эхо-пакетов. Защита: ограничение размера пакета (MTU) и глубокая инспекция (DPI).

### Диагностика "Зависших" сессий

Если `ping` проходит, а `curl` или `ssh` виснет — проверяем MTU:
```bash
# Поиск узкого места в MTU без прав root
tracepath -n google.com

# Ручная проверка с запретом фрагментации (DF-бит)
# -s 1472 (data) + 8 (icmp) + 20 (ip) = 1500 байт
ping -s 1472 -M do 8.8.8.8
```

## Дополнительная информация

*   **[Обзор протокола ICMP](./icmp_overview.md)** — общая структура и типы сообщений.
*   **[RFC 4890](https://tools.ietf.org/html/rfc4890)** — рекомендации по фильтрации ICMPv6 в межсетевых экранах.
*   **[MTU и диагностика PMTUD](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — подробнее о "черных дырах" в сети.
*   **[Сетевая диагностика Linux](../../../Linux/Diagnostics/Networking/ping.md)** — использование `ping` и `mtr`.
