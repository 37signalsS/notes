# IPsec: диагностика KAME/racoon

> **SSoT:** Основной документ по IPsec — [ipsec.md](./ipsec.md). Данный файл содержит историческую документацию по диагностике устаревшей реализации KAME/racoon.
>
> **⚠ Устаревшая реализация:** Для диагностики strongSwan см. [раздел troubleshooting в SSoT](./ipsec.md#диагностика-и-troubleshooting).

---

## Definitions

**KAME Diagnostics** — набор команд и утилит для проверки работоспособности IPsec-туннелей в стеке KAME: `racoonctl`, `setkey`, логи демона racoon.

---

## Basic Concepts

### Принцип работы IPsec-туннеля

> **Важно:** Туннель поднимается только при наличии трафика! Без тестового пакета (ping) фазы IKE не начнутся.

### Инструменты диагностики KAME

| Утилита | Назначение |
|---------|------------|
| `racoonctl show-sa isakmp` | Проверка SA фазы 1 (ISAKMP) |
| `racoonctl show-sa esp` | Проверка SA фазы 2 (ESP/AH) |
| `setkey -D` | Просмотр SAD из ядра |
| `setkey -DP` | Просмотр SPD из ядра |
| `tcpdump` | Анализ IKE/ESP трафика |
| `/var/log/daemon.log` | Логи демона racoon |

---

## Practical Scenarios

### Проверка работоспособности

**Тестовый пинг для поднятия туннеля:**

```bash
ping -I 192.168.1.1 192.168.255.1
```

### Диагностика ISAKMP SA (Фаза 1)

```bash
racoonctl show-sa isakmp
```

**Пример вывода:**

```
Destination    Cookies                              Created
10.0.1.1.500   356a7e11111a93f:367111530375c065    2018-10-02 09:18:28
```

**Интерпретация:** Наличие записи означает успешное прохождение фазы 1. Отсутствует — проблема с IKE (PSK, алгоритмы, сетевая связимость).

### Диагностика ESP SA (Фаза 2)

```bash
racoonctl show-sa esp
```

**Пример вывода:**

```
10.0.1.1 10.0.255.1
esp mode=tunnel spi=2148175815(0x800a8fc7) reqid=0(0x00000000)
E: 3des-cbc 799e587f 6a2b4b78 5590cc2a 3d3ee331 f7e7f472 01abcdef
A: hmac-sha1 01c5161f 46679a36 5d07ee9d f159fc9a 01abcdef
seq=0x00000000 replay=4 flags=0x00000000 state=mature
created: Oct 2 09:22:44 2018 current: Oct 2 10:39:21 2018
diff: 4597(s) hard: 28800(s) soft: 23040(s)
```

**Ключевые поля:**

| Поле | Значение |
|------|----------|
| `state=mature` | SA активен и готов к работе |
| `hard` | Жёсткий лимит времени жизни (пересоздание SA) |
| `soft` | Мягкий лимит (предупреждение о скором истечении) |
| `E:` | Параметры шифрования (алгоритм + ключ) |
| `A:` | Параметры аутентификации (алгоритм + ключ) |

### Анализ трафика (tcpdump)

**Мониторинг IKE-трафика:**

```bash
tcpdump -i eth1 host 10.0.255.1
```

**Захват ESP-трафика для анализа:**

```bash
tcpdump -i eth1 -w ipsec.pcap esp &
# ... запуск тестового трафика (ping, telnet, netcat) ...
killall tcpdump
tcpdump -vr ipsec.pcap
```

**Пример вывода tcpdump (успешное прохождение фаз):**

```
18:01:06.409631 IP 10.0.1.1.500 > 10.0.255.1.500: isakmp: phase 1 I ident
18:01:06.439276 IP 10.0.255.1.500 > 10.0.1.1.500: isakmp: phase 1 R ident
18:01:07.412451 IP 10.0.1.1.500 > 10.0.255.1.500: isakmp: phase 2/others I oakley-quick[E]
18:01:08.467373 IP 10.0.1.1 > 10.0.255.1: ESP(spi=0x7aabfa82,seq=0x1), length 116
```

**Интерпретация:**

| Строка | Значение |
|--------|----------|
| `phase 1 I ident` | Инициатор начинает фазу 1 (Main mode) |
| `phase 1 R ident` | Респондент отвечает |
| `phase 2/others I oakley-quick[E]` | Инициатор начинает фазу 2 (Quick mode) |
| `ESP(spi=...,seq=...)` | Туннель активен, идёт передача данных |

### Логи racoon

```bash
cat /var/log/daemon.log
```

**Успешное установление:**

```
Oct 3 17:53:26 racoon: INFO: initiate new phase 1 negotiation: 10.0.1.1[500]<=>10.0.255.1[500]
Oct 3 17:53:26 racoon: INFO: ISAKMP-SA established 10.0.1.1[500]-10.0.255.1[500]
Oct 3 17:53:27 racoon: INFO: IPsec-SA established: ESP/Tunnel 10.0.1.1[500]->10.0.255.1[500]
```

**Повышение уровня логирования** (`/etc/racoon.conf`):

```bash
log debug;  # Максимальный уровень детализации
```

---

## Additional Information

### Типовые проблемы и решения

| Проблема | Возможная причина | Решение |
|----------|-------------------|---------|
| Туннель не поднимается | Нет трафика | Отправить тестовый пакет (`ping -I`) |
| `No route to host` | Проблема с ARP для /32 маски | Добавить статическую ARP-запись |
| Фаза 1 не проходит | Несоответствие PSK или алгоритмов | Проверить `/etc/racoon/psk.txt` и `exchange_mode` |
| Фаза 2 не проходит | Несоответствие SP | Проверить `spdadd` правила в `/etc/ipsec-tools.conf` |
| Трафик не идёт | Неправильная маршрутизация | Проверить маршруты и secondary IP |
| `racoonctl` не находит SA | Демон racoon не запущен | `service racoon start` |

### Порядок диагностики

1. **Проверить сетевую связимость:** `ping` между внешними IP
2. **Запустить tcpdump:** `tcpdump -i eth1 host <remote_ip>`
3. **Отправить тестовый трафик:** `ping -I <local_svc> <remote_svc>`
4. **Проверить фазу 1:** `racoonctl show-sa isakmp`
5. **Проверить фазу 2:** `racoonctl show-sa esp`
6. **Проверить логи:** `cat /var/log/daemon.log`
7. **Проверить SAD/SPD ядра:** `setkey -D`, `setkey -DP`

### Связанные документы

- **[IPsec (основной SSoT)](./ipsec.md)** — определения, протоколы, настройка, troubleshooting strongSwan
- **[Архитектура IPsec](./ipsec_architecture.md)** — детальное описание SA, SP, режимы инкапсуляции
- **[Настройка KAME/racoon](./ipsec_linux_setup.md)** — конфигурация KAME/racoon
- **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — основы работы с утилитой
