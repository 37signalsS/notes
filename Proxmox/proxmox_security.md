# Безопасность и Hardening Proxmox VE

## Определения

**Defense in Depth** — стратегия безопасности, предполагающая использование нескольких независимых уровней защиты: сеть, хост, приложение, данные, мониторинг.

**CIS Benchmark** — набор рекомендаций по настройке безопасности, разработанный Center for Internet Security. Уровень 1 — минимальные требования, Уровень 2 — hardened конфигурация.

**AppArmor** — Mandatory Access Control (MAC) система в Linux, ограничивающая права процессов на файлы, сети и capabilities. Используется в Proxmox по умолчанию вместо SELinux.

**PVE Firewall** — встроенный межсетевой экран Proxmox, работающий на уровне netfilter (iptables/nftables) с правилами на уровнях датацентра, узла и VM/LXC.

**Auditd** — Linux Audit Framework для мониторинга и логирования системных вызовов, изменений файлов, аутентификации и действий пользователей.

**fail2ban** — инструмент блокировки IP-адресов при обнаружении подозрительной активности (brute-force, сканирование) через анализ логов.

## Теоретический блок

### Уровни безопасности Proxmox

```
┌──────────────────────────────────────────────────┐
│  5. Мониторинг и аудит (Prometheus, auditd, logs) │
├──────────────────────────────────────────────────┤
│  4. Приложение (Proxmox API, RBAC, API-токены)    │
├──────────────────────────────────────────────────┤
│  3. Гости (AppArmor, firewall в VM, шифрование)   │
├──────────────────────────────────────────────────┤
│  2. Хост (SSH, fail2ban, обновления, ядро)        │
├──────────────────────────────────────────────────┤
│  1. Сеть (物理ическая, VLAN, firewall, VPN)        │
└──────────────────────────────────────────────────┘
```

### RBAC в Proxmox

Proxmox поддерживает три модели аутентификации:
- **PAM**: Системные пользователи Linux
- **LDAP/AD**: Централизованная аутентификация
- **OpenID Connect**: OAuth2-совместимые провайдеры

Встроенные роли:
- `PVEAdmin` — полный доступ
- `PVEAuditor` — только чтение
- `PVEDatastoreAdmin` — управление хранилищами
- `PVEVMAdmin` — управление VM
- `PVEVMUser` — доступ к консоли VM

## Практические сценарии

### 1. Hardening SSH на узлах Proxmox

```bash
# /etc/ssh/sshd_config — hardened настройки
Port 22
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no
Protocol 2
MaxSessions 3
MaxStartups 10:30:60

# Алгоритмы шифрования (современные)
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org
```

```bash
systemctl restart ssh
```

### 2. Настройка fail2ban

```bash
apt install -y fail2ban

# /etc/fail2ban/jail.local
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = nftables-multiport

[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600

[pve-auth]
enabled = true
port = 8006
filter = pve-auth
logpath = /var/log/pveproxy/access.log
maxretry = 5
bantime = 3600

# /etc/fail2ban/filter.d/pve-auth.conf
[Definition]
failregex = ^.* pveproxy\[[0-9]+\]: authentication failure; .+ rhost=<HOST>
            ^.* pveproxy\[[0-9]+\]: unauthorized request from <HOST>
ignoreregex =
```

```bash
systemctl enable --now fail2ban
fail2ban-client status pve-auth
```

### 3. AppArmor

```bash
# Проверка статуса AppArmor
aa-status

# Профили Proxmox по умолчанию
ls /etc/apparmor.d/
# → usr.sbin.pve-proxy
# → usr.sbin.pvedaemon
# → etc.

# Включение режима enforce для Proxmox сервисов
aa-enforce /usr/sbin/pve-proxy
aa-enforce /usr/sbin/pvedaemon

# Генерация нового профиля (если нужен кастомный)
aa-genprof /usr/local/bin/my-service
```

### 8. Auditd — аудит действий

```bash
apt install -y auditd audispd-plugins

# /etc/audit/rules.d/proxmox.rules

# Мониторинг изменений в конфигурации кластера
-w /etc/pve/ -p wa -k proxmox_config
-w /etc/pve/corosync.conf -p rwa -k corosync_config
-w /etc/pve/storage.cfg -p rwa -k storage_config
-w /etc/pve/network/interfaces -p rwa -k network_config

# Мониторинг SSH ключей
-w /root/.ssh/ -p wa -k ssh_keys
-w /home/ -p wa -k home_dirs

# Мониторинг пакетных операций
-w /var/log/apt/ -p wa -k apt_logs
-w /usr/bin/apt -p x -k apt_commands

# Мониторинг Proxmox API
-w /var/log/pveproxy/ -p wa -k pve_api_logs

# Мониторинг firewall правил
-w /etc/pve/firewall/ -p wa -k firewall_rules

# Мониторинг пользователей
-w /etc/passwd -p wa -k user_modification
-w /etc/shadow -p wa -k password_modification
-w /etc/group -p wa -k group_modification

# Мониторинг запуска сервисов
-a always,exit -F arch=b64 -S execve -C uid!=root -k non_root_exec

# Мониторинг privileged команд
-a always,exit -F arch=b64 -S mount -S umount2 -k privileged_mount
-a always,exit -F arch=b64 -S ptrace -k process_trace

# Make audit configuration immutable (requires reboot to change)
-e 2
```

```bash
# Перезапуск auditd
systemctl restart auditd

# Проверка правил
auditctl -l

# Поиск в логах аудита
ausearch -k proxmox_config --interpret
ausearch -k ssh_keys --interpret
aureport --summary
```

### 9. Шифрование дисков VM (LUKS)

```bash
# При создании VM с шифрованным диском
qm set 101 --scsi0 local-lvm:32,encryption=aes-256-cbc

# Или через CLI при создании
qm create 101 --name encrypted-vm \
  --scsi0 local-lvm:32,encryption=aes-256-cbc,secret=encrypted \
  --net0 virtio,bridge=vmbr0

# Проверка шифрования
qm config 101 | grep encryption
# → scsi0: local-lvm:vm-101-disk-0,size=32G,encryption=aes-256-cbc
```

### 10. CIS Benchmark — основные проверки

```bash
# Установка Lynis (аудит безопасности)
apt install -y lynis

# Запуск аудита
lynis audit system

# Проверка CIS-рекомендаций
lynis audit system --tests-from-group "firewall"
lynis audit system --tests-from-group "authentication"
lynis audit system --tests-from_group "networking"

# Ключевые проверки для Proxmox:
# - Аутентификация по ключам SSH
# - Отключение парольного входа
# - Настройка парольной политики
# - Включение аудита
# - Настройка firewall
# - Обновления пакетов
# - Проверка SUID/SGID файлов
```

## Диагностика и устранение неполадок

### Firewall блокирует доступ к API

```bash
# Проверка правил
pve-firewall log | tail -20

# Временное отключение (НЕ в production!)
pve-firewall set options --enable 0

# Просмотр заблокированных соединений
journalctl -u pve-firewall -f

# Добавление правила для доверенной IP
pve-firewall add --rule in --source 10.0.0.100 --proto tcp --dport 8006 --action ACCEPT
```

### fail2ban заблокировал legitimate IP

```bash
# Просмотр заблокированных
fail2ban-client status pve-auth

# Разбан IP
fail2ban-client set pve-auth unbanip 10.0.0.100

# Добавление в whitelist
# /etc/fail2ban/jail.local
[DEFAULT]
ignoreip = 127.0.0.1/8 10.0.0.0/24
```

### AppArmor блокирует сервис

```bash
# Проверка denial
aa-logprof

# Перевод в complain mode (временно)
aa-complain /usr/sbin/pve-proxy

# Генерация обновленного профиля
aa-genprof /usr/sbin/pve-proxy
```

## Лучшие практики

1. **Отключение парольного входа**: `PasswordAuthentication no` + SSH ключи. Для root только по ключу: `PermitRootLogin prohibit-password`.

2. **API-токены**: Используйте отдельных пользователей с минимальными правами для автоматизации (Ansible, мониторинг). Никогда не `root@pam`.

3. **Файрвол по умолчанию**: Включайте `pve-firewall` на всех уровнях (datacenter, host, VM). Используйте security groups для стандартных политик.

4. **Обновления**: Подписка на Proxmox security announcements. Регулярное `apt update && apt dist-upgrade`.

5. **Аудит**: Настройте auditd для мониторинга критических файлов (`/etc/pve/`, SSH ключи, пользователи). Интегрируйте с SIEM.

6. **fail2ban**: Обязательно для SSH и Proxmox API. Настройте `bantime >= 3600`.

7. **Шифрование**: Используйте LUKS для дисков VM с конфиденциальными данными. ДляPBS — client-side encryption.

8. **Out-of-band доступ**: IPMI/iDRAC/iKVM для доступа при блокировке firewall или сетевых проблем.

9. **Разделение сетей**: Отдельные VLAN для management, Ceph, Corosync, guest трафика. Не смешивайте.

10. **Мониторинг**: Настройте алерты на brute-force, несанкционированный доступ, изменения конфигурации.

## Граничные случаи

- **PVE Firewall и Corosync**: При включенном firewall убедитесь, что UDP 5405–5412 (knet) и TCP 5403 (QDevice) открыты между узлами. Иначе кластер распадается. См. также [Продвинутый Firewall в Proxmox VE](./proxmox_firewall_advanced.md).

- **API-токен и привилегии**: Токен с привилегиями `PVEVMAdmin` может удалять VM. Всегда проверяйте scope прав через `pveum user token list`.

- **AppArmor и Ceph**: Профиль AppArmor может блокировать операции Ceph OSD. Проверяйте логи: `journalctl -u ceph-osd | grep apparmor`.

- **fail2ban и Proxmox API**: Proxmox API использует HTTP 401 для аутентификации. fail2ban должен фильтровать именно по `pveproxy` логам, а не по system auth.

- **Auditd и производительность**: Полный аудит всех syscall может значительно снизить производительность. Фильтруйте по конкретным events (`-a always,exit -F arch=b64 -S execve`).

### Связанные темы

- [SSH Hardening](../Linux/Security/ssh/server/ssh_hardening_best_practices.md)
- [AppArmor](../Linux/Security/Mechanisms/AppArmor.md)
- [fail2ban](../Linux/Security/Tools/fail2ban.md)
- [auditd](../Linux/SystemAdministration/Logging/auditd.md)
- [iptables basics -- SSoT](../Linux/Networking/Settings/tools/iptables_basics.md)
- [nftables architecture -- SSoT](../Linux/Networking/Settings/tools/nftables/architecture_and_concepts.md)
- [Conntrack Production Tuning -- SSoT](../Linux/Networking/Concepts/conntrack_production_tuning.md)
- [Продвинутый Firewall в Proxmox](./proxmox_firewall_advanced.md)
- [CIS Benchmark (Ansible)](../Ansible/ansible-os-hardening.md)
- [Сетевые технологии Proxmox](./proxmox_networking.md)
- [Кластеризация и HA](./proxmox_cluster.md)
- [ACME и SSL-сертификаты в Proxmox VE](./proxmox_acme_ssl.md)
