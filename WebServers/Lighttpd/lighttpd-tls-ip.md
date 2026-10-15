# Настройка TLS для IP-адреса в Lighttpd

**Актуально для:** Lighttpd 1.4.x (1.4.75+) / Certbot 5.4+ / Let's Encrypt shortlived

---

## Определения

**Lighttpd** (разг. *«lighty»*) — легковесный веб-сервер и обратный прокси-сервер с открытым исходным кодом, оптимизированный для высокой производительности и критически низкого потребления памяти в окружениях с ограниченными ресурсами.

**TLS для IP-адреса** — метод криптографической защиты сетевого трафика с использованием доверенного сертификата X.509, выданного удостоверяющим центром напрямую на публичный IPv4- или IPv6-адрес без привязки к доменному имени.

**IP SAN (Subject Alternative Name IP)** — расширение стандарта X.509 (RFC 5280), содержащее сетевой адрес узла в поле `iPAddress` (в отличие от стандартного `dNSName`), что позволяет клиентам и веб-браузерам корректно валидировать узел при обращении по «чистому» IP без ошибок несоответствия имени (`ERR_CERT_COMMON_NAME_INVALID`).

**shortlived-сертификат** — профиль сертификата Let's Encrypt с ограниченным сроком действия 160 часов (≈6,6 дней), применяемый для публичных IP-адресов. За счет короткого жизненного цикла не требует списков отзыва (CRL) и снижает окно уязвимости инфраструктуры при компрометации приватного ключа.

**OCSP Stapling** — механизм оптимизации проверки статуса отзыва сертификата (RFC 6066), при котором Lighttpd периодически опрашивает OCSP-сервер удостоверяющего центра, кэширует подписанный ответ и прикрепляет его к первичному TLS-рукопожатию. Исключает прямые запросы клиентов к OCSP-респондеру, снижая задержку установки соединения и защищая приватность пользователей.

**ACME-клиент** — утилита (например, Certbot или acme.sh), автоматизирующая выпуск, валидацию владения идентификатором и ротацию сертификатов по протоколу ACME (RFC 8555). Для работы с IP-адресами требует поддержки профилей (`--preferred-profile shortlived`) и идентификаторов IP (`--ip-address`).

**HTTP-01** — метод валидации владения идентификатором в протоколе ACME через размещение проверочного токена по пути `http://<IP>/.well-known/acme-challenge/<TOKEN>` по протоколу HTTP на стандартном порту 80.

**TLS-ALPN-01** — метод валидации владения сетевым адресом через протокол TLS на порту 443 (RFC 8737) с использованием согласования протокола ALPN (`acme-tls/1`) и временного самоподписанного сертификата с расширением `id-pe-acmeIdentifier`. Позволяет подтверждать владение без открытия незащищенного порта 80.

**mod_openssl** — динамический модуль Lighttpd на базе библиотеки OpenSSL, обеспечивающий криптографическую терминацию TLS 1.2/1.3, поддержку ALPN, OCSP Stapling и раздельное указание путей к цепочке сертификатов (`ssl.pemfile`) и приватному ключу (`ssl.privkey`).

---

## Базовые концепции

### Сертификаты для IP-адресов в Let's Encrypt

Публичные удостоверяющие центры исторически выпускали доверенные сертификаты преимущественно для доменных имен (FQDN). С 15 января 2026 года Let's Encrypt официально поддерживает выпуск публично доверенных сертификатов для публичных IP-адресов (IPv4 и IPv6) через выделенный профиль ACME:

*   **Профиль shortlived:** Единственный поддерживаемый профиль для IP-адресов в Let's Encrypt. Срок действия составляет строго 160 часов (6 дней и 16 часов). Выпуск 90-дневных сертификатов для IP-адресов не поддерживается.
*   **Сфера применения в Sysadmin/DevOps/SRE:**
    *   Прямой доступ к панелям мониторинга и администрирования на выделенных серверах без привязки DNS.
    *   Межсерверное взаимодействие микросервисов, узлов Consul, etcd и кластеров баз данных в bare-metal окружениях при отсутствии внутренней зоны split-horizon DNS.
    *   API-шлюзы и конечные точки сбора телеметрии для Edge-узлов и IoT.
    *   Защита от атак подмены DNS (DNS spoofing/poisoning) за счет обращения напрямую к доверенному IP.
*   **Ограничения и квоты (Rate Limits):**
    *   Дубликаты сертификатов: не более 50 сертификатов на один IP-адрес в неделю.
    *   Неудачные попытки валидации: 5 ошибок на аккаунт/IP в час.
    *   Поддерживаются только публично маршрутизируемые IP. Частные диапазоны RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), петлевые (`127.0.0.0/8`) и link-local (`fe80::/10`) адреса отклоняются сервером ACME.

### Архитектура модуля mod_openssl в Lighttpd

В современных версиях Lighttpd (≥1.4.75) обработка TLS инкапсулирована в модуле `mod_openssl`:

```
Клиент (Браузер / cURL)
        │
        ▼ (Порт 80: HTTP/1.1)
[ Lighttpd: mod_redirect ] ──► Редирект 301 на https://<IP>/
        │
        ▼ (Порт 443: TCP Syn/Ack)
[ Lighttpd: mod_openssl  ] ──► TLS 1.3 / TLS 1.2 Handshake
        ├─► Проверка IP SAN в fullchain.pem
        ├─► Отдача кэшированного ответа OCSP Stapling (ocsp.der)
        └─► Согласование ALPN (h2, http/1.1)
        │
        ▼ (Защищенная обработка HTTP-сессии)
[ Lighttpd Core Engine   ] ──► Статика / Reverse Proxy / FastCGI
```

1.  **Приоритет TLS 1.3 и Perfect Forward Secrecy (PFS):** По умолчанию Lighttpd активирует актуальные шифронаборы с эфемерным обменом ключами Диффи-Хеллмана на эллиптических кривых (ECDHE) и алгоритмами AEAD (`TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`).
2.  **Раздельная конфигурация ключей:** Начиная с Lighttpd 1.4.53 устранены требования объединять сертификат и приватный ключ в один файл. Директива `ssl.pemfile` указывает на цепочку (`fullchain.pem`), а `ssl.privkey` — на закрытый ключ (`privkey.pem`).
3.  **Автоматическая перезагрузка без простоя (Graceful Reload):** Lighttpd поддерживает обновление TLS-контекста без разрыва активных клиентских соединений по сигналу `SIGHUP` (`systemctl reload lighttpd`).

### Жизненный цикл и стратегия ротации shortlived-сертификатов

Срок жизни сертификата в 160 часов превращает процесс обновления из фоновой редкой задачи в непрерывный сервисный конвейер:

```
День 0                День 4 (≈96ч)              День 6.6 (160ч)
  │                         │                           │
  ▼                         ▼                           ▼
Выпуск (160h) ──────► Окно обновления ────────────► Истечение срока
                            │
               Каждые 3 часа: certbot renew
                            │
                            ├─► Успех: генерация ocsp.der → reload lighttpd
                            └─► Ошибка: алерт в мониторинг (SRE SLA: <48ч)
```

*   **Интервал запуска проверок:** Запуск процедуры обновления каждые 3–4 часа.
*   **Точка инициации обновления:** Сервер ACME и клиент Certbot инициируют перевыпуск, когда до истечения остается менее 48–72 часов.
*   **Синхронизация времени:** Критический фактор для короткоживущих сертификатов. Рассинхронизация системных часов даже на 1–2 часа может привести к отказу в валидации рукопожатия старыми или строгими клиентами.

---

## Практические сценарии

### Сценарий 1: Развертывание Lighttpd с доверенным TLS на публичном IP

Сценарий описывает полную процедуру настройки bare-metal или виртуального сервера под управлением Debian 12 / Ubuntu 24.04.

#### 1. Системные требования и синхронизация времени

```bash
# Обновление индекса пакетов и системы
sudo apt update && sudo apt upgrade -y

# Настройка системного часового пояса и синхронизации времени по NTP
sudo timedatectl set-timezone UTC
sudo systemctl enable --now systemd-timesyncd

# Проверка синхронизации часов
timedatectl status
# → Time zone: UTC
# → System clock synchronized: yes
# → NTP service: active
```

#### 2. Конфигурация межсетевого экрана (nftables / UFW)

Веб-серверу необходим порт 80 (для первичной HTTP-01 ACME-валидации и редиректа) и порт 443 (для HTTPS-трафика).

```bash
# Вариант с UFW:
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP ACME challenge and redirect'
sudo ufw allow 443/tcp comment 'HTTPS TLS traffic'
sudo ufw enable
sudo ufw status verbose
# → 22/tcp                     ALLOW IN    Anywhere
# → 80/tcp                     ALLOW IN    Anywhere
# → 443/tcp                    ALLOW IN    Anywhere

# Вариант с nftables (/etc/nftables.conf):
# add rule inet filter input tcp dport { 22, 80, 443 } ct state new accept
```

#### 3. Установка Lighttpd и Certbot

```bash
# Установка Lighttpd и OpenSSL-модуля
sudo apt install -y lighttpd lighttpd-mod-openssl

# Установка актуальной версии Certbot через snap (требуется версия ≥5.4 для поддержки webroot с IP)
sudo apt install -y snapd
sudo snap install core
sudo snap refresh core
sudo snap install --classic certbot

# Создание симлинка для вызова certbot в PATH
sudo ln -sf /snap/bin/certbot /usr/bin/certbot

# Проверка версии Certbot
certbot --version
# → certbot 5.4.0
```

#### 4. Подготовка директорий и первичный выпуск сертификата через Webroot

Создайте стандартную структуру директорий и проверьте права доступа:

```bash
# Создание веб-корня и директории проверки ACME
sudo mkdir -p /var/www/html/.well-known/acme-challenge
sudo chown -R www-data:www-data /var/www/html
sudo chmod -R 755 /var/www/html

# Запуск первичной конфигурации Lighttpd для обслуживания порта 80
sudo systemctl enable --now lighttpd
```

Выпуск сертификата с явным указанием публичного IP-адреса и профиля `shortlived`:

```bash
# Замените 198.51.100.1 на ваш фактический публичный IP-адрес
export SERVER_IP="198.51.100.1"

sudo certbot certonly \
  --webroot \
  --webroot-path /var/www/html \
  --preferred-profile shortlived \
  --ip-address "${SERVER_IP}" \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email
# → Successfully received certificate.
# → Certificate is saved at: /etc/letsencrypt/live/198.51.100.1/fullchain.pem
# → Key is saved at:         /etc/letsencrypt/live/198.51.100.1/privkey.pem
```

#### 5. Настройка OCSP Stapling и хука автоматического обновления

Для включения OCSP Stapling в Lighttpd необходим файл ответа респондера в формате DER. Настройте скрипт автоматической генерации ответа при каждой успешной ротации:

```bash
# Создание директории хранения OCSP-ответов с правами для чтения веб-сервером
sudo mkdir -p /etc/letsencrypt/ocsp
sudo chown -R root:www-data /etc/letsencrypt/ocsp
sudo chmod 750 /etc/letsencrypt/ocsp

# Создание исполняемого хука ротации
sudo tee /etc/letsencrypt/renewal-hooks/post/update-ocsp-and-reload.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Директории и параметры
SERVER_IP="198.51.100.1"
CERT_DIR="/etc/letsencrypt/live/${SERVER_IP}"
OCSP_DIR="/etc/letsencrypt/ocsp"
OCSP_FILE="${OCSP_DIR}/ocsp.der"

if [ -f "${CERT_DIR}/cert.pem" ] && [ -f "${CERT_DIR}/chain.pem" ]; then
    # Извлечение URL респондера из сертификата
    OCSP_URI=$(openssl x509 -in "${CERT_DIR}/cert.pem" -noout -ocsp_uri)

    if [ -n "${OCSP_URI}" ]; then
        # Формирование запроса и сохранение подписанного DER-ответа
        openssl ocsp -issuer "${CERT_DIR}/chain.pem" \
                     -cert "${CERT_DIR}/cert.pem" \
                     -url "${OCSP_URI}" \
                     -noverify \
                     -no_nonce \
                     -respout "${OCSP_FILE}.tmp" 2>/dev/null || true

        if [ -s "${OCSP_FILE}.tmp" ]; then
            mv "${OCSP_FILE}.tmp" "${OCSP_FILE}"
            chmod 644 "${OCSP_FILE}"
            chown root:www-data "${OCSP_FILE}"
        fi
    fi
fi

# Мягкая перезагрузка Lighttpd для применения новых сертификатов
systemctl reload lighttpd
EOF

sudo chmod +x /etc/letsencrypt/renewal-hooks/post/update-ocsp-and-reload.sh

# Первичная генерация OCSP-файла вручную
sudo /etc/letsencrypt/renewal-hooks/post/update-ocsp-and-reload.sh
```

#### 6. Продакшен-конфигурация Lighttpd для TLS на IP

Отредактируйте `/etc/lighttpd/lighttpd.conf`:

```lighttpd
server.modules += (
    "mod_openssl",
    "mod_redirect",
    "mod_setenv"
)

server.document-root = "/var/www/html"
server.port = 80
server.username = "www-data"
server.group = "www-data"

# Поддержка HTTP/2 через ALPN
server.feature-flags += ("server.h2" => "enable")

# Блок HTTP (Порт 80): отдача ACME challenge токенов и редирект остального трафика на HTTPS
$SERVER["socket"] == ":80" {
    # Исключение для ACME HTTP-01 проверки
    $HTTP["url"] =~ "^/\.well-known/acme-challenge/" {
        # Обработка без редиректа
    }
    else $HTTP["host"] =~ ".*" {
        url.redirect = ( "^/(.*)" => "https://%0/$1" )
    }
}

# Блок HTTPS (Порт 443): терминация TLS на IP
$SERVER["socket"] == ":443" {
    ssl.engine = "enable"
    ssl.pemfile = "/etc/letsencrypt/live/198.51.100.1/fullchain.pem"
    ssl.privkey = "/etc/letsencrypt/live/198.51.100.1/privkey.pem"

    # Ограничение протоколов (запрет устаревших TLS 1.0 и TLS 1.1)
    ssl.openssl.ssl-conf-cmd = ("MinProtocol" => "TLSv1.2")

    # Приоритет серверных шифров (AEAD и Perfect Forward Secrecy)
    ssl.honor-cipher-order = "enable"
    ssl.cipher-list = "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256"

    # OCSP Stapling для ускорения TLS-рукопожатий
    ssl.stapling-file = "/etc/letsencrypt/ocsp/ocsp.der"

    # Заголовки безопасности HTTP
    setenv.add-response-header = (
        "Strict-Transport-Security" => "max-age=15768000",
        "X-Frame-Options" => "DENY",
        "X-Content-Type-Options" => "nosniff",
        "Referrer-Policy" => "no-referrer",
        "Permissions-Policy" => "geolocation=(), microphone=(), camera=()",
        "Content-Security-Policy" => "default-src 'self'"
    )
}
```

Проверка конфигурации и применение:

```bash
# Валидация синтаксиса конфигурации Lighttpd
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
# → Syntax OK

# Применение конфигурации
sudo systemctl restart lighttpd
sudo systemctl status lighttpd --no-pager
# → Active: active (running)
```

#### 7. Отказоустойчивая автоматизация ротации (systemd timer)

Для shortlived-сертификатов стандартный запуск Certbot дважды в сутки недостаточен. Отключите стандартный таймер snap и настройте специализированный юнит:

```bash
# Отключение дефолтного снап-таймера
sudo systemctl disable --now snap.certbot.renew.timer 2>/dev/null || true

# Создание сервиса обновления
sudo tee /etc/systemd/system/certbot-ip-renew.service << 'EOF'
[Unit]
Description=Certbot IP Shortlived Certificate Renewal
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --no-self-upgrade
EOF

# Создание таймера с периодичностью запуска каждые 3 часа
sudo tee /etc/systemd/system/certbot-ip-renew.timer << 'EOF'
[Unit]
Description=Timer for Certbot IP Shortlived Certificate Renewal

[Timer]
OnCalendar=*-*-* 00/3:15:00
RandomizedDelaySec=600
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Регистрация и запуск таймера
sudo systemctl daemon-reload
sudo systemctl enable --now certbot-ip-renew.timer

# Проверка статуса таймеров в системе
systemctl list-timers certbot-ip-renew.timer
# → NEXT                         LEFT       LAST PASSED UNIT                    ACTIVATES
# → Thu 2026-10-15 03:15:00 UTC  2h 45min   n/a  n/a    certbot-ip-renew.timer  certbot-ip-renew.service
```

---

### Сценарий 2: Принудительный HTTP → HTTPS редирект с поддержкой IPv4 и IPv6

При обращении по IP-адресу клиент может запрашивать как IPv4 (`http://198.51.100.1/path`), так и IPv6 в квадратных скобках (`http://[2001:db8::1]/path`). Конфигурация редиректа должна сохранять структуру пути и bracket-нотацию:

```lighttpd
server.modules += ("mod_redirect")

$SERVER["socket"] == ":80" {
    # Исключение для локального ACME-челленджа
    $HTTP["url"] !~ "^/\.well-known/acme-challenge/" {
        # Регулярное выражение захватывает как обычные IP, так и [IPv6]
        $HTTP["host"] =~ "^(\[?[0-9a-fA-F.:]+\]?)(?::[0-9]+)?$" {
            url.redirect = ( "^/(.*)" => "https://%1/$1" )
        }
    }
}
```

Тестирование редиректа:

```bash
# Проверка редиректа через cURL
curl -I http://198.51.100.1/api/v1/health
# → HTTP/1.1 301 Moved Permanently
# → Location: https://198.51.100.1/api/v1/health
```

---

### Сценарий 3: Валидация сертификата через TLS-ALPN-01 (без открытия порта 80)

В изолированных средах или по соображениям корпоративной безопасности порт 80 может быть полностью закрыт на внешнем сетевом шлюзе. Для выпуска сертификата используется метод `TLS-ALPN-01` на порту 443:

```bash
# Временная остановка веб-сервера для освобождения 443 порта на время валидации
sudo systemctl stop lighttpd

# Выпуск через Certbot в режиме standalone с методом tls-alpn
sudo certbot certonly \
  --standalone \
  --preferred-challenges tls-alpn-01 \
  --preferred-profile shortlived \
  --ip-address 198.51.100.1 \
  --agree-tos \
  --register-unsafely-without-email

# Запуск веб-сервера после завершения проверки
sudo systemctl start lighttpd
```

> **Примечание:** Для бесперебойной автоматизации TLS-ALPN без остановки Lighttpd используется связка с обратным прокси на уровне L4 (например, HAProxy со SNI/ALPN маршрутизацией запросов `acme-tls/1` на локальный бэкенд валидации).

---

### Сценарий 4: SRE-мониторинг экспирации shortlived-сертификатов (Prometheus)

Для shortlived-сертификатов со сроком 160 часов дефолтные правила алертинга Prometheus (срабатывающие за 14–30 дней) приводят к постоянным ложным срабатываниям или пропуску аварии.

#### 1. Мониторинг через blackbox_exporter

Конфигурация модуля в `/etc/prometheus/blackbox.yml`:

```yaml
modules:
  http_ip_tls:
    prober: http
    timeout: 5s
    http:
      method: GET
      preferred_ip_protocol: ip4
      fail_if_ssl: false
      fail_if_not_ssl: true
      tls_config:
        insecure_skip_verify: false
```

Конфигурация правил алертинга в Prometheus (`tls_ip_alerts.yml`):

```yaml
groups:
  - name: tls_ip_monitoring
    rules:
      - alert: TLSCertificateExpiringSoonWarning
        expr: (probe_ssl_earliest_cert_expiry - time()) < 172800
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "TLS certificate for IP {{ $labels.instance }} expires in less than 48 hours"
          description: "Shortlived certificate remaining time is {{ $value | humanizeDuration }}. Check certbot renewal timer."

      - alert: TLSCertificateExpiringCritical
        expr: (probe_ssl_earliest_cert_expiry - time()) < 86400
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "TLS certificate for IP {{ $labels.instance }} expires in less than 24 hours"
          description: "Immediate action required: shortlived cert will expire in {{ $value | humanizeDuration }}."
```

#### 2. Локальный Textfile Collector для Node Exporter

Если внешний blackbox_exporter недоступен, скрипт проверки экспортирует метрику локально:

```bash
sudo tee /usr/local/bin/check-ip-cert-expiry.sh << 'EOF'
#!/bin/bash
set -euo pipefail

CERT_FILE="/etc/letsencrypt/live/198.51.100.1/cert.pem"
PROM_FILE="/var/lib/node_exporter/textfile_collector/certificate_expiry.prom"

if [ -f "$CERT_FILE" ]; then
    EXPIRY_DATE=$(openssl x509 -enddate -noout -in "$CERT_FILE" | cut -d= -f2)
    EXPIRY_EPOCH=$(date -d "$EXPIRY_DATE" +%s)
    echo "# HELP certificate_expiry_seconds Time when TLS certificate expires" > "$PROM_FILE.tmp"
    echo "# TYPE certificate_expiry_seconds gauge" >> "$PROM_FILE.tmp"
    echo "certificate_expiry_seconds{cert=\"ip_shortlived\"} $EXPIRY_EPOCH" >> "$PROM_FILE.tmp"
    mv "$PROM_FILE.tmp" "$PROM_FILE"
fi
EOF

sudo chmod +x /usr/local/bin/check-ip-cert-expiry.sh
```

---

## Операции и команды

### Диагностика TLS-рукопожатия и IP SAN

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `openssl s_client -connect <IP>:443 -servername <IP> -brief` | Проверка TLS-рукопожатия с IP SNI | `Protocol: TLSv1.3`, `Verification: OK` |
| `openssl s_client -connect <IP>:443 -status -brief` | Проверка наличия и статуса OCSP Staple | `OCSP Response Status: successful (0x0)` |
| `openssl x509 -in /etc/letsencrypt/live/<IP>/cert.pem -noout -text \| grep -A1 "Subject Alternative Name"` | Проверка расширения IP SAN | `IP Address:<IP>` |
| `openssl x509 -in /etc/letsencrypt/live/<IP>/cert.pem -noout -dates` | Проверка срока действия сертификата | `notBefore=...`, `notAfter=...` (окно 160ч) |
| `curl -vkI https://<IP>/` | Проверка согласования протокола ALPN и HTTP/2 | `ALPN: offers h2,http/1.1`, `HTTP/2 200` |
| `lighttpd -tt -f /etc/lighttpd/lighttpd.conf` | Валидация синтаксиса конфига Lighttpd | `Syntax OK` |
| `certbot certificates` | Просмотр активных сертификатов и путей хранения | `Certificate Name: <IP>`, `Expiry Date: ...` |
| `certbot renew --dry-run` | Тестирование механизма ротации без перевыпуска | `All simulated renewals succeeded` |

### Практические команды валидации

```bash
# 1. Проверка поля SAN с гарантией наличия IP-адреса
openssl x509 -in /etc/letsencrypt/live/198.51.100.1/cert.pem -noout -ext subjectAltName
# → X509v3 Subject Alternative Name:
# →     IP Address:198.51.100.1

# 2. Проверка статуса OCSP-ответа из кэшированного DER-файла
openssl ocsp -in /etc/letsencrypt/ocsp/ocsp.der -text -no_nonce | grep -E "Cert Status|This Update|Next Update"
# → Cert Status: good
# → This Update: Oct 14 18:00:00 2026 GMT
# → Next Update: Oct 18 18:00:00 2026 GMT

# 3. Детальный аудит шифра и протокола
openssl s_client -connect 198.51.100.1:443 -tls1_3 -brief
# → CONNECTION ESTABLISHED
# → Protocol version: TLSv1.3
# → Ciphersuite: TLS_AES_256_GCM_SHA384
```

---

## Устранение неисправностей

### 1. Ошибка проверки валидности сертификата клиентом (CERTIFICATE_VERIFY_FAILED)

*   **Симптомы:** Браузер или утилита `curl` возвращает ошибку `SSL: CERTIFICATE_VERIFY_FAILED: IP address mismatch` или `unable to get local issuer certificate`.
*   **Причины:**
    *   В сертификате отсутствует расширение `iPAddress` (сертификат выпущен как обычный доменный).
    *   В директиве `ssl.pemfile` указан `cert.pem` вместо `fullchain.pem` (отсутствует промежуточный сертификат Let's Encrypt).
    *   Рассинхронизация системных часов на сервере или клиенте (текущее время вне диапазона `notBefore` / `notAfter`).
*   **Диагностика:**
    ```bash
    # Проверка цепочки сертификатов
    openssl s_client -connect 198.51.100.1:443 -showcerts </dev/null
    # Проверка наличия промежуточного сертификата в выводе

    # Проверка соответствия времени
    date -u
    openssl x509 -in /etc/letsencrypt/live/198.51.100.1/cert.pem -noout -dates
    ```
*   **Решение:**
    1.  Убедитесь, что в `lighttpd.conf` указано:
        ```lighttpd
        ssl.pemfile = "/etc/letsencrypt/live/198.51.100.1/fullchain.pem"
        ```
    2.  При отсутствии IP SAN перевыпустите сертификат с ключом `--ip-address`.
    3.  Перезапустите `systemd-timesyncd` на сервере: `sudo systemctl restart systemd-timesyncd`.

---

### 2. Сбой автоматического обновления Certbot (Webroot Unauthorized)

*   **Симптомы:** В `journalctl -u certbot-ip-renew` регистрируется ошибка: `Invalid response from http://<IP>/.well-known/acme-challenge/... 403 Forbidden` или `404 Not Found`.
*   **Причины:**
    *   Некорректные права на директорию `/var/www/html/.well-known/acme-challenge` (пользователь `www-data` не может прочитать файл).
    *   Редирект на HTTPS перехватывает путь `/.well-known/acme-challenge/` и блокирует валидацию на чистом HTTP.
    *   Внешний файрвол блокирует входящий трафик на порт 80.
*   **Диагностика:**
    ```bash
    # Создание тестового файла
    echo "test" | sudo tee /var/www/html/.well-known/acme-challenge/healthcheck.txt
    curl -i http://198.51.100.1/.well-known/acme-challenge/healthcheck.txt
    ```
*   **Решение:**
    1.  Восстановите права:
        ```bash
        sudo chown -R www-data:www-data /var/www/html
        sudo chmod -R 755 /var/www/html
        ```
    2.  Убедитесь, что в секции `$SERVER["socket"] == ":80"` настроено исключение из редиректа для URL `^/\.well-known/acme-challenge/`.

---

### 3. OCSP Stapling не передается клиенту (No response sent)

*   **Симптомы:** Команда `openssl s_client -connect <IP>:443 -status` возвращает `OCSP response: no response sent`.
*   **Причины:**
    *   Файл `ocsp.der` отсутствует или пуст (размер 0 байт).
    *   Права доступа запрещают пользователю веб-сервера `www-data` читать файл `ocsp.der`.
    *   Срок действия ответа респондера (`Next Update`) истек.
*   **Диагностика:**
    ```bash
    ls -l /etc/letsencrypt/ocsp/ocsp.der
    # Проверка срока валидности ответа
    openssl ocsp -in /etc/letsencrypt/ocsp/ocsp.der -text -no_nonce | grep "Next Update"
    ```
*   **Решение:**
    1.  Сгенерируйте файл принудительно через `/etc/letsencrypt/renewal-hooks/post/update-ocsp-and-reload.sh`.
    2.  Установите права на чтение: `sudo chmod 644 /etc/letsencrypt/ocsp/ocsp.der`.
    3.  Выполните мягкую перезагрузку Lighttpd: `sudo systemctl reload lighttpd`.

---

### 4. Конфликт сокетов при старте (Address already in use)

*   **Симптомы:** Сервис `lighttpd` переходит в состояние `failed`, в логах `can't bind to socket: 0.0.0.0:443: Address already in use`.
*   **Причины:**
    *   Порт занят другим процессом (Nginx, Apache, зависший экземпляр Certbot standalone).
*   **Диагностика:**
    ```bash
    sudo ss -tulpn | grep -E ':80|:443'
    # → tcp LISTEN 0 128 0.0.0.0:443 1234/nginx
    ```
*   **Решение:**
    1.  Остановите и отключите конфликтующую службу: `sudo systemctl stop nginx && sudo systemctl disable nginx`.
    2.  Перезапустите Lighttpd: `sudo systemctl restart lighttpd`.

---

## Лучшие практики

### Архитектура и надежность (SRE)

*   **Мягкая перезагрузка вместо перезапуска:** Всегда используйте `systemctl reload lighttpd` (сигнал `SIGHUP`) в deploy-хуках Certbot. Это обновляет криптографический контекст в памяти воркера без сброса активных соединений и очередей HTTP-запросов.
*   **Многоуровневый алертинг:** Для shortlived-сертификатов устанавливайте двухуровневый порог алертов:
    *   Warning: менее 48 часов до экспирации (достаточно времени для ручного вмешательства инженера).
    *   Critical: менее 24 часов до экспирации (страница инцидента SRE, риск недоступности сервиса).
*   **Тестирование на сервере Staging:** При первичной отладке скриптов обновления всегда используйте флаг `--staging` (`--test-cert`), чтобы избежать исчерпания недельного лимита Let's Encrypt (50 дубликатов на IP).

### Безопасность

*   **Разграничение прав на приватные ключи:** Каталог `/etc/letsencrypt/live` и приватные ключи `privkey.pem` должны иметь права `0600` (чтение только владельцем `root`). Lighttpd считывает файлы ключей до сброса привилегий к пользователю `www-data`, поэтому назначение полных прав на ключи не требуется.
*   **HSTS и ограничения:** Директива HSTS (`Strict-Transport-Security`) должна применяться с осторожностью. Если IP-адрес является динамическим или планируется к возврату провайдеру, устанавливайте умеренный `max-age` (например, 7–30 дней), чтобы не блокировать доступ будущим владельцам IP при отзыве сертификата. Для IP-адресов параметр `preload` не поддерживается.
*   **Запрет устаревших шифронаборов:** Конфигурация `ssl.openssl.ssl-conf-cmd = ("MinProtocol" => "TLSv1.2")` гарантирует отключение TLS 1.0 и 1.1 на уровне ядра OpenSSL независимо от версий клиентских библиотек.

### Откат и очистка окружения (Rollback / Cleanup)

В случае компрометации приватного ключа или необходимости полного демонтажа TLS-сервиса:

```bash
# 1. Отзыв сертификата на сервере ACME
sudo certbot revoke \
  --cert-path /etc/letsencrypt/live/198.51.100.1/cert.pem \
  --reason keycompromise

# 2. Удаление артефактов из системы
sudo certbot delete --cert-name 198.51.100.1

# 3. Отключение кастомного таймера обновления
sudo systemctl disable --now certbot-ip-renew.timer
sudo rm -f /etc/systemd/system/certbot-ip-renew.*
sudo systemctl daemon-reload

# 4. Удаление OCSP-кэша
sudo rm -rf /etc/letsencrypt/ocsp
```

---

## Дополнительная информация

### Особенности работы с IPv6

Для IPv6-адресов директивы сокетов в Lighttpd оформляются с квадратными скобками:

```lighttpd
# Прослушивание IPv6-сокетов
$SERVER["socket"] == "[2001:db8::1]:443" {
    ssl.engine = "enable"
    ssl.pemfile = "/etc/letsencrypt/live/2001:db8::1/fullchain.pem"
    ssl.privkey = "/etc/letsencrypt/live/2001:db8::1/privkey.pem"
}
```

Выпуск сертификата для IPv6:

```bash
sudo certbot certonly \
  --webroot \
  --webroot-path /var/www/html \
  --preferred-profile shortlived \
  --ip-address 2001:db8::1
```

Проверка доступности по IPv6:

```bash
curl -g -6I https://[2001:db8::1]/
# → HTTP/2 200
```

### Известные ограничения

*   **Отсутствие Wildcard для IP:** Невозможно выпустить wildcard-сертификат для диапазона IP-адресов или подсети CIDR (`198.51.100.0/24`). Сертификат выпускается строго на конкретный хостовый IP.
*   **Ограничение профилей:** Профиль `shortlived` является единственным одобренным методом для IP в Let's Encrypt; получение стандартного 90-дневного сертификата на IP невозможно.
*   **Требования к Certbot:** Поддержка комбинации `--webroot` и `--ip-address` появилась в Certbot версии 5.4. В версиях 5.3 поддерживался только плагин `standalone`.

---

## См. также

*   **[Lighttpd — архитектура и администрирование](lighttpd_overview.md)**
*   **[Let's Encrypt и Certbot: общие принципы](../Concepts/https_with_certbot.md)**
*   **[Протокол TLS](../../Networking/Protocols/tls.md)**
*   **[Настройка TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**
*   **[Инфраструктура открытых ключей (PKI)](../../Security/Concepts/pki_overview.md)**
