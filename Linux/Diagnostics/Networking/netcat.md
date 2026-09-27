# Netcat (nc): универсальный сетевой инструмент

## Определения

**Netcat (nc)** — утилита командной строки для чтения и записи данных по сетевым соединениям TCP/UDP. Часто называется «швейцарским ножом сетевого администрирования» за простоту и универсальность. Используется для проверки портов, передачи файлов, создания простых серверов, отладки протоколов и даже передачи потоков данных (shell).

**Реализации:**
- **netcat-openbsd** — дефолтная в Debian/Ubuntu. Поддерживает `-X` (proxy), `-x` (SOCKS), `-k` (keep-alive), UDP.
- **netcat-traditional** — классическая реализация GNU. Поддерживает `-e` (exec), `-g` (source-routing). **Удалена из Debian 12+** из-за проблем безопасности.
- **ncat (nmap-ncat)** — реализация от Nmap. Поддерживает SSL/TLS (`--ssl`), фильтры (`--allow`), SOCKS5-прокси.
- **socat** — более мощная альтернатива с поддержкой SSL, UNIX-сокетов, PTY. Подробнее: **[socat](../../Networking/socat_overview.md)**.

## Сравнение реализаций

| Возможность | netcat-openbsd (nc) | ncat | socat |
|:---|:---:|:---:|:---:|
| TCP-подключения | + | + | + |
| UDP (`-u`) | + | + | + |
| SSL/TLS | `-X proxy` | `--ssl` | `OPENSSL-*` |
| Exec (`-e`) | Нет (openbsd) | + | `SYSTEM:` |
| Keep-alive (`-k`) | + | + | `fork` |
| Порт-сканирование (`-z`) | + | + | Нет |
| SOCKS5-прокси | `-X` | `--socks5` | Нет |
| Лимит соединений | Нет | `--max-connections` | `fork` |

## Практические сценарии

### 1. Проверка доступности TCP-порта

Самый частый use-case — проверка, открыт ли порт на удалённом хосте.

```bash
# Базовая проверка (-z — scan mode, -v — verbose)
nc -zv example.com 443
# → Connection to example.com 443 port [tcp/https] succeeded!

# Проверка нескольких портов
nc -zv example.com 22 80 443

# Диапазон портов (сканирование)
nc -zv example.com 80-90 2>&1 | grep succeeded

# С таймаутом 2 секунды
nc -zv -w 2 example.com 443
```

**Интерпретация:**
- `succeeded` / `open` — порт открыт, сервис слушает.
- `Connection refused` — порт закрыт ОС (сервис не запущен).
- `Timed out` — пакеты отбрасываются файрволом (DROP) или хост недоступен.
- `No route to host` — проблема маршрутизации.

### 2. Проверка UDP-порта

```bash
# Проверка UDP-порта (DNS)
nc -zvu -w 2 8.8.8.8 53

# Проверка NTP
nc -zvu -w 2 pool.ntp.org 123
```

**Важно:** UDP-проверка менее надёжна, чем TCP. Ответ может быть потерян, и nc покажет «timeout» даже при работающем сервисе. Для надёжности используйте `dig` (DNS) или `chronyc` (NTP).

### 3. Прослушивание TCP-порта (простой сервер)

```bash
# Запуск простого TCP-сервера на порту 8080
nc -l -p 8080

# С поддержкой keep-alive (не закрывается после одного соединения)
nc -lk -p 8080

# С привязкой к конкретному IP
nc -l -p 8080 -s 192.168.1.10
```

### 4. Передача файлов

```bash
# На приёмнике (сервер):
nc -l -p 9999 > received_file.tar.gz

# На отправителе (клиент):
nc -w 3 receiver_ip 9999 < file_to_send.tar.gz

# Передача директории (tar + nc)
# На приёмнике:
nc -l -p 9999 | tar xzf -

# На отправителе:
tar czf - /path/to/dir | nc -w 3 receiver_ip 9999
```

### 5. Проброс портов (Port Forwarding через nc + exec)

```bash
# Проброс удалённого порта 3306 (MySQL) на локальный порт 3306
# Через SSH-бастерион:
ssh -L 3306:db-server:3306 user@bastion

# Альтернатива через nc (без SSH):
# На бастерионе:
mkfifo /tmp/fwd
nc -l -p 3306 < /tmp/fwd | nc db-server 3306 > /tmp/fwd
```

### 6. Echo/Reply сервер для тестирования

```bash
# Эхо-сервер (возвращает всё, что получил)
while true; do nc -l -p 9090 -c 'cat'; done

# Или с fork (множественные соединения, ncat):
ncat -lk -p 9090 -c 'cat'

# Echo через /dev/tcp (bash built-in)
while true; do echo "HTTP/1.1 200 OK\r\n\r\nHello" | nc -l -p 8080; done
```

### 7. Сканирование хостов и сервисов

```bash
# Проверка нескольких хостов на один порт
for host in 192.168.1.{1..254}; do
    nc -zw1 $host 22 2>/dev/null && echo "$host:22 open"
done

# Проверка сервисов по списку
nc -zv host 80 443 8080 2>&1 | grep -E "succeeded|open"
```

### 8. Перехват данных из pipe (listener + обработка)

```bash
# Приём данных и запись в файл с таймстемпами
nc -l -p 9090 | while IFS= read -r line; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') $line" >> /var/log/incoming.log
done
```

### 9. Тестирование сценариев с Docker

```bash
# Проверка доступности сервиса в контейнере
docker exec -it mycontainer nc -zv localhost 5432

# Проверка порта контейнера с хоста
nc -zv $(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' mycontainer) 8080
```

### 10. Простой chat между хостами

```bash
# На Хосте A (сервер):
nc -l -p 9999

# На Хосте B (клиент):
nc host_a_ip 9999

# Ввод текста на любом хосте отображается на другом.
```

## Диагностика и отладка

### Проверка перед запуском nc

```bash
# Проверка, не занят ли порт
ss -tlnp | grep :8080

# Проверка доступности удалённого хоста
ping -c 2 target_host

# Проверка маршрута
ip route get target_ip
```

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Connection refused` | Сервис не слушает на порту | `ss -tlnp \| grep :<port>`, проверить логи сервиса |
| `Connection timed out` | Файрвол DROP, хост недоступен | `ip route get <host>`, `nft list ruleset`, `mtr` |
| `No route to host` | Нет маршрута, интерфейс DOWN | `ip route show`, `ip -br link` |
| `Network is unreachable` | Нет маршрута до подсети | Проверить таблицу маршрутизации, default gateway |
| `bind: Address already in use` | Порт уже занят другим процессом | `ss -tlnp \| grep :<port>`, `-k` для reuseaddr |
| `bind: Permission denied` | Порт < 1024 без root | Использовать `sudo` или `setcap` |
| `nc: UDP connect warning` | UDP не может подтвердить доставку | Нормально; используйте `-w` для таймаута |

### Edge Cases

- **localhost vs 0.0.0.0:** `nc -l -p 8080` слушает на `0.0.0.0` (все интерфейсы) по умолчанию. Для привязки к конкретному IP: `nc -l -p 8080 -s 127.0.0.1`.
- **IPv6:** Используйте `-6` для принудительного IPv6: `nc -6 -zv ::1 22`.
- **TIME-WAIT:** При массовых проверках nc может исчерпать ephemeral порты. Проверяйте: `ss -tn state time-wait | wc -l`.
- **nc -e (exec):** Доступен только в `netcat-traditional` и `ncat`. **Опасен** с точки зрения безопасности — не используйте в production без контроля доступа.

## Best Practices

1. **Всегда используйте `-n`** в скриптах для отключения DNS-резолва (скорость + стабильность).
2. **Для UDP указывайте `-w`** (таймаут), иначе nc будет ждать ответа бесконечно.
3. **Для production-проверки портов** предпочитайте `ss -tlnp` или `curl` вместо nc (он не оставляет следов в логах).
4. **Для массового сканирования** используйте `nmap` — он быстрее и поддерживает SYN-сканирование.
5. **Для зашифрованных соединений** используйте `ncat --ssl` или `socat`.
6. **Не используйте `-e`** (exec) в production — это вектор атаки. Используйте `socat` с `su`/`chroot` для безопасного exec.

## Дополнительная информация

### Связанные темы

- **[socat: универсальный ретранслятор](../../Networking/socat_overview.md)** — более мощная альтернатива nc с SSL, UNIX-сокетами.
- **[Инструменты диагностики сети](../../Networking/network_diagnostics_tools.md)** — полный обзор инструментов (ss, nmap, iperf3, tcpdump).
- **[Порядок диагностики сети](../../Networking/network_troubleshooting_order.md)** — методология Bottom-Up.
- **[Проверка доступности порта](../../Networking/network_diagnostics_tools.md#сценарий-1-проверка-доступности-порта-l4)** — альтернативные методы (bash `/dev/tcp`, `curl`, `nmap`).
- **[Альтернативы ping](../../../Networking/Troubleshooting/ping_alternatives.md)** — nc как замена ICMP.
