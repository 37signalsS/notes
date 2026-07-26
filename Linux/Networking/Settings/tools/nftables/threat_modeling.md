# nftables — моделирование угроз и схемы защиты

## Определения

**Моделирование угроз** — систематический процесс выявления, анализа и оценки потенциальных угроз безопасности для определения оптимальных мер противодействия.

**DoS/DDoS (Denial of Service)** — атака, направленная на приведение сетевого ресурса или узла в состояние, при котором он становится недоступен для легитимных пользователей из-за исчерпания ресурсов (полосы пропускания, процессорного времени, памяти).

**IP-спуфинг (IP Spoofing)** — техника подмены IP-адреса источника в заголовке пакета с целью обхода механизмов аутентификации на основе адреса или организации атак типа "отражение" (reflection).

**SYN-флуд (SYN Flood)** — вид DoS-атаки на транспортном уровне, использующий механизм "трёхэтапного рукопожатия" TCP для переполнения очереди соединений сервера.

**Брутфорс (Brute-force)** — метод автоматизированного перебора комбинаций (паролей, ключей) для получения несанкционированного доступа к сервису.

## Основные концепции

### Алгоритм разработки политики безопасности

При проектировании набора правил nftables рекомендуется следовать циклу:

1.  **Инвентаризация активов:** Определение критических сервисов (порты, протоколы) и легитимных источников трафика.
2.  **Анализ векторов атак:** Оценка рисков для каждого сервиса (например, уязвимость SSH к брутфорсу).
3.  **Формирование схемы разграничения:** Выбор одной из типовых моделей защиты (см. ниже).
4.  **Техническая реализация:** Написание правил nftables с использованием современных механизмов (динамические сеты, коннект-трекинг).
5.  **Валидация и аудит:** Регулярная проверка эффективности правил и анализ логов на предмет аномалий.

### Типовые угрозы и меры нейтрализации

| Угроза | Вектор атаки | Реализация в nftables |
| :--- | :--- | :--- |
| **SYN-флуд** | L4 (TCP) | Применение `synproxy` для разгрузки стека или `limit rate` для пакетов с флагом SYN. |
| **Сканирование портов** | Разведка (Recon) | Блокировка пакетов в состоянии `invalid`, лимиты на новые соединения и ловушки (Port Knocking). |
| **IP-спуфинг** | L3 (IP) | Проверка соответствия входящего интерфейса и адреса (фильтрация Bogon и Martians). |
| **Брутфорс** | L7 (Application) | Динамические списки (`set`) с флагом `timeout` для автоматической блокировки атакующих IP. |
| **Некорректные пакеты** | Эксплуатация стека | Глубокая проверка TCP-флагов и отбрасывание фрагментированных пакетов (`ip frag-off & 0x3fff != 0`). |
| **Утечка данных** | Исходящий трафик | Строгая политика `DROP` в цепочке `output` с разрешением только доверенных назначений. |

### Источники данных для моделирования

Для актуализации модели угроз рекомендуется использовать:
- [MITRE ATT&CK Matrix](https://attack.mitre.org/) (раздел Network)
- [CISA Known Exploited Vulnerabilities](https://www.cisa.gov/known-exploited-vulnerabilities-catalog)
- Списки **Bogon/Martian IPs** (Team Cymru, IANA)
- Данные Threat Intelligence (abuse.ch, OTX AlienVault)

---

## Практические сценарии

Ниже приведены реализации схем защиты, соответствующие различным уровням риска.

### Сценарий №1: Базовая защита узла (Stateful Firewall)

Подходит для рабочих станций и серверов во внутреннем контуре. Основной упор на отслеживание состояния соединений.

```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Разрешить установленные соединения (Stateful)
        ct state established,related accept

        # 2. Отбросить некорректные пакеты
        ct state invalid drop

        # 3. Разрешить локальный трафик
        iif "lo" accept

        # 4. Разрешить ICMP (ping) с ограничением частоты
        icmp type echo-request limit rate 5/second accept
        
        # 5. Разрешить SSH для управления (рекомендуется ограничение по IP)
        tcp dport 22 accept
    }
}
```

### Сценарий №2: Защита публичного веб-сервера (Anti-DDoS Baseline)

Включает защиту от спуфинга, ограничение скорости новых соединений и базовую фильтрацию TCP.

```bash
table inet filter {
    # Список для временной блокировки агрессивных источников
    set blackhole {
        type ipv4_addr
        flags timeout
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Блокировка по черному списку
        ip saddr @blackhole drop

        # Защита от спуфинга: отбрасывать пакеты с loopback-адресами извне
        iif != "lo" ip saddr 127.0.0.0/8 drop
        
        ct state established,related accept
        ct state invalid drop

        # Защита от SYN-флуда на HTTP/HTTPS портах
        tcp dport { 80, 443 } tcp flags syn limit rate over 100/second add @blackhole { ip saddr timeout 1m } drop
        tcp dport { 80, 443 } accept

        # Разрешить SSH с защитой от перебора (более 3 поп/мин -> бан на 15 мин)
        tcp dport 22 ct state new limit rate over 3/minute add @blackhole { ip saddr timeout 15m } drop
        tcp dport 22 accept
    }
}
```

### Сценарий №3: Безопасный шлюз (Egress Filtering)

Максимальное ограничение исходящего трафика для предотвращения связи вредоносного ПО с C2-серверами (Command & Control).

```bash
table inet filter {
    chain output {
        type filter hook output priority 0; policy drop;

        # Разрешить уже установленные ответы на входящие запросы
        ct state established,related accept

        # Разрешить DNS только к доверенным серверам
        udp dport 53 ip daddr { 8.8.8.8, 1.1.1.1 } accept

        # Разрешить HTTP/HTTPS только для обновлений системы (например, к зеркалам)
        tcp dport { 80, 443 } ip daddr @update_mirrors accept

        # Разрешить NTP для синхронизации времени
        udp dport 123 accept
    }
}
```

### Сценарий №4: Глубокая инспекция и Synproxy

Для высоконагруженных систем, подверженных постоянным атакам на стек TCP. Использование `synproxy` позволяет серверу не выделять ресурсы на соединение до тех пор, пока клиент не подтвердит владение IP-адресом (завершит рукопожатие).

```bash
table inet raw {
    chain prerouting {
        type filter hook prerouting priority -300;
        
        # Направить SYN-пакеты на веб-порты в synproxy
        tcp dport { 80, 443 } tcp flags syn notrack
    }
}

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        
        # Обработка пакетов, прошедших через synproxy
        tcp dport { 80, 443 } ct state invalid,untracked synproxy mss 1460 wscale 7 sack-perm accept
        
        ct state established,related accept
    }
}
```

---

## Дополнительная информация

### См. также

- [nftables — архитектура и основные концепции](./architecture_and_concepts.md)
- [Практические сценарии nftables](./practical_scenarios.md)
- [Тестирование правил nftables](./firewall_testing.md)
- [Рекомендации по настройке правил файрвола](../../../../../Networking/Concepts/firewall_rules_best_practices.md)
- [Bogon IPs (Martians) List](https://www.team-cymru.com/bogon-reference)
