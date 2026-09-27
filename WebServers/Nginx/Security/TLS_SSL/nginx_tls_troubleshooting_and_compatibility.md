# Диагностика TLS/SSL в Nginx и совместимость клиентов

## Определения

**TLS Troubleshooting (Диагностика TLS)** — систематический процесс выявления причин сбоев при установке защищенного соединения (рукопожатия). Включает анализ системных логов, проверку цепочек доверия сертификатов, согласование наборов шифров между клиентом и сервером, а также верификацию конфигурации Nginx на всех уровнях (`main`, `http`, `server`).

**Server Name Indication (SNI)** — расширение TLS, позволяющее клиенту передавать имя хоста до завершения рукопожатия. Это критично для корректного выбора виртуального хоста (`server`) на одном IP-адресе и для отладки несовпадений сертификатов.

**Encrypted Client Hello (ECH)** — расширение TLS 1.3, шифрующее всё приветствие клиента. В 2026 году является ключевым механизмом защиты приватности, скрывающим SNI от сетевых посредников. При сбоях ECH требуется отдельный диагностический путь: проверка `ssl_ech_file`, DNS-записей HTTPS/SVCB и версии OpenSSL.

**OCSP Stapling** — механизм оптимизации, при котором сервер сам запрашивает статус валидности своего сертификата у CA и передает его клиенту в процессе рукопожатия, ускоряя проверку и повышая приватность. Диагностика включает проверку ответа OCSP, доступности резолвера и наличия AIA в сертификате.

**MTTR (Mean Time To Repair)** — среднее время восстановления сервиса после инцидента. В контексте TLS инциденты (истекший сертификат, несовместимые шифры, сбой ECH) напрямую влияют на MTTR, поэтому наличие runbook'ов и автоматизированных проверок является обязательным.

**Runbook** — пошаговая инструкция (playbook) для оператора/SRE по реагированию на типичный инцидент. Для TLS-инцидентов runbook включает команды диагностики, критерии escalation и шаги отката.

## Основные концепции

### Методология диагностики TLS

Диагностика TLS в Nginx следует иерархическому подходу: от глобальных параметров к локальным, от конфигурации к сети.

1. **Валидация конфигурации**: `nginx -t` выявляет синтаксические ошибки до любого воздействия на рабочий сервис. Запускается на всех нодах перед применением изменений.
2. **Анализ логов**: `error_log` уровня `info` в блоке `http` или `main` обеспечивает детализацию рукопожатия без снижения производительности. В production рекомендуется `warn` с временным повышением до `info` при инциденте.
3. **Проверка цепочки сертификатов**: `openssl s_client` с флагом `-servername` позволяет проверить, что сервер передает полную цепочку (Leaf + Intermediate) и что срок действия не истек.
4. **Согласование шифров**: `openssl ciphers -v` на сервере и клиенте выявляет отсутствие пересечения. В 2026 году базовый набор должен включать TLS_AES_256_GCM_SHA384, TLS_AES_128_GCM_SHA256 и TLS_CHACHA20_POLY1305_SHA256.
5. **Проверка совместимости клиентов**: Тестирование на репрезентативных клиентах (браузеры, мобильные ОС, инфраструктурные агенты) до внедрения новых директив.

### Иерархия источников ошибок

TLS-ошибки могут возникать на четырех уровнях. Определение уровня сужает область поиска:

| Уровень | Примеры ошибок | Директивы/компоненты |
| :--- | :--- | :--- |
| **Глобальный (`http`)** | `no shared cipher`, `ssl_stapling: no data`, `shared zone "SSL" too small` | `ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`, `resolver` |
| **Локальный (`server`)** | `certificate verify failed`, `ECH decryption failed`, `ssl_reject_handshake` | `ssl_certificate`, `ssl_ech_file`, `ssl_protocols` |
| **mTLS** | `400 Bad Request (No required SSL certificate was sent)`, `Unknown CA` | `ssl_client_certificate`, `ssl_verify_client`, `ssl_verify_depth` |
| **Сеть/клиент** | `alert handshake failure (40)`, `Connection reset` | Брандмауэр, MTU, прозрачные прокси, устаревние ОС |

### Жизненный цикл диагностического сеанса

```text
Инцидент → Сбор контекста (логи, метрики, affected nodes) →
Локализация уровня (global/server/mTLS/сеть) →
Выбор SSoT-файла для конкретных ошибок →
Валидация гипотезы (openssl s_client, curl, nginx -T) →
Устранение → Верификация → Post-mortem
```

## Практические сценарии

### 1. Истекший сертификат в production

Сценарий: мониторинг сообщает об истечении срока действия сертификата на одном из фронтенд-узлов.

```bash
# 1. Проверка срока действия на проблемном узле
echo | openssl s_client -connect node01.example.com:443 -servername example.com 2>/dev/null | \
  openssl x509 -noout -dates
# → notAfter=Dec 22 23:59:59 2025 GMT

# 2. Проверка наличия нового сертификата
ls -la /etc/letsencrypt/live/example.com/
# → cert.pem  chain.pem  fullchain.pem  privkey.pem

# 3. Проверка конфигурации
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 4. Graceful reload
systemctl reload nginx

# 5. Валидация
echo | openssl s_client -connect node01.example.com:443 -servername example.com 2>/dev/null | \
  openssl x509 -noout -enddate
# → notAfter=Mar 22 23:59:59 2026 GMT
```

**Дополнительные проверки:**
- `journalctl -u nginx --since "2 minutes ago"` — убедиться, что reload не вызвал ошибок.
- `curl -I https://example.com` — убедиться, что ответ возвращается по HTTPS.

### 2. Несовместимость шифров после обновления OpenSSL

Сценарий: после обновления OpenSSL с 3.0 на 3.5 часть клиентов получает `alert handshake failure (40)`.

```bash
# 1. Определение поддерживаемых клиентом шифров (на стороне клиента или в lab)
openssl ciphers -v 'TLSv1.2' | awk '{print $2}' | sort -u

# 2. Определение активных шифров на сервере
nginx -T 2>/dev/null | grep -A1 "ssl_ciphers"
# или
openssl ciphers -v -ssl3 | grep -i "TLS_AES\|TLS_CHACHA20"

# 3. Проверка пересечения
comm -12 <(openssl ciphers -v 'TLSv1.2' | awk '{print $2}' | sort) <(nginx -T 2>/dev/null | grep ssl_ciphers | sed 's/.*://;s/;/\n/g' | tr -d ' ' | sort)

# 4. Временное добавление шифра для диагностики
# (только в staging!)
# ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256:TLS_CHACHA20_POLY1305_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
```

### 3. Сбой ECH после ротации ключей

Сценарий: после ротации ECH-ключей часть клиентов получает `ECH decryption failed`.

```bash
# 1. Проверка конфигурации ECH
nginx -T 2>/dev/null | grep ssl_ech
# → ssl_ech_file /etc/nginx/ssl/ech/private.pem;

# 2. Проверка файла ключа
ls -la /etc/nginx/ssl/ech/
# → private.pem  public.pem

# 3. Проверка DNS-записей (должны содержать публичный ключ ECH)
dig +short HTTPS example.com
# → . 31536000 1 1 . echodraft=...

# 4. Валидация ECH
openssl s_client -connect example.com:443 -servername example.com -ech 2>&1 | grep "ECH"
# → ECH accepted

# 5. Если ECH rejected — проверка совпадения ключей
openssl pkey -in /etc/nginx/ssl/ech/private.pem -pubout
# → сравнить с DNS-записью
```

### 4. Диагностика проблем с QUIC/HTTP/3 после reload

Сценарий: после `systemctl reload nginx` HTTP/3 перестает отвечать, хотя TCP/443 продолжает работать.

```bash
# 1. Проверка UDP-порта
ss -ulpn | grep :443
# →State      Recv-Q     Send-Q       Local Address:Port       Peer Address:Port  Process
# →UNCONN     0          0            0.0.0.0:443              0.0.0.0:*        users:(("nginx",pid=1234,fd=6))

# 2. Проверка модуля HTTP/3
nginx -V 2>&1 | grep -o 'http_v3_module'
# → http_v3_module

# 3. Проверка конфигурации
nginx -T 2>/dev/null | grep -E "quic|http3|alt-svc"
# → listen 443 quic reuseport;
# → http3 on;
# → add_header Alt-Svc 'h3=":443"; ma=86400';

# 4. Проверка ответа через HTTP/3
curl --http3 -v -I https://example.com 2>&1 | grep -i "alt-svc"
# → alt-svc: h3=":443"; ma=86400

# 5. Если UDP не слушается — проверка quic_bpf
nginx -T 2>/dev/null | grep quic_bpf
# → quic_bpf on;
# При проблемах с BPF временно отключите или используйте quic_retry on;
```

### 5. Восстановление после сбоя OCSP Stapling

Сценарий: клиенты сообщают о задержках при установке соединения, в логах появляется `ssl_stapling: no data`.

```bash
# 1. Проверка ответа OCSP
echo | openssl s_client -connect example.com:443 -servername example.com -status 2>&1 | grep -i "ocsp"
# → OCSP response status: successful (0x0)

# 2. Если no data — проверка AIA
openssl x509 -in /etc/nginx/ssl/fullchain.pem -noout -text | grep -A1 "Authority Information Access"
# → Authority Information Access:
# →   OCSP - URI:http://ocsp.example.com

# 3. Проверка резолвера
nginx -T 2>/dev/null | grep resolver
# → resolver 8.8.8.8 1.1.1.1 valid=300s;

# 4. Очистка кэша OCSP (если используется)
# В Nginx нет прямой команды очистки OCSP-кэша; перезагрузка перезапускает запрос:
systemctl reload nginx

# 5. Мониторинг в реальном времени
tail -f /var/log/nginx/error.log | grep -i "stapling"
```

## Операции и команды

### Диагностика TLS-рукопожатия

```bash
# Полная проверка рукопожатия (TLS 1.3 + OCSP + SNI)
openssl s_client -connect domain.com:443 -servername domain.com -status -alpn h2
# → ...
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful (0x0)

# Проверка с детальной цепочкой сертификатов
openssl s_client -connect domain.com:443 -servername domain.com -showcerts \
  -CAfile /etc/ssl/certs/ca-certificates.crt
# → показывает все сертификаты в цепочке и путь верификации

# Проверка поддержки ECH (OpenSSL 4.0+)
openssl s_client -connect domain.com:443 -servername domain.com -ech 2>&1 | grep "ECH"
# → ECH accepted
```

### Проверка совместимости клиентов

```bash
# Проверка поддержки TLS 1.3 конкретным клиентом
openssl s_client -connect domain.com:443 -servername domain.com -tls1_3

# Проверка доступных шифров клиента
openssl ciphers -v 'TLSv1.3' | awk '{print $2}' | sort -u

# Проверка HTTP/3 через ALPN
openssl s_client -connect domain.com:443 -servername domain.com -alpn h3
```

### Мониторинг TLS-сессий

```bash
# Активные TLS-сессии (требует ngx_http_stub_status_module)
curl -s http://127.0.0.1/nginx_status | grep "server accepts handled requests"
# → 12345 12345 67890

# Статистика шифров из audit-лога
awk '{print $8}' /var/log/nginx/tls_audit.log | sort | uniq -c | sort -rn | head -10
# →    5432 TLS_AES_256_GCM_SHA384
# →    3211 TLS_AES_128_GCM_SHA256

# Проверка истечения сертификатов
echo | openssl s_client -connect domain.com:443 -servername domain.com 2>/dev/null | \
  openssl x509 -noout -dates
# → notBefore=Sep 22 00:00:00 2025 GMT
# → notAfter=Dec 22 23:59:59 2025 GMT
```

### Управление службой Nginx

```bash
# Проверка синтаксиса (обязательно перед reload)
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Graceful reload без разрыва соединений
systemctl reload nginx

# Принудительная перезагрузка (при проблемах с graceful)
systemctl restart nginx

# Проверка статуса
systemctl status nginx
# → Active: active (running) since Tue 2025-09-22 12:00:00 UTC; 2h ago
```

### Верификация после изменений

```bash
# 1. Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации
systemctl reload nginx

# 3. Проверка активных слушающих портов (TCP)
ss -tlnpn | grep :443
# → LISTEN 0 128 0.0.0.0:443 0.0.0.0:*

# 4. Проверка UDP-порта для HTTP/3
ss -ulpn | grep :443
# → UNCONN 0 0 0.0.0.0:443 0.0.0.0:*

# 5. Проверка TLS 1.3 и шифра
openssl s_client -connect domain.com:443 -servername domain.com -status 2>&1 | \
  grep -E "Protocol|Cipher|OCSP"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful (0x0)
```

## Устранение неполадок

### Общая методология

При поступлении alert'а или жалобы на HTTPS-доступность следуйте алгоритму:

1. **Локализация уровня**: Определите, является ли проблема глобальной (все домены), локальной (один `server` блок) или специфичной для mTLS.
   - Глобальная: проверьте `nginx.conf`, `error_log`, `ssl_ciphers`, `ssl_protocols`.
   - Локальная: проверьте `ssl_certificate`, `ssl_ech_file`, `ssl_reject_handshake`.
   - mTLS: проверьте `ssl_client_certificate`, `ssl_verify_client`, `ssl_verify_depth`.
2. **Сбор контекста**: `nginx -T` (активная конфигурация), `journalctl -u nginx --since "10 minutes ago"`, `tail -100 /var/log/nginx/error.log`.
3. **Валидация гипотезы**: `openssl s_client`, `curl`, `nginx -t`.
4. **Устранение**: Внесите исправление в соответствующий SSoT-файл, проверьте синтаксис, примените `reload`.
5. **Верификация**: Повторите проверку из шага 3, убедитесь, что alert'ы сняты.

### Детализация типичных ошибок по уровням

#### Глобальный уровень (`http`)

Детальные таблицы ошибок и решения находятся в **[Глобальные параметры TLS в Nginx](./nginx_tls_global_parameters.md)**. Основные группы:
- `no shared cipher` — проблема в `ssl_ciphers` или `ssl_protocols`.
- `ssl_stapling: no data` — отсутствует AIA или недоступен OCSP-responder.
- `shared zone "SSL" too small` — переполнен `ssl_session_cache`.
- `kTLS not available` — ядро < 5.10 или OpenSSL собран без `enable-ktls`.

#### Уровень `server`

Детальные таблицы ошибок и решения находятся в **[Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md)**. Основные группы:
- `certificate verify failed` — неполная цепочка или просроченный сертификат.
- `ECH decryption failed` — неверные ключи или отсутствие DNS-записей.
- `ssl_stapling: no data` — отсутствует AIA в `ssl_certificate`.
- `400 Bad Request (No required SSL certificate was sent)` — ошибка в mTLS-конфигурации.

#### mTLS

Детальные таблицы ошибок и решения находятся в **[Конфигурация Mutual TLS (mTLS) в Nginx](./nginx_mtls_configuration.md)**. Основные группы:
- `400 Bad Request (No required SSL certificate was sent)` — клиент не предоставил сертификат.
- `Handshake failure (Unknown CA)` — издатель клиентского сертификата отсутствует в `ssl_client_certificate`.
- `CRL is not valid yet` — некорректная дата в CRL.

### Диагностика совместимости клиентов

```bash
# Проверка поддержки TLS 1.3 конкретным клиентом
openssl s_client -connect domain.com:443 -servername domain.com -tls1_3

# Проверка цепочки сертификатов с детальным выводом
openssl s_client -connect domain.com:443 -servername domain.com -showcerts \
  -CAfile /etc/ssl/certs/ca-certificates.crt

# Проверка поддержки HTTP/3
curl --http3 -I https://domain.com 2>&1 | grep -i "alt-svc"
```

### Внешний аудит

Для публичных сервисов используйте **SSL Labs Server Test** ([https://www.ssllabs.com/ssltest/](https://www.ssllabs.com/ssltest/)).

**На что смотреть (2026):**
- **Grade A+**: Требует наличия HSTS и отсутствия устаревших шифров.
- **Chain issues**: Ошибки «Extra download» указывают на отсутствие Intermediate CA в `ssl_certificate`.
- **PQC Support**: Проверка готовности к постквантовым атакам (Hybrid ML-KEM).
- **Protocol Support**: TLS 1.3 должен быть активен, TLS 1.0/1.1 — отключены.

### Логирование для аудита

Для анализа совместимости реальных клиентов добавьте расширенный формат лога:

```nginx
log_format tls_audit '$remote_addr [$time_local] "$request" '
                     'proto:$ssl_protocol cipher:$ssl_cipher '
                     'curve:$ssl_curves ech:$ssl_ech_status';

access_log /var/log/nginx/tls_audit.log tls_audit;
```

Для повышения детализации отладки установите уровень логирования `info` в блоке `http` или `main`:

```nginx
error_log /var/log/nginx/error.log info;
```

## Рекомендации и лучшие практики

### Чеклист SRE для TLS-инцидентов

- [ ] **Runbook**: Наличие пошаговой инструкции для каждого типа TLS-инцидента (сертификат, шифры, ECH, OCSP).
- [ ] **Мониторинг**: Автоматические проверки срока действия сертификатов (за 30, 14 и 7 дней до истечения).
- [ ] **Alerting**: Alert на `error_log` с ключевыми словами `handshake failure`, `certificate verify failed`, `ECH decryption failed`.
- [ ] **Автоматизация**: Скрипты ротации сертификатов с автоматическим `nginx -t` и `reload`.
- [ ] **Бэкап**: Автоматическое резервное копирование `ssl_certificate` и `ssl_certificate_key` перед каждой ротацией.
- [ ] **Канареечные deployments**: Изменения в `ssl_ciphers` или `ssl_protocols` применяются сначала на одной ноде, затем на всех.
- [ ] **Документация**: Актуальная матрица совместимости клиентов (см. раздел ниже).

### Процедуры операционной поддержки

**Ротация сертификатов:**
1. Получите новый сертификат через Certbot или внутренний CA.
2. Скопируйте файлы в `/etc/letsencrypt/live/example.com/` (или `/etc/nginx/ssl/`).
3. Выполните `nginx -t`.
4. Выполните `systemctl reload nginx`.
5. Проверьте: `openssl s_client -connect domain.com:443 -servername domain.com -status`.

**Валидация после изменений:**
```bash
# 1. Проверка синтаксиса
nginx -t

# 2. Применение
systemctl reload nginx

# 3. Логи
journalctl -u nginx --since "1 minute ago"

# 4. Audit-лог
tail -100 /var/log/nginx/tls_audit.log
```

**Откат изменений:**
```bash
# Если reload вызвал проблемы
git checkout /etc/nginx/conf.d/example.com.conf  # или восстановите из бэкапа
systemctl reload nginx
```

**Бэкап конфигурации виртуальных хостов:**
```bash
# Бэкап конфигурации
tar czf /backup/nginx-vhosts-$(date +%F).tar.gz /etc/nginx/conf.d/

# Бэкап сертификатов (если не используются Let's Encrypt)
tar czf /backup/nginx-ssl-$(date +%F).tar.gz /etc/nginx/ssl/
```

### Совместимость клиентов (Baseline 2026)

| Категория | Поддержка | Рекомендация |
| :--- | :--- | :--- |
| **Современные (Chrome 125+, FF 125+)** | TLS 1.3, HTTP/3, ECH, Hybrid PQC | Полная поддержка всех функций безопасности 2026 года. |
| **Apple (iOS 18+, macOS 15+)** | TLS 1.3, HTTP/3, Hybrid PQC | ECH поддерживается нативно при наличии DNS HTTPS записей. |
| **Legacy Android (8.0 - 11.0)** | TLS 1.2 / 1.3 | Требуют наличия ECDHE-AES-GCM шифров для работы. |
| **Инфраструктурные (Java 11, Go 1.22+)** | TLS 1.3 | Поддерживают современный TLS, но могут не поддерживать ECH. |

**Важное замечание**: TLS 1.0 и 1.1 полностью выведены из эксплуатации (RFC 8996). В Nginx 1.30+ поддержка этих протоколов может быть удалена на уровне сборки.

### Производительность TLS-диагностики

| Инструмент | Влияние на production | Рекомендация |
| :--- | :--- | :--- |
| `error_log info` | Увеличивает I/O при интенсивном трафике | Используйте только при инциденте; в常态 — `warn` |
| `openssl s_client` | Без влияния (внешний запрос) | Без ограничений |
| `nginx -T` | Без влияния (только чтение конфига) | Без ограничений |
| Audit-лог (`tls_audit.log`) | Умеренное увеличение I/O | Включайте на production с ротацией через `logrotate` |
| `curl --http3` | Без влияния | Без ограничений |

## Дополнительная информация

### См. также

*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура, ECH, PQC, kTLS и жизненный цикл соединения.
*   **[Глобальные параметры TLS в Nginx](./nginx_tls_global_parameters.md)** — настройка `http`-блока: шифры, сессии, OCSP, kTLS.
*   **[Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md)** — настройка `server`-блоков, ECH, 0-RTT и QUIC.
