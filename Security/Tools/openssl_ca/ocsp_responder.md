# OCSP Responder — настройка и эксплуатация

## Определения

**OCSP (Online Certificate Status Protocol, RFC 6960)** — протокол проверки статуса отзыва конкретного сертификата в реальном времени. Клиент отправляет запрос OCSP-резолверу с указанием серийного номера сертификата и получает ответ: `good`, `revoked` или `unknown`.

**OCSP Responder (Responder)** — сервер, отвечающий на OCSP-запросы. Подписывает ответ собственным ключом, подтверждающим полномочия на выдачу статусов. В отличие от CRL, OCSP позволяет проверять статус одного сертификата без загрузки всего списка отзыва.

**OCSP Stapling** — механизм, при котором TLS-сервер (Nginx, Apache) самостоятельно запрашивает OCSP-ответ и «прикрепляет» его к TLS-рукопожатию. Клиент не обращается к OCSP-резолверу напрямую, что ускоряет соединение и повышает приватность.

**OCSP Must-Staple (RFC 7633)** — расширение сертификата, требующее от сервера обязательной отправки OCSP-ответа. Если сервер не предоставляет Staple, клиент должен разорвать соединение.

**AIA (Authority Information Access)** — расширение сертификата, содержащее URL OCSP-резолвера (`id-ad-ocsp`).

---

## Теоретический блок

### CRL vs OCSP

| Характеристика | CRL | OCSP |
| :--- | :--- | :--- |
| Протокол | HTTP/LDAP (файл) | HTTP ( запрос/ответ) |
| Гранулярность | Весь список отзыва | Один сертификат |
| Размер данных | Большой (растёт со временем) | Малый (~300 байт) |
| Актуальность | Зависит от интервала публикации | Мгновенная (real-time) |
| Доступность | Файл должен быть доступен клиенту | OCSP-резолвер должен быть доступен |
| Приватность | Клиент видит весь список | Клиент видит только запрашиваемый сертификат |
| Нагрузка на CA | Минимальная (публикация файла) | Средняя (отвечает на запросы) |

### Архитектура OCSP в two-tier PKI

```text
                  ┌──────────────┐
                  │   Root CA    │
                  │  (offline)   │
                  └──────┬───────┘
                         │ подписывает
                  ┌──────▼───────┐
                  │ Intermediate │
                  │     CA       │
                  └──┬───────┬───┘
                     │       │
          подпись    │       │  OCSP Signing
          leaf-     │       │  Certificate
          серти     │       │
         фикатов    │       │
                     │  ┌────▼─────────┐
                     │  │ OCSP Responder│
                     │  │ (на Intermediate│
                     │  │  CA узле)     │
                     │  └──────────────┘
                     │
              ┌──────▼──────┐
              │ TLS-сервер  │
              │ (Nginx/etc) │
              └─────────────┘
```

**Ключевой момент:** OCSP-резолвер не требует отдельного сервера. Он может работать на узле Intermediate CA и подписывать ответы сертификатом, выданным тем же Intermediate CA.

### Жизненный цикл OCSP-ответа

1. Клиент (или TLS-сервер при Stapling) формирует OCSP-запрос:
   - Серийный номер сертификата
   - Издатель (issuer)
   - Хэш AlgorithmIdentifier
2. Запрос отправляется на OCSP-резолвер (URL из расширения AIA сертификата)
3. Резолвер проверяет статус в `index.txt` (или CRL)
4. Резолвер подписывает ответ своим OCSP-сертификатом
5. Клиент проверяет подпись OCSP-ответа и срок его действия

### Рекомендации 2026

- Для production-сред: **обязательно** настраивать OCSP Stapling на TLS-серверах
- Интервал обновления OCSP-ответа на сервере: 1–4 часа (по умолчанию 1 час в Nginx)
- Срок действия OCSP-ответа: 7 дней (стандарт Let's Encrypt), для внутренних CA — настраивается
- **OCSP Must-Staple** рекомендуется для публичных сертификатов; для внутренних — опционально

---

## Практический блок

### Предварительные требования

- Работающий two-tier CA (Root + Intermediate)
- OpenSSL 3.0+
- Intermediate CA ключ и сертификат
- `index.txt` и `serial` файлы на Intermediate CA

### Шаг 1: Создание OCSP-сертификата на Intermediate CA

OCSP-резолверу нужен собственный сертификат для подписи ответов. Этот сертификат выдаётся тем же Intermediate CA.

```bash
# Генерация ключа для OCSP-резолвера
openssl genrsa -aes256 -out ocsp.key 4096
# → введите passphrase

# Создание CSR
openssl req -new -key ocsp.key -out ocsp.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=MyOrg/CN=OCSP Responder"

# Добавление расширений в файл
cat > ocsp_ext.cnf << 'EOF'
authorityKeyIdentifier = keyid,issuer
basicConstraints = CA:FALSE
extendedKeyUsage = OCSPSigning
EOF

# Подписание сертификата Intermediate CA
openssl ca -config openssl.cnf \
  -extensions v3_ca \
  -extfile ocsp_ext.cnf \
  -in ocsp.csr \
  -out ocsp.crt \
  -days 365 \
  -notext

# Проверка
openssl x509 -in ocsp.crt -text -noout | grep -A2 "Extended Key Usage"
# → Extended Key Usage: OCSP Signing
```

### Шаг 2: Запуск встроенного OCSP-резолвера OpenSSL

OpenSSL содержит встроенный OCSP-сервер, пригодный для dev/staging и中小型 production.

```bash
# Запуск OCSP-резолвера
openssl ocsp \
  -index ./db/index.txt \
  -rsigner ocsp.crt \
  -rkey ocsp.key \
  -CA intermediate.crt \
  -port 8080 \
  -nmin 60 \
  -text

# Параметры:
#   -index    — файл базы сертификатов (index.txt)
#   -rsigner  — сертификат OCSP-резолвера
#   -rkey     — ключ OCSP-резолвера
#   -CA       — сертификат Intermediate CA
#   -port     — порт для прослушивания
#   -nmin     — интервал обновления в минутах (кэширование ответа)
#   -text     — подробный вывод в stdout
```

### Шаг 3: Тестирование OCSP-резолвера

```bash
# Запрос статуса конкретного сертификата
openssl ocsp \
  -issuer intermediate.crt \
  -cert leaf.crt \
  -url http://127.0.0.1:8080 \
  -resp_text

# Ожидаемый ответ (сертификат действителен):
# → OCSP Response Status: successful (0x0)
# → Cert Status: good

# После отзыва сертификата:
# → Cert Status: revoked
# → Revocation Time: Oct 21 12:00:00 2026 GMT
```

### Шаг 4: Настройка OCSP Stapling в Nginx

```nginx
server {
    listen 443 ssl;
    server_name my-service.local;

    ssl_certificate     /etc/ssl/certs/leaf.crt;
    ssl_certificate_key /etc/ssl/private/leaf.key;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;

    # Доверенный сертификат для проверки подписи OCSP-ответа
    # (должен содержать всю цепочку: leaf + intermediate)
    ssl_trusted_certificate /etc/ssl/certs/ca-chain.crt;

    # Резолвер для OCSP-запросов
    resolver 127.0.0.1:8080 valid=300s;
    resolver_timeout 5s;

    # Кэш OCSP-ответов
    ssl_stapling_cache shared:OCSP:10m;
}
```

```bash
# Проверка работы Stapling
openssl s_client -connect my-service.local:443 -servername my-service.local -status </dev/null 2>/dev/null | grep -A 5 "OCSP Response"
# → OCSP Response Status: successful (0x0)
# → Cert Status: good
```

### Шаг 5: Автоматический запуск OCSP-резолвера (systemd)

```ini
# /etc/systemd/system/ocsp-responder.service
[Unit]
Description=OpenSSL OCSP Responder
After=network.target

[Service]
Type=simple
User=ca-operator
Group=ca-operator
WorkingDirectory=/opt/ca/intermediate
ExecStart=/usr/bin/openssl ocsp \
  -index ./db/index.txt \
  -rsigner ./ocsp.crt \
  -rkey ./ocsp.key \
  -CA ./intermediate.crt \
  -port 8080 \
  -nmin 60 \
  -text
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ocsp-responder
sudo systemctl status ocsp-responder
```

### Шаг 6: Настройка OCSP Stapling в Apache

```apache
<VirtualHost *:443>
    ServerName my-service.local

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/leaf.crt
    SSLCertificateKeyFile /etc/ssl/private/leaf.key

    # Цепочка для проверки OCSP
    SSLCACertificateFile /etc/ssl/certs/ca-chain.crt

    # OCSP Stapling
    SSLUseStapling On
    SSLStaplingCache "shmcb:/var/run/ocsp(128000)"
    SSLStaplingResponseMaxAge 900
    SSLStaplingReturnResponderErrors off
</VirtualHost>
```

### Шаг 7: Встраивание AIA в сертификаты

Чтобы клиенты знали URL OCSP-резолвера, добавьте расширение AIA при подписании сертификатов.

```bash
# Добавление в openssl.cnf (секция [v3_server_cert] или [v3_req])
cat >> openssl.cnf << 'EOF'
authorityInfoAccess = OCSP;URI:http://ocsp.internal:8080
EOF

# Или через -extfile при подписании
cat > aia_ext.cnf << 'EOF'
authorityInfoAccess = OCSP;URI:http://ocsp.internal:8080
EOF

openssl ca -config openssl.cnf \
  -extensions v3_server_cert \
  -extfile aia_ext.cnf \
  -in leaf.csr \
  -out leaf.crt \
  -days 90
```

```bash
# Проверка наличия AIA в сертификате
openssl x509 -in leaf.crt -text | grep -A2 "Authority Information"
# → Authority Information Access:
# →   OCSP - URI:http://ocsp.internal:8080
```

### Отзыв сертификата и проверка через OCSP

```bash
# Отзыв сертификата
openssl ca -config openssl.cnf \
  -revoke leaf.crt \
  -crl_reason keyCompromise

# Перезапуск OCSP-резолвера (он перечитает index.txt)
sudo systemctl restart ocsp-responder

# Проверка статуса через OCSP
openssl ocsp \
  -issuer intermediate.crt \
  -cert leaf.crt \
  -url http://127.0.0.1:8080
# → Cert Status: revoked
# → Revocation Time: Oct 21 12:00:00 2026 GMT
```

---

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `OCSP response: no response sent` | OCSP-резолвер недоступен или не настроен | Проверьте порт 8080, логи ocsp-responder, доступность `index.txt` |
| `OCSP response has wrong issuer` | OCSP-сертификат подписан другим CA | Убедитесь, что `ocsp.crt` подписан тем же Intermediate CA |
| `Certificate verify failed` | Клиент не доверяет OCSP-сертификату | Добавьте `ca-chain.crt` в `ssl_trusted_certificate` (Nginx) или `SSLCACertificateFile` (Apache) |
| `Certificate is expired` | Срок действия `ocsp.crt` истёк | Перевыпустите OCSP-сертификат |
| `Response verify failure` | OCSP-ответ просрочен | Увеличьте `-nmin` или `ssl_stapling_cache` размер; проверьте синхронизацию часов |

---

## Лучшие практики

1. **Размещение:** OCSP-резолвер работает на узле Intermediate CA (не на Root)
2. **Доступность:** Обеспечьте высокую доступность через DNS round-robin или load balancer
3. **Кэширование:** TLS-сервер кэширует OCSP-ответ (обычно 1–4 часа), уменьшая нагрузку на резолвер
4. **Бэкап:** Регулярно резервируйте `ocsp.key` — его потеря потребует перевыпуска OCSP-сертификата
5. **Мониторинг:** Добавьте алерт на недоступность OCSP-резолвера (Blackbox Exporter HTTP probe)
6. **Логирование:** Включите логирование запросов для аудита и диагностики
7. **Не используйте** встроенный OpenSSL OCSP-сервер для production с >100 нод — рассмотрите step-ca или Vault PKI

---

## Дополнительная информация

- **RFC 6960** — [OCSP (Online Certificate Status Protocol)](https://datatracker.ietf.org/doc/html/rfc6960)
- **RFC 7633** — [X.509 Certificate Extension for OCSP Must-Staple](https://datatracker.ietf.org/doc/html/rfc7633)
- **[CRL Distribution Points](./crl_distribution_points.md)** — альтернативный/дополнительный механизм отзыва
- **[Обзор PKI](../../Concepts/pki_overview.md)** — базовые понятия PKI
- **[Blackbox Exporter](../../../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md)** — мониторинг доступности OCSP-резолвера
- **[TLS Optimization](../../../WebServers/Concepts/web_performance/tls_optimization.md)** — OCSP Stapling и производительность TLS
