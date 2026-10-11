# SSL/TLS в MariaDB: шифрование трафика

**Актуально для:** MariaDB 10.6 / 10.11 / 11.2 / 11.4

## Определения

**SSL/TLS (Secure Sockets Layer / Transport Layer Security)** — криптографические протоколы для защиты трафика между клиентом и сервером. Обеспечивают шифрование данных, проверку подлинности сторон и целостность сообщений.

**mTLS (mutual TLS)** — режим взаимной аутентификации, при котором сервер проверяет клиентский сертификат, а клиент — серверный. В MariaDB включается через `REQUIRE X509` на уровне учётной записи.

**CA (Certificate Authority)** — центр сертификации, который подписывает сертификаты. В MariaDB может быть публичным (Let's Encrypt) или внутренним (self-signed или корпоративный).

**CRL (Certificate Revocation List)** — список отозванных сертификатов. В MariaDB задаётся переменной `ssl_crl` и проверяется при установке TLS-соединения (только при сборке с OpenSSL).

**Cipher suite** — набор алгоритмов шифрования для одной TLS-сессии (например, `TLS_AES_256_GCM_SHA384`).

**require_secure_transport** — глобальная переменная MariaDB, которая запрещает незашифрованные подключения на весь инстанс.

**REQUIRE SSL / REQUIRE X509** — ограничения на уровне пользователя. `REQUIRE SSL` требует наличия TLS-соединения; `REQUIRE X509` дополнительно требует предъявления валидного клиентского сертификата.

## Основные концепции

### Зачем шифровать трафик MariaDB

Даже внутри доверенной сети незашифрованный трафик уязвим к пассивному прослушиванию (`tcpdump`, зеркалирование портов), ARP spoofing и компрометации узла. TLS шифрует весь MySQL-протокол: учётные данные, запросы, результаты и метаданные.

### Как работает TLS в MariaDB

1. **Рукопожатие (handshake):** клиент отправляет `ClientHello` с поддерживаемыми версиями TLS и cipher suites.
2. **Выбор параметров:** сервер отвечает `ServerHello`, выбирая версию и cipher suite из пересечения поддерживаемых сторонами.
3. **Аутентификация сервера:** сервер передаёт сертификат (`ssl_cert`) и цепочку CA. Клиент проверяет подпись по `ssl_ca`.
4. **Аутентификация клиента (опционально, mTLS):** сервер запрашивает клиентский сертификат и проверяет его по `ssl_ca` и опционально `ssl_crl`.
5. **Генерация ключей:** стороны вырабатывают симметричный сессионный ключ.
6. **Шифрование трафика:** все последующие пакеты MariaDB-протокола шифруются сессионным ключом.

### Уровни принудительного шифрования

| Уровень | Механизм | Область действия | Примечание |
| :--- | :--- | :--- | :--- |
| **Глобальный** | `require_secure_transport = ON` | Весь инстанс | Блокирует любые незашифрованные подключения. |
| **Уровень пользователя** | `REQUIRE SSL` / `REQUIRE X509` | Конкретная учётная запись | Позволяет смешивать зашифрованные и незашифрованные учётные записи. |
| **Уровень репликации** | `MASTER_SSL=1` + пути к сертификатам | Соединение источник → реплика | Требует отдельной конфигурации на реплике. Подробнее: [Сценарий 5: Настройка с SSL/TLS](../replication/setup_guide.md#сценарий-5-настройка-с-ssltls). |
| **Сетевой** | Файрвол + `bind-address` | Сеть | Не шифрует трафик, но ограничивает поверхность атаки. См. [Сетевая безопасность](network-security.md). |

## Предварительные требования

### Окружение

- MariaDB 10.6, 10.11, 11.2 или 11.4 (LTS-версии предпочтительны), собранная с OpenSSL.
- ОС: RHEL/CentOS 8+, Debian 11+, Ubuntu 20.04+ или эквивалент.
- Права суперпользователя (`root` или `sudo`).
- OpenSSL 1.1.1+ или 3.x для генерации сертификатов.
- Доступ к файрволу хоста для ограничения порта 3306/TCP.

### Инструменты и знания

- Понимание модели PKI: CA, CSR, сертификаты, приватные ключи, цепочки доверия.
- Навыки работы с `my.cnf` и динамическими переменными MariaDB.
- Знакомство с `mariadb-secure-installation` и базовой закалкой (см. [Начальная закалка](hardening.md)).
- Доступ к SIEM-системе для сбора аудит-логов (см. [Аудит](audit.md)).

## Пошаговые инструкции

### Шаг 1: Подготовка директорий и прав

```bash
mkdir -p /etc/mysql/ssl
chmod 700 /etc/mysql/ssl
chown mysql:mysql /etc/mysql/ssl
```

На **RHEL/CentOS** с SELinux:

```bash
semanage fcontext -a -t mysqld_etc_t "/etc/mysql/ssl(/.*)?"
restorecon -Rv /etc/mysql/ssl
```

На **Debian/Ubuntu** с AppArmor убедитесь, что профиль `/etc/apparmor.d/usr.sbin.mysqld` разрешает чтение `/etc/mysql/ssl/** r,`. После изменения профиля примените его:

```bash
apparmor_parser -r /etc/apparmor.d/usr.sbin.mysqld
```

### Шаг 2: Генерация CA, серверного и клиентского сертификатов

#### Вариант A: Внутренний self-signed CA

```bash
cd /etc/mysql/ssl

# 1. Создание CA
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out ca-key.pem
chmod 600 ca-key.pem
openssl req -new -x509 -nodes -days 3650 -key ca-key.pem -out ca.pem \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example Corp/OU=IT/CN=Example CA"

# 2. Создание ключа и запроса сервера
openssl req -newkey rsa:4096 -nodes -keyout server-key.pem -out server-req.pem \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example Corp/OU=IT/CN=db01.example.com"
openssl rsa -in server-key.pem -out server-key.pem
openssl x509 -req -in server-req.pem -days 3650 -CA ca.pem -CAkey ca-key.pem \
  -set_serial 01 -out server-cert.pem

# 3. Создание клиентского сертификата (для mTLS / REQUIRE X509 / репликации)
openssl req -newkey rsa:4096 -nodes -keyout client-key.pem -out client-req.pem \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example Corp/OU=IT/CN=mariadb-client"
openssl rsa -in client-key.pem -out client-key.pem
openssl x509 -req -in client-req.pem -days 3650 -CA ca.pem -CAkey ca-key.pem \
  -set_serial 02 -out client-cert.pem

# 4. Проверка цепочки
openssl verify -CAfile ca.pem server-cert.pem client-cert.pem
# → server-cert.pem: OK
# → client-cert.pem: OK

# 5. Установка прав
chmod 600 *.pem
chown mysql:mysql server-key.pem client-key.pem
```

> **Примечание:** Для совместимости со старыми клиентами допускается RSA 2048. Для новых сред используйте RSA 4096 или ECC P-384. Приватный ключ никогда не должен читаться другими пользователями: `chmod 600`.

#### Вариант B: Корпоративный CA

Если в организации есть корпоративный CA, используйте его для подписи CSR. Преимущества: единая точка отзыва, интеграция с Active Directory/PKI, централизованный мониторинг сроков действия.

```bash
# Генерация CSR на сервере
openssl req -newkey rsa:4096 -nodes -keyout server-key.pem -out server-req.pem \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example Corp/OU=IT/CN=db01.example.com"

# Отправьте server-req.pem в корпоративный PKI-портал и получите подписанный сертификат.
# Сохраните его как server-cert.pem вместе с промежуточными сертификатами.
```

### Шаг 3: Настройка сервера (`my.cnf`)

```ini
[mariadb]
# Пути к файлам сертификатов (абсолютные пути обязательны)
ssl_ca   = /etc/mysql/ssl/ca.pem
ssl_cert = /etc/mysql/ssl/server-cert.pem
ssl_key  = /etc/mysql/ssl/server-key.pem

# Запрет незашифрованных соединений (глобально)
require_secure_transport = ON

# Использование современных версий TLS
tls_version = TLSv1.2,TLSv1.3

# Опционально: ограничение списка cipher suites на стороне сервера
# ssl_cipher = ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305
```

> **Важно:** `require_secure_transport` не даст запуститься серверу, если указанные файлы сертификатов отсутствуют или нечитаемы. Убедитесь в корректности путей и прав доступа перед перезапуском.

### Шаг 4: Привязка требований к учётным записям

```sql
-- Требование SSL для существующего пользователя
ALTER USER 'app_user'@'%' REQUIRE SSL;

-- Требование X509 (проверка валидности клиентского сертификата — mTLS)
ALTER USER 'admin_user'@'%' REQUIRE X509;

-- Для репликации через TLS (выполняется на источнике)
CREATE USER 'repl_ssl'@'192.168.1.%' IDENTIFIED BY 'StrongPassword123'
    REQUIRE SSL;
GRANT REPLICATION SLAVE ON *.* TO 'repl_ssl'@'192.168.1.%';
```

### Шаг 5: Перезапуск и базовая проверка

```bash
# Проверка конфигурации (если доступно)
mariadbd --validate-config --defaults-file=/etc/mysql/my.cnf

# Перезапуск
systemctl restart mariadb

# Проверка статуса
systemctl status mariadb
# → active (running)
```

## Верификация TLS-соединения

### Проверка переменных сервера

```sql
-- Поддержка TLS скомпилирована?
SHOW VARIABLES LIKE 'have_ssl';
-- → have_ssl | YES

-- Глобальное требование TLS?
SHOW VARIABLES LIKE 'require_secure_transport';
-- → require_secure_transport | ON

-- Пути к сертификатам и версии TLS
SHOW VARIABLES LIKE 'ssl%';
-- → ssl_ca   | /etc/mysql/ssl/ca.pem
-- → ssl_cert | /etc/mysql/ssl/server-cert.pem
-- → ssl_key  | /etc/mysql/ssl/server-key.pem
-- → tls_version | TLSv1.2,TLSv1.3
```

### Проверка активных соединений

```sql
-- Какие соединения используют шифрование
SELECT USER, HOST, DB, SSL_TYPE, SSL_CIPHER
FROM information_schema.PROCESSLIST
WHERE SSL_TYPE IS NOT NULL AND SSL_TYPE != '';
```

### Проверка через CLI-клиент

```bash
# Подключение с проверкой CA
mariadb --ssl --ssl-ca=/etc/mysql/ssl/ca.pem \
  -e "SHOW STATUS LIKE 'Ssl_cipher'; SHOW STATUS LIKE 'Ssl_version';"
# → Ssl_cipher | TLS_AES_256_GCM_SHA384
# → Ssl_version | TLSv1.3

# Подключение с клиентским сертификатом (mTLS)
mariadb --ssl --ssl-ca=/etc/mysql/ssl/ca.pem \
  --ssl-cert=/etc/mysql/ssl/client-cert.pem \
  --ssl-key=/etc/mysql/ssl/client-key.pem \
  -e "SELECT USER(), CURRENT_USER();"
```

### Внешняя проверка через OpenSSL

```bash
# Проверка сертификата сервера и цепочки
openssl s_client -connect 10.0.5.20:3306 -servername db01.example.com \
  -CAfile /etc/mysql/ssl/ca.pem
# → Verify return code: 0 (ok)
# → SSL-Session: Protocol : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
```

## CRL (Certificate Revocation List)

Если приватный ключ клиента скомпрометирован, его сертификат нужно отозвать через CRL. MariaDB проверяет CRL только при сборке с OpenSSL.

### Создание CRL

```bash
cd /etc/mysql/ssl

# Минимальный openssl.cnf для работы ca-команд
cat > openssl.cnf <<'EOF'
[ ca ]
default_ca = CA_default

[ CA_default ]
dir               = .
certs             = $dir
crl_dir           = $dir
database          = $dir/index.txt
new_certs_dir     = $dir
certificate       = $dir/ca.pem
serial            = $dir/serial
crl               = $dir/ca.crl.pem
private_key       = $dir/ca-key.pem
name_opt          = default_ca
cert_opt          = default_ca
default_days      = 3650
default_crl_days  = 30
default_md        = sha256
preserve          = no
policy            = policy_anything

[ policy_anything ]
countryName             = optional
stateOrProvinceName     = optional
localityName            = optional
organizationName        = optional
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional
EOF

# Файл индекса и серийных номеров (если отсутствуют)
touch index.txt
echo 01 > serial

# Отзыв клиентского сертификата (серийный номер 02)
openssl ca -revoke client-cert.pem -config openssl.cnf -keyfile ca-key.pem -cert ca.pem

# Генерация CRL
openssl ca -gencrl -config openssl.cnf -keyfile ca-key.pem -cert ca.pem -out ca.crl.pem

# Проверка содержимого CRL
openssl crl -in ca.crl.pem -noout -text
```

### Настройка сервера для использования CRL

```ini
[mariadb]
ssl_crl = /etc/mysql/ssl/ca.crl.pem
```

> **Важно:** `ssl_crl` — глобальная нединамическая переменная. После изменения CRL требуется **перезапуск** сервера MariaDB. Настройте крон-задачу для регулярной регенерации CRL и перезапуска, либо используйте MaxScale как промежуточный прокси с поддержкой динамического обновления CRL без перезапуска backend-серверов. См. [MaxScale: безопасность и шифрование](../MaxScale/maxscale_overview.md#безопасность-и-шифрование).

### Проверка отзыва

После добавления `ssl_crl` в конфигурацию и перезапуска сервера, попытка подключения отозванным сертификатом будет отклонена:

```bash
mariadb --ssl --ssl-ca=/etc/mysql/ssl/ca.pem \
  --ssl-cert=/etc/mysql/ssl/client-cert.pem \
  --ssl-key=/etc/mysql/ssl/client-key.pem \
  -e "SELECT 1;"
# → ERROR 2026 (HY000): SSL connection error: certificate revoked
```

## Автоматизация жизненного цикла сертификатов

Ручная ротация сертификатов — частая причина инцидентов: просроченный сертификат блокирует все TLS-соединения. Автоматизируйте выпуск, мониторинг срока и ротацию.

### Мониторинг срока действия

```bash
# Дней до истечения сертификата сервера
END=$(openssl x509 -in /etc/mysql/ssl/server-cert.pem -noout -enddate | cut -d= -f2)
echo $(( ($(date -d "$END" +%s) - $(date +%s)) / 86400 ))" days left"
# → 89 days left

# Проверка через сеть (как видит клиент)
echo | openssl s_client -connect 10.0.5.20:3306 -servername db01.example.com 2>/dev/null | \
  openssl x509 -noout -enddate
# → notAfter=Dec 31 23:59:59 2026 GMT
```

Алерт: при остатке < 30 дней — уведомление; < 7 дней — критический алерт. Интеграция с Prometheus/Alertmanager см. в [Мониторинг безопасности](security-monitoring.md).

### Автоматический выпуск (Let's Encrypt / ACME)

Для публично доступных инстансов (или через DNS-01 challenge для внутренних):

```bash
# Выпуск через certbot (DNS-01 для внутренних CA/доменов)
sudo certbot certonly --manual --preferred-challenges dns \
  -d db01.example.com --server https://acme-v02.api.letsencrypt.org/directory

# Копирование в директорию MariaDB
sudo cp /etc/letsencrypt/live/db01.example.com/fullchain.pem /etc/mysql/ssl/server-cert.pem
sudo cp /etc/letsencrypt/live/db01.example.com/privkey.pem /etc/mysql/ssl/server-key.pem
sudo chown mysql:mysql /etc/mysql/ssl/server-key.pem
sudo chmod 600 /etc/mysql/ssl/server-key.pem
```

**Пояснения:**
- Для внутренних инстансов без публичного DNS используйте DNS-01 challenge или внутренний CA (step-ca, Smallstep).
- Let's Encrypt выдаёт сертификаты на 90 дней — автоматическая ротация обязательна.

### Zero-downtime ротация сертификатов

MariaDB читает сертификаты при старте; для ротации без разрыва соединений:

```bash
# 1. Выпустить новый сертификат (параллельно со старым)
# 2. Разместить новый сертификат
sudo cp new-server-cert.pem /etc/mysql/ssl/server-cert.pem
sudo cp new-server-key.pem /etc/mysql/ssl/server-key.pem
sudo chown mysql:mysql /etc/mysql/ssl/server-key.pem
sudo chmod 600 /etc/mysql/ssl/server-key.pem

# 3. Перезапуск (кратковременный разрыв; соединения переподключаются)
sudo systemctl restart mariadb

# 4. Проверка
mariadb --ssl --ssl-ca=/etc/mysql/ssl/ca.pem -e "SHOW STATUS LIKE 'Ssl_cipher';"
# → Ssl_cipher | TLS_AES_256_GCM_SHA384
```

**Пояснения:**
- Перезапуск необходим, так как `ssl_cert`/`ssl_key` — нединамические переменные.
- Для сред, где перезапуск неприемлем, используйте MaxScale как TLS-терминатор: ротация на MaxScale не требует перезапуска backend-серверов. См. [MaxScale: безопасность и шифрование](../MaxScale/maxscale_overview.md#безопасность-и-шифрование).
- При использовании `REQUIRE X509` (mTLS) ротация клиентских сертификатов требует согласованного окна: старые и новые сертификаты должны быть валидны одновременно.

### Ansible-автоматизация

```yaml
- name: Проверить срок сертификата
  ansible.builtin.command: >
    openssl x509 -in /etc/mysql/ssl/server-cert.pem -noout -enddate
  register: cert_end
  changed_when: false

- name: Алерт при истечении < 30 дней
  ansible.builtin.assert:
    that:
      - (cert_end.stdout | regex_replace('notAfter=', '') | to_datetime('%b %d %H:%M:%S %Y %Z') - ansible_date_time.epoch | int).days > 30
    fail_msg: "Сертификат MariaDB истекает менее чем через 30 дней"
```

## Типичные ошибки и устранение неполадок

### Ошибка: `ERROR 2026 (HY000): SSL connection error: Unable to get certificate`

**Симптом:** клиент не может установить TLS-соединение.

**Причины и решения:**
- `ssl_key` или `ssl_cert` не существуют или имеют неверные права.
  - Проверка: `ls -l /etc/mysql/ssl/server*.pem`
  - Решение: `chown mysql:mysql /etc/mysql/ssl/server-key.pem && chmod 600 /etc/mysql/ssl/server-key.pem`
- SELinux блокирует чтение файлов сертификатов процессом `mysqld`.
  - Проверка: `ausearch -m avc -ts recent | grep mysqld`
  - Решение: `semanage fcontext -a -t mysqld_etc_t "/etc/mysql/ssl(/.*)?" && restorecon -Rv /etc/mysql/ssl`
- Сертификат просрочен.
  - Проверка: `openssl x509 -in /etc/mysql/ssl/server-cert.pem -noout -dates`

### Ошибка: `ERROR 2026 (HY000): SSL connection error: Unable to get issuer certificate`

**Симптом:** клиент не может проверить цепочку сертификатов.

**Причина:** `ssl_ca` не указан, путь неверен, или промежуточный сертификат отсутствует в цепочке.

**Решение:**
```bash
# Проверка цепочки
openssl verify -CAfile /etc/mysql/ssl/ca.pem /etc/mysql/ssl/server-cert.pem
# Убедитесь, что сертификат сервера подписан именно этим CA.
```

### Ошибка: `ERROR 2026 (HY000): SSL connection error: certificate verify failed`

**Симптом:** имя хоста в сертификате не совпадает с именем, к которому подключается клиент.

**Решение:**
- Убедитесь, что поле `CN` или Subject Alternative Name в сертификате совпадает с хостом подключения.
- Используйте `--ssl-verify-server-cert` на клиенте или явно передавайте `--ssl-ca`.

### Ошибка: `Got an error reading communication packet`

**Симптом:** соединение обрывается после включения TLS.

**Причина:** несовпадение версий TLS или cipher suites между клиентом и сервером.

**Решение:**
```sql
-- Проверка поддерживаемых версий
SHOW VARIABLES LIKE 'tls_version';
-- Проверка поддерживаемых cipher suites
SHOW VARIABLES LIKE 'ssl_cipher';
-- Обновите драйвер MariaDB/MySQL на клиенте.
```

### Ошибка: `ERROR 2026 (HY000): SSL connection error: tlsv1 alert internal error`

**Симптом:** handshake завершается с внутренней ошибкой.

**Решение:**
- Убедитесь, что клиент поддерживает `TLSv1.2` или `TLSv1.3`.
- Проверьте, не запрещён ли нужный cipher suite на стороне сервера (`ssl_cipher`).
- На стороне сервера проверьте ошибки в журнале: `journalctl -u mariadb --since "5 minutes ago"`.

### Ошибка: `require_secure_transport` блокирует легитимные подключения

**Симптом:** после включения `require_secure_transport = ON` старые приложения теряют доступ.

**Решение:**
1. Проверьте, какие пользователи не имеют `REQUIRE SSL`:
   ```sql
   SELECT User, Host, ssl_type FROM mysql.user WHERE ssl_type IS NULL OR ssl_type = 'None';
   ```
2. Добавьте `REQUIRE SSL` нужным пользователям.
3. Для миграции legacy-клиентов сначала включите аудит подключений:
   ```ini
   [mariadb]
   plugin_load_add = server_audit
   server_audit_events = CONNECT
   server_audit_logging = ON
   ```
   После анализа логов добавьте `REQUIRE SSL` и только затем включите `require_secure_transport`.

### Ошибка: CRL не обновляется без перезапуска

**Симптом:** после отзыва сертификата клиент по-прежнему подключается.

**Решение:** `ssl_crl` является нединамической переменной. Перегенерируйте CRL и перезапустите MariaDB. Для сред, где перезапуск неприемлем, используйте MaxScale как промежуточный прокси с поддержкой динамического обновления CRL без перезапуска backend-серверов (см. [MaxScale: безопасность и шифрование](../MaxScale/maxscale_overview.md#безопасность-и-шифрование)).

## Лучшие практики

1. **Минимум TLS 1.2.** Запретите TLS 1.0 и 1.1 через `tls_version = TLSv1.2,TLSv1.3`. TLS 1.3 предпочтительнее, если все клиенты его поддерживают.
2. **Длина ключей.** RSA ≥ 4096 бит или ECC P-384/P-256. RSA 2048bit — минимальный порог для совместимости.
3. **Срок действия сертификатов.** Для внутренних CA — не более 1–2 лет. Настройте автоматическую ротацию за 30 дней до истечения срока.
4. **Права на файлы.** Ключи (`server-key.pem`, `client-key.pem`) — `600`, владелец `mysql:mysql`. CA и сертификаты — `644`, владелец `root:root`.
5. **mTLS для критичных учётных записей.** Используйте `REQUIRE X509` для администраторов и сервисных учётных записей репликации. Это защищает от кражи пароля.
6. **Аудит подключений.** Включите `server_audit_events = CONNECT` для фиксации факта шифрования каждого подключения. См. [Аудит](audit.md).
7. **Сетевой контроль + TLS.** TLS не заменяет файрвол. Ограничьте порт 3306 только доверенными подсетями. См. [Сетевая безопасность](network-security.md).
8. **Криптографическое разделение.** Храните CA-ключ и ключи табличных пространств TDE на разных носителях. См. [Шифрование данных (TDE)](tde.md).
9. **Диагностика после изменений.** После обновления сертификатов проверяйте `SHOW STATUS LIKE 'Ssl_cipher';` и тестируйте подключение через `openssl s_client`.
10. **Не дублируйте TLS для локальных соединений.** Unix socket-соединения считаются безопасными и не требуют TLS.
11. **Ротация сертификатов.** Планируйте ротацию до истечения срока действия. Используйте промежуточные CA, чтобы минимизировать риск компрометации корневого ключа.

## Дополнительная информация

### См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation` и первичная накалка.
- **[Аутентификация](authentication.md)** — плагины аутентификации и политика паролей.
- **[Сетевая безопасность](network-security.md)** — `bind-address`, файрвол, защита от DoS.
- **[Аудит](audit.md)** — `server_audit`, комплаенс, интеграция с SIEM.
- **[Шифрование данных (TDE)](tde.md)** — шифрование табличных пространств и ключевое управление.
- **[Ролевая модель (RBAC)](rbac.md)** — создание ролей, гранулярные привилегии.
- **[Бинарное логирование](binary-logging.md)** — forensic, ротация, шифрование бинарных логов.
- **[Сценарий 5: Настройка с SSL/TLS](../replication/setup_guide.md#сценарий-5-настройка-с-ssltls)** — репликация через TLS.
- **[MaxScale: безопасность и шифрование](../MaxScale/maxscale_overview.md#безопасность-и-шифрование)** — TLS на уровне прокси.

### Смежные темы

- **[Обзор MariaDB](../overview.md)** — архитектура и стратегия развития.
- **[Конфигурация MariaDB](../configuration.md)** — `my.cnf`, иерархия загрузки.
- **[Установка MariaDB](../installation_and_setup.md)** — установка и начальная закалка.
- **[SQL Injection](../../../Security/ApplicationSecurity/sql_injection.md)** — защита от внедрения SQL.
- **[HashiCorp Vault](../../../Vault/overview.md)** — управление ключами шифрования.
- **[Шифрование данных в покое](../../Concepts/encryption_at_rest.md)** — теория TDE, DEK/KEK, Envelope Encryption.
- **[Безопасная установка СУБД](../../installation_security.md)** — общие принципы закалки.
