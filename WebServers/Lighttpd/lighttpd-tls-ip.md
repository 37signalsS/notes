# Настройка TLS для IP-адреса в Lighttpd

---

## Определения

**Lighttpd** — легковесный, высокопроизводительный веб-сервер, оптимизированный для окружений с ограниченными ресурсами.

**TLS для IP-адреса** — метод защиты трафика с использованием легитимного сертификата Let's Encrypt (профиль `shortlived`), выданного напрямую на IPv4 или IPv6-адрес без использования доменного имени.

**shortlived-сертификат** — сертификат Let's Encrypt со сроком действия 160 часов (≈6 дней), доступный только для IP-адресов. Не требует встраивания информации об отзыве (CRL), так как короткий срок жизни снижает окно уязвимости при компрометации ключа.

**OCSP Stapling** — оптимизация проверки статуса сертификата, при которой Lighttpd самостоятельно запрашивает ответ от OCSP-responder Let's Encrypt и передает его клиенту во время TLS-рукопожатия. Ускоряет соединение и защищает приватность, исключая прямой запрос клиента к серверам Let's Encrypt.

**ACME-клиент** — программа, автоматизирующая получение и обновление сертификатов по протоколу ACME (Automated Certificate Management Environment). Для IP-адресов обязательна поддержка профилей (`--preferred-profile`) и флага `--ip-address`.

---

## Базовые концепции

### Особенности сертификатов для IP (Let's Encrypt 2026)

С 15 января 2026 года Let's Encrypt официально поддерживает выпуск доверенных сертификатов для публичных IP-адресов. Основные характеристики:

*   **Профиль shortlived:** Единственный доступный профиль для IP-адресов. Срок действия — 160 часов (≈6 дней).
*   **Автоматизация:** Требует обязательного использования ACME-клиентов (Certbot ≥5.4, acme.sh) с частым циклом обновления (каждые 3–6 часов).
*   **Валидация:** Используется метод `HTTP-01` (через порт 80) или `TLS-ALPN-01` (через порт 443). Поддержка `TLS-ALPN-01` требует настройки `ssl.acme-tls-1` в Lighttpd ≥1.4.53.
*   **Доверие:** Сертификаты принимаются всеми современными браузерами и ОС без установки дополнительных корневых сертификатов.
*   **Ограничения:** IP-адреса должны быть публичными и контролируемыми. Rate limits Let's Encrypt действуют и для IP-адресов (50 сертификатов на регистрацию в неделю).

### Архитектура TLS в Lighttpd

Lighttpd использует модуль `mod_openssl` (реже `mod_gnutls`, `mod_mbedtls`, `mod_wolfssl`, `mod_nss`) для обработки шифрования. В 2026 году рекомендации:

1.  **TLS 1.3** как приоритетный протокол. Lighttpd ≥1.4.75 имеет обновленные defaults для cipher suites, а в будущих версиях MinProtocol по умолчанию будет TLSv1.3.
2.  **ECDHE** для обеспечения Perfect Forward Secrecy (PFS). Дефолтные cipher suites Lighttpd ≥1.4.75: `EECDH+AESGCM:CHACHA20:!PSK:!DHE` (AEAD, forward-secret).
3.  **OCSP Stapling** для ускорения проверки статуса короткоживущих сертификатов. Lighttpd ≥1.4.78 может автоматически проверять и перезагружать OCSP-ответы раз в минуту.
4.  **Альтернативные TLS-библиотеки:** `mod_gnutls` (GnuTLS), `mod_mbedtls` (mbedTLS), `mod_wolfssl` (wolfSSL), `mod_nss` (NSS) — выбираются в зависимости от требований к лицензированию и размеру footprint.

### Жизненный цикл shortlived-сертификата

```
Запрос (ACME) → Валидация (HTTP-01/TLS-ALPN-01) → Выпуск (160h) → Развертывание → Истечение (≈6 дней) → Обновление
     ↓                                                                                              ↑
     └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Автоматизация критична: при сбое обновления сервис становится недоступным для доверенных клиентов. Рекомендуется мониторинг остатка срока действия и валидация обновления не реже двух раз в день.

---

## Практические сценарии

### Сценарий 1: Базовая настройка сервера и TLS на IP

Этот сценарий описывает процесс развертывания защищенного сервиса на «голом» IP-адресе с использованием Lighttpd.

#### 1. Подготовка сервера

Первоначальная настройка ОС (Ubuntu/Debian):

```bash
# Обновление пакетов
sudo apt update && sudo apt upgrade -y

# Синхронизация времени (критично для проверки валидности shortlived-сертификатов)
sudo timedatectl set-timezone UTC
sudo systemctl enable --now systemd-timesyncd

# Проверка времени
timedatectl status
# → Time zone: UTC
# → System clock synchronized: yes
```

#### 2. Настройка Firewall (UFW/nftables)

Защита SSH и открытие веб-портов:

```bash
# UFW (Debian/Ubuntu)
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# nftables (альтернатива)
sudo nft add rule inet filter input tcp dport 22 accept
sudo nft add rule inet filter input tcp dport 80 accept
sudo nft add rule inet filter input tcp dport 443 accept
```

#### 3. Установка веб-сервера и Certbot

```bash
sudo apt install lighttpd -y

# Certbot через snap (рекомендуется EFF для гарантии актуальности)
sudo snap install --classic certbot

# Проверка версии (требуется ≥5.4 для webroot + IP-адрес)
certbot --version
# → certbot 5.4.0
```

#### 4. Получение сертификата для IP

Использование профиля `shortlived` для выпуска доверенного сертификата на IP:

```bash
sudo certbot certonly \
  --preferred-profile shortlived \
  --ip-address <YOUR_IP> \
  --webroot --webroot-path /var/www/html/
```

*Сертификаты сохраняются в: `/etc/letsencrypt/live/<YOUR_IP>/`*

**Примечания:**
*   Certbot ≥5.4 необходим для поддержки `--webroot` с `--ip-address`.
*   Для staging-тестирования добавьте `--staging`.
*   Путь `/var/www/html/` должен существовать и быть доступен для чтения Lighttpd.

#### 5. Генерация OCSP-ответа

Для включения OCSP Stapling предварительно сгенерируйте DER-encoded OCSP-ответ:

```bash
# Создание директории для OCSP
sudo mkdir -p /etc/letsencrypt/ocsp

# Получение OCSP-ответа (использует openssl s_client)
sudo openssl s_client -connect <YOUR_IP>:443 \
  -servername <YOUR_IP> \
  -status \
  -CAfile /etc/letsencrypt/live/<YOUR_IP>/chain.pem \
  </dev/null 2>/dev/null | openssl ocsp -no_nonce -out /etc/letsencrypt/ocsp/ocsp.der

# Или через certbot hook (автоматизация)
sudo tee /etc/letsencrypt/renewal-hooks/post/ocsp-der.sh << 'EOF'
#!/bin/bash
DOMAIN="<YOUR_IP>"
OPENSSL="/usr/bin/openssl"
OCSP_DIR="/etc/letsencrypt/ocsp"
CHAIN="/etc/letsencrypt/live/${DOMAIN}/chain.pem"
DER="${OCSP_DIR}/ocsp.der"
${OPENSSL} s_client -connect ${DOMAIN}:443 -servername ${DOMAIN} -status -CAfile ${CHAIN} </dev/null 2>/dev/null | ${OPENSSL} ocsp -no_nonce -out ${DER}
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/post/ocsp-der.sh
```

#### 6. Конфигурация Lighttpd для HTTPS

Отредактируйте `/etc/lighttpd/lighttpd.conf`:

```lighttpd
server.modules += ("mod_openssl", "mod_redirect", "mod_setenv")

# Автоперезагрузка сертификатов (lighttpd ≥1.4.78)
server.feature-flags += ("server.reload-tls" => "enable")

$SERVER["socket"] == ":443" {
    ssl.engine = "enable"
    ssl.pemfile = "/etc/letsencrypt/live/<YOUR_IP>/fullchain.pem"
    ssl.privkey = "/etc/letsencrypt/live/<YOUR_IP>/privkey.pem"

    # Настройки протокола (TLS 1.2+ для совместимости, TLS 1.3 активен)
    ssl.openssl.ssl-conf-cmd = ("MinProtocol" => "TLSv1.2")

    # Cipher suites (дефолты Lighttpd ≥1.4.75 уже forward-secret и AEAD)
    ssl.honor-cipher-order = "enable"

    # OCSP Stapling
    ssl.stapling-file = "/etc/letsencrypt/ocsp/ocsp.der"
    ssl.stapling-verify = "enable"

    # Заголовки безопасности
    setenv.add-response-header = (
        "Strict-Transport-Security" => "max-age=15768000; includeSubDomains",
        "X-Frame-Options" => "DENY",
        "X-Content-Type-Options" => "nosniff",
        "Referrer-Policy" => "no-referrer",
        "Permissions-Policy" => "geolocation=(), microphone=(), camera=()"
    )

    server.document-root = "/var/www/html"
}

# Принудительный редирект HTTP → HTTPS
$SERVER["socket"] == ":80" {
    $HTTP["host"] =~ "([0-9a-fA-F.:]+)" {
        url.redirect = ( "^/(.*)" => "https://%1/$1" )
    }
}
```

**Валидация конфигурации:**

```bash
# Проверка синтаксиса
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
# → Syntax OK

# Перезапуск
sudo systemctl restart lighttpd

# Проверка статуса
sudo systemctl status lighttpd --no-pager
# → Active: active (running)
```

#### 7. Автоматизация обновления

Для `shortlived`-сертификатов проверка должна быть частой. Рекомендуется systemd timer вместо cron для интеграции с journald:

```bash
# Отключение встроенного certbot timer (если установлен через snap)
sudo systemctl disable --now snap.certbot.renew.timer

# Создание собственного systemd service
sudo tee /etc/systemd/system/certbot-ip-renew.service << 'EOF'
[Unit]
Description=Certbot Renewal for IP Certificate
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --no-self-upgrade --deploy-hook "systemctl reload lighttpd"
EOF

# Создание systemd timer (каждые 3 часа)
sudo tee /etc/systemd/system/certbot-ip-renew.timer << 'EOF'
[Unit]
Description=Run Certbot Renewal Every 3 Hours

[Timer]
OnCalendar=*-*-* *:00/3:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Активация
sudo systemctl daemon-reload
sudo systemctl enable --now certbot-ip-renew.timer
```

**Альтернатива: cron (если systemd timer недоступен):**

```bash
# Добавьте в sudo crontab -e
0 */3 * * * /usr/bin/certbot renew --quiet --no-self-upgrade --deploy-hook "systemctl reload lighttpd"
```

### Сценарий 2: Принудительный редирект HTTP → HTTPS

Настройка автоматического перенаправления всех незащищенных запросов с поддержкой IPv4 и IPv6.

```lighttpd
server.modules += ("mod_redirect")

$SERVER["socket"] == ":80" {
    $HTTP["host"] =~ "([0-9a-fA-F.:]+)" {
        url.redirect = ( "^/(.*)" => "https://%1/$1" )
    }
}
```

**Примечание:** Регулярное выражение адаптировано для IPv4 и IPv6. Для IPv6 адреса в bracket-нотации (`[::1]`) редирект сохраняет скобки.

### Сценарий 3: Настройка заголовков безопасности (HSTS и защита)

Для усиления защиты добавьте модуль `mod_setenv` и настройте заголовки в блоке порт 443:

```lighttpd
server.modules += ("mod_setenv")

$SERVER["socket"] == ":443" {
    # ... существующие настройки ssl ...

    setenv.add-response-header = (
        "Strict-Transport-Security" => "max-age=15768000; includeSubDomains",
        "X-Frame-Options" => "DENY",
        "X-Content-Type-Options" => "nosniff",
        "Referrer-Policy" => "no-referrer",
        "Permissions-Policy" => "geolocation=(), microphone=(), camera=()",
        "Content-Security-Policy" => "default-src 'self'; script-src 'self'; style-src 'self'"
    )
}
```

**Валидация заголовков:**

```bash
curl -sI https://<YOUR_IP> | grep -E "Strict-Transport|X-Frame|X-Content|Referrer|Permissions"
# → Strict-Transport-Security: max-age=15768000; includeSubDomains
# → X-Frame-Options: DENY
# → X-Content-Type-Options: nosniff
```

---

## Операции и команды

### Мониторинг и валидация TLS

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `openssl s_client -connect <IP>:443 -servername <IP>` | Проверка handshake и сертификата | Отображение сертификата, протокола, cipher suite |
| `openssl s_client -connect <IP>:443 -status` | Проверка OCSP Stapling | `OCSP Response Status: successful` |
| `openssl x509 -in fullchain.pem -noout -dates` | Проверка срока действия | `notBefore` / `notAfter` |
| `openssl x509 -in fullchain.pem -noout -subject -issuer` | Проверка субъекта и издателя | Subject: `/IP=<IP>` |
| `curl -vI https://<IP>` | Проверка редиректа и заголовков | `HTTP/2 200`, заголовки HSTS |
| `lighttpd -tt -f /etc/lighttpd/lighttpd.conf` | Валидация конфигурации | `Syntax OK` |
| `openssl ciphers -v 'TLSv1.3'` | Список поддерживаемых TLS 1.3 cipher suites | `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256` |
| `openssl ciphers -v 'TLSv1.2'` | Список поддерживаемых TLS 1.2 cipher suites | `ECDHE-ECDSA-AES256-GCM-SHA384` и др. |

### Управление сертификатами

| Команда | Назначение |
| :--- | :--- |
| `certbot certificates` | Список всех сертификатов |
| `certbot renew --dry-run` | Тест обновления без фактической выдачи |
| `certbot revoke --cert-path /etc/letsencrypt/live/<IP>/cert.pem` | Отзыв сертификата |
| `certbot delete --cert-name <IP>` | Удаление сертификата из системы |
| `openssl x509 -in cert.pem -noout -text` | Детальный просмотр сертификата |

### Тестирование TLS-конфигурации

```bash
# Полный тест handshake с отображением всех деталей
openssl s_client -connect <IP>:443 \
  -servername <IP> \
  -alpn h2,http/1.1 \
  -cipher 'ECDHE+AESGCM:CHACHA20' \
  -brief
# → Protocol: TLSv1.3
# → Cipher: TLS_AES_256_GCM_SHA384
# → ALPN: h2

# Проверка поддержки TLS 1.3
openssl s_client -connect <IP>:443 -tls1_3 -brief
# → Protocol: TLSv1.3

# Проверка поддержки TLS 1.2
openssl s_client -connect <IP>:443 -tls1_2 -brief
# → Protocol: TLSv1.2
```

### Управление OCSP Stapling

```bash
# Принудительное обновление OCSP-ответа
sudo openssl s_client -connect <IP>:443 \
  -servername <IP> \
  -status \
  -CAfile /etc/letsencrypt/live/<IP>/chain.pem \
  </dev/null 2>/dev/null | \
  sudo openssl ocsp -no_nonce -out /etc/letsencrypt/ocsp/ocsp.der

# Проверка времени следующего обновления
openssl ocsp -in /etc/letsencrypt/ocsp/ocsp.der -text -no_nonce
# → Next Update: <timestamp>
```

---

## Устранение неисправностей

### Сценарий 1: Сбой обновления сертификата

**Симптомы:** `certbot renew` возвращает ошибку, Lighttpd продолжает использовать истекший сертификат.

**Причины:**
*   Истекший срок действия shortlived-сертификата (160 часов).
*   Порт 80 занят другим процессом (HTTP-01 валидация невозможна).
*   Ошибка разрешения DNS/IP для `--ip-address`.
*   Rate limit Let's Encrypt достигнут.

**Диагностика:**
```bash
# Проверка статуса сертификата
sudo certbot certificates
# → Certificate Name: <IP>
# → Expiry Date: 2026-01-20 12:00:00+00:00 (EXPIRED)

# Проверка порта 80
sudo ss -tlnp | grep ':80'
# → LISTEN 0 128 *:80 *:users:(("nginx",pid=1234,fd=4))

# Проверка логов certbot
sudo journalctl -u certbot-ip-renew.timer -n 50 --no-pager
# → Failed to renew certificate: <IP> with error: <details>
```

**Решение:**
1.  Остановите конкурирующий процесс на порту 80.
2.  Выполните принудительное обновление: `sudo certbot renew --force-renewal`.
3.  Проверьте rate limits: `sudo certbot show_account`.
4.  Для staging-тестирования: `sudo certbot renew --staging`.

### Сценарий 2: OCSP Stapling не работает

**Симптомы:** `openssl s_client -connect <IP>:443 -status` возвращает `OCSP Response Data: no response sent`.

**Причины:**
*   Файл `ocsp.der` отсутствует или устарел.
*   Неверный путь в `ssl.stapling-file`.
*   OCSP-responder Let's Encrypt недоступен.

**Диагностика:**
```bash
# Проверка существования файла
sudo ls -la /etc/letsencrypt/ocsp/ocsp.der
# → -rw-r--r-- 1 root root 256 Jan 15 12:00 ocsp.der

# Проверка срока действия OCSP-ответа
openssl ocsp -in /etc/letsencrypt/ocsp/ocsp.der -text -no_nonce
# → Next Update: Jan 20 12:00:00 2026 GMT

# Проверка конфигурации Lighttpd
grep stapling /etc/lighttpd/lighttpd.conf
# → ssl.stapling-file = "/etc/letsencrypt/ocsp/ocsp.der"
```

**Решение:**
1.  Перегенерируйте OCSP-ответ (см. Сценарий 1, шаг 5).
2.  Убедитесь, что `ssl.stapling-verify = "enable"` установлен.
3.  Перезагрузите Lighttpd: `sudo systemctl reload lighttpd`.

### Сценарий 3: Ошибка валидации TLS-рукопожатия

**Симптомы:** Браузер/`curl` возвращает `SSL: CERTIFICATE_VERIFY_FAILED` или `unable to get local issuer certificate`.

**Причины:**
*   Неполная цепочка сертификатов (`fullchain.pem` вместо `cert.pem`).
*   Установлен неправильный путь в `ssl.pemfile`.
*   Срок действия shortlived-сертификата истек.
*   Часовой пояс сервера некорректный (невалидный `notBefore`/`notAfter`).

**Диагностика:**
```bash
# Проверка цепочки сертификатов
openssl verify -CAfile /etc/letsencrypt/live/<IP>/chain.pem /etc/letsencrypt/live/<IP>/cert.pem
# → OK

# Проверка срока действия
openssl x509 -in /etc/letsencrypt/live/<IP>/cert.pem -noout -dates
# → notBefore: Jan 15 12:00:00 2026 GMT
# → notAfter: Jan 21 12:00:00 2026 GMT

# Проверка часового пояса
timedatectl status
# → Time zone: UTC
# → System clock synchronized: yes
```

**Решение:**
1.  Убедитесь, что используется `ssl.pemfile = "/etc/letsencrypt/live/<IP>/fullchain.pem"` (содержит промежуточный сертификат).
2.  При истекшем сертификате: `sudo certbot renew --force-renewal`.
3.  Проверьте синхронизацию времени: `sudo systemctl restart systemd-timesyncd`.

### Сценарий 4: Порт 443 недоступен

**Симптомы:** `curl https://<IP>` возвращает `Connection refused` или `Connection timed out`.

**Причины:**
*   Lighttpd не слушает порт 443.
*   Файрвол блокирует порт 443.
*   Другой процесс занимает порт 443.
*   Ошибка в конфигурации Lighttpd (неверный сокет).

**Диагностика:**
```bash
# Проверка слушающих сокетов
sudo ss -tlnp | grep ':443'
# → LISTEN 0 128 *:443 *:users:(("lighttpd",pid=1234,fd=5))

# Проверка файрвола
sudo ufw status verbose
# → 443/tcp ALLOW IN Anywhere

# Проверка логов Lighttpd
sudo journalctl -u lighttpd -n 50 --no-pager
# → ... address already in use
```

**Решение:**
1.  Настройте сокет явно: `$SERVER["socket"] == ":443"` или `$SERVER["socket"] == "<IP>:443"`.
2.  Освободите порт: `sudo fuser -k 443/tcp`.
3.  Проверьте конфигурацию: `sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf`.

---

## Лучшие практики

### Автоматизация и мониторинг

*   **Валидация обновления не реже двух раз в день:** короткий срок жизни shortlived-сертификатов делает сбои обновления критичными. Настройте systemd timer с проверкой каждые 3 часа.
*   **Мониторинг остатка срока действия:** настройте алерт при остатке <24 часов. Prometheus + blackbox_exporter или скриптовая проверка через `openssl x509 -enddate`.
*   **Тестирование обновления в staging:** перед production-развертыванием протестируйте полный цикл обновления на staging-среде с `--staging` флагом.
*   **Логирование:** настройте forwarding логов Lighttpd и Certbot в centralized logging (ELK, Loki) для расследования инцидентов.

### Безопасность

*   **Минимизация cipher suites:** доверяйте дефолтам Lighttpd ≥1.4.75. Явное указание `ssl.cipher-list` может привести к устареванию конфигурации. Если требуется кастомизация, используйте `ssl.openssl.ssl-conf-cmd = ("CipherString" => "...")`.
*   **OCSP Must-Staple:** рассмотрите добавление EKU `OCSP Must Staple` (OID 1.3.6.1.5.5.7.1.24) для усиления безопасности. Требует поддержки клиентами.
*   **HSTS preload:** для inclusion в список preload HSTS требуется `max-age=31536000` (1 год) и `includeSubDomains`. Для IP-адресов preload не рекомендуется (IP могут меняться).
*   **Заголовки безопасности:** настройте CSP, Referrer-Policy, Permissions-Policy в соответствии с политикой приложения.

### Производительность

*   **TLS session resumption:** настройте `ssl.session-tickets` и `ssl.session-cache` для снижения latency при повторных соединениях.
*   **HTTP/2:** Lighttpd ≥1.4.59 включает HTTP/2 по умолчанию при использовании TLS. Убедитесь, что ALPN настроен корректно (`-alpn h2,http/1.1`).
*   **Сетевой overhead:** при использовании TCP-сокетов (`listen = 127.0.0.1:9000` для FastCGI) учитывайте overhead loopback. Для межсерверного взаимодействия используйте Unix-сокеты где возможно.

### Управление конфигурацией

*   **Идемпотентность:** храните конфигурацию Lighttpd в VCS (git). Используйте `lighttpd -tt -f /etc/lighttpd/lighttpd.conf` в pre-commit hooks.
*   **Разделение окружений:** используйте отдельные конфигурации для staging и production. В staging — `--staging` флаг Certbot.
*   **Резервное копирование:** берите backup `/etc/letsencrypt/` и `/etc/lighttpd/lighttpd.conf` перед каждым обновлением.

---

## Дополнительная информация

### OCSP Stapling

Для короткоживущих сертификатов (`shortlived`) крайне рекомендуется включить OCSP Stapling, чтобы браузеры не тратили время на запросы к серверам Let's Encrypt:

```lighttpd
ssl.stapling-file = "/etc/letsencrypt/ocsp/ocsp.der"
ssl.stapling-verify = "enable"
```

**Примечание:** Требуется предварительная генерация файла `ocsp.der` через скрипт-хук Certbot или вручную. Lighttpd ≥1.4.78 может автоматически обновлять OCSP-ответ.

### IPv6 поддержка

Если сервер имеет IPv6, сертификат можно получить аналогичным образом. В конфиге Lighttpd для IPv6 используется отдельный сокет:

```lighttpd
$SERVER["socket"] == "[::]:443" {
    ssl.engine = "enable"
    # те же настройки, что и для IPv4
}
```

**Валидация IPv6:**

```bash
curl -g -6I https://[<YOUR_IPV6>]/ --connect-timeout 5
# → HTTP/2 200
```

### Известные ограничения

*   **Только shortlived:** Let's Encrypt не выдает обычные (90-дневные) сертификаты для IP-адресов. Автоматизация обновления обязательна.
*   **Версия Certbot:** для webroot-режима с IP-адресами требуется Certbot ≥5.4. Для standalone/manual плагинов — ≥5.3.
*   **OCSP Stapling:** требует предварительной генерации DER-файла. При отсутствии файла Lighttpd не включает stapling, но не падает.
*   **HSTS preload:** IP-адреса не могут быть добавлены в список preload из-за потенциальной смены адреса.

### См. также

*   **[Let's Encrypt и Certbot: общие принципы](../Concepts/https_with_certbot.md)**
*   **[Протокол TLS](../../Networking/Protocols/tls.md)**
*   **[Настройка TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**
*   **[Инфраструктура открытых ключей (PKI)](../../Security/Concepts/pki_overview.md)**
