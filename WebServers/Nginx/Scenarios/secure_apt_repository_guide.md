# Создание защищённого APT-репозитория с Nginx и mTLS

**Актуально для:** Nginx 1.26.x / 1.28.x, reprepro 5.4.x, Debian 12 (Bookworm) / Ubuntu 24.04 LTS (Noble)

## Определения

**Защищённый APT-репозиторий** — хранилище пакетов Debian/Ubuntu, доступ к которому ограничен на транспортном уровне (L4/L7) и разрешён исключительно аутентифицированным клиентам с валидными криптографическими сертификатами.

**mTLS (Mutual TLS)** — механизм взаимной криптографической аутентификации, при котором сервер и клиент предъявляют X.509-сертификаты. Исключает несанкционированный доступ к содержимому репозитория даже при компрометации URL-адреса или нахождении репозитория в публично доступной сети. Детальная архитектура и параметры веб-сервера описаны в документе **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**.

**reprepro** — консольная утилита для создания и сопровождения локальных репозиториев пакетов `.deb`. Генерирует статическую структуру индексов (`Packages`, `Sources`, `Release`), управляя файловой базой данных пакетов (Berkeley DB). Это позволяет использовать высокопроизводительный статический веб-сервер (Nginx) для раздачи файлов. Детальное описание внутреннего устройства: **[Практические сценарии reprepro](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)**.

**GPG-подпись (GNU Privacy Guard)** — механизм обеспечения целостности и неотказуемости метаданных репозитория. В то время как mTLS защищает транспортный канал и ограничивает круг читателей, подпись файла `Release` закрытым GPG-ключом гарантирует клиенту `apt`, что индексные файлы и контрольные суммы пакетов не были подменены.

**CRL (Certificate Revocation List)** — подписанный центром сертификации список отозванных серийных номеров сертификатов. Позволяет оперативно заблокировать доступ скомпрометированного или выведенного из эксплуатации сервера-клиента без перевыпуска общего CA.

**OCSP (Online Certificate Status Protocol)** — сетевой протокол проверки статуса сертификата в реальном времени. В высоконагруженных и масштабируемых инфраструктурах дополняет или заменяет статические списки CRL.

**EKU (Extended Key Usage)** — расширение сертификата X.509 v3, определяющее разрешённые сценарии применения открытого ключа. Для клиентских сертификатов APT обязательно наличие OID `1.3.6.1.5.5.7.3.2` (`clientAuth` / Client Authentication).

**DEB822** — современный структурированный формат конфигурации репозиториев APT (файлы `.sources`), принятый по умолчанию в Ubuntu 24.04 LTS и Debian 12+. Заменяет устаревший однострочный формат `sources.list`. Подробнее: **[Управление репозиториями в Debian и Ubuntu](../../../Linux/PackageManagement/deb_repositories_sources_list.md)**.

**Пользователь `_apt`** — системная непривилегированная учётная запись в Debian и Ubuntu, под которой процесс `apt` выполняет сетевые запросы при сбросе привилегий (`privilege dropping`). Файлы клиентских сертификатов и закрытых ключей должны быть доступны для чтения этому пользователю.

---

## Базовые концепции

### Архитектура эшелонированной защиты

Распространение внутренних артефактов на bare metal-серверах и виртуальных машинах требует применения принципа многоуровневой эшелонированной защиты («Defense in Depth»):

```
+-------------------------------------------------------------------------------+
|                               Уровень L4 / L7                                 |
|  Клиент APT -> TCP/IP -> TLS 1.3 Handshake (Проверка клиентского X.509)       |
|  [Nginx: ssl_verify_client on + ssl_crl /etc/nginx/ssl/crl.pem]               |
+-------------------------------------------------------------------------------+
                                       |
                                       v  mTLS Handshake успешен
+-------------------------------------------------------------------------------+
|                       Уровень авторизации и веб-сервера                       |
|  Nginx проверяет Subject DN, блокирует служебные каталоги (conf/, db/)        |
|  и отдаёт статические файлы индексов и пакетов (dists/, pool/)                |
+-------------------------------------------------------------------------------+
                                       |
                                       v  HTTP 200 OK (InRelease / Release)
+-------------------------------------------------------------------------------+
|                       Уровень верификации пакетов (APT)                       |
|  Клиент валидирует цифровую подпись Release через локальный GPG-keyring       |
|  [Подпись сформирована утилитой reprepro закрытым ключом репозитория]         |
+-------------------------------------------------------------------------------+
                                       |
                                       v  Хеши пакетов проверены (SHA256)
+-------------------------------------------------------------------------------+
|                         Установка пакета в ОС (dpkg)                          |
+-------------------------------------------------------------------------------+
```

1. **Сетевой уровень и транспортная аутентификация (mTLS):** Nginx обрывает TLS-рукопожатие на этапе согласования, если клиент не предоставил сертификат, подписанный доверенным центром сертификации (CA), либо если серийный номер сертификата внесён в актуальный CRL.
2. **Уровень изоляции веб-сервера:** Раздача ограничивается каталогами `dists/` и `pool/`. Доступ к служебной базе данных пакетов (`db/`) и конфигурационным файлам распределения (`conf/`) безусловно блокируется правилами веб-сервера со статусом 404, исключая утечку метаданных и структуры релизов.
3. **Уровень целостности содержимого (GPG):** Защищает от компрометации транспортного уровня или повреждения данных на диске. Пакетный менеджер `apt` проверяет подпись файла `InRelease` (или пары `Release` + `Release.gpg`), сверяя хеш-суммы загружаемых файлов `.deb` из каталога `pool/`.
4. **Уровень изоляции системных процессов:** Генерация индексов выполняется под выделенной системной учётной записью `reprepro`. Веб-сервер работает под пользователем `www-data` и имеет права исключительно на чтение опубликованных каталогов, что предотвращает модификацию индексов через потенциальные уязвимости веб-сервера.

### Жизненный цикл mTLS-соединения в APT

Взаимодействие клиента `apt` с защищённым репозиторием происходит по следующему протоколу:

1. **Инициация сессии:** Команда `apt-get update` запускает дочерний транспортный процесс (`/usr/lib/apt/methods/https`), который выполняет сброс привилегий до непривилегированного пользователя `_apt`.
2. **Чтение учётных данных:** Транспорт считывает пути к сертификатам из директив `Acquire::https::<host>` и обращается к файлам клиентского ключа и сертификата.
3. **TLS 1.3 Рукопожатие:**
   - Клиент отправляет `ClientHello` с указанием SNI (`repo.example.com`).
   - Nginx отправляет `ServerHello`, свой сертификат и запрос клиентского сертификата `CertificateRequest`. В TLS 1.3 данный запрос передаётся в зашифрованном виде.
   - Клиент отправляет сертификат (`Certificate`) и подтверждение владения закрытым ключом (`CertificateVerify`).
4. **Валидация на стороне Nginx:**
   - Проверка цепочки доверия вплоть до корневого CA (`ssl_client_certificate`).
   - Проверка глубины вложенности (`ssl_verify_depth`).
   - Проверка срока действия сертификата (`Not Before` / `Not After`).
   - Проверка актуального списка отзыва (`ssl_crl`).
5. **Авторизация запроса:** Nginx сопоставляет запрошенный URI с правилами доступа и отдаёт запрошенные пакеты или манифесты.

### Модель прав доступа и изоляции

| Субъект | Назначение | Права на `/srv/repo/conf` | Права на `/srv/repo/db` | Права на `/srv/repo/pool` | Права на `/srv/repo/dists` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`reprepro`** (сервисный пользователь) | Управление репозиторием, экспорт индексов, подпись | `rwx` (0700) | `rwx` (0700) | `rwx` (0755/0750) | `rwx` (0755/0750) |
| **`www-data`** (воркер Nginx) | Раздача статики клиентам | Нет доступа | Нет доступа | Только чтение (`r-x`) | Только чтение (`r-x`) |
| **`_apt`** (клиентский процесс) | Скачивание пакетов на клиенте | Неприменимо | Неприменимо | Чтение по HTTP(S) | Чтение по HTTP(S) |

---

## Практические сценарии

### Предварительные требования

#### Аппаратные и системные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **Операционная система** | Debian 12 (Bookworm) или Ubuntu 24.04 LTS (Noble) | Поддерживаются также Debian 11 и Ubuntu 22.04 LTS |
| **Веб-сервер** | Nginx версии 1.26+ (Stable) или 1.28+ (Mainline) | Требуется поддержка синтаксиса `http2 on;` и модуля `ngx_http_ssl_module` |
| **Утилита репозитория** | `reprepro` (≥ 5.4.x) | Входит в стандартные репозитории Debian/Ubuntu |
| **Криптография** | `gnupg` (≥ 2.2.x), `openssl` (≥ 3.0.x) | Для формирования GPG-ключей и управления PKI |
| **Файловая система** | ext4 или xfs с поддержкой hardlinks | Размещение каталога `db/` на сетевых файловых системах (NFS/CIFS) запрещено из-за блокировок Berkeley DB |
| **Энтропия ядра** | Ядро Linux ≥ 5.18: штатный пул CSPRNG (`poolsize` = 256) | В современных ядрах `getrandom()` не блокируется; утилита `haveged` признана устаревшей |

#### Проверка состояния системы и энтропии

В ядрах Linux начиная с версии 5.18 (Debian 12 использует 6.1 LTS, Ubuntu 24.04 — 6.8 LTS) генератор случайных чисел ядра был полностью переработан на алгоритм BLAKE2s. Размер пула зафиксирован на значении 256 бит, а генерация ключей больше не блокируется при исчерпании старых счетчиков:

```bash
# Проверка версии ядра и размера пула энтропии
uname -r
# → 6.8.0-45-generic

cat /proc/sys/kernel/random/poolsize
# → 256

cat /proc/sys/kernel/random/entropy_avail
# → 256
```

> [!NOTE]
> На устаревших ядрах (Linux < 5.6 / 5.4 в Ubuntu 20.04) размер пула составлял 4096 бит, и при генерации ключей требовалось наличие демона `haveged`. На Debian 12 и Ubuntu 24.04 установка `haveged` не требуется и не рекомендуется.

```bash
# Установка базового набора утилит на сервере репозитория
sudo apt-get update && sudo apt-get install -y nginx reprepro gnupg curl openssl ca-certificates
```

---

### Сценарий 1: Подготовка инфраструктуры PKI и сертификатов

Для организации mTLS используется изолированный центр сертификации (Private CA). Публичные центры сертификации (включая Let's Encrypt) не выпускают сертификаты с расширением `clientAuth`, пригодные для взаимного TLS.

Детальное пошаговое создание промышленного двухуровневого центра сертификации (Root CA offline + Intermediate CA) приведено в руководстве **[Двухуровневый CA на OpenSSL](../../../Security/Tools/openssl_ca/two_tier/overview.md)**.

Ниже приведен регламент подготовки артефактов для сервера репозитория и клиентов.

#### 1. Структура необходимых криптографических файлов

```text
/etc/nginx/ssl/
├── ca.crt                  # Цепочка CA (Intermediate CA + Root CA)
├── server.fullchain.crt    # Сертификат сервера репозитория с цепочкой
├── server.key              # Закрытый ключ сервера (права 0600)
└── crl.pem                 # Актуальный список отзыва сертификатов
```

#### 2. Выпуск клиентского сертификата с расширением EKU `clientAuth`

Каждый сервер-клиент или группа машин получает индивидуальную пару ключей:

```bash
# 1. Генерация закрытого ключа клиента (ECDSA P-256 или RSA 4096)
openssl ecparam -name prime256v1 -genkey -noout -out client-node01.key

# 2. Создание запроса на сертификат (CSR)
openssl req -new -key client-node01.key -out client-node01.csr \
  -subj "/C=RU/ST=Moscow/O=Internal/OU=Infrastructure/CN=client-node01.prod.internal"

# 3. Подписание сертификата промежуточным CA с обязательным EKU clientAuth
printf "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth\nsubjectKeyIdentifier=hash\n" > client_ext.cnf

openssl x509 -req -in client-node01.csr -CA /etc/ssl/ca/intermediate.crt \
  -CAkey /etc/ssl/ca/intermediate.key -CAcreateserial \
  -out client-node01.crt -days 365 -sha256 -extfile client_ext.cnf
# → Signature ok

# 4. Проверка корректности расширений сертификата
openssl x509 -in client-node01.crt -noout -text | grep -A 1 "Extended Key Usage"
# → X509v3 Extended Key Usage:
# →     TLS Web Client Authentication
```

#### 3. Формирование начального файла CRL

Для работы директивы `ssl_crl` в Nginx требуется наличие валидного файла CRL:

```bash
# Генерация файла отзыва на стороне CA
openssl ca -config /etc/ssl/ca/openssl.cnf -gencrl -out /etc/nginx/ssl/crl.pem

# Проверка содержимого CRL
openssl crl -in /etc/nginx/ssl/crl.pem -noout -text
# → Certificate Revocation List (CRL): Last Update / Next Update
```

---

### Сценарий 2: Конфигурация Nginx (версии 1.26+ / 1.28+)

Конфигурация решает ключевую задачу: обеспечение строгого mTLS-доступа к пакетам и манифестам, сохраняя при этом доступность открытого GPG-ключа для первоначальной инициализации клиентов.

#### Архитектурное решение для отдачи открытого GPG-ключа

В протоколе TLS рукопожатие происходит до передачи HTTP-заголовков. Если директива `ssl_verify_client on;` активна на виртуальном хосте, подключение клиента без сертификата будет разорвано на уровне TLS. Для первичного получения открытого ключа репозитория (`public.gpg`) используются два метода:

1. **Рекомендуемый (Out-of-band / HTTP порт 80):** Открытый GPG-ключ отдаётся через порт 80 (HTTP) по строгому пути `/public.gpg`, в то время как все остальные запросы принудительно перенаправляются на HTTPS (301 Redirect). Подделка ключа через незащищенный HTTP исключена, так как отпечаток (fingerprint) ключа сверяется клиентом, либо ключ распространяется централизованно (Ansible, Puppet).
2. **Альтернативный (mTLS с `ssl_verify_client optional`):** Проверка сертификата включается в режиме `optional`, а требование валидности переносится на уровень location Nginx через проверку `$ssl_client_verify = SUCCESS`. Путь `/public.gpg` исключается из проверки.

Ниже приведена промышленная конфигурация для первого варианта (строгий L4/L7 mTLS):

```nginx
# /etc/nginx/conf.d/secure_apt_repo.conf

# Расширенный формат логирования с аудитом mTLS
log_format mtls_repo_json escape=json '{'
    '"time_local":"$time_local",'
    '"remote_addr":"$remote_addr",'
    '"request":"$request",'
    '"status":$status,'
    '"bytes_sent":$body_bytes_sent,'
    '"request_time":$request_time,'
    '"ssl_protocol":"$ssl_protocol",'
    '"ssl_cipher":"$ssl_cipher",'
    '"ssl_client_verify":"$ssl_client_verify",'
    '"ssl_client_serial":"$ssl_client_serial",'
    '"ssl_client_s_dn":"$ssl_client_s_dn",'
    '"ssl_client_i_dn":"$ssl_client_i_dn"'
'}';

server {
    listen 80;
    listen [::]:80;
    server_name repo.example.com;

    root /srv/repo;

    # Открытый доступ исключительно к публичному GPG-ключу репозитория
    location = /public.gpg {
        try_files $uri =404;
    }

    # Все остальные запросы принудительно перенаправляются на mTLS HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    # Современный синтаксис Nginx 1.25.1+ (включая 1.26 Stable и 1.28 Mainline)
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name repo.example.com;

    root /srv/repo;
    access_log /var/log/nginx/repo_access.log mtls_repo_json;
    error_log  /var/log/nginx/repo_error.log warn;

    # Серверные SSL-сертификаты
    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Параметры безопасности TLS (только TLS 1.3 и надежный TLS 1.2)
    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:RepoSSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # HSTS (2 года)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Настройки mTLS аутентификации
    ssl_client_certificate /etc/nginx/ssl/ca.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    # Список отзыва сертификатов (CRL)
    ssl_crl /etc/nginx/ssl/crl.pem;

    # Блокировка служебных каталогов reprepro (префиксные совпадения высокой точности)
    location ^~ /conf/ {
        return 404;
    }

    location ^~ /db/ {
        return 404;
    }

    location ^~ /dbs/ {
        return 404;
    }

    location ^~ /incoming/ {
        return 404;
    }

    location ^~ /tmp/ {
        return 404;
    }

    # Раздача манифестов и deb-пакетов
    location / {
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;

        # Разрешены только безопасные методы чтения
        limit_except GET HEAD {
            deny all;
        }
    }
}
```

#### Валидация конфигурации Nginx

```bash
# Проверка синтаксиса
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Применение изменений без разрыва активных соединений
sudo systemctl reload nginx

# Проверка порта 80: доступность GPG-ключа и редирект для остальных путей
curl -s -o /dev/null -w "%{http_code}" http://repo.example.com/public.gpg
# → 200

curl -s -o /dev/null -w "%{http_code}" http://repo.example.com/dists/noble/Release
# → 301

# Проверка порта 443 без клиентского сертификата (должен возвращать 400 Bad Request)
curl -k -s -o /dev/null -w "%{http_code}" https://repo.example.com/dists/noble/Release
# → 400
```

---

### Сценарий 3: Настройка и инициализация репозитория (reprepro)

Подробное руководство по управлению пакетами и жизненному циклу `reprepro` см. в документе **[Практические сценарии reprepro](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)**.

#### 1. Подготовка служебного пользователя и каталогов

```bash
# Создание выделенного системного пользователя
sudo useradd -r -s /usr/sbin/nologin -m -d /srv/repo reprepro

# Включение пользователя веб-сервера в группу reprepro для чтения файлов
sudo usermod -aG reprepro www-data

# Формирование структуры каталогов
sudo -u reprepro mkdir -p /srv/repo/{conf,db,dists,pool,incoming,tmp}

# Разграничение прав доступа
sudo chmod 0750 /srv/repo
sudo chmod 0700 /srv/repo/conf /srv/repo/db /srv/repo/incoming /srv/repo/tmp
sudo chmod 0755 /srv/repo/dists /srv/repo/pool
```

#### 2. Конфигурация распределений (`conf/distributions`)

Создайте файл `/srv/repo/conf/distributions` от имени пользователя `reprepro`:

```text
Origin: InternalInfrastructure
Label: Corporate Private Repo
Codename: noble
Suite: stable
Architectures: amd64 arm64
Components: main
Description: Защищенный репозиторий ПО для Ubuntu 24.04 LTS (Noble)
SignWith: 7A8B9C0D1E2F3A4B
Pull: noble
Contents: .gz .bz2
DebIndices: Packages Release .gz
DscIndices: Sources Release .gz

Origin: InternalInfrastructure
Label: Corporate Private Repo
Codename: bookworm
Suite: stable
Architectures: amd64 arm64
Components: main
Description: Защищенный репозиторий ПО для Debian 12 (Bookworm)
SignWith: 7A8B9C0D1E2F3A4B
Pull: bookworm
Contents: .gz .bz2
DebIndices: Packages Release .gz
DscIndices: Sources Release .gz
```

#### 3. Экспорт публичного GPG-ключа репозитория

```bash
# Экспорт открытого ключа в корень репозитория для клиентов
sudo -u reprepro gpg --armor --export 7A8B9C0D1E2F3A4B > /srv/repo/public.gpg
sudo chmod 0644 /srv/repo/public.gpg
```

#### 4. Инициализация и первичный экспорт индексов

```bash
# Проверка конфигурации reprepro
sudo -u reprepro reprepro -V -b /srv/repo check
# → Everything seems to be correct

# Генерация первичных пустых манифестов и их подписание
sudo -u reprepro reprepro -b /srv/repo export
# → Exporting noble...
# → Exporting bookworm...
```

---

### Сценарий 4: Настройка клиентов APT

Для корректной работы клиент должен:
1. Иметь доверенный открытый GPG-ключ для проверки подписи репозитория.
2. Передавать свой сертификат и закрытый ключ при каждом HTTPS-запросе.
3. Предоставить процессу `apt` (пользователю `_apt`) права на чтение клиентского ключа.

#### Шаг 1: Установка открытого GPG-ключа репозитория

В современных версиях Debian/Ubuntu утилита `apt-key` выведена из эксплуатации. Ключи сохраняются в бинарном формате в директории `/etc/apt/keyrings/`:

```bash
# Создание директории для изолированных ключей
sudo install -m 0755 -d /etc/apt/keyrings

# Загрузка и деарморинг ключа через порт 80 (без mTLS)
curl -fsSL http://repo.example.com/public.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/internal-repo.gpg
sudo chmod 0644 /etc/apt/keyrings/internal-repo.gpg
```

#### Шаг 2: Настройка источника пакетов

##### Вариант А: Современный формат DEB822 (Ubuntu 24.04 / Debian 12) — Рекомендуется

Создайте файл `/etc/apt/sources.list.d/internal-repo.sources`:

```deb822
Types: deb
URIs: https://repo.example.com
Suites: noble
Components: main
Architectures: amd64 arm64
Signed-By: /etc/apt/keyrings/internal-repo.gpg
```

##### Вариант Б: Классический однострочный формат (`.list`)

Создайте файл `/etc/apt/sources.list.d/internal-repo.list`:

```text
deb [signed-by=/etc/apt/keyrings/internal-repo.gpg arch=amd64,arm64] https://repo.example.com noble main
```

#### Шаг 3: Настройка параметров аутентификации mTLS в APT

Создайте конфигурационный файл `/etc/apt/apt.conf.d/99internal-repo`:

```conf
# Конфигурация mTLS для взаимодействия с закрытым репозиторием
Acquire::https::repo.example.com {
    SslCert "/etc/apt/ssl/client.crt";
    SslKey  "/etc/apt/ssl/client.key";
    CaInfo  "/etc/apt/ssl/ca.crt";
};
```

#### Шаг 4: Разграничение прав доступа к клиентскому закрытому ключу

> [!IMPORTANT]
> При выполнении `apt-get update` пакетный менеджер сбрасывает привилегии до непривилегированного пользователя `_apt`. Если файл `/etc/apt/ssl/client.key` имеет права `0600 root:root`, процесс завершится ошибкой:
> `E: Method https has died unexpectedly!`
> `E: Sub-process https returned an error code (100)`
> `Could not open file /etc/apt/ssl/client.key - open (13: Permission denied)`

```bash
# Установка корректного владельца и прав доступа
sudo install -d -m 0755 /etc/apt/ssl
sudo chown root:_apt /etc/apt/ssl/client.key
sudo chmod 0640 /etc/apt/ssl/client.key

# Сертификаты доступны для чтения всем процессам
sudo chown root:root /etc/apt/ssl/client.crt /etc/apt/ssl/ca.crt
sudo chmod 0644 /etc/apt/ssl/client.crt /etc/apt/ssl/ca.crt
```

#### Валидация на стороне клиента

```bash
# Обновление списков пакетов
sudo apt-get update
# → Hit:1 https://repo.example.com noble InRelease
# → Reading package lists... Done

# Проверка видимости репозитория и политик версий
apt-cache policy
# → 500 https://repo.example.com noble/main amd64 Packages
# →     release o=InternalInfrastructure,a=noble,n=noble,l=Corporate Private Repo,c=main,b=amd64
# →     origin repo.example.com
```

---

### Сценарий 5: Автоматизация публикаций и управление очередью (CI/CD)

В production-средах добавление пакетов в репозиторий выполняется пайплайнами сборки. Параллельные запуски `reprepro` приводят к ошибке блокировки базы `Database is locked`. Для предотвращения коллизий используется утилита `flock`.

#### 1. Скрипт безопасной публикации пакета

Создайте исполняемый файл `/usr/local/bin/repo-publish-pkg.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/srv/repo"
LOCK_FILE="/var/lock/reprepro.lock"
CODENAME="${1:-}"
DEB_FILE="${2:-}"

if [[ -z "$CODENAME" || -z "$DEB_FILE" ]]; then
    echo "Использование: $0 <codename> <path-to-deb-package>"
    exit 1
fi

if [[ ! -f "$DEB_FILE" ]]; then
    echo "Ошибка: файл $DEB_FILE не найден"
    exit 2
fi

# Выполнение операции с файловой блокировкой и таймаутом 60 секунд
exec 200>"$LOCK_FILE"
flock -x -w 60 200 || { echo "Ошибка: Таймаут ожидания освобождения блокировки репозитория"; exit 3; }

echo "Публикация пакета $(basename "$DEB_FILE") в дистрибутив $CODENAME..."
sudo -u reprepro reprepro -b "$REPO_DIR" includedeb "$CODENAME" "$DEB_FILE"

echo "Успешно опубликовано."
```

#### 2. Systemd-сервис и таймер для периодического экспорта и валидации

Создайте `/etc/systemd/system/reprepro-export.service`:

```ini
[Unit]
Description=Reprepro Repository Export and Verification
After=network.target

[Service]
Type=oneshot
User=reprepro
Group=reprepro
ExecStart=/usr/bin/flock -n /var/lock/reprepro.lock /usr/bin/reprepro -b /srv/repo export
StandardOutput=journal
StandardError=journal
```

Создайте `/etc/systemd/system/reprepro-export.timer`:

```ini
[Unit]
Description=Nightly Reprepro Export and Index Regeneration

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация таймера
sudo systemctl daemon-reload
sudo systemctl enable --now reprepro-export.timer
```

---

### Сценарий 6: Ротация сертификатов, отзыв через CRL и перезагрузка Nginx

> [!WARNING]
> Nginx считывает файл, указанный в директиве `ssl_crl`, в оперативную память исключительно во время старта или перезагрузки конфигурации (`reload`). Изменение файла `crl.pem` на диске **не блокирует** скомпрометированный клиент автоматически до момента выполнения команды `systemctl reload nginx`!

#### Регламент отзыва скомпрометированного клиентского сертификата

```bash
# 1. Отзыв сертификата на управляющем сервере CA
openssl ca -config /etc/ssl/ca/openssl.cnf -revoke /etc/ssl/ca/certs/client-compromised.crt
# → Revoking Certificate 1004.
# → Data Base Updated

# 2. Перегенерация списка CRL
openssl ca -config /etc/ssl/ca/openssl.cnf -gencrl -out /etc/nginx/ssl/crl.pem

# 3. Валидация синтаксиса CRL файла
openssl crl -in /etc/nginx/ssl/crl.pem -noout -text | grep "Revoked Certificates" -A 5
# → Revoked Certificates:
# →     Serial Number: 1004

# 4. ОБЯЗАТЕЛЬНО: Перезагрузка Nginx для применения обновленного CRL
sudo systemctl reload nginx

# 5. Проверка отзыва с использованием клиентского сертификата (должно возвращать 400)
curl -v --cert client-compromised.crt --key client-compromised.key \
     --cacert /etc/nginx/ssl/ca.crt https://repo.example.com/dists/noble/Release
# → < HTTP/2 400
# → < 400 Bad Request
# → < The SSL certificate error
```

---

### Сценарий 7: Мониторинг, метрики и аудит (SRE-практика)

В промышленной эксплуатации SRE-команда контролирует:
- Срок действия SSL/TLS-сертификата сервера и корневых CA.
- Срок действия клиентских сертификатов на целевых хостах.
- Целостность базы данных `reprepro` и соответствие файлов в `pool/`.
- Доступное дисковое пространство в разделе `/srv/repo`.

#### Скрипт проверки состояния репозитория для Prometheus Node Exporter Textfile Collector

Создайте `/usr/local/bin/repo-prometheus-metrics.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

TEXTFILE_DIR="/var/lib/node_exporter/textfile_collector"
TMP_FILE="${TEXTFILE_DIR}/repo_status.prom.tmp"
TARGET_FILE="${TEXTFILE_DIR}/repo_status.prom"
REPO_DIR="/srv/repo"
SERVER_CERT="/etc/nginx/ssl/server.fullchain.crt"

mkdir -p "$TEXTFILE_DIR"

# 1. Проверка срока действия серверного сертификата (в днях)
EXPIRY_DATE=$(openssl x509 -enddate -noout -in "$SERVER_CERT" | cut -d= -f2)
EXPIRY_EPOCH=$(date -d "$EXPIRY_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

# 2. Проверка целостности метаданных reprepro
REPREPRO_CHECK_STATUS=1
if sudo -u reprepro reprepro -b "$REPO_DIR" check > /dev/null 2>&1; then
    REPREPRO_CHECK_STATUS=0
fi

# 3. Свободное место на разделе репозитория (в процентах)
DISK_USED_PERCENT=$(df -P "$REPO_DIR" | awk 'NR==2 {print $5}' | tr -d '%')

# Формирование метрик Prometheus
cat <<EOF > "$TMP_FILE"
# HELP apt_repo_ssl_cert_days_remaining Дней до истечения сертификата сервера
# TYPE apt_repo_ssl_cert_days_remaining gauge
apt_repo_ssl_cert_days_remaining $DAYS_LEFT

# HELP apt_repo_reprepro_check_status Статус проверки индексов reprepro (0 = OK, 1 = Error)
# TYPE apt_repo_reprepro_check_status gauge
apt_repo_reprepro_check_status $REPREPRO_CHECK_STATUS

# HELP apt_repo_disk_used_percent Процент занятого места на диске репозитория
# TYPE apt_repo_disk_used_percent gauge
apt_repo_disk_used_percent $DISK_USED_PERCENT
EOF

mv "$TMP_FILE" "$TARGET_FILE"
```

Создайте systemd-таймер `/etc/systemd/system/repo-metrics.timer` с запуском каждые 15 минут для актуализации метрик.

---

## Операции и команды

### Управление Nginx

| Действие | Команда | Назначение |
| :--- | :--- | :--- |
| **Тестирование конфигурации** | `sudo nginx -t` | Проверка синтаксиса перед перезагрузкой |
| **Применение изменений** | `sudo systemctl reload nginx` | Плавный перезапуск воркеров (обновление CRL, ротация сертификатов) |
| **Проверка статуса демона** | `systemctl status nginx` | Контроль активности процесса master и воркеров |
| **Мониторинг TLS-соединений** | `ss -tlnp '( sport = :443 )'` | Проверка прослушиваемого сокета и очередей backlog |

### Управление PKI и сертификатами

```bash
# 1. Просмотр срока действия клиентского сертификата
openssl x509 -in /etc/apt/ssl/client.crt -noout -dates
# → notBefore=Oct 17 00:00:00 2026 GMT
# → notAfter=Oct 17 00:00:00 2027 GMT

# 2. Проверка цепочки доверия от клиента до Root CA
openssl verify -CAfile /etc/nginx/ssl/ca.crt /etc/apt/ssl/client.crt
# → /etc/apt/ssl/client.crt: OK

# 3. Универсальная проверка соответствия открытого и закрытого ключей (RSA и ECDSA)
# Хеши публичного ключа из сертификата и закрытого ключа должны совпадать:
openssl x509 -in client.crt -pubkey -noout | openssl sha256
openssl pkey -in client.key -pubout | openssl sha256
# → (hashes match)

# 4. Проверка отзыва конкретного клиентского сертификата через CRL
openssl verify -crl_check_leaf -CAfile /etc/nginx/ssl/ca.crt \
               -CRLfile /etc/nginx/ssl/crl.pem /etc/apt/ssl/client.crt
# → client.crt: OK
```

### Управление репозиторием (reprepro)

```bash
# Проверка согласованности базы данных пакетов
sudo -u reprepro reprepro -V -b /srv/repo check
# → Everything seems to be correct

# Верификация целостности файлов пакетов в каталоге pool/
sudo -u reprepro reprepro -b /srv/repo verify

# Список всех зарегистрированных пакетов для конкретного релиза
sudo -u reprepro reprepro -b /srv/repo list noble
# → noble|main|amd64: internal-service 2.4.1-1

# Добавление deb-пакета с блокировкой от параллельных процессов
flock -x -w 30 /var/lock/reprepro.lock -c \
  "sudo -u reprepro reprepro -b /srv/repo includedeb noble /tmp/internal-service_2.4.1-1_amd64.deb"

# Удаление пакета из дистрибутива
sudo -u reprepro reprepro -b /srv/repo remove noble internal-service
```

### Диагностика mTLS и сетевого взаимодействия

```bash
# Полный тест TLS 1.3 рукопожатия с передачей клиентского сертификата
openssl s_client -connect repo.example.com:443 -servername repo.example.com \
  -tls1_3 -CAfile /etc/apt/ssl/ca.crt -cert /etc/apt/ssl/client.crt -key /etc/apt/ssl/client.key
# → SSL handshake has read ... bytes and written ... bytes
# → Verification: OK

# Тестирование скачивания манифеста через curl
curl -v --cert /etc/apt/ssl/client.crt --key /etc/apt/ssl/client.key \
     --cacert /etc/apt/ssl/ca.crt https://repo.example.com/dists/noble/InRelease
# → HTTP/2 200

# Аудит логов Nginx: поиск соединений с неуспешной проверкой сертификата
awk '$0 ~ /"ssl_client_verify":"FAILED/ {print $0}' /var/log/nginx/repo_access.log | tail -n 20
```

---

## Устранение неисправностей

| Ошибка / Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `400 Bad Request (No required SSL certificate was sent)` | Клиент не отправил сертификат, либо запрос отправлен через браузер/curl без параметров `--cert` | Убедитесь, что в `/etc/apt/apt.conf.d/` настроен блок `Acquire::https::<host>`. Проверьте синтаксис директивы `SslCert` и `SslKey`. |
| `Could not open file /etc/apt/ssl/client.key - open (13: Permission denied)` | Процесс `apt` сбросил привилегии на пользователя `_apt`, у которого нет прав на чтение закрытого ключа | Выполните: `sudo chown root:_apt /etc/apt/ssl/client.key && sudo chmod 0640 /etc/apt/ssl/client.key`. |
| `SSL certificate problem: unable to get local issuer certificate` | В файле `CaInfo` на клиенте или `ssl_client_certificate` на сервере отсутствует промежуточный или корневой CA | Объедините сертификаты Intermediate и Root CA в один PEM-файл: `cat intermediate.crt root.crt > ca.crt`. |
| `Nginx reload: the "http2" parameter of the "listen" directive is deprecated` | Использование синтаксиса Nginx до версии 1.25.1 (`listen 443 ssl http2;`) | Замените на раздельные директивы в блоке `server`: `listen 443 ssl;` и `http2 on;`. |
| `GPG error: Release: The following signatures were invalid: EXPKEYSIG` | Истёк срок действия открытого GPG-ключа репозитория на клиенте | Обновите ключ на сервере (`reprepro`), экспортируйте обновлённый `public.gpg` и обновите keyring на клиентах: `curl ... | gpg --dearmor > /etc/apt/keyrings/...`. |
| `reprepro: Database is locked` | Предыдущий процесс `reprepro` аварийно завершился, либо параллельный процесс выполняет экспорт | Проверьте блокирующие процессы: `lsof +L1 /srv/repo/db`. Запускайте все модифицирующие операции через `flock /var/lock/reprepro.lock`. |
| `Nginx 403 Forbidden` при обращении к `/pool/` или `/dists/` | Пользователь `www-data` не имеет прав на чтение файлов или выполнение каталогов (`rx`) | Добавьте веб-сервер в группу репозитория: `sudo usermod -aG reprepro www-data`, выставьте права: `chmod 0750 /srv/repo` и `chmod 0755 /srv/repo/pool`. |
| `Nginx 404 Not Found` на `/conf/` или `/db/` | Штатное поведение | Директивы `location ^~ /conf/ { return 404; }` успешно блокируют доступ к внутренним данным. Изменений не требуется. |
| Отозванный сертификат продолжает успешно подключаться | После обновления файла `crl.pem` не была выполнена перезагрузка конфигурации веб-сервера | Nginx кэширует CRL в оперативной памяти. Выполните `sudo systemctl reload nginx`. |
| `openssl verify: unable to get certificate CRL` | Использование флага `-crl_check` при отсутствии CRL для корневого CA в едином бандле | Используйте флаг `-crl_check_leaf`, который проверяет отзыв только для конечного (клиентского) сертификата. |
| `Hash Sum mismatch` при `apt-get update` | Несогласованность хешей между манифестом `Release` и индексами `Packages.gz` после прерванного экспорта | Перегенерируйте индексы на сервере: `sudo -u reprepro reprepro -b /srv/repo export`. На клиенте очистите кэш: `sudo apt-get clean && sudo rm -rf /var/lib/apt/lists/*`. |
| `certificate has expired` при подключении клиента | Истёк срок действия клиентского или серверного сертификата | Проверьте даты: `openssl x509 -in client.crt -noout -dates`. Перевыпустите сертификат с помощью Intermediate CA. |

---

## Рекомендации и лучшие практики

### Безопасность

1. **Строгий TLS 1.3:** Для mTLS рекомендуется принудительное использование TLS 1.3 (`ssl_protocols TLSv1.3;`), так как в этой версии протокола этап `CertificateRequest` и передача сертификата клиента полностью зашифрованы.
2. **Минимизация привилегий:** Веб-сервер (`www-data`) не должен иметь прав на запись ни в одну из директорий репозитория. Каталоги `conf/` и `db/` должны быть закрыты для чтения веб-сервером на уровне файловой системы (`chmod 0700 reprepro:reprepro`).
3. **Ограничение времени жизни клиентских ключей:** Устанавливайте срок действия клиентских сертификатов не более 90–180 дней с автоматизированной ротацией.
4. **Контроль EKU:** Запрещайте выпуск клиентских сертификатов без явного указания расширения `extendedKeyUsage = clientAuth`.

### Эксплуатация и SRE

5. **Атомарность операций `reprepro`:** Все операции добавления и удаления пакетов должны оборачиваться в утилиту `flock` во избежание повреждения файлов Berkeley DB.
6. **Регламент обновления CRL:** Настройте systemd-таймер на периодическое скачивание актуального CRL от CA и последующий graceful reload Nginx (`systemctl reload nginx`).
7. **Резервное копирование:** Каталоги `/srv/repo/conf/` и `/srv/repo/db/` представляют собой критическое состояние репозитория и подлежат регулярному резервному копированию. Каталоги `pool/` и `dists/` могут быть повторно сгенерированы из исходных deb-пакетов при наличии базы.
8. **Изоляция сетевого периметра:** Несмотря на стойкость mTLS, доступ к порту 443 репозитория рекомендуется дополнительно ограничивать на сетевом уровне (межсетевые экраны, Security Groups, внутренние VLAN/VPN).

---

## Дополнительная информация

### См. также

- **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)** — глубокий обзор директив SSL, OCSP Stapling, переменных mTLS и отладки веб-сервера.
- **[Практические сценарии reprepro](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)** — полное руководство по работе с утилитой `reprepro`, входящими очередями и подписью пакетов.
- **[Управление репозиториями в Debian и Ubuntu (sources.list)](../../../Linux/PackageManagement/deb_repositories_sources_list.md)** — детальный разбор синтаксиса DEB822 и классических источников APT.
- **[Приоритеты пакетов в APT (Pinning)](../../../Linux/PackageManagement/deb_apt_pinning.md)** — приоритизация внутреннего репозитория над официальными зеркалами на стороне клиента.
- **[Двухуровневый CA на OpenSSL](../../../Security/Tools/openssl_ca/two_tier/overview.md)** — пошаговое развёртывание Root и Intermediate CA для генерации инфраструктурных сертификатов.
