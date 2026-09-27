# Socat: универсальный сетевой ретранслятор

## Установка

### Debian/Ubuntu

```bash
sudo apt update && sudo apt install -y socat
# → Версия по умолчанию: 1.7.4.x (проверить: socat -V)
```

### RHEL/CentOS/Rocky/AlmaLinux

```bash
# RHEL 8+ / CentOS 8+ / Rocky / AlmaLinux
sudo dnf install -y socat

# CentOS 7 (EPEL)
sudo yum install -y epel-release && sudo yum install -y socat
```

### Fedora

```bash
sudo dnf install -y socat
```

### Arch Linux / Manjaro

```bash
sudo pacman -S socat
```

### Из исходников (последняя версия)

```bash
wget http://www.dest-unreach.org/socat/download/socat-1.8.0.0.tar.gz
tar xzf socat-1.8.0.0.tar.gz
cd socat-1.8.0.0
./configure --prefix=/usr/local
make -j$(nproc)
sudo make install
# → Проверка: /usr/local/bin/socat -V
```

### Проверка версии и возможностей

```bash
socat -V
# → Выводит версию, дату сборки и список скомпилированных модулей
# Обратите внимание на: OpenSSL, SCTP, READLINE, IPv6, UNIX sockets
```

---

## Определения

* **socat (SOcket CAT)** — многофункциональная утилита командной строки, предназначенная для установки двух двунаправленных потоков данных и перенаправления данных между ними. В отличие от `netcat`, socat работает с «адресами», которые могут быть сетевыми сокетами, файлами, устройствами, программами или очередями сообщений.
* **Адрес (Address)** — ключевая концепция socat. Каждый аргумент команды — это описание конечной точки (например, `TCP-LISTEN:8080` или `FILE:/tmp/log.txt`).
* **Цепочка адресов (Address Chaining)** — возможность объединять несколько адресов в один поток с помощью оператора `!!`, что позволяет строить сложные конвейеры обработки данных внутри одного процесса socat.

## Основные концепции

### Отличие от Netcat (nc)

Socat является значительно более мощным инструментом, поддерживающим сложные протоколы и механизмы изоляции.

| Характеристика | Netcat (nc) | Socat |
| :--- | :--- | :--- |
| **Протоколы** | TCP, UDP | TCP, UDP, SSL/TLS, SCTP, UNIX Sockets, PTY, TUN/TAP, POSIX MQ. |
| **Шифрование** | Отсутствует. | Нативная поддержка OpenSSL (клиент и сервер). |
| **Параллелизм** | Обычно одно соединение. | Опция `fork` для обработки множества клиентов. |
| **Изоляция** | Нет. | Поддержка `chroot`, `su`, `netns` (в v1.8+). |
| **Цепочки** | Через pipe в shell. | Встроенная логика объединения `!!`. |

### Ключевые опции и флаги

*   **`-u` (Unidirectional)** — однонаправленный режим (только чтение из первого адреса и запись во второй).
*   **`-U` (Unidirectional reverse)** — однонаправленный режим в обратную сторону.
*   **`-t <timeout>`** — время ожидания (в секундах) перед закрытием второго потока после того, как первый сообщил об EOF.
*   **`fork`** — создает дочерний процесс для каждого нового соединения.
*   **`reuseaddr`** — позволяет биндить порт, игнорируя состояние `TIME_WAIT`.
*   **`netns=<name>`** (v1.8+) — открытие сокета внутри указанного сетевого пространства имен.
*   **`range=<network>`** — ограничение доступа по IP-подсети.

## Практические сценарии

### 1. TCP-прокси с логированием и цепочкой
Пересылка трафика с модификацией или дублированием данных.

```bash
# Простой прокси с логированием в stdout
socat -v TCP-LISTEN:8080,fork,reuseaddr TCP:10.0.0.5:80
```

### 2. Защищенный SSL/TLS туннель
Создание зашифрованного канала для приложений без поддержки TLS.

```bash
# Серверная часть (терминация SSL)
socat OPENSSL-LISTEN:443,cert=server.pem,key=server.key,verify=0,fork TCP:localhost:8080

# Клиентская часть (инициация SSL)
socat TCP-LISTEN:8080,fork OPENSSL:server.example.com:443,verify=0
```

### 3. Работа с UDP Multicast
Прием мультикаст-трафика и пересылка его в TCP-сокет.

```bash
socat UDP4-RECVFROM:224.0.0.1:1234,ip-add-membership=224.0.0.1:eth0,fork TCP:localhost:8080
```

### 4. Создание TUN/TAP интерфейса
Проброс L2/L3 трафика между узлами через сокет.

```bash
# Создание TAP-интерфейса и привязка его к TCP-порту
socat TUN:192.168.1.1/24,up,tun-type=tap TCP-LISTEN:5555,reuseaddr,fork
```

### 5. Проброс Unix-сокета в TCP
Позволяет удаленно обращаться к локальным ресурсам (Docker, DB).

```bash
socat TCP-LISTEN:2375,range=127.0.0.1/32,reuseaddr,fork UNIX-CONNECT:/var/run/docker.sock
```

### 6. Виртуальный последовательный порт (PTY)
Связывание двух эмулируемых терминалов.

```bash
socat PTY,link=/tmp/ttyV0,rawer PTY,link=/tmp/ttyV1,rawer
```

### 7. Использование цепочек (Address Chaining)
Пример объединения записи в файл и вывода в stdout через один поток.

```bash
socat STDIN GOPEN:/tmp/log.txt!!STDOUT
```

### 8. Управление HAProxy через Runtime API

Взаимодействие с HAProxy через UNIX-сокет для управления балансировщиком без перезапуска.

```bash
# Просмотр статистики всех бэкендов
echo "show stat" | socat stdio /var/run/haproxy.sock
# → app_servers,server1,0,0,0,0,...,UP,...

# Просмотр информации о процессе
echo "show info" | socat stdio /var/run/haproxy.sock

# Временное отключение сервера (drain mode)
echo "set server app_servers/server1 state drain" | socat stdio /var/run/haproxy.sock

# Полное отключение сервера
echo "disable server app_servers/server1" | socat stdio /var/run/haproxy.sock

# Включение сервера обратно
echo "enable server app_servers/server1" | socat stdio /var/run/haproxy.sock

# Изменение веса сервера на лету (canary deployment)
echo "set server app_servers/server1 weight 30" | socat stdio /var/run/haproxy.sock

# Просмотр текущего веса
echo "get weight app_servers/server1" | socat stdio /var/run/haproxy.sock

# Просмотр состояния всех серверов
echo "show servers state" | socat stdio /var/run/haproxy.sock
```

### 9. Мониторинг QEMU/QMP через socat

Удалённый мониторинг и управление виртуальными машинами через QEMU Machine Protocol (QMP).

```bash
# Соединение с QMP-сокетом и инициализация
echo '{"execute": "qmp_capabilities"}' | socat - UNIX-CONNECT:/var/run/libvirt/qemu/domain.sock
# → {"return": {}}

# Запрос статуса VM
echo '{"execute": "query-status"}' | socat - UNIX-CONNECT:/var/run/libvirt/qemu/domain.sock
# → {"return": {"running": true, "status": "running"}}

# Запрос информации о CPU
echo '{"execute": "query-cpus-fast"}' | socat - UNIX-CONNECT:/var/run/libvirt/qemu/domain.sock

# Запрос статистики блочных устройств
echo '{"execute": "query-blockstats"}' | socat - UNIX-CONNECT:/var/run/libvirt/qemu/domain.sock

# Ограничение I/O для диска (throttling)
echo '{"execute": "block-set-io-throttle", "arguments": {"node-name": "drive-virtio-disk0", "bps": 10485760, "iops": 1000}}' | socat - UNIX-CONNECT:/var/run/libvirt/qemu/domain.sock
```

### 10. SSH ProxyCommand с socat

Проброс TCP-трафика через промежуточный хост для доступа к изолированным сервисам.

```bash
# Доступ к порту 5432 (PostgreSQL) на хосте за бастерионом
# Адрес: db-server:5432, бастерион: bastion.example.com
ssh -o ProxyCommand="socat - EXEC:'ssh -W %h:%p bastion.example.com'" user@db-server

# Альтернатива с указанием порта бастерона
ssh -o ProxyCommand="socat - EXEC:'ssh -W %h:%p -p 2222 bastion.example.com'" user@db-server

# Использование в ~/.ssh/config
# Host db-internal
#     ProxyCommand socat - EXEC:'ssh -W %h:%p bastion.example.com'
#     User dbadmin
#     Port 5432
```

### 11. Проброс портов для отладки сервисов

Быстрое перенаправление портов для локальной отладки удалённых сервисов.

```bash
# Проброс удалённого PostgreSQL на локальный порт
socat TCP-LISTEN:5432,fork,reuseaddr TCP:db-server.internal:5432

# Проброс Redis с аутентификацией через SSH-туннель
socat TCP-LISTEN:6379,fork,reuseaddr OPENSSL:bastion.example.com:443,verify=0

# Проброс нескольких портов одновременно (параллельные процессы)
socat TCP-LISTEN:8080,fork,reuseaddr TCP:app-server:80 &
socat TCP-LISTEN:3000,fork,reuseaddr TCP:app-server:3000 &
socat TCP-LISTEN:5432,fork,reuseaddr TCP:app-server:5432 &
```

### 12. Эмуляция сервера для тестирования

Создание mock-серверов для тестирования клиентов в CI/CD.

```bash
# Эхо-сервер (возвращает все полученные данные)
socat TCP-LISTEN:9999,reuseaddr,fork STDOUT

# Сервер, записывающий запросы в файл
socat TCP-LISTEN:9999,reuseaddr,fork GOPEN:/tmp/requests.log,creat,append

# Сервер с автоматическим ответом (через fork и system)
socat TCP-LISTEN:9999,reuseaddr,fork SYSTEM:'echo "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"'
```

---

## Безопасность и лучшие практики

1.  **Минимизация привилегий**: Используйте `su=<user>` и `gid=<group>` при запуске от root.
2.  **Изоляция**: Применяйте `chroot` для ограничение доступа команд `EXEC` и `SYSTEM` к ФС.
3.  **Фильтрация**: Всегда ограничивайте `LISTEN` адреса опцией `range`.
4.  **Валидация SSL**: В продакшене используйте `verify=1` и `cafile`.
5.  **Контроль ресурсов**: Флаг `-t` предотвращает "зависание" полуоткрытых соединений.

## Диагностика и отладка

```bash
# Проверка версии и скомпилированных модулей
socat -V

# Максимальная детализация процесса установки соединения
socat -d -d -d -D TCP-LISTEN:8080 STDOUT
```

## Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `socat[12345]: E addressreshape(): No such file or directory` | Указан несуществующий UNIX-сокет или файл | Проверьте путь: `ls -la /path/to/socket` |
| `socat[12345]: E connect(): Connection refused` | Сервис не слушает на указанном адресе или порту | Убедитесь, что сервис запущен: `ss -tlnp \| grep :PORT` |
| `socat[12345]: E bind(): Address already in use` | Порт уже занят другим процессом | Используйте `reuseaddr` или проверьте: `ss -tlnp \| grep :PORT` |
| `socat[12345]: E bind(): Permission denied` | Попытка забиндить порт <1024 без root | Используйте `sudo` или `setcap` |
| `socat[12345]: W handle_child增高(): recvmsg(): Connection reset by peer` | Удалённая сторона разорвала соединение | Проверьте firewall, статус сервиса, логи приложения |
| `socat[12345]: E SSL_connect(): error:...` | Проблема с SSL/TLS handshake | Проверьте сертификаты, `verify` настройки, версию OpenSSL |
| `socat: DNS resolution error` | Невозможно разрезолвить имя хоста | Проверьте DNS: `resolvectl query hostname` |
| `fork` не работает, соединения «зависают» | Процесс-родитель не порождает детей | Убедитесь, что `fork` указан в опциях адреса |

### Методы диагностики

```bash
# Максимальная детализация (для отладки проблем с подключением)
socat -d -d -d -D TCP-LISTEN:8080 STDOUT
# -d   — вывод инфо об адресах
# -d -d — вывод инфо о соединениях
# -d -d -d — вывод инфо о передаче данных
# -D   — вывод hex-дампа данных

# Проверка доступности сервиса перед запуском socat
ss -tlnp | grep :8080
# → LISTEN  0  128  0.0.0.0:8080  0.0.0.0:*  users:(("nginx",pid=1234,fd=6))

# Проверка SSL-сертификата
openssl s_client -connect server.example.com:443 -servername server.example.com

# Проверка UNIX-сокета
ls -la /var/run/haproxy.sock
# → srwxrwxrwx 1 haproxy haproxy 0 ... /var/run/haproxy.sock
```

---

## Интеграция с systemd

### Запуск socat как системный сервис

Создайте unit-файл для автоматического запуска прокси при загрузке системы.

```ini
# /etc/systemd/system/socat-proxy.service
[Unit]
Description=Socat TCP Proxy
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/bin/socat TCP-LISTEN:8080,fork,reuseaddr TCP:10.0.0.5:80
Restart=always
RestartSec=5
LimitNOFILE=65536

# Безопасность
User=nobody
Group=nogroup
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log

[Install]
WantedBy=multi-user.target
```

```bash
# Активация и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now socat-proxy
sudo systemctl status socat-proxy

# Просмотр логов
journalctl -u socat-proxy -f
```

### Пример: SSL-терминатор с автоматическим restart

```ini
# /etc/systemd/system/socat-ssl-terminator.service
[Unit]
Description=Socat SSL Terminator for Backend
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/socat OPENSSL-LISTEN:443,cert=/etc/ssl/private/server.pem,key=/etc/ssl/private/server.key,verify=0,fork TCP:localhost:8080
Restart=on-failure
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

---

## Дополнительная информация

### Смежные темы

*   **[Инструменты сетевой диагностики](./network_diagnostics_tools.md)** — сравнение `nc`, `socat`, `nmap`.
*   **[Сетевые пространства имен (NetNS)](./Tools/iproute2/ip_netns.md)** — механизм изоляции сетевого стека (socat v1.8+ поддерживает `netns`).
*   **[Интерфейс сокетов (Socket API)](../../Networking/Concepts/socket_api.md)** — основы работы системных вызовов сокетов.
*   **[Протокол TLS](../../Networking/Protocols/tls.md)** — принципы работы шифрования (для `OPENSSL-*` адресов socat).
*   **[HAProxy: обзор](../../WebServers/haproxy_overview.md)** — управление через socat к UNIX-сокету Runtime API.
*   **[SSH: клиентские настройки](../Security/ssh/ssh_client_config.md)** — `ProxyCommand` с socat для проброса трафика.
*   **[KVM/QEMU: обзор](../Virtualization/kvm/overview.md)** — мониторинг VM через QMP-сокет с помощью socat.

### Полезные ресурсы
*   [Официальный сайт socat (dest-unreach.org)](http://www.dest-unreach.org/socat/)
*   [Socat v1.8 Release Notes](http://www.dest-unreach.org/socat/doc/socat-1.8.0.html)
