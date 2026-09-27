# NFS: Безопасность и аутентификация

---

## Определения

**NFS-безопасность** — комплекс мер по защите сетевой файловой системы, включающий проверку подлинности (аутентификацию), разграничение прав доступа (авторизацию), контроль целостности данных и сетевую изоляцию.

**RPCSEC_GSS** — протокольный механизм безопасности, интегрирующий GSS-API (Generic Security Services Application Program Interface) в стек RPC. Позволяет использовать Kerberos для аутентификации и опционального шифрования/целостности каждого пакета NFS.

**Labeled NFS** — расширение протокола NFSv4.2, передающее метки безопасности (Security Attributes) между клиентом и сервером. Поддерживает принудительный контроль доступа (MAC) в SELinux, AppArmor и других системах.

**NFSv4 ACL** — механизм списков управления доступом протокола NFSv4, обеспечивающий детальное разграничение прав (allow/deny) на уровне отдельных файлов и директорий с наследованием.

**idmapd (rpc.idmapd)** — демон маппинга UID/GID в имена пользователей и групп. Для NFSv4 обеспечивает согласованность прав между клиентом и сервером независимо от локальных баз пользователей.

**Keytab** — файл с набором зашифрованных ключей principals Kerberos, используемый для автоматической аутентификации служб без интерактивного ввода пароля.

**KDC (Key Distribution Center)** — центр распределения ключей в инфраструктуре Kerberos. Выпускает и проверяет билеты (TGT, service tickets). Состоит из AS (Authentication Service) и TGS (Ticket Granting Service).

---

## Основные концепции

### Методы аутентификации (`sec=`)

Параметр `sec` в `/etc/exports` или опциях монтирования определяет уровень криптографической защиты.

| Метод | Уровень защиты | Техническое описание |
| :--- | :--- | :--- |
| **`sys`** | Минимальный | Использует стандартные UID/GID. Сервер доверяет идентификаторам, присланным клиентом. **Уязвим** к подмене IP и spoofing UID 0. Является значением по умолчанию в большинстве дистрибутивов. |
| **`krb5`** | Средний | Аутентификация на базе билетов Kerberos. Проверяет подлинность пользователя через KDC, но трафик передается в открытом виде. |
| **`krb5i`** | Высокий | Kerberos + контроль целостности (Integrity). Каждый пакет подписывается HMAC-SHA2, защищая от модификации (MitM) и replay-атак. |
| **`krb5p`** | Максимальный | Kerberos + шифрование (Privacy). Полное шифрование данных и метаданных трафика AES-256. Рекомендуется для недоверенных сетей и соблюдения compliance (PCI-DSS, HIPAA). |

### Архитектура RPCSEC_GSS

RPCSEC_GSS является прослойкой между RPC-вызовами и механизмами GSS-API. Протокол обеспечивает три базовых свойства:

1.  **Аутентификация (Authentication):** Подтверждение личности вызывающей стороны через билет Kerberos.
2.  **Целостность (Integrity):** Каждый RPC-запрос и ответ подписывается с помощью session key, полученного из Kerberos keytab.
3.  **Конфиденциальность (Privacy):** Опциональное шифрование тела RPC-сообщения (режим `krb5p`).

**Жизненный цикл сессии:**
- Клиент инициирует `SET_CLIENT` с creds Kerberos, получая handle.
- Для каждого последующего RPC-вызова передается handle + подпись/шифрование.
- При смене ключей или таймауте происходит `DESTROY` и повторная установка контекста.

**Важно:** RPCSEC_GSS не шифрует ARP-запросы и DNS-трафик. Для полной защиты используйте изолированную VLAN.

### Механизмы маппинга (Squash)

Управление тем, как сервер интерпретирует запросы от пользователей клиента.

- **`root_squash` (По умолчанию):** Запросы от `root` (UID 0) преобразуются в анонимного пользователя (`nobody`). Это критически важно для защиты сервера от скомпрометированных клиентов.
- **`no_root_squash`:** `root` на клиенте обладает правами `root` на сервере. Разрешено только для специфических задач (например, бездисковая загрузка), где доверие между узлами абсолютно.
- **`all_squash`:** Все пользователи маппятся в анонимного (`anonuid`/`anongid`). Идеально для публичных хранилищ "только для чтения" или гостевого доступа.

### ACL NFSv4

Современный механизм контроля доступа, встроенный в протокол NFSv4. В отличие от классических POSIX ACL (файловая система), NFSv4 ACL унифицирован и поддерживает:

- **Allow/Deny записи:** Возможность явного запрета (`deny`) с более высоким приоритетом, чем `allow`.
- **Наследование:** ACL может автоматически применяться к новым файлам и директориям (inherit flags).
- **Группы:** Права назначаются как пользователям, так и группам.
- **Типы доступа:** `r` (read), `w` (write), `x` (execute), `d` (delete), `t` (read attributes), `T` (write attributes), `l` (list directory), `a` (append), `D` (delete child).

**Синтаксис:**
```text
A:fdg:user@domain:rwatTnNcCy
# where: A=Allow, D=Deny, fdg=flags (file/directory/inherit), user@domain=principal
```

### Безопасность NFSv4

NFSv4 вносит фундаментальные архитектурные улучшения безопасности по сравнению с NFSv3:

1.  **Единый порт 2049/TCP:** Все операции (включая монтирование) выполняются через один порт. Устраняет необходимость в `rpcbind` (portmapper) и `mountd`, которые в NFSv3 были объектами сканирования.
2.  **Pseudo Root:** Виртуальное корневое дерево, через которое осуществляется доступ. Скрывает реальные пути на сервере от клиентов.
3.  **Встроенная поддержка ACL:** ACL управляются напрямую протоколом, а не через отдельные системные вызовы файловой системы.
4.  **Stateful протокол:** Сервер хранит состояние сессий, что позволяет реализовать тонкую привязку прав к конкретным клиентам.

### Безопасность поддеревьев (Subtree Check)

- **`subtree_check`:** Сервер проверяет, находится ли запрашиваемый файл в разрешенном поддереве. Это безопаснее, если экспортируется не весь раздел диска, но может вызывать проблемы с открытыми файлами при переименовании директорий.
- **`no_subtree_check`:** Отключает проверку. Повышает производительность и стабильность, рекомендуется, если экспортируется вся файловая система (весь раздел).

### idmapd и безопасность именования

Демон `rpc.idmapd` работает на обоих концах соединения и преобразует числовые UID/GID в имена пользователей и обратно. **Безопасные практики:**

- Параметр `Domain` в `/etc/idmapd.conf` должен быть идентичен на сервере и всех клиентах. Несовпадение приведет к ошибкам "Permission denied" даже при совпадающих UID/GID.
- Используйте централизованный LDAP/SSSD для синхронизации UID/GID между узлами, чтобы исключить несоответствия.
- Отключайте кэширование `idmapd` (`CacheTimeout=0`) в средах с частым изменением членства в группах, чтобы избежать устаревших прав доступа.

---

## Практические сценарии

### Закаленная конфигурация экспорта (`/etc/exports`)

Пример настройки с максимальной изоляцией, шифрованием и ACL:

```ini
# Экспорт для критических данных (NFSv4.2, Kerberos с шифрованием, явный ACL)
/srv/nfs/secure 10.0.1.20(rw,sync,sec=krb5p,root_squash,no_subtree_check)

# Публичное хранилище (только чтение, полный squash в nobody)
/srv/nfs/public 10.0.1.0/24(ro,all_squash,anonuid=65534,anongid=65534)

# Внутренний обмен (только чтение, Kerberos с проверкой целостности)
/srv/nfs/internal 10.0.1.0/24(ro,no_subtree_check,sec=krb5i)
```

**Применение конфигурации:**
```bash
sudo exportfs -ra
sudo exportfs -v
# → /srv/nfs/secure 10.0.1.20(rw,wdelay,root_squash,no_subtree_check,sec=krb5p,...)
```

### Настройка Labeled NFS (SELinux)

Для передачи контекстов SELinux убедитесь, что используется NFSv4.2.

**На сервере и клиенте:**
```bash
# Проверка поддержки в ядре (должно быть Y)
grep CONFIG_NFS_V4_2 /boot/config-$(uname -r)
# → CONFIG_NFS_V4_2=y
```

**На сервере (RHEL/CentOS/Rocky):**
```bash
# Разрешение экспорта NFS в SELinux (включено по умолчанию в большинстве политик)
sudo setsebool -P nfs_export_all_rw on
sudo setsebool -P nfs_export_all_ro on

# Применение метки к директории экспорта
sudo semanage fcontext -a -t nfs_t "/srv/nfs/shared(/.*)?"
sudo restorecon -Rv /srv/nfs/shared

# Проверка
ls -Zd /srv/nfs/shared
# → system_u:object_r:nfs_t:s0 /srv/nfs/shared
```

**На клиенте:**
```bash
sudo mount -t nfs -o nfsvers=4.2 10.0.0.5:/data /mnt/data
# Проверка меток
ls -Z /mnt/data
# → system_u:object_r:nfs_t:s0 file.txt
```

### ACL NFSv4 на практике

Установка прав через `nfs4_setfacl` (пакет `nfs4-acl-tools` в Debian/Ubuntu или часть `nfs-utils` в RHEL):

```bash
# Предоставить пользователю alice права на чтение и запись
sudo nfs4_setfacl -a "A:fdg:alice@example.local:rwx" /mnt/shared/project

# Запретить пользователю bob доступ к директории
sudo nfs4_setfacl -a "D:fdg:bob@example.local:rwx" /mnt/shared/project

# Наследование для новых файлов (директория)
sudo nfs4_setfacl -m "A:fdg:devgroup@example.local:rwxt" /mnt/shared/project

# Просмотр текущих ACL
nfs4_getfacl /mnt/shared/project
# → A:fdg:alice@example.local:rwx
# → D:fdg:bob@example.local:rwx
# → A:fdg:devgroup@example.local:rwxt
```

### Харденинг RPC и Сетевого экрана

NFSv4 требует только порт **2049/TCP**. Все остальные службы (portmapper, mountd) можно отключить или ограничить.

**Сетевая изоляция (рекомендуется):**
- Размещайте NFS в отдельной VLAN или физической подсети.
- Никогда не экспонируйте NFS в публичную сеть без VPN/туннеля.

**Firewalld (RHEL/CentOS):**
```bash
# Разрешить NFS только из доверенной зоны
sudo firewall-cmd --permanent --zone=internal --add-service=nfs
sudo firewall-cmd --permanent --zone=public --remove-service=nfs
sudo firewall-cmd --reload
# → success
```

**UFW (Ubuntu):**
```bash
sudo ufw allow from 10.0.1.0/24 to any port 2049 proto tcp
# → Rule added
```

**iptables / nftables (ручные правила):**
```bash
# iptables
sudo iptables -A INPUT -p tcp --dport 2049 -s 10.0.1.0/24 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 2049 -j DROP

# nftables
sudo nft add rule inet filter input tcp dport 2049 ip saddr 10.0.1.0/24 accept
sudo nft add rule inet filter input tcp dport 2049 drop
```

**Отключение лишних RPC-служб (NFSv4-only среда):**
```bash
# RHEL/CentOS
sudo systemctl mask --now rpcbind.socket rpcbind.service
sudo systemctl mask --now rpc.statd.service rpc.idmapd.service  # Осторожно: может сломать NFSv3 и NSM

# Debian/Ubuntu
sudo systemctl disable --now rpcbind rpcbind.socket
```

### Интеграция с Kerberos (пошаговая настройка)

#### Шаг 1. Подготовка KDC и principals

На KDC-сервере (MIT Kerberos или FreeIPA):
```bash
# MIT Kerberos (kadmin.local)
kadmin.local -q "addprinc -randkey nfs/server.example.local"
kadmin.local -q "addprinc -randkey host/server.example.local"
kadmin.local -q "addprinc nfs/client.example.local"  # Для клиента
```

#### Шаг 2. Создание keytab на сервере NFS

```bash
kadmin.local -q "ktadd -k /tmp/nfs.keytab nfs/server.example.local host/server.example.local"
# Проверка содержимого
sudo ktutil -k /etc/krb5.keytab -t
# → FILE:/etc/krb5.keytab:
# → Vno 5
# → nfs/server.example.local@EXAMPLE.LOCAL (aes256-cts-hmac-sha384-192)
```

Скопируйте keytab на сервер:
```bash
sudo mv /tmp/nfs.keytab /etc/krb5.keytab
sudo chown root:root /etc/krb5.keytab
sudo chmod 600 /etc/krb5.keytab
```

#### Шаг 3. Конфигурация Kerberos на сервере

```bash
# /etc/krb5.conf (фрагмент)
[libdefaults]
    default_realm = EXAMPLE.LOCAL
    dns_lookup_realm = false
    dns_lookup_kdc = true
    rdns = false
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true
    default_tgs_enctypes = aes256-cts-hmac-sha384-192
    default_tkt_enctypes = aes256-cts-hmac-sha384-192
    permitted_enctypes = aes256-cts-hmac-sha384-192 aes128-cts-hmac-sha256-128
```

Запустите GSS-демон на сервере:
```bash
sudo systemctl enable --now rpc-svcgssd
sudo systemctl status rpc-svcgssd
# → active (running)
```

#### Шаг 4. Конфигурация клиента

На клиенте создайте аналогичный `/etc/krb5.conf` и скопируйте keytab:
```bash
sudo ktutil -k /etc/krb5.keytab -t
# → Vno 5
# → nfs/client.example.local@EXAMPLE.LOCAL
# → nfs/server.example.local@EXAMPLE.LOCAL

sudo systemctl enable --now rpc-gssd
```

#### Шаг 5. Обновление `/etc/exports`

```ini
/srv/nfs/secure 10.0.1.20(rw,sync,sec=krb5p,root_squash,no_subtree_check)
```

Примените:
```bash
sudo exportfs -ra
```

#### Шаг 6. Монтирование с Kerberos

```bash
sudo mount -t nfs -o nfsvers=4.2,sec=krb5p 10.0.1.5:/srv/nfs/secure /mnt/secure
```

#### Шаг 7. Проверка

```bash
# Билеты в кеше
klist
# → Ticket cache: FILE:/tmp/krb5cc_1000
# → Default principal: user@EXAMPLE.LOCAL
# → Valid starting       Expires              Service principal
# → 09/12/2026 10:00:00  09/13/2026 10:00:00  krbtgt/EXAMPLE.LOCAL@EXAMPLE.LOCAL

# Проверка безопасности активного монтирования
nfsstat -m | grep -i sec
# → sec=krb5p

# Проверка GSS-сессий на сервере
sudo cat /proc/net/rpc/use-gss/protocol
# → nfs
```

### Диагностика и аудит безопасности NFS

#### Мониторинг активных монтирований

```bash
# Проверка параметров безопасности активных соединений
nfsstat -m
# → /mnt/secure from 10.0.1.5:/srv/nfs/secure
# → Flags: rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,namlen=255,hard,proto=tcp,nconnect=4,sec=krb5p,...

# Детальная статистика RPC
cat /proc/self/mountstats | grep -A2 "/mnt/secure"
# → device 10.0.1.5:/srv/nfs/secure mounted on /mnt/secure
# → ops: 1452, numacl: 0, numdir: 12
```

#### Аудит через auditd

Для отслеживания отказов в доступе к NFS-экспортам на сервере:

```bash
# Добавление правил аудита
sudo auditctl -w /srv/nfs/ -p rwxa -k nfs_export_access
sudo auditctl -w /etc/exports -p wa -k nfs_export_config

# Просмотр событий
sudo ausearch -k nfs_export_access --start recent
# → time->Sat Sep 12 13:00:00 2026
# → type=PROCTITLE msg=audit(1726168800.123:456): proctitle="nginx"
# → type=PATH msg=audit(1726168800.123:456): item=0 name="/srv/nfs/secure/file.txt" inode=12345 dev=fd:00 mode=0100644
# → type=PROCTITLE msg=audit(1726168800.123:456): proctitle="/usr/sbin/rpc.mountd"
# → type=SYSCALL msg=audit(1726168800.123:456): arch=c000003e syscall=2 success=no exit=-13
```

#### Проверка билетов Kerberos

```bash
# Просмотр текущих билетов
klist -e
# → Ticket cache: FILE:/tmp/krb5cc_1000
# → Default principal: user@EXAMPLE.LOCAL
# → Valid starting       Expires              Service principal
# → 09/12/2026 10:00:00  09/13/2026 10:00:00  krbtgt/EXAMPLE.LOCAL@EXAMPLE.LOCAL (aes256-cts-hmac-sha384-192)

# Получение нового билета
kinit user@EXAMPLE.LOCAL
Password for user@EXAMPLE.LOCAL:

# Удаление билетов
kdestroy
```

#### Проверка экспортов и их безопасности

```bash
# Просмотр всех активных экспортов с опциями безопасности
sudo exportfs -v | grep -E "sec=|root_squash|all_squash"
# → /srv/nfs/secure 10.0.1.20(rw,wdelay,root_squash,no_subtree_check,sec=krb5p,...)
# → /srv/nfs/public 10.0.1.0/24(ro,wdelay,all_squash,no_subtree_check,sec=sys,...)
```

---

## Дополнительная информация

### Шифрование без Kerberos

Если внедрение инфраструктуры Kerberos избыточно, используйте туннелирование для защиты трафика:

#### WireGuard VPN

Создание зашифрованного канала между клиентом и сервером:

**На сервере (`/etc/wireguard/wg0.conf`):**
```ini
[Interface]
PrivateKey = <server_private_key>
Address = 10.200.0.1/24
ListenPort = 51820
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
# Клиент
PublicKey = <client_public_key>
AllowedIPs = 10.200.0.2/32
```

**На клиенте (`/etc/wireguard/wg0.conf`):**
```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.200.0.2/24
DNS = 10.0.1.1

[Peer]
PublicKey = <server_public_key>
Endpoint = <server_public_ip>:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

Запуск:
```bash
sudo systemctl enable --now wg-quick@wg0
# Проверка
sudo wg show
# → latest handshake: 1 minute ago
```

После поднятия туннеля монтируйте NFS через внутренний IP WireGuard:
```bash
sudo mount -t nfs -o nfsvers=4.2 10.200.0.1:/srv/nfs/secure /mnt/secure
```

#### IPsec (StrongSwan)

Для корпоративных сред с жесткими требованиями к безопасности:

```bash
# Установка
sudo apt install strongswan

# Конфигурация (/etc/ipsec.conf — оба узла)
# Используйте PSK или сертификаты x.509 для аутентификации.
# После поднятия туннеля (interfaces между 10.200.0.1 и 10.200.0.2) монтируйте NFS через эти адреса.
```

### Управление keytab и билетами

#### Резервное копирование

```bash
# Копирование keytab в защищенное хранилище
sudo cp /etc/krb5.keytab /root/backups/krb5.keytab.$(date +%Y%m%d)
sudo chmod 600 /root/backups/krb5.keytab.*
```

**Проверка перед восстановлением:**
```bash
sudo ktutil -k /etc/krb5.keytab -t
# Убедитесь, что отображаются все ожидаемые principals (nfs/host, host/host)
```

#### Ротация ключей

```bash
# Генерация нового ключа для principal
kadmin.local -q "cpw -randkey nfs/server.example.local"

# Перезапись keytab
kadmin.local -q "ktadd -k /etc/krb5.keytab nfs/server.example.local"

# Перезапуск служб
sudo systemctl restart rpc-svcgssd
```

### Контрольный список (Checklist)

- [ ] Использовать только NFSv4.2 (отключить NFSv3 в `/etc/nfs.conf` или `/etc/default/nfs-kernel-server`).
- [ ] Применять `root_squash` для всех общих ресурсов.
- [ ] Для недоверенных сетей использовать `sec=krb5p`.
- [ ] Ограничивать экспорт конкретными IP-адресами (избегать имен хостов, которые можно подменить через DNS-спуфинг).
- [ ] Использовать `no_subtree_check` для целых разделов, `subtree_check` — только при экспорте поддеревьев.
- [ ] Настроить идентичный параметр `Domain` в `/etc/idmapd.conf` на сервере и всех клиентах.
- [ ] Централизовать UID/GID через LDAP/SSSD для согласованного маппинга.
- [ ] Размещать NFS в отдельной VLAN; на сетевом экране разрешать 2049/tcp только из подсети хранилища.
- [ ] На клиентах использовать `hard` монтирование для защиты от повреждения данных при сбоях сервера.
- [ ] Включить и настроить `auditd` для логирования отказов в доступе к NFS-экспортам.
- [ ] Регулярно проверять лог `/var/log/audit/audit.log` на предмет отказов в доступе (особенно при использовании SELinux).
- [ ] Создать резервную копию `/etc/krb5.keytab` и внести её в процедуры Disaster Recovery.
- [ ] Проверить статус `nfs-idmapd` на сервере и клиенте (`systemctl status nfs-idmapd`).
- [ ] Настроить `nfs4_setfacl` на сервере для критически важных директорий, если требуется детальный контроль доступа.

### Связанные темы

- **[NFS: Основные концепции](./index.md)** — архитектура, версии и блокировки.
- **[NFS: Настройка сервера и клиента](./nfs_setup.md)** — базовые шаги развертывания, параметры монтирования.
- **[Kerberos: Аутентификация](../../../../Security/Concepts/kerberos.md)** — принципы работы билетов и keytab.
- **[Концепции Firewall](../../../../Networking/Concepts/firewall_concepts.md)** — теория сетевой фильтрации.
- **[Настройка Firewall в Linux](../../../../Linux/Networking/Settings/tools/firewall_common.md)** — примеры для UFW, firewalld, iptables и nftables.
- **[LDAP и SSSD](../../../SystemAdministration/Users/LDAP_SSSD/index.md)** — централизация UID/GID для корректного маппинга.
