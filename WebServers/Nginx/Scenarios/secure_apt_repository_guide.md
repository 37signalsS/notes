# Создание защищённого APT-репозитория с Nginx и mTLS

## Определения

**Защищённый APT-репозиторий** — хранилище пакетов Debian/Ubuntu, доступ к которому ограничен на транспортном уровне (L4/L7) и разрешён только аутентифицированным клиентам с валидными сертификатами.

**mTLS (Mutual TLS)** — механизм взаимной проверки подлинности, при котором и сервер, и клиент предъявляют SSL/TLS-сертификаты. Это исключает несанкционированный доступ даже при знании URL-адреса репозитория. Подробнее: **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**.

**reprepro** — специализированный инструмент командной строки для управления локальными репозиториями пакетов `.deb`. Он генерирует статическую структуру индексов (`Packages`, `Sources`, `Release`), что позволяет использовать любой веб-сервер для раздачи. Детальное описание управления пакетами: **[Практические сценарии reprepro](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)**.

**GPG-подпись (GNU Privacy Guard)** — механизм обеспечения целостности и подлинности пакетов. В отличие от mTLS (защищающего доступ), GPG гарантирует, что содержимое репозитория не было изменено третьей стороной.

**CRL (Certificate Revocation List)** — список отозванных серийных номеров сертификатов. Используется для блокировки доступа скомпрометированных клиентов без изменения глобальной конфигурации.

**EKU (Extended Key Usage)** — расширение X.509 v3, указывающее назначение сертификата. Для клиентских сертификатов обязательно наличие OID `1.3.6.1.5.5.7.3.2` (Client Authentication).

---

## Базовые концепции

### Архитектура эшелонированной защиты

Сценарий реализует принцип «Defense in Depth» для распространения внутреннего ПО на bare metal-серверах:

1. **Сетевой уровень (mTLS):** Nginx блокирует любые запросы без клиентского сертификата, подписанного доверенным CA.
2. **Уровень аутентификации:** Проверка серийного номера или Common Name (CN) сертификата клиента через переменные `$ssl_client_s_dn_cn` или `$ssl_client_serial`.
3. **Уровень целостности (GPG):** Клиент `apt` проверяет подпись файла `Release`, подтверждая, что пакеты получены от доверенного владельца репозитория.
4. **Уровень изоляции:** Использование `reprepro` для разделения кодовых имен (codenames) и архитектур (`amd64`, `arm64`), а также блокировка доступа к служебным директориям (`conf/`, `dbs/`).

### Жизненный цикл сертификатов

На bare metal-инфраструктуре жизненный цикл mTLS-инфраструктуры включает:

1. **Развертывание PKI** — создание двухуровневой иерархии (Root CA offline, Intermediate CA online).
2. **Выпуск сертификатов** — выпуск сертификата сервера репозитория и индивидуальных клиентских сертификатов.
3. **Настройка Nginx** — конфигурация mTLS, CRL, логирования.
4. **Настройка клиентов** — распространение CA-корня и клиентских сертификатов.
5. **Эксплуатация** — мониторинг срока действия, ротация, обработка отзыва.
6. **Деcommissioning** — безопасное удаление репозитория и отзыв сертификатов.

### Принципы безопасности

- **Private CA:** Публичные CA (Let's Encrypt) не выпускают клиентские сертификаты с EKU Client Auth. Используется внутренний CA.
- **Иерархия:** Root CA хранится offline. Intermediate CA используется для повседневных операций.
- **Цепочка доверия:** `ssl_client_certificate` должен содержать Intermediate CA + Root CA.
- **Глубина проверки:** `ssl_verify_depth` установлен не менее `2` при использовании Intermediate CA.

---

## Практические сценарии

### Предварительные требования

#### Аппаратные и программные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **ОС** | Debian 12 (Bookworm), Ubuntu 22.04/24.04 (Jammy/Noble) | Другие дистрибутивы на основе Debian также поддерживаются |
| **Пакеты** | `nginx` (≥ 1.27), `reprepro` (≥ 5.4), `gnupg` (≥ 2.2), `curl`, `openssl` | `gnupg2` на Ubuntu 22.04+ |
| **Права доступа** | root или пользователь с правами sudo | Для управления Nginx и системными директориями |
| **Энтропия** | ≥ 1000 бит в `/proc/sys/kernel/random/entropy_avail` | На виртуальных машинах без `haveged` генерация ключей может зависнуть |
| **Файловая система** | ext4 или xfs с поддержкой hardlinks | Не рекомендуется размещать `dbs/` на NFS из-за файловых блокировок BDB |

#### Начальное состояние системы

```bash
# Обновление индексов и установка зависимостей
sudo apt-get update && sudo apt-get install -y nginx reprepro gnupg2 curl openssl haveged

# Включение и запуск haveged (рекомендуется на виртуальных машинах)
sudo systemctl enable --now haveged

# Проверка энтропии
cat /proc/sys/kernel/random/entropy_avail
# → 3000+ (норма)
```

### Сценарий 1: Подготовка инфраструктуры PKI

Для mTLS требуется собственный центр сертификации. Использование публичных CA (Let's Encrypt) для аутентификации клиентов не рекомендуется из-за сложности контроля выпуска.

**Необходимые компоненты:**
- `ca.crt`: Корневой сертификат вашего CA (Intermediate + Root в одном файле).
- `server.crt / server.key`: Сертификат сервера репозитория.
- `client.crt / client.key`: Индивидуальные ключи для каждой клиентской машины или группы.
- `crl.pem`: Список отозванных сертификатов.

> **Инструкции по созданию:** **[Двухуровневый CA на OpenSSL](../../../Security/Tools/openssl_ca/two_tier/overview.md)**.

### Сценарий 2: Конфигурация Nginx (1.27+ bare metal)

Настройка разделяет публичную зону (для GPG-ключа) и защищённую зону (для пакетов). В production используется bare metal-развёртывание с systemd.

```nginx
# Глобальный формат логирования
log_format mtls_repo '$remote_addr - $ssl_client_s_dn_cn [$time_local] '
                     '"$request" $status $body_bytes_sent';

server {
    listen 80;
    listen [::]:80;
    server_name repo.example.com;

    root /srv/repo;

    # Публичный доступ только к открытому GPG-ключу
    location = /public.gpg {
        try_files $uri =404;
    }

    # Все остальные запросы принудительно на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name repo.example.com;

    root /srv/repo;
    access_log /var/log/nginx/repo_access.log mtls_repo;

    # TLS Сертификаты сервера
    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Настройки безопасности TLS
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    # HSTS (максимальный срок — 2 года)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    # mTLS
    ssl_client_certificate /etc/nginx/ssl/ca.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    # CRL — критично для блокировки утерянных ключей
    ssl_crl /etc/nginx/ssl/crl.pem;

    location / {
        autoindex on;

        # Защита служебных директорий reprepro
        location ~ ^/(conf|db) {
            deny all;
            return 404;
        }
    }
}
```

**Валидация:**
```bash
# Проверка конфигурации
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезагрузка Nginx
sudo systemctl reload nginx

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://repo.example.com/public.gpg
# → 200
curl -s -o /dev/null -w "%{http_code}" http://repo.example.com/dists/noble/Release
# → 301
```

**Edge cases:**
- Если Nginx возвращает 403 на `pool/` — проверьте права доступа к файлам `.deb`. Пользователь `www-data` должен иметь права на чтение.
- При использовании SELinux добавьте контексты: `semanage fcontext -a -t httpd_sys_content_t "/srv/repo(/.*)?" && restorecon -Rv /srv/repo`.

### Сценарий 3: Настройка репозитория (reprepro)

Подробное описание установки, управления пакетами и автоматизации приведено в документе **[Практические сценарии reprepro](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)**.

Краткий пример `conf/distributions`:

```text
Origin: InternalRepo
Label: Private Packages
Codename: noble
Architectures: amd64 arm64 all source
Components: main
Description: Защищенный репозиторий для Ubuntu 24.04
SignWith: <ID_ВАШЕГО_GPG_КЛЮЧА>
```

**Валидация:**
```bash
reprepro -V -b /srv/repo check
# → Everything seems to be correct
```

### Сценарий 4: Настройка клиента APT

Клиент должен доверять GPG-ключу и CA, а также предъявлять свой сертификат.

#### Шаг 1: Добавление GPG-ключа

Современный метод (без `apt-key`):
```bash
curl -fsSL https://repo.example.com/public.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/internal-repo.gpg
```

#### Шаг 2: Настройка источника

```bash
echo "deb [signed-by=/etc/apt/keyrings/internal-repo.gpg] https://repo.example.com noble main" | \
    sudo tee /etc/apt/sources.list.d/internal-repo.list
```

#### Шаг 3: Настройка аутентификации (mTLS)

Создайте файл `/etc/apt/apt.conf.d/99internal-repo`:
```conf
Acquire::https::repo.example.com {
    SslCert "/etc/apt/ssl/client.crt";
    SslKey  "/etc/apt/ssl/client.key";
    CaInfo  "/etc/apt/ssl/ca.crt";
};
```

**Безопасность:** `sudo chmod 600 /etc/apt/ssl/client.key`.

**Валидация:**
```bash
sudo apt-get update
# → (без ошибок GPG)
apt-cache policy
# → internal-repo:
# →   500 https://repo.example.com noble/main amd64 Packages
# →   100 /var/lib/dpkg/status
```

### Сценарий 5: Развёртывание на bare metal и systemd

На production-серверах репозиторий разворачивается как системная служба с автоматическим обновлением индексов.

#### Структура директорий

```text
/srv/repo/
├── conf/
│   └── distributions
├── pool/
│   └── main/
├── dists/
├── incoming/
└── tmp/
```

#### Создание dedicated пользователя

```bash
sudo useradd -r -s /usr/sbin/nologin -m -d /srv/repo reprepro
sudo chown -R reprepro:reprepro /srv/repo
sudo chmod 0700 /srv/repo/conf
sudo chmod 0700 /srv/repo/dbs
```

#### Systemd сервис для обновления индексов

Создайте `/etc/systemd/system/repo-export.service`:
```ini
[Unit]
Description=Export reprepro indices
After=network.target

[Service]
Type=oneshot
User=reprepro
Group=reprepro
ExecStart=/usr/bin/flock -n /var/lock/reprepro.lock /usr/bin/reprepro -b /srv/repo export
```

Создайте `/etc/systemd/system/repo-export.timer`:
```ini
[Unit]
Description=Daily reprepro export

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

**Валидация:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now repo-export.timer
sudo systemctl start repo-export.service

# Проверка статуса таймера
systemctl status repo-export.timer
# → Active: active (waiting) since ...

# Проверка логов
journalctl -u repo-export.service
# → Exporting indices...
```

### Сценарий 6: Мониторинг и аудит

#### Health check скрипт

```bash
#!/bin/bash
# /usr/local/bin/repo-health-check.sh

REPO_DIR="/srv/repo"
LOG_FILE="/var/log/repo-health.log"

check_repo() {
    local exit_code=0

    if ! reprepro -V -b "$REPO_DIR" check > /dev/null 2>&1; then
        echo "$(date) CRITICAL: Repository configuration is invalid" >> "$LOG_FILE"
        exit_code=1
    fi

    if ! reprepro -b "$REPO_DIR" verify > /dev/null 2>&1; then
        echo "$(date) CRITICAL: Package integrity check failed" >> "$LOG_FILE"
        exit_code=1
    fi

    local avail=$(df -h "$REPO_DIR" | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$avail" -gt 90 ]; then
        echo "$(date) WARNING: Disk usage above 90%" >> "$LOG_FILE"
    fi

    return $exit_code
}

check_repo
exit $?
```

#### Systemd timer для health check

```ini
# /etc/systemd/system/repo-health.service
[Unit]
Description=Repository health check

[Service]
Type=oneshot
ExecStart=/usr/local/bin/repo-health-check.sh

# /etc/systemd/system/repo-health.timer
[Unit]
Description=Hourly repository health check

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

**Валидация:**
```bash
sudo systemctl enable --now repo-health.timer
sudo systemctl start repo-health.service

# Проверка
cat /var/log/repo-health.log
# → 2026-09-22 ... INFO: Repository healthy
```

---

## Операции и команды

### Управление Nginx

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| **Проверка конфигурации** | `nginx -t` | Обязательно выполнять перед применением изменений. |
| **Перезагрузка конфигурации** | `nginx -s reload` | Graceful reload, без разрыва существующих соединений. |
| **Перезапуск worker'ов** | `nginx -s reopen` | Повторное открытие лог-файлов. |
| **Остановка** | `nginx -s stop` | Быстрая остановка. |
| **Корректное завершение** | `nginx -s quit` | Ожидание завершения текущих запросов. |
| **Статус через systemd** | `systemctl status nginx` | Проверка активного статуса службы. |

### Управление PKI и сертификатами

```bash
# Просмотр деталей клиентского сертификата
openssl x509 -in client.crt -text -noout
# → Subject, Issuer, Serial, Not Before/After, X509v3 extensions

# Проверка срока действия
openssl x509 -in client.crt -noout -dates
# → notBefore=May  1 00:00:00 2026 GMT
# → notAfter=May  1 00:00:00 2027 GMT

# Проверка подписи сертификата CA
openssl verify -CAfile ca.crt client.crt
# → client.crt: OK

# Проверка соответствия ключа и сертификата
openssl x509 -noout -modulus -in client.crt | openssl md5
openssl ecparam  -noout -modulus -in client.key | openssl md5
# → хеши должны совпадать

# Проверка цепочки с промежуточным CA
openssl verify -CAfile ca.crt -untrusted intermediate.crt client.crt
# → client.crt: OK

# Генерация CSR (Certificate Signing Request)
openssl req -new -key client.key -out client.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example/OU=IT/CN=client-01"

# Подпись CSR Intermediate CA
openssl x509 -req -in client.csr -CA intermediate.crt -CAkey intermediate.key \
  -CAcreateserial -out client.crt -days 365 -sha384 \
  -extfile <(echo "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth")
```

### Управление CRL

```bash
# Генерация CRL (OpenSSL CA)
openssl ca -gencrl -config openssl.cnf -out crl.pem

# Просмотр содержимого CRL
openssl crl -in crl.pem -text -noout
# → показывает отозванные серийные номера и даты

# Конвертация CRL в DER (для некоторых приложений)
openssl crl -in crl.pem -outform DER -out crl.der
```

### Управление репозиторием (reprepro)

```bash
# Проверка синтаксиса конфигурации
reprepro -V -b /srv/repo check
# → Everything seems to be correct

# Регенерация индексов
reprepro -b /srv/repo export
# → Exporting indices...

# Проверка целостности файлов в пуле
reprepro -b /srv/repo verify

# Просмотр содержимого БД
reprepro -b /srv/repo dumpdb

# Детальный листинг пакетов
reprepro -V -b /srv/repo list noble
# → noble|main|amd64: my-app 1.0

# Добавление пакета (с блокировкой flock)
flock -n /var/lock/reprepro.lock -c "reprepro -b /srv/repo includedeb noble /tmp/package.deb"

# Удаление пакета
reprepro -b /srv/repo remove noble my-app
```

### Диагностика mTLS-соединений

```bash
# Полная проверка handshake с клиентским сертификатом
openssl s_client -connect repo.example.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -servername repo.example.com -showcerts
# → Verify return code: 0 (ok)

# Проверка через curl (удобно для скриптов)
curl -v --cert client.crt --key client.key --cacert ca.crt \
  https://repo.example.com/dists/noble/Release
# → HTTP/2 200

# Проверка отзыва через CRL
openssl verify -crl_check -CAfile ca.crt -CRLfile crl.pem client.crt
# → client.crt: OK

# Проверка статуса OCSP для сертификата
openssl ocsp -issuer intermediate.crt -cert client.crt \
  -url http://ocsp.example.com:80 -CAfile ca.crt
# → Response Status: successful (0x0)
```

### Анализ логов

```bash
# Фильтрация неудачных mTLS-аутентификаций
awk '$8 ~ /FAILED/' /var/log/nginx/repo_access.log | tail -n 20

# Проверка отозванных клиентов
grep -i "400 Bad Request" /var/log/nginx/error.log | tail -n 20

# Мониторинг активных TLS-сессий
ss -tnp | grep :443 | grep ESTAB | wc -l
```

---

## Устранение неисправностей

### Типичные ошибки

| Ошибка в логе / симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `400 Bad Request (No required SSL certificate was sent)` | Клиент не отправил сертификат или его CA отсутствует в `ssl_client_certificate`. | Убедитесь, что `ssl_client_certificate` содержит весь цепочку доверия (Intermediate + Root). Проверьте, что клиентский сертификат имеет EKU Client Auth. |
| `Handshake failure (Unknown CA)` | Издатель клиентского сертификата не найден в `ssl_client_certificate`. | Добавьте соответствующий Intermediate CA в `ssl_client_certificate`. Проверьте: `openssl verify -CAfile ca.crt client.crt`. |
| `certificate verify failed` | Ошибка в `ssl_client_certificate` или просроченный сертификат. | Убедитесь, что файл содержит всю цепочку до Root CA. Проверьте срок: `openssl x509 -in cert.pem -noout -dates`. |
| `GnuTLS: A TLS fatal alert has been received` | Несоответствие версий TLS или отсутствие общего набора шифров. | Убедитесь, что на сервере разрешён TLS 1.3. Проверьте `ssl_protocols` в конфигурации. |
| `GPG error: The following signatures were invalid` | Неверный/истекший ключ, рассинхронизация времени, поврежденные индексы. | 1. Проверьте время: `timedatectl status`. 2. Проверьте ключ: `gpg --list-keys --keyid-format LONG`. 3. Перегенерируйте индексы: `reprepro -b /srv/repo export`. 4. Распространите актуальный публичный ключ. |
| `Database is locked` | Параллельный запуск `reprepro` или незавершенная предыдущая операция. | Проверьте процессы: `lsof +L1 | grep reprepro`. Убедитесь, что только одна команда `reprepro` выполняется одновременно. Используйте `flock` в скриптах. |
| `Not enough entropy` | Недостаточно энтропии для генерации ключей GPG. | Установите `haveged` (`sudo apt install haveged && sudo systemctl enable --now haveged`). Проверьте: `cat /proc/sys/kernel/random/entropy_avail` → должно быть > 1000. |
| `Hash Sum mismatch` | Несогласованность индексов и пула после нештатного обновления. | Очистите кэш APT: `sudo apt clean && sudo rm -rf /var/lib/apt/lists/*`. Перегенерируйте индексы на сервере: `reprepro -b /srv/repo export`. |
| `404 при apt-get update` | Отсутствует `dists/<codename>/Release` или неверный codename. | Проверьте URL: `curl -I https://repo.example.com/dists/noble/Release`. Убедитесь, что codename в `sources.list` совпадает с `conf/distributions`. |
| `CRL is not valid yet` | CRL имеет невалидную дату начала действия. | Перегенерируйте CRL. Проверьте системное время: `timedatectl status`. |

### Диагностика совместимости клиентов

```bash
# Проверка поддержки TLS 1.3 конкретным клиентом
openssl s_client -connect repo.example.com:443 -tls1_3 \
  -cert client.crt -key client.key -CAfile ca.crt

# Проверка цепочки с детальным выводом
openssl s_client -connect repo.example.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -showcerts

# Проверка переменных mTLS в активной конфигурации
nginx -T 2>/dev/null | grep ssl_client
# → показывает все директивы mTLS в активной конфигурации

# Проверка логов на ошибки handshake
tail -f /var/log/nginx/error.log | grep -i "handshake\|ssl\|verify"
```

---

## Рекомендации и лучшие практики

### Безопасность

1. **TLS 1.3:** Обязателен для mTLS (шифрование `CertificateRequest`).
2. **Private CA:** Используется внутренний CA для клиентских сертификатов. Публичные CA не выпускают Client Auth сертификаты.
3. **Иерархия:** Root CA хранится offline. Intermediate CA используется для повседневных операций.
4. **Цепочка:** `ssl_client_certificate` содержит Intermediate CA + Root CA в одном файле.
5. **EKU:** Клиентские сертификаты имеют расширение `clientAuth` (OID `1.3.6.1.5.5.7.3.2`).
6. **Глубина:** `ssl_verify_depth` установлен не менее `2`.
7. **Права доступа:** Ключи — `600`, сертификаты — `644`, директории — `750`.
8. **Ротация:** TTL клиентских сертификатов — не более 90 дней. Сертификаты сервера — 30 дней до истечения срока.

### Эксплуатация

9. **Мониторинг:** Настройте `systemd` timer или `cron` для периодического запуска `reprepro check` и `reprepro verify`. Интегрируйте проверку в Prometheus/node_exporter через textfile collector.
10. **Логирование:** Включите логирование `$ssl_client_verify`, `$ssl_client_s_dn_cn`, `$ssl_client_serial` для аудита доступа.
11. **Резервное копирование:** Делайте бэкап `dbs/` отдельно от `pool/` и `dists/`. Тестируйте восстановление не реже раза в квартал.
12. **Аудит:** Ведите лог всех операций `reprepro` через wrapper-скрипты или hook-скрипты (`PostIncomingHook`, `PostDeleteHook`).
13. **Изоляция сети:** Размещайте репозиторий во внутренней сети. При публичном доступе используйте mTLS.
14. **Тестирование:** Все новые пакеты тестируйте в изолированном тестовом репозитории перед публикацией в production.

---

## Дополнительная информация

### См. также

- **[Практические сценарии reprepro](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)** — развертывание репозитория, управление пакетами, клиентская конфигурация, бэкап и восстановление.
- **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)** — детальная конфигурация mTLS, OCSP, PQC, диагностика.
- **[Приоритеты пакетов в APT (Pinning)](../../../Linux/PackageManagement/deb_apt_pinning.md)** — управление приоритетами на стороне клиента для гарантированной установки из внутреннего репозитория.
