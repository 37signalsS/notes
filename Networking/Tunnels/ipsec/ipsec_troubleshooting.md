# IPSec: диагностика и troubleshooting

## Проверка работоспособности

**Важно:** Туннель поднимается только при наличии трафика!

```bash
# Пинг с конкретного IP
ping -I 192.168.1.1 192.168.255.1
```

---

## Диагностика ISAKMP SA

```bash
racoonctl show-sa isakmp
```

### Пример вывода

```
Destination Cookies Created
10.0.1.1.500 356a7e11111a93f:367111530375c065 2018-10-02 09:18:28
```

---

## Диагностика ESP SA

```bash
racoonctl show-sa esp
```

### Пример вывода

```
10.0.1.1 10.0.255.1
esp mode=tunnel spi=2148175815(0x800a8fc7) reqid=0(0x00000000)
E: 3des-cbc 799e587f 6a2b4b78 5590cc2a 3d3ee331 f7e7f472 01abcdef
A: hmac-sha1 01c5161f 46679a36 5d07ee9d f159fc9a 01abcdef
seq=0x00000000 replay=4 flags=0x00000000 state=mature
created: Oct 2 09:22:44 2018 current: Oct 2 10:39:21 2018
diff: 4597(s) hard: 28800(s) soft: 23040(s)
```

---

## Анализ трафика (tcpdump)

### Мониторинг установления соединения

```bash
# Мониторинг установления соединения
tcpdump -i eth1 host 10.0.255.1

# Захват ESP-трафика для анализа
tcpdump -i eth1 -w ipsec.pcap esp &
# ... запуск тестового трафика (ping, telnet, netcat) ...
killall tcpdump
tcpdump -vr ipsec.pcap
```

### Пример вывода tcpdump

```
18:01:06.409631 IP 10.0.1.1.500 > 10.0.255.1.500: isakmp: phase 1 I ident
18:01:06.439276 IP 10.0.255.1.500 > 10.0.1.1.500: isakmp: phase 1 R ident
18:01:07.412451 IP 10.0.1.1.500 > 10.0.255.1.500: isakmp: phase 2/others I oakley-quick[E]
18:01:08.467373 IP 10.0.1.1 > 10.0.255.1: ESP(spi=0x7aabfa82,seq=0x1), length 116
```

---

## Логи racoon

```bash
cat /var/log/daemon.log
```

### Успешное установление

```
Oct 3 17:53:26 racoon: INFO: initiate new phase 1 negotiation: 10.0.1.1[500]<=>10.0.255.1[500]
Oct 3 17:53:26 racoon: INFO: ISAKMP-SA established 10.0.1.1[500]-10.0.255.1[500]
Oct 3 17:53:27 racoon: INFO: IPsec-SA established: ESP/Tunnel 10.0.1.1[500]->10.0.255.1[500]
```

---

## Типовые проблемы

| Проблема | Возможная причина | Решение |
|----------|-------------------|---------|
| Туннель не поднимается | Нет трафика | Отправить тестовый пакет (ping) |
| `No route to host` | Проблема с ARP для /32 маски | Добавить статическую ARP-запись |
| Фаза 1 не проходит | Несоответствие параметров PSK или алгоритмов | Проверить `/etc/racoon/psk.txt` и `exchange_mode` |
| Фаза 2 не проходит | Несоответствие SP | Проверить `spdadd` правила в `/etc/ipsec-tools.conf` |
| Трафик не идёт | Неправильная маршрутизация | Проверить маршруты и secondary IP |

---

## Связанные документы

- **[IPSec: архитектура](./ipsec_architecture.md)** — концепции SA, SP, режимы инкапсуляции
- **[IPSec: настройка на Linux](./ipsec_linux_setup.md)** — конфигурация racoon и setkey
- **[tcpdump](../ServicesAndTools/Wireshark/tcpdump.md)** — основы работы с утилитой
