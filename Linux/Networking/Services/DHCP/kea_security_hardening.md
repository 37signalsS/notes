# Kea DHCP: Безопасность и Hardening

---

## Определения

**Security Hardening** — процесс укрепления безопасности системы путём отключения ненужных сервисов, ограничения доступа, настройки шифрования и применения принципов наименьших привилегий.

**Rogue DHCP Server** — неавторизованный DHCP-сервер в сети, который может выдавать вредоносные настройки (DNS, шлюз) для атаки MitM.

**DHCP Snooping** — L2-механизм коммутатора, фильтрующий неавторизованные DHCP-ответы.

**Option 82 (Relay Agent Information)** — опция DHCP, добавляемая relay-агентом (коммутатором) для идентификации физического порта и VLAN клиента.

---

## Основные концепции

### Уровни безопасности Kea

| Уровень | Описание | Методы |
|:--- |:--- |:--- |
| **L1: Network** | Ограничение сетевого доступа | Firewall, VLAN, ACL |
| **L2: Transport** | Шифрование и аутентификация | TLS, Basic Auth |
| **L3: Application** | Безопасность конфигурации | Validation, RBAC |
| **L4: OS** | Безопасность хоста | SELinux, AppArmor, systemd |
| **L5: Monitoring** | Обнаружение аномалий | Логи, алерты, SIEM |

---

## Практические сценарии

### 1. Firewall: ограничение доступа к Kea

#### nftables (рекомендуется)

```bash
#!/usr/sbin/nft -f
# /etc/nftables.conf

# Очистка правил
flush ruleset

# Таблица фильтрации
table inet kea-filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Established/Related
        ct state established,related accept

        # Loopback
        iif lo accept

        # ICMP (ping)
        ip protocol icmp accept
        ip6 nexthdr icmpv6 accept

        # SSH (только management сеть)
        ip saddr 10.0.0.0/24 tcp dport 22 accept

        # DHCP (UDP 67/68) — откуда ожидается клиентский трафик
        ip saddr 10.0.10.0/24 udp dport {67,68} accept
        ip saddr 10.0.20.0/24 udp dport {67,68} accept

        # Kea Control Agent (TCP 8000) — только management
        ip saddr 10.0.0.0/24 tcp dport 8000 ct state new accept

        # Логирование отброшенных пакетов
        limit rate 5/minute log prefix "kea-drop: " level warn
        drop
    }
}
```

#### iptables (альтернатива)

```bash
# Политика по умолчанию
iptables -P INPUT DROP
iptables -P FORWARD DROP

# Established/Related
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Loopback
iptables -A INPUT -i lo -j ACCEPT

# SSH
iptables -A INPUT -s 10.0.0.0/24 -p tcp --dport 22 -j ACCEPT

# DHCP
iptables -A INPUT -s 10.0.10.0/24 -p udp --dport 67 -j ACCEPT
iptables -A INPUT -s 10.0.20.0/24 -p udp --dport 67 -j ACCEPT

# Control Agent
iptables -A INPUT -s 10.0.0.0/24 -p tcp --dport 8000 -j ACCEPT

# Logging
iptables -A INPUT -j LOG --log-prefix "kea-drop: " --log-level 4
```

### 2. TLS и аутентификация Control Agent

#### Генерация сертификатов

```bash
# 1. Генерация CA
openssl genrsa -out ca-key.pem 4096
openssl req -new -x509 -days 3650 -key ca-key.pem -out ca.pem \
  -subj "/CN=Kea CA/O=Example Corp"

# 2. Сертификат сервера
openssl genrsa -out server-key.pem 2048
openssl req -new -key server-key.pem -out server.csr \
  -subj "/CN=dhcp-1.corp.example.com/O=Example Corp"
openssl x509 -req -days 3650 -in server.csr -CA ca.pem -CAkey ca-key.pem \
  -CAcreateserial -out server-cert.pem

# 3. Проверка
openssl verify -CAfile ca.pem server-cert.pem

# 4. Установка прав
chmod 600 ca-key.pem server-key.pem
chown kea:kea *.pem
mv *.pem /etc/kea/
```

#### Конфигурация TLS в kea-ctrl-agent.conf

```json
{
    "Control-agent": {
        "http-host": "0.0.0.0",
        "http-port": 8000,
        "trust-anchor": "/etc/kea/ca.pem",
        "cert-file": "/etc/kea/server-cert.pem",
        "key-file": "/etc/kea/server-key.pem",
        "cert-required": true,
        "authentication": {
            "type": "basic",
            "realm": "Kea DHCP Management",
            "users": [
                {
                    "user": "admin",
                    "password": "$5$rounds=10000$salt$hash"
                },
                {
                    "user": "monitoring",
                    "password": "$5$rounds=10000$salt$hash",
                    "user-context": {"ro": true}
                }
            ]
        }
    }
}
```

#### Генерация хеша пароля

```bash
# SHA-256
echo -n "password" | openssl dgst -sha256
# Или с солью
python3 -c "import hashlib; print(hashlib.sha256(b'salt:password').hexdigest())"
```

### 3. SELinux (RHEL/Rocky/AlmaLinux)

```bash
# Проверка текущего контекста
ls -laZ /usr/sbin/kea-dhcp4
# → system_u:object_r:dhcp_exec_t:s0

# Проверка порта 8000
semanage port -l | grep http_port_t

# Добавление порта 8000
semanage port -a -t http_port_t -p tcp 8000

# Восстановление контекста
restorecon -Rv /etc/kea/
restorecon -Rv /var/lib/kea/
restorecon -Rv /var/log/kea/

# Проверка audit логов
ausearch -m avc --recent | grep kea

# Если нужен новый модуль (крайний случай)
audit2allow -a -M kea-custom
semodule -i kea-custom.pp
```

### 4. AppArmor (Ubuntu/Debian)

```bash
# Проверка профилей
aa-status | grep kea

# Профиль для kea-dhcp4
# /etc/apparmor.d/usr.sbin.kea-dhcp4

#include <tunables/global>

/usr/sbin/kea-dhcp4 {
  #include <abstractions/base>
  #include <abstractions/nameservice>

  # Network
  network inet raw,
  network inet udp,
  network inet6 raw,

  # Config files
  /etc/kea/** r,
  /var/lib/kea/** rw,
  /var/log/kea/** w,

  # Libraries
  /usr/lib/kea/hooks/*.so mr,

  # Permissions
  capability net_raw,
  capability net_bind_service,
}
```

```bash
# Применение
apparmor_parser -r /etc/apparmor.d/usr.sbin.kea-dhcp4

# В режиме отладки (complain)
aa-complain /usr/sbin/kea-dhcp4
```

### 5. DHCP Snooping + Option 82

#### Конфигурация на Cisco

```
! Включение DHCP Snooping
ip dhcp snooping
ip dhcp snooping vlan 10,20

! Доверенные порты (к DHCP-серверу)
interface Gi0/1
 description To-Kea-DHCP
 ip dhcp snooping trust

! Недоверенные порты (к клиентам)
interface Gi0/2
 description To-Users
 ip dhcp snooping limit rate 10

! Option 82 (Relay Agent)
interface Vlan10
 ip helper-address 10.0.0.10
 ip dhcp snooping information option
```

#### Обработка Option 82 в Kea

```json
{
    "Dhcp4": {
        "hooks-libraries": [
            {
                "library": "/usr/lib/kea/hooks/libdhcp_flex_id.so",
                "parameters": {
                    "identifier-expression": "relay[0].option[82].hex"
                }
            }
        ],
        "client-classes": [
            {
                "name": "vlan10-users",
                "test": "relay[0].option[82].option[1].hex == 'VLAN10'",
                "option-data": [
                    {"name": "routers", "data": "10.0.10.1"}
                ]
            },
            {
                "name": "vlan20-phones",
                "test": "relay[0].option[82].option[1].hex == 'VLAN20'",
                "option-data": [
                    {"name": "routers", "data": "10.0.20.1"}
                ]
            }
        ]
    }
}
```

### 6. Защита от Rogue DHCP

#### На уровне сети

```bash
# Cisco: ограничение DHCP-серверов
ip dhcp snooping vlan 10
ip dhcp snooping trust  # Только доверенный порт

# Проверка_BINDING
show ip dhcp snooping binding
```

#### На уровне Kea

```json
{
    "Dhcp4": {
        "authoritative": true,
        "match-clients": "hardware",
        "check-option-82": true,
        "client-classes": [
            {
                "name": "known-clients",
                "test": "hw-address == 00:50:56:*"
            }
        ]
    }
}
```

### 7. Ограничение rate (Anti-DoS)

```bash
# nftables: limit DHCP requests per source
table inet kea-rate-limit {
    chain input {
        type filter hook input priority 1; policy accept;

        # Ограничение DHCP requests per source IP
        ip saddr 0.0.0.0/0 udp dport 67 limit rate 10/second burst 20 packets accept
        ip saddr 0.0.0.0/0 udp dport 67 drop

        # Ограничение Control Agent requests
        ip saddr 10.0.0.0/24 tcp dport 8000 limit rate 5/second burst 10 packets accept
        ip saddr 10.0.0.0/24 tcp dport 8000 drop
    }
}
```

### 8. Логирование и аудит

```json
{
    "Dhcp4": {
        "loggers": [
            {
                "name": "kea-dhcp4",
                "severity": "INFO",
                "output-options": [
                    {
                        "output": "/var/log/kea/kea-dhcp4.log",
                        "pattern": "%d{%Y-%m-%d %H:%M:%S.%q} %-5p %c - %m\n"
                    }
                ],
                "maxsize": 104857600,
                "maxver": 10
            },
            {
                "name": "kea-dhcp4.audit",
                "severity": "INFO",
                "output-options": [
                    {
                        "output": "/var/log/kea/kea-dhcp4-audit.log",
                        "pattern": "%d{%Y-%m-%d %H:%M:%S.%q} %m\n"
                    }
                ]
            }
        ]
    }
}
```

```bash
# Аудит через auditd
auditctl -w /etc/kea/ -p wa -k kea-config
auditctl -w /var/lib/kea/ -p wa -k kea-leases
auditctl -w /var/log/kea/ -p wa -k kea-logs

# Проверка аудита
ausearch -k kea-config --recent
```

### 9. systemd sandboxing

```ini
# /etc/systemd/system/kea-dhcp4.service.d/security.conf
[Service]
# Ограничение прав
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_NET_ADMIN
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/kea /var/log/kea
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
MemoryDenyWriteExecute=yes

# Сеть
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
SystemCallFilter=@system-service
SystemCallArchitectures=native
```

---

## Дополнительная информация

### Чеклист безопасности для production

```bash
# 1. Firewall
nft list ruleset | grep -E "67|68|8000"

# 2. TLS
openssl s_client -connect localhost:8000 -CAfile /etc/kea/ca.pem

# 3. SELinux/AppArmor
getenforce  # Enforcing?
aa-status | grep kea  # enforcing?

# 4. Права на файлы
ls -la /etc/kea/*.pem  # 600 для ключей
ls -la /var/lib/kea/   # kea:kea owner

# 5. Аудит
ausearch -k kea-config --recent | tail -20

# 6. Логи
journalctl -u kea-dhcp4 --since "1 hour ago" | grep -i "auth\|tls\|error"
```

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полный обзор.
- **[Kea DHCP: Production Operations](./kea_production_operations.md)** — day-2 ops.
- **[Kea DHCP: Вопросы для собеседования](./kea_interview_questions.md)** — подготовка.
- **[DHCP: Безопасность](../../../../Networking/Protocols/DHCP/dhcp_security.md)** — общая безопасность DHCP.
- **[Kea DHCP Documentation](https://kea.readthedocs.io/)** — официальная документация.
