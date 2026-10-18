# Безопасность и Hardening Proxmox VE

**Актуально для:** Proxmox VE 9.x (PVE 8.x — EOL 31.08.2026)

## Определения

**Defense in Depth** — стратегия многоуровневой защиты: сеть, хост, управляющая плоскость, гости, мониторинг. В PVE уровни пересекаются, но не заменяют друг друга: firewall не спасает от утечки API-токена, auditd не спасает от открытого порта 8006.

**RBAC Proxmox** — role-and-path based permissions: пользователь, группа или API-токен получают роль на path (`/vms`, `/nodes/node1`, `/storage`, …). Действие разрешено только при наличии привилегии, входящей в роль, на указанный path.

**Realms** — области аутентификации (`pam`, `pve`, `ldap`, `ad`, `openid`): `root@pam` — системный root; `@pve` — локальный store в `/etc/pve/priv/shadow.cfg` (SHA-256); LDAP/AD/OpenID — централизованные.

**API Token** — stateless-креденшел `PVEAPIToken=user@realm!tokenid=secret`; приватность = пересечение ACL пользователя и ACL токена (`--privsep 1`). Создание и диагностика — [REST API](./proxmox_rest_api.md).

**2FA (TFA)** — второй фактор в PVE: TOTP, WebAuthn (U2F — legacy), recovery keys; может навязываться realm-ом (`tfa type=oath` / YubiKey OTP).

**PVE Firewall** — распределённый netfilter-слой (датацентр / узел / гость) поверх nftables (в PVE 8+ — по умолчанию); правила в `/etc/pve/firewall/*.fw`. Глубина — [Продвинутый Firewall](./proxmox_firewall_advanced.md).

**AppArmor** — MAC, в PVE включён по умолчанию (вместо SELinux); профили для `pve-proxy`, `pvedaemon` и др.

**pmxcfs** — cluster FS под `/etc/pve`; конфиги узлов и приватные ключи (`/etc/pve/priv/`) реплицируются кластерно — доступен всем нодам, защищён только POSIX-правами.

## Теоретический блок

### Многоуровневая модель PVE

```text
┌─────────────────────────────────────────────────────────────┐
│  6. Аудит и мониторинг (auditd, access.log, Prometheus)     │
├─────────────────────────────────────────────────────────────┤
│  5. Управляющая плоскость (RBAC, 2FA, API-токены, TLS:8006) │
├─────────────────────────────────────────────────────────────┤
│  4. Хост (SSH keys-only, fail2ban, обновления, AppArmor)    │
├─────────────────────────────────────────────────────────────┤
│  3. Гости (unprivileged LXC, firewall=1, шифрование дисков) │
├─────────────────────────────────────────────────────────────┤
│  2. Сеть (VLAN mgmt/cluster/guest, pve-firewall, VPN)       │
├─────────────────────────────────────────────────────────────┤
│  1. Физика / OOB (IPMI/iLO/iDRAC, диск, out-of-band)        │
└─────────────────────────────────────────────────────────────┘
```

### Атакующие поверхности PVE

| Поверхность | Порт / путь | Основные риски | Основная защита |
| --- | --- | --- | --- |
| Web UI / REST API | TCP 8006 | Перебор паролей, утечка токена, RCE-цепочки | 2FA, токены, firewall, TLS |
| SSH | TCP 22 | Brute-force, компрометация ключей | Keys-only, fail2ban, ACL |
| Corosync | UDP 5405–5412 | Разрыв кворума, MITM кластера | Выделенная сеть, authkey |
| Live migration | TCP 60000–60050 | Перехват памяти гостя | Изолированная mgmt-сеть |
| pmxcfs `/etc/pve` | локально | Подделка ACL, теневых пользователей | Только root, auditd |
| `/etc/pve/priv` | локально | Ключи PBS, storage passwords, API | root-only, backup вне узла |
| Гости (KVM/LXC) | — | Escape, lateral movement | AppArmor, unprivileged, VLAN |

### RBAC: роли и ACL

Встроенные роли (полный список — GUI / `pveum`):

| Роль | Назначение |
| --- | --- |
| `Administrator` | Все привилегии |
| `PVEAdmin` | Большинство операций; **без** `Sys.PowerMgmt`, `Sys.Modify`, `Realm.Allocate`, `Permissions.Modify` |
| `PVEAuditor` | Только чтение (мониторинг, discovery) |
| `PVEUserAdmin` | Управление пользователями |
| `PVEVMAdmin` / `PVEVMUser` | Полное / типовое управление гостями |
| `PVEDatastoreAdmin` / `PVEDatastoreUser` | Хранилища и шаблоны |
| `PVESysAdmin` | Аудит, системная консоль, syslog |
| `PVEPool*`, `PVESDN*`, `PVEMapping*` | Пулы, SDN, resource mapping |
| `NoAccess` | Запрет доступа (в т.ч. отмена унаследованного ACL) |

Триплет ACL: `(path, subject, role)`; subject — user, group или **token**. `Permissions.Modify` и `Sys.Modify` — критические привилегии: их держат у минимального круга. Примеры и диагностика — [REST API](./proxmox_rest_api.md), создание automation-токена — [Service Discovery](./proxmox_service_discovery.md#сценарий-1-создание-api-токена-с-минимальными-правами).

### Модель аутентификации

| Realm | Где хранятся учётки | Когда применять | Риск / примечание |
| --- | --- | --- | --- |
| `pam` | `/etc/passwd`, `/etc/shadow` | root, операторы с shell-доступом к узлу | Утечка PAM = shell на узле |
| `pve` | `/etc/pve/priv/shadow.cfg` | GUI/API-пользователи без shell | SHA-256; удобен для малых инсталляций |
| LDAP/AD | Внешний каталог | Корпоративный SSO | TLS для bind; group→role mapping |
| OpenID Connect | Внешний IdP | 2FA на стороне IdP | Проверка redirect/issuers |

`root@pam` — неуничтожимый «super-admin» PVE; не используйте его пароль в automation и не создавайте API-токены `root@pam!…` с широкими правами.

## Практические сценарии

### 1. Hardening SSH на узлах

SSH в PVE — точка входа операторов и канал cluster-действий (join, migrate по SSH). Полный набор практик — [SSH Hardening (SSoT)](../Linux/Security/ssh/server/ssh_hardening_best_practices.md). Ниже — минимальный контур для PVE-хоста:

```bash
# /etc/ssh/sshd_config.d/pve-hardening.conf
Port 22
PermitRootLogin prohibit-password   # root — только по ключу
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no
MaxSessions 3
MaxStartups 10:30:60

Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org
```

```bash
sshd -t && systemctl reload ssh
# → # (без вывода = конфигурация OK)

# Резерв SSH-доступ: OOB / консоль IPMI — до перезагрузки проверьте ключ
```

Не отключайте SSH полностью: cluster-операции используют его между нодами. Ограничьте источник правилом firewall (22/tcp только mgmt-subnet).

### 2. Двухфакторная аутентификация (2FA)

Методы: **TOTP** (HMAC-SHA1, 30 с), **WebAuthn** (FIDO2/TPM), **recovery keys** (одноразовые), legacy **U2F** / YubiKey OTP (realm-enforced). Несколько факторов на пользователя — страховка от потери смартфона.

**Важно:** не включайте enforcement на realm, пока не выпущены TOTP/recovery для root@pam — иначе self-lockout. Откат: отредактируйте `/etc/pve/domains.cfg`, уберите строку `tfa type=oath` (или YubiKey).

#### 2.1. Пользовательский TOTP (opt-in)

1. GUI: Datacenter → Users → пользователь → TFA → **TOTP** (Randomize / QR).
2. Подтвердить пароль (кроме root) и OTP → Apply.
3. Дополнительно: recovery keys — распечатать / в vault.

CLI-геннерация ключа (realm-enforced workflow):

```bash
oathkeygen
# → P6NDPDL6QDS7YFP4   (Base32; тот же ключ — в профиль пользователя и в OTP-app)

# QR в терминале (пакет qrencode)
OATHKEYID=$(oathkeygen)
qrencode -t ANSIUTF8 -o - \
  "otpauth://totp/PVE:${USER}@$(hostname -f)?secret=${OATHKEYID}"
```

#### 2.2. Принудительный TOTP на realm

1. Сначала: `oathkeygen` → GUI Users → Key IDs (или TFA-диалог) для **всех** админов, включая root@pam.
2. Datacenter → Authentication → realm → Edit → TFA = **OATH**.
3. Тест: выход и вход с OTP до завершения сессии.

Откат:

```bash
# /etc/pve/domains.cfg — удалить строку tfa type=oath
```

#### 2.3. Разблокировка TFA

TOTP: 8 неудачных попыток блокируют факторы; WebAuthn/recovery — лимит 100, блокировка ~1 час. Администратор:

```bash
pveum user tfa unlock joe@pve
```

### 3. API-токены и минимальные привилегии

```bash
# Отдельный пользователь (не root@pam) под automation
pveum user add automation@pve --comment "CI; owner: platform"

# privsep=1 (пересечение ACL), срок жизни, secret — один раз
pveum user token add automation@pve ci --privsep 1 \
  --expire "$(date -d '+90 days' +%s)" \
  --comment "CI; rotate quarterly"

pveum acl modify /vms --token 'automation@pve!ci' --roles PVEVMAdmin
pveum acl modify /nodes --token 'automation@pve!ci' --roles PVEAuditor
pveum user token permissions automation@pve ci
```

Ограничения: API-токены **не работают с консольными** endpoint-ами (vnc/spice/xtermjs) — консоль только через пользовательскую сессию. Мониторинг — `PVEAuditor` на `/nodes` и `/vms`, без `Permissions.Modify`. Подробнее — [REST API](./proxmox_rest_api.md).

### 4. Ограничение доступа к API (порт 8006)

По умолчанию pveproxy слушает все интерфейсы; доступность 8006 «всем, кому есть маршрут» — не теоретический риск, а стандартная находка сканеров.

```bash
# /etc/pve/firewall/host.fw (или cluster.fw) — пример
[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -p tcp -dport 8006 -source 10.0.10.0/24   # только mgmt-subnet
IN ACCEPT -p tcp -dport 22   -source 10.0.10.0/24
```

```bash
pve-firewall restart
```

Полная семантика правил — [Продвинутый Firewall](./proxmox_firewall_advanced.md). TLS для :8006 (ACME/свой CA) — [ACME и SSL](./proxmox_acme_ssl.md); не оставляйте production на самоподписном сертификате без причины.

### 5. fail2ban: SSH и pveproxy

```bash
apt install -y fail2ban

# /etc/fail2ban/jail.local
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = nftables-multiport
ignoreip = 127.0.0.1/8 ::1 10.0.10.0/24

[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log

[pve-auth]
enabled = true
port = 8006
filter = pve-auth
logpath = /var/log/pveproxy/access.log
maxretry = 5
```

```bash
# /etc/fail2ban/filter.d/pve-auth.conf
[Definition]
failregex = ^.* pveproxy\[[0-9]+\]: authentication failure; .+ rhost=<HOST>
            ^.* pveproxy\[[0-9]+\]: unauthorized request from <HOST>
ignoreregex =
```

```bash
systemctl enable --now fail2ban
fail2ban-client status pve-auth
# → Number of jail: 1 ... (jail active)
```

fail2ban дополняет, но не заменяет firewall-ограничение source-подсети.

### 6. AppArmor

```bash
aa-status | head -20
# → apparmor module is loaded
# → 38 profiles are in enforce mode ... (в т.ч. pve-proxy, pvedaemon)

ls /etc/apparmor.d/ | grep -E 'pve|qemu|lxc'
aa-enforce /usr/sbin/pve-proxy /usr/sbin/pvedaemon
```

Denial → `journalctl -k | grep DENIED` → `aa-logprof` / `aa-genprof`. Временный complain: `aa-complain /usr/sbin/pve-proxy` — только для диагностики, сразу возвращайте enforce. AppArmor-профили гостей и Ceph — граничные случаи ниже.

### 7. Auditd: аудит управляющей плоскости

```bash
apt install -y auditd audispd-plugins

# /etc/audit/rules.d/90-proxmox.rules
# Конфигурация кластера
-w /etc/pve/ -p wa -k proxmox_config
-w /etc/pve/corosync.conf -p rwa -k corosync_config
-w /etc/pve/storage.cfg -p rwa -k storage_config
-w /etc/pve/firewall/ -p wa -k firewall_rules
-w /etc/pve/user.cfg -p wa -k pve_users
-w /etc/pve/priv/ -p wa -k pve_priv

# SSH
-w /root/.ssh/ -p wa -k ssh_keys
-w /home/ -p wa -k home_dirs

# Пакеты и логи
-w /var/log/apt/ -p wa -k apt_logs
-w /usr/bin/apt -p x -k apt_commands
-w /var/log/pveproxy/ -p wa -k pve_api_logs

# Учётные записи ОС
-w /etc/passwd -p wa -k user_modification
-w /etc/shadow -p wa -k password_modification
-w /etc/group  -p wa -k group_modification

# Не root (осторожно с объёмом)
-a always,exit -F arch=b64 -S execve -C uid!=root -k non_root_exec
```

```bash
augenrules --load && systemctl restart auditd
auditctl -l
ausearch -k proxmox_config --interpret
ausearch -k pve_priv --interpret
aureport --summary
```

Не ставьте `-e 2` (immutable) без плана перезагрузки; полный syscall-аудит роняет производительность — фильтруйте по path/key. Интеграция с SIEM и поиск UPID — [Логирование](./proxmox_logging.md).

### 8. Шифрование данных в PVE

Слои шифрования — разные гарантии и разные операционные издержки:

| Слой | Что шифрует | Когда | Ограничения |
| --- | --- | --- | --- |
| ZFS native (`encryption=aes-256-gcm`) | Dataset/том целиком | Общие хранилища на PVE | Задержка ввода passphrase/key на boot; snapshot/replicate — см. wiki ZFS |
| Диск гостя (`encryption=aes-256-cbc` + secret) | qcow2-образ на file-storage | Отдельные конфиденциальные VM | Не для raw LVM-thin без конвертации; миграция/снапшот — осторожно; формат legacy-AES в QEMU |
| PBS client-side (`encryption-key`) | Backup-набор | Защита бэкапов от чтения на PBS | Без ключа восстановление невозможно; хранить ключ **вне** PVE/PBS |
| Full-disk LUKS хоста | Корень/данные узла | Физический контроль доступа | Manual unlock на boot (или keyscript); нет official full-disk installer |

```bash
# Диск гостя на file-storage (qcow2), шифрование PVE
qm set 101 --scsi0 local:100,encryption=aes-256-cbc
# Секрет задаётся в конфиге VM (encryption key) — GUI: VM → Options → Encryption

# ZFS dataset для гостей
zfs create -o encryption=aes-256-gcm -o keylocation=prompt \
  -o keyformat=passphrase rpool/data-vms
```

Client-side encryption для PBS: `encryption-key autogen` в опциях storage — [Хранилища](./proxmox_storage.md), [Обновления/бэкапы](./proxmox_updates.md). Kлючи PBS лежат в `/etc/pve/priv/storage/` — не копируйте их в git/CI-артефакты.

### 9. Безопасность гостей (VM / LXC)

- **LXC:** по умолчанию unprivileged + AppArmor; `privileged: 1` — только если гость не может работать иначе; `nesting` без нужды — не включать.
- **KVM:** `netN: …,firewall=1` — прогнать трафик через PVE firewall; не давать USB/PCI passthrough «на всё» без inventory.
- **Шаблоны:** импортируйте cloud-images только с официальных источников и сверяйте checksum; шаблон — SSoT [Шаблоны ВМ](./proxmox_vm_templates.md).
- **QEMU Guest Agent:** полезен операционно; привилегии `VM.GuestAgent.*` — отдельно, не в «супер-роли».
- **Уязвимости ядра/QEMU:** следите за [Обновлениями](./proxmox_updates.md) (security-канал), не откладывайте ядро при CVE в KVM.

### 10. Сеть и изоляция трафика

Разделяйте VLAN: **management** (8006, SSH), **cluster** (corosync 5405–5412, migration 60000–60050, SSH между нодами), **storage** (NFS/iSCSI/Ceph), **guest**. Corosync — на выделенном интерфейсе; latency и jitter критичны ([Кластер](./proxmox_cluster.md)). WireGuard/OpenVPN для удалённого доступа — [VPN](./proxmox_vpn_tunnels.md). Сетевые профили — [Сети](./proxmox_networking.md).

### 11. Обновления и security-каналы

```bash
apt update && apt list --upgradable
# Без enterprise-подписки — non-subscription repo (см. Обновления)
```

Критичные CVE ядра/QEMU/стреков — не «потом в окно обслуживания», а по SLA ([Обновления](./proxmox_updates.md)). Подписка на Proxmox security announcements — обязательна для production.

### 12. Аудит готовности (checklist-команды)

```bash
# 2FA и токены
pveum user list
pveum user token list automation@pve
pveum user token permissions automation@pve ci

# Firewall
pve-firewall status
pve-firewall compile

# SSH / сервисы
sshd -T | grep -E 'permitrootlogin|passwordauthentication'
systemctl is-active pveproxy pve-firewall fail2ban

# Логи и обновления
zgrep -h 'authentication failure' /var/log/pveproxy/access.log* | tail
apt list --upgradable 2>/dev/null | wc -l

# CIS-аудит хоста
apt install -y lynis
lynis audit system --tests-from-group "firewall"
lynis audit system --tests-from-group "authentication"
```

## Диагностика и устранение неполадок

### Firewall блокирует доступ к API

```bash
pve-firewall status
pve-firewall compile
journalctl -u pve-firewall -f

# Просмотр логов (если log_level включён)
tail -f /var/log/pve/pvefirewall.log

# Аварийный обход — только консоль/IPMI, временно:
pve-firewall set options --enable 0
# Вернуть: pve-firewall set options --enable 1

# Правило НЕ добавляется pve-firewall add (такой команды нет):
# в /etc/pve/firewall/host.fw → [RULES] → IN ACCEPT -p tcp -dport 8006 -source <mgmt>
pve-firewall restart
```

### fail2ban заблокировал легитимный IP

```bash
fail2ban-client status pve-auth
fail2ban-client set pve-auth unbanip 10.0.10.5
# whitelist — в /etc/fail2ban/jail.local → ignoreip
```

### AppArmor блокирует сервис

```bash
journalctl -k | grep DENIED | tail
aa-logprof
aa-complain /usr/sbin/pve-proxy   # временно
aa-enforce /usr/sbin/pve-proxy    # обязательно вернуть
```

### Пользователь заблокирован TFA

```bash
pveum user tfa unlock joe@pve
# Recovery key — при входе; при enforcement-ошибках — domains.cfg (см. 2FA)
```

### Подозрение на утечку токена / пароля

```bash
pveum user token list <user>
pveum user token destroy <user> <tokenid>   # мгновенный отзыв
pveum user modify <user> --enable 0         # временная блокировка
zgrep -E 'token|authentication' /var/log/pveproxy/access.log* | tail -50
ausearch -k pve_priv -k proxmox_config --interpret | tail
```

## Лучшие практики

1. **Не root@pam в automation** — отдельные пользователи, `--privsep 1`, узкие ACL, `--expire` + ротация.
2. **2FA для всех interactive-учёток**; recovery keys — в vault/сейфе; enforcement — только после выпуска факторов root.
3. **SSH keys-only**, root — `prohibit-password`; OOB-доступ (IPMI/iLO/iDRAC) — проверен до hardening.
4. **Порт 8006** — только mgmt-subnet через pve-firewall; доверенный TLS ([ACME](./proxmox_acme_ssl.md)).
5. **fail2ban** на sshd + pveproxy; **auditd** на `/etc/pve/`, `/etc/pve/priv/`, SSH-ключи.
6. **Разделение сетей** mgmt / cluster / storage / guest; corosync — не в гостевом VLAN.
7. **Обновления** по security-каналу; kernel/QEMU CVE — приоритет выше косметики.
8. **Шифрование** — осознанно: ZFS/PBS-ключ / диск гостя; ключи вне PVE и вне git.
9. **Гости**: unprivileged LXC, `firewall=1` на NIC, шаблоны с checksum.
10. **Регулярный walkthrough** checklist (раздел 12) + review ACL (`pveum acl list`) и токенов.
11. **Секреты**: `/etc/pve/priv/` не «приватный git»; backup ключей — сейф, не тот же кластер.
12. **Реагирование**: access.log + task log ([Логирование](./proxmox_logging.md)) — первые источники при инциденте.

## Граничные случаи

- **PVE Firewall и corosync**: при enable кластерные ACCEPT генерируются автоматически (UDP 5405–5412); при ручных DROP-политиках не забудьте SSH 22 и миграцию 60000–60050. QDevice/QNetd — TCP 5403 ([Кластер](./proxmox_cluster.md)).
- **API-токен и консоль**: vnc/spice/xtermjs/serial не принимают `PVEAPIToken` — только session ticket.
- **`pve-firewall` CLI**: `start|stop|restart|status|compile|simulate` — **без** `add`; правки — файлы `.fw`, GUI или API.
- **AppArmor и Ceph**: denial в `ceph-osd` — `journalctl -u ceph-osd | grep -i apparmor`; не отключайте профиль «навсегда».
- **Auditd**: `non_root_exec` и полный execve-аудит шумят; `-e 2` — только с планом отката.
- **Шифрование гостя vs live migration**: encrypted disks могут блокировать/ограничивать миграцию — проверяйте на стенде.
- **Локальный `local-lvm` — raw**: «Encrypt» из GUI требует подходящий storage/format; для ZFS/PBS используйте их нативные механизмы.
- **Удаление VM**: `destroy` не «секретно затирает» данные на SSD/thin — чувствительные данные — на уровне шифрования + crypto-erase, не hope.

### Связанные темы

- [REST API и токены](./proxmox_rest_api.md)
- [Автоматизация Ansible](./proxmox_ansible.md)
- [Proxmox Service Discovery](./proxmox_service_discovery.md)
- [Продвинутый Firewall](./proxmox_firewall_advanced.md)
- [Сетевые технологии](./proxmox_networking.md)
- [VPN-туннели](./proxmox_vpn_tunnels.md)
- [Мониторинг](./proxmox_monitoring.md)
- [Логирование](./proxmox_logging.md)
- [Обновления](./proxmox_updates.md)
- [Хранилища](./proxmox_storage.md)
- [ACME и SSL](./proxmox_acme_ssl.md)
- [Кластеризация и HA](./proxmox_cluster.md)
- [Шаблоны ВМ](./proxmox_vm_templates.md)
- [SSH Hardening (SSoT)](../Linux/Security/ssh/server/ssh_hardening_best_practices.md)
- [AppArmor (SSoT)](../Linux/Security/Mechanisms/AppArmor.md)
- [fail2ban (SSoT)](../Linux/Security/Tools/fail2ban.md)
- [auditd (SSoT)](../Linux/SystemAdministration/Logging/auditd.md)
- [nftables (SSoT)](../Linux/Networking/Settings/tools/nftables/architecture_and_concepts.md)
- [CIS / OS Hardening (Ansible)](../Ansible/ansible-os-hardening.md)
