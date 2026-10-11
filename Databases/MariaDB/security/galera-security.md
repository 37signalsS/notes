# Безопасность кластера Galera в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS (Galera 4); `wsrep_ssl_mode` и `[sst] ssl_mode` — только Enterprise Server 10.6+

## Определения

**Galera Cluster** — синхронная multi-master репликация для MariaDB (wsrep API). Узлы реплицируют транзакции на уровне сертификации (certification-based replication).

**SST (State Snapshot Transfer)** — полная передача состояния узлу, присоединяющемуся к кластеру (или отстающему). Выполняется через `mariabackup`, `rsync` или `mysqldump`.

**IST (Incremental State Transfer)** — передача только отставших событий из write-set cache (gcache), когда узел временно отключался.

**wsrep_provider_options** — параметры провайдера Galera (gmcast, evs, socket), задаваемые в `my.cnf` или динамически.

**wsrep_allowlist** — список IP-адресов, которым разрешено присоединяться к кластеру и запрашивать SST/IST. Задаётся переменной `wsrep_allowlist` или таблицей `mysql.wsrep_allowlist` (колонка `ip`); появилась в MariaDB 10.10.

**wsrep_sst_method** — метод SST: `mariabackup` (по умолчанию с 10.2, не блокирует донора), `rsync`, `mysqldump`. Меняется динамически (`SET GLOBAL`) на узле-доноре; на всех узлах должен быть одинаковый.

**garbd (Galera Arbitrator Daemon)** — демон, участвующий в кворуме без хранения данных; используется для split-brain-защиты в нечётных конфигурациях.

**gcache** — кольцевой буфер write-set'ов на диске (файл `galera.cache` в datadir, опция `gcache.name`); используется для IST. Размер — `gcache.size` (опция провайдера, задаётся только через `wsrep_provider_options`).

## Основные концепции

### Поверхность атаки Galera

| Вектор | Риск | Защита |
| :--- | :--- | :--- |
| SST-трафик | передача полных данных в открытом виде | шифрование SST (`[sst]` секция) |
| Replication-трафик | перехват write-set'ов | TLS на провайдере (wsrep_provider_options) |
| Присоединение узла | rogue-узел в кластере | `wsrep_allowlist`, аутентификация SST |
| gcache на диске | утечка данных из кеша | права на datadir, шифрование диска |
| garbd | компрометация кворума | сегментация, минимальные права |

### Критический факт: TLS для репликации НЕ шифрует SST

Шифрование трафика репликации (`wsrep_provider_options` с `socket.ssl_*`) защищает только инкрементальную репликацию. **SST по умолчанию передаётся в открытом виде** (socat-пайп без шифрования, `encrypt=0`). Для защиты SST требуется отдельная настройка секции `[sst]` в `my.cnf`.

### Методы шифрования SST

| Метод | Параметр | Механизм |
| :--- | :--- | :--- |
| Нет (дефолт) | `encrypt=0` | незашифрованный socat TCP pipe |
| TLS (socat OpenSSL) | `encrypt=2` + `tca`, `tcert` | TLS через OpenSSL, встроенный в socat |
| TLS + Galera-сертификаты | `encrypt=3` + `tcert`, `tkey` | TLS с Galera-совместимыми сертификатами и ключами |
| TLS + стандартные сертификаты | `encrypt=4` | TLS со стандартными MySQL/MariaDB SSL-сертификатами |
| Нативное шифрование | `encrypt=AES256` + `encrypt-key-file` (+ `use-extra=1`) | шифрование SST-потока AES-256 (pass-through опции mariadb-backup) |
| TLS верхнего уровня | `ssl_mode` в `[sst]` | `DISABLED` / `REQUIRED` / `VERIFY_CA` / `VERIFY_IDENTITY` (Enterprise; методы `mariabackup` и `rsync`) |

- `encrypt=1` — устаревший метод TLS, удалён; не используйте.
- При `ssl_mode` ≠ `DISABLED` и настроенных серверных `ssl_cert`/`ssl_key` утилита `mariadb-backup` автоматически включает `encrypt=3`, переиспользуя сертификаты сервера.
- **DARE (шифрование данных на диске):** физические методы (`mariabackup`, `rsync`) копируют уже зашифрованные файлы — все узлы должны использовать одинаковые ключи шифрования; логический `mysqldump` допускает разные ключи на узлах.

### Аутентификация SST

`wsrep_sst_auth` задаёт учётные данные для SST-донора. Пользователю нужны глобальные привилегии `RELOAD, PROCESS, LOCK TABLES, BINLOG MONITOR, REPLICA MONITOR` (в документации к более ранним версиям указан `REPLICATION CLIENT`).

**MariaDB Enterprise Server 11.4+:** если `wsrep_sst_auth` не задан, донор при каждом SST создаёт временного внутреннего пользователя (`'wsrep.sst.<timestamp>_<node_id>'@localhost`) с генерируемым паролем, выдаёт ему нужные привилегии и удаляет после завершения — пароль не хранится в `my.cnf`. Явное указание `wsrep_sst_auth` переключает поведение обратно на ручное.

Без аутентификации любой узел, знающий адрес, может запросить SST.

### Сетевая сегментация

- **3306** — клиентские подключения и SST методом `mysqldump`.
- **4567** — репликационный трафик Galera (TCP; при multicast — также UDP). Адрес/порт задаются опцией `gmcast.listen_addr`.
- **4568** — Incremental State Transfer (IST), опция `ist.recv_addr`.
- **4444** — SST для всех методов, кроме `mysqldump` (опция `wsrep_sst_receive_address`).
- Все эти порты — только в доверенной сети/VLAN, недоступной извне. Пример (firewalld):

```bash
sudo firewall-cmd --permanent --zone=galera \
  --add-rich-rule='rule family="ipv4" source address="10.0.5.0/24" port port="4567-4568" protocol="tcp" accept'
sudo firewall-cmd --permanent --zone=galera \
  --add-rich-rule='rule family="ipv4" source address="10.0.5.0/24" port port="4444" protocol="tcp" accept'
sudo firewall-cmd --reload
```

- `wsrep_allowlist` — белый список IP для присоединения.

## Предварительные требования

- MariaDB 10.11 LTS / 11.4 / 11.8 / 12.3 LTS с Galera 4 (wsrep API 26). В MariaDB 12.3 Galera требует отдельного пакета `mariadb-server-galera`.
- Обязательные опции Galera: `wsrep_on=ON`, `binlog_format=ROW`, `default_storage_engine=InnoDB`, `innodb_doublewrite=1` (значение по умолчанию, не менять).
- Минимум 3 узла (или 2 узла + garbd) для кворума.
- `socat` на всех узлах — требуется для SST методом `mariabackup` (в RHEL/CentOS — из EPEL).
- Для шифрования SST: общий ключевой файл на всех узлах (`encrypt=AES256`) или TLS-сертификаты (`encrypt=2/3/4`, `[sst] ssl_mode`).
- Для TLS репликации: сертификаты на всех узлах.
- Для `wsrep_allowlist`: MariaDB 10.10+.

## Практические сценарии

### Сценарий 1: Шифрование SST (нативное, AES-256)

```ini
# my.cnf на ВСЕХ узлах (файл содержит пароль — права 0600 root:mysql)
[galera]
wsrep_provider = /usr/lib/galera/libgalera_smm.so
wsrep_cluster_address = gcomm://10.0.5.20,10.0.5.21,10.0.5.22
wsrep_sst_method = mariabackup

# Аутентификация SST (ES 11.4+ можно не задавать — см. пояснения)
wsrep_sst_auth = mariadbbackup:StrongPassword

# Шифрование SST
[sst]
use-extra = 1
encrypt = AES256
encrypt-key-file = /etc/mysql/galera/sst.key
```

```sql
-- Пользователь для SST на каждом узле (ручной режим)
CREATE USER 'mariadbbackup'@'localhost' IDENTIFIED BY 'StrongPassword';
GRANT RELOAD, PROCESS, LOCK TABLES, BINLOG MONITOR, REPLICA MONITOR ON *.* TO 'mariadbbackup'@'localhost';
```

```bash
# Генерация ключа (на одном узле, затем копирование на остальные)
openssl rand -hex 32 > /etc/mysql/galera/sst.key
sudo chown mysql:mysql /etc/mysql/galera/sst.key
sudo chmod 600 /etc/mysql/galera/sst.key

# Копирование на остальные узлы (по защищённому каналу)
scp /etc/mysql/galera/sst.key db02:/etc/mysql/galera/sst.key
scp /etc/mysql/galera/sst.key db03:/etc/mysql/galera/sst.key
```

**Пояснения:**
- Ключевой файл должен быть идентичен на всех узлах и недоступен посторонним.
- `use-extra=1` включает pass-through опций mariadb-backup (`encrypt`, `encrypt-key-file`).
- `encrypt = AES256` — нативное шифрование SST-потока.
- **ES 11.4+:** не задавайте `wsrep_sst_auth` — донор создаст временного пользователя с генерируемым паролем на время SST (см. «Аутентификация SST»); пароль не попадёт в `my.cnf`.
- Ограничьте скорость SST, чтобы не насыщать сеть: `[sst] rlimit = 100M` (байт/с, суффиксы K/M/G).

### Сценарий 2: TLS для репликационного трафика (Community)

```ini
[galera]
wsrep_provider_options = "socket.ssl=true; \
socket.ssl_ca=/etc/mysql/ssl/ca.pem; \
socket.ssl_cert=/etc/mysql/ssl/node-cert.pem; \
socket.ssl_key=/etc/mysql/ssl/node-key.pem; \
socket.ssl_cipher=AES256-SHA256"
```

```bash
# Опции socket.ssl_* НЕ динамические — требуется перезапуск узла
sudo systemctl restart mariadb

# Текущие значения провайдера (опции без значения по умолчанию,
# включая SSL-опции, в выводе НЕ отображаются — проверяйте логи)
mariadb -e "SHOW GLOBAL VARIABLES LIKE 'wsrep_provider_options';"

# Косвенная проверка: TLS-хендшейк пишется в error log при старте,
# а трафик на 4567 становится нечитаемым (см. «Проверка шифрования SST»)
```

**Пояснение:** в Community-версии TLS провайдера настраивается через `wsrep_provider_options` (опции `socket.ssl`, `socket.ssl_ca`, `socket.ssl_cert`, `socket.ssl_key`, `socket.ssl_cipher` — все PEM-формат, не динамические). Переменная `wsrep_ssl_mode` (`PROVIDER` / `SERVER` / `SERVER_X509`) доступна только в MariaDB Enterprise Server 10.6+: `SERVER` — TLS через серверные `ssl_cert`/`ssl_key`/`ssl_ca` (default в ES 10.6, но без проверки X.509), `SERVER_X509` — TLS с обязательной верификацией сертификатов, `PROVIDER` — обратно-совместимый режим через `wsrep_provider_options`.

### Сценарий 3: Ограничение присоединения к кластеру

```sql
-- Белый список IP для присоединения (колонка ip; MariaDB 10.10+)
INSERT INTO mysql.wsrep_allowlist(ip) VALUES('10.0.5.20');
INSERT INTO mysql.wsrep_allowlist(ip) VALUES('10.0.5.21');
INSERT INTO mysql.wsrep_allowlist(ip) VALUES('10.0.5.22');

-- Проверка
SELECT * FROM mysql.wsrep_allowlist;
-- → 10.0.5.20, 10.0.5.21, 10.0.5.22

-- Удаление узла из белого списка
DELETE FROM mysql.wsrep_allowlist WHERE ip='10.0.5.22';
```

```ini
# Альтернатива через переменную (не динамическая — требует перезапуска)
[galera]
wsrep_allowlist = 10.0.5.20,10.0.5.21,10.0.5.22
```

### Сценарий 4: garbd для кворума

```bash
# Пакет: galera-arbitrator-4
# Запуск garbd на отдельном хосте (третий ЦОД)
# -a — адрес кластера, -g — имя группы (кластера),
# -o — опции провайдера (GCS/GCOMM), -l — лог
garbd -a gcomm://10.0.5.20,10.0.5.21,10.0.5.22 \
  -g my_cluster \
  -o "socket.ssl=true;socket.ssl_key=/etc/ssl/galera/server-key.pem;socket.ssl_cert=/etc/ssl/galera/server-cert.pem;socket.ssl_ca=/etc/ssl/galera/ca-cert.pem;socket.ssl_cipher=AES256-SHA256" \
  -l /var/log/garbd.log

# Проверка
pgrep -a garbd
# → 12345 garbd -a gcomm://...
```

```ini
# Альтернатива: конфигурационный файл (Debian: /etc/default/garb, RHEL: /etc/sysconfig/garb)
daemon=1
address="gcomm://10.0.5.20,10.0.5.21,10.0.5.22"
group="my_cluster"
options="gmcast.segment=1"
log="/var/log/garbd.log"
# запуск: garbd --cfg /path/to/arbitrator.config
```

**Пояснение:** garbd участвует в кворуме, но не хранит данных и не обслуживает клиентский трафик. В кластере 2 узла + garbd суммарный вес голосов = 3: при выходе garbd два узла сохраняют кворум (2 из 3), но потеря ещё одного узла — уже нет. garbd может только присоединиться к существующему кластеру — bootstrap через garbd невозможен. **Если garbd запускается с TLS, обязательно указать `socket.ssl_cipher`**, иначе контекст SSL не инициализируется (`gu::NotSet`).

### Сценарий 5: Защита gcache

```ini
# gcache.size и gcache.page_size — опции провайдера,
# задаются только через wsrep_provider_options
[galera]
wsrep_provider_options = "gcache.size=1G; \
gcache.page_size=128M; \
gcache.name=/var/lib/mysql-galera/galera.cache; \
gcache.recover=yes"
```

```bash
# Права на gcache и состояние кластера
ls -la /var/lib/mysql/galera.cache /var/lib/mysql/grastate.dat
# → -rw-r----- mysql mysql
```

**Пояснения:**
- `gcache.size` — размер кольцевого буфера write-set'ов (по умолчанию 128M). Чем больше, тем выше шанс, что переподключившийся узел получит IST вместо полного SST.
- `gcache.name` — вынести буфер на отдельный диск/раздел можно, изменив путь; файлы страниц имеют префикс `gcache.page`.
- `gcache.recover=yes` — восстановление gcache при старте: узел может отдавать IST после перезапуска всего кластера.
- **Enterprise:** gcache можно зашифровать на диске (DARE) через `encrypt_binlog=ON` — переменная управляет шифрованием binlog, relay log и GCache.

## Проверка и валидация

### Проверка шифрования SST

```bash
# Захват трафика во время SST (тестовая среда)
sudo tcpdump -i eth0 -nn port 4444 -A | head -20
# → при шифровании: бинарный мусор, не читаемые данные
# → без шифрования: видны SQL/данные
```

### Проверка allowlist

```sql
SELECT * FROM mysql.wsrep_allowlist;
-- → только доверенные IP
```

### Проверка кворума и членства

```sql
SHOW STATUS LIKE 'wsrep_cluster_status';
-- → wsrep_cluster_status = Primary
SHOW STATUS LIKE 'wsrep_cluster_size';
-- → wsrep_cluster_size = 3
SHOW STATUS LIKE 'wsrep_incoming_addresses';
-- → адреса всех узлов кластера
SHOW STATUS LIKE 'wsrep_ready';
-- → wsrep_ready = ON
```

```bash
# Порты Galera слушаются на всех узлах
ss -tnlp | grep -E ':(3306|4567|4568|4444)\b'
```

## Устранение неполадок

### SST не шифруется

**Причина:** секция `[sst]` не прочитана, `use-extra=1` не задан (для `encrypt=AES256`), `encrypt-key-file` недоступен пользователю `mysql`, или `[sst] ssl_mode` установлен в `DISABLED`.

**Диагностика:**
```bash
sudo tail -50 /var/log/mysql/error.log | grep -i sst
# → проверьте ошибки чтения ключа
ls -la /etc/mysql/galera/sst.key
# → -rw------- mysql mysql
# Логи самого SST (donor: backup, joiner: prepare/move)
ls -la /var/lib/mysql/mariadb-backup.*.log
```

**Решение:** проверьте синтаксис `[sst]` секции, `use-extra=1` и права на ключевой файл.

### SST не стартует: «socat not found»

**Причина:** не установлен `socat` — обязательная зависимость метода `mariabackup` на доноре и joiner'е (в RHEL/CentOS — из EPEL).

**Диагностика:** в error log: `WSREP_SST: [ERROR] socat not found in path: ...`.

**Решение:** `sudo apt install socat` / `sudo yum install epel-release socat` на всех узлах.

### Узел не может присоединиться

**Причина:** IP отсутствует в `wsrep_allowlist`, закрыты порты 4567/4568/4444, или несовпадает метод SST (`wsrep_sst_method` должен быть одинаковым на доноре и joiner'е).

**Решение:** добавьте IP в allowlist (`INSERT INTO mysql.wsrep_allowlist(ip) VALUES('...')`), проверьте сетевую доступность портов и единообразие `wsrep_sst_method`.

### Split-brain после потери связи

**Причина:** потеря кворума при чётном числе узлов.

**Решение:** используйте нечётное число узлов или garbd. При восстановлении после разделения сети — выберите одну сторону раздела и на одном её узле выполните:

```sql
SET GLOBAL wsrep_provider_options='pc.bootstrap=true';
```

Никогда не форсируйте перезапуск всех узлов одновременно без понимания состояния кворума: при полном обесточивании безопасный bootstrap — через `mariadbd --wsrep-new-cluster` на узле с актуальным `grastate.dat` (`safe_to_bootstrap: 1`).

## Лучшие практики

1. **Шифруйте SST.** По умолчанию SST передаёт полные данные открытым текстом — это главный риск Galera.
2. **Сегментируйте трафик.** Репликация и SST — в отдельной VLAN, недоступной извне.
3. **`wsrep_allowlist`.** Белый список IP — дешёвая защита от rogue-узлов.
4. **Аутентификация SST.** `wsrep_sst_auth` с минимальными привилегиями; на ES 11.4+ — автоматическое управление временным пользователем (без пароля в `my.cnf`).
5. **Нечётное число узлов или garbd.** Защита от split-brain.
6. **Права на gcache.** Кеш write-set'ов содержит данные — ограничьте доступ.
7. **Защищайте узел с основной записью.** Не используйте write-primary как SST-донора (SST кратковременно блокирует коммит на доноре): задайте `wsrep_sst_donor=node3,node4,` (завершающая запятая разрешает любой другой узел при недоступности предпочитаемых).
8. **Ограничивайте скорость SST.** `[sst] rlimit = 100M` — чтобы SST не насыщал сеть кластера.
9. **Следите за сертификатами (Enterprise).** `wsrep_certificate_expiration_hours_warning=72` — предупреждение в error log за 72 часа до истечения срока X.509-сертификата.

## Граничные случаи

- **Шифрование ≠ аутентификация.** Репликационный TLS (в т.ч. Enterprise `SERVER` — default в ES 10.6) шифрует трафик, но НЕ проверяет сертификат пира: узел примет любого участника TLS-хендшейка. Для требований PCI DSS / SOC 2 / ISO 27001 используйте `SERVER_X509` (Enterprise) или защиту на сетевом уровне (allowlist, VLAN).
- **`VERIFY_IDENTITY` с `mariabackup` = `VERIFY_CA`:** SST-скрипт различает только начало `VERIFY`, проверка имени хоста работает только для метода `rsync` (stunnel `verifyPeer`). При изменяющихся адресах узлов (NAT, контейнеры) под `rsync` `VERIFY_IDENTITY` потребует перевыпуска сертификатов — используйте `VERIFY_CA`.
- **garbd не может bootstrap кластера** — только присоединиться к существующему; при полном обесточивании bootstrap делает один из узлов (`--wsrep-new-cluster`).
- **garbd + TLS:** без явного `socket.ssl_cipher` SSL-контекст не инициализируется (ошибка `gu::NotSet`).
- **Ключи DARE при SST:** физические методы требуют одинаковых ключей шифрования на всех узлах (донор копирует уже зашифрованные файлы), логический `mysqldump` — нет.
- **Апгрейд мажорной версии:** `mariabackup` SST не подходит для некоторых апгрейдов мажорных версий (формат redo log изменён в 10.8, MDEV-27437) — используйте метод `rsync`.
- **IPv6:** для SST по IPv6 задайте `[sst] sockopt=",pf=ip6"`.
- **Кластер-проверка имени (Enterprise):** перед SST/IST донор сверяет `wsrep_cluster_name` присоединяющегося узла — защита от SST в «чужой» кластер.
- **Онлайн-замена сертификатов (Enterprise):** `socket.dynamic=true` + `SET GLOBAL wsrep_provider_options='socket.ssl_reload=true'` переинициализирует TLS-контекст без перезапуска (файлы должны лежать по тем же путям).

## Дополнительная информация

### Ограничения

- `wsrep_ssl_mode` (`PROVIDER`/`SERVER`/`SERVER_X509`) и `[sst] ssl_mode` (`DISABLED`/`REQUIRED`/`VERIFY_CA`/`VERIFY_IDENTITY`) — только MariaDB Enterprise Server 10.6+; Community использует `wsrep_provider_options` (`socket.ssl*`) и `[sst]` (`encrypt`, `tcert`/`tkey`/`tca`).
- `[sst] ssl_mode` поддерживают только методы `mariabackup` и `rsync`; `rsync` с TLS требует `stunnel` (ES 12.3.3-0 Beta не устанавливает его автоматически); `mysqldump` игнорирует `[sst] ssl_mode` — его TLS настраивается через `[client]`/`[mariadb-dump]` (`ssl-ca`, `ssl-cert`, `ssl-key`, `ssl-verify-server-cert`).
- Шифрование SST добавляет задержку при больших базах; измерьте на staging.
- Опции `socket.ssl*` не динамические — изменение требует перезапуска узла (в Enterprise сертификаты можно перезагрузить онлайн через `socket.ssl_reload`, см. «Граничные случаи»).
- `wsrep_provider_options` ограничен 2048 символами — при большом числе опций включите `plugin-wsrep-provider=ON` (MariaDB 11.4+, встроен, но выключен по умолчанию): опции становятся отдельными переменными `wsrep_provider_<имя>`.
- Шифрование gcache на диске — Enterprise-фича (`encrypt_binlog=ON`).

### Смежные темы

- **[Высокая доступность](../high_availability.md)** — операции Galera, кворум, garbd.
- **[SSL/TLS](ssl-tls.md)** — TLS-конфигурация.
- **[Сетевая безопасность](network-security.md)** — сегментация.
- **[TDE](tde.md)** — шифрование данных на диске (DARE).
- **[Мониторинг безопасности](security-monitoring.md)** — мониторинг кластера.
- **[Zero-Downtime Upgrade](../Operations/zero_downtime_upgrade.md)** — апгрейд Galera-кластера.
