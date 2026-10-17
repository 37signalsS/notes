# Диагностика TLS/SSL в Nginx и совместимость клиентов

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x – 1.30.x (Mainline), OpenSSL 3.0+ / 3.5+, Linux Kernel 5.15+ / 6.x

## Определения

**TLS Troubleshooting (Диагностика TLS)** — системный процесс локализации и устранения сбоев на этапах согласования протокола, криптографического рукопожатия (handshake), валидации цепочки сертификатов и симметричной передачи данных. Включает многоуровневый анализ сетевого стека ядра (L3/L4), событийного цикла Nginx (L7), криптографического провайдера OpenSSL и хранилища доверия на стороне клиента.

**Server Name Indication (SNI)** — расширение протокола TLS (RFC 6066), передающее доменное имя запрашиваемого виртуального хоста в открытом виде (или в зашифрованном при ECH) внутри структуры сообщения `ClientHello`. Позволяет Nginx сопоставить входящий запрос с директивой `server_name` и выбрать соответствующий блок `server` с нужным SSL-сертификатом до завершения криптографического рукопожатия.

**Encrypted Client Hello (ECH)** — расширение TLS 1.3 (RFC 9460), шифрующее всё приветствие клиента (включая SNI) открытым ключом сервера, опубликованным в DNS-записи типа HTTPS/SVCB. Защищает приватность маршрутизации на сетевом уровне. Требует наличия связки `ssl_ech_file` в Nginx, OpenSSL 3.5+/4.0+ и корректной синхронизации ключей с локальным DNS-сервером.

**OCSP Stapling** — механизм оптимизации проверки статуса цифрового сертификата (RFC 6066 / RFC 6960), при котором Nginx самостоятельно и асинхронно опрашивает OCSP-респондер центра сертификации (CA), кэширует подписанный ответ и прикрепляет (staples) его к сообщению `ServerHello`. Диагностика механизма включает проверку расширения **Authority Information Access (AIA)** в сертификате, сетевую доступность респондера и корректность директивы `resolver` в Nginx.

**Цепочка доверия (Chain of Trust) и Incomplete Chain** — иерархический путь криптографической валидации от конечного сертификата сервера (Leaf) через один или несколько промежуточных удостоверяющих центров (Intermediate CA) к доверенному корневому сертификату (Root CA). Дефект «Incomplete Chain» возникает, если файл, указанный в `ssl_certificate`, содержит только Leaf-сертификат без Intermediate CA. Это приводит к сбоям у CLI-утилит (curl, git), мобильных клиентов и API-сервисов, не имеющих встроенного механизма докачки промежуточных звеньев.

**TLS Alert** — стандартизированные протокольные сообщения об ошибках или завершении сессии (RFC 8446), состоящие из уровня серьезности (Warning или Fatal) и байтового кода описания. При получении или отправке Fatal Alert соединение немедленно разрывается на уровне TLS. Типичные коды: 40 (`handshake_failure`), 42 (`bad_certificate`), 46 (`certificate_unknown`), 48 (`unknown_ca`), 112 (`unrecognized_name`), 116 (`certificate_required`).

**MTU и Path MTU (PMTU) Blackhole** — сетевой сбой на уровне L3/L4, при котором TCP-пакеты стандартного размера (SYN, ACK) успешно проходят сетевой маршрут, но большие пакеты TLS-рукопожатия (в частности, `ServerHello` с сертификатом длиной 3–6 КБ) молча отбрасываются промежуточным сетевым оборудованием из-за заниженного MTU и блокировки управляющих пакетов ICMP Type 3 Code 4 (Fragmentation Needed). Проявляется как зависание соединения сразу после отправки `ClientHello`.

**Client Fingerprinting (JA3 / JA4)** — метод идентификации и классификации клиентского ПО на основе статических параметров его `ClientHello` (поддерживаемые версии TLS, перечень шифров, список расширений TLS, поддерживаемые эллиптические кривые и форматы точек). Применяется инженерами SRE и безопасности для локализации несовместимостей клиентов и детектирования аномального трафика.

**Mean Time To Repair (MTTR)** — среднее время локализации и восстановления сервиса после инцидента. В контексте эксплуатации TLS снижение MTTR достигается за счет автоматизированной верификации конфигурации перед reload, стандартизированных runbook-инструкций и непрерывного мониторинга сроков действия сертификатов.

**Runbook** — пошаговый инженерный регламент действий дежурного администратора/SRE при возникновении типового инцидента (истечение срока действия сертификата, несовместимость шифронаборов, рассинхронизация ключей, падение OCSP-респондера).

**Debug Connection** — директива блока `events` в Nginx (`debug_connection <IP>;`), активирующая максимально детальный журнал (`debug`) исключительно для указанного IP-адреса администратора или тестового узла. Позволяет исследовать ход TLS-рукопожатия на production-сервере без создания паразитной нагрузки на дисковую подсистему и процессор.

---

## Архитектура и основные концепции

### Иерархия уровней возникновения сбоев TLS

Ошибки при установке защищенного соединения в инфраструктуре под управлением Nginx классифицируются по четырем технологическим слоям:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Сетевой уровень (L3/L4: Сеть ядра Linux, Firewall, MTU)             │
│    - Дроп TCP/UDP пакетов (iptables/nftables)                          │
│    - MTU/PMTU Blackhole (зависание на больших сертификатах)             │
│    - Недоступность UDP/443 для протокола QUIC (HTTP/3)                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ 2. Уровень Nginx Core (L7: Маршрутизация, Конфигурация, Сокеты)       │
│    - Синтаксические ошибки и ошибки прав доступа к ключам (0600/0640)  │
│    - Маршрутизация SNI -> server_name (Default Drop: reject_handshake) │
│    - Ошибки сокетов (listen 443 ssl / quic reuseport)                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ 3. Криптографический движок (OpenSSL 3.x/3.5+ Engine & Providers)      │
│    - Отсутствие пересечения шифронаборов (no shared cipher)            │
│    - Неподдерживаемые версии протоколов (TLS 1.2 vs TLS 1.3)           │
│    - Ошибки дешифрования ECH (ECH decryption failed)                   │
│    - Сбои проверки подписи и цепочки Intermediate CA                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ 4. Клиентское окружение (Client Trust Store & Application Runtime)     │
│    - Устаревшие корневые сертификаты в ОС клиента (/etc/ssl/certs)     │
│    - Отсутствие поддержки SNI в устаревших CLI/библиотеках             │
│    - Ошибки взаимной аутентификации mTLS (клиент не передал ключ)      │
└────────────────────────────────────────────────────────────────────────┘
```

### Жизненный цикл рукопожатия TLS и критические точки отказа

В зависимости от версии протокола точки отказа распределяются по шагам рукопожатия следующим образом:

#### Рукопожатие TLS 1.3 (1-RTT)

```text
Клиент                                                Nginx (OpenSSL)
  │                                                          │
  │─── 1. ClientHello (SNI, Ciphers, Curves, KeyShare) ────►│ [Точка 1]
  │                                                          │
  │◄── 2. ServerHello (Selected Cipher, KeyShare) ──────────│ [Точка 2]
  │◄── 3. {EncryptedExtensions (ALPN)} ─────────────────────│ [Точка 3]
  │◄── 4. {Certificate (Full Chain)} ───────────────────────│ [Точка 4]
  │◄── 5. {CertificateVerify (Подпись сервера)} ────────────│ [Точка 5]
  │◄── 6. {Finished} ───────────────────────────────────────│ [Точка 6]
  │                                                          │
  │─── 7. {Finished} ───────────────────────────────────────►│
  │─── 8. [HTTP Request / Application Data] ────────────────►│ (Защищенный канал)
```

- **[Точка 1] Обработка `ClientHello`:**
  - *Сбой:* Nginx не находит запрошенный `server_name` и передает запрос в дефолтный виртуальный хост, где активна директива `ssl_reject_handshake on`. Сервер немедленно завершает сессию.
  - *Сбой:* В `ClientHello` отсутствуют шифронаборы, поддерживаемые Nginx (`no shared cipher`).
  - *Сбой ECH:* Клиент шифрует приветствие публичным ключом ECH, но сервер не может его расшифровать из-за устаревшего `ssl_ech_file`.
- **[Точка 2] Формирование `ServerHello`:**
  - *Сбой:* Несовместимость алгоритмов обмена ключами (ECDHE Groups / Hybrid PQC ML-KEM).
- **[Точка 3] `EncryptedExtensions`:**
  - *Сбой:* ALPN mismatch (клиент запросил `h2`, но сервер поддерживает только `http/1.1`).
- **[Точка 4] Передача `Certificate`:**
  - *Сбой (PMTU Blackhole):* Пакет размером >1500 байт дропается по пути. Рукопожатие виснет по таймауту.
  - *Сбой валидации:* В файле сертификата отсутствует промежуточный сертификат (Intermediate CA), клиент возвращает `alert(48): unknown_ca`.
  - *Сбой срока действия:* Срок действия сертификата истек, клиент возвращает `alert(45): certificate_expired`.
- **[Точка 5] `CertificateVerify`:**
  - *Сбой:* Несовпадение закрытого ключа сервера с открытым ключом в сертификате (`key values mismatch`).
- **[Точка 6] Завершение рукопожатия:**
  - *Сбой:* Повреждение сессионных ключей или сбой MAC-подписи.

### Протокольные коды TLS Alerts

При возникновении криптографической или логической ошибки сторона, зафиксировавшая сбой, отправляет двухбайтовый `TLS Alert`:

| Код (Dec/Hex) | Имя Alert (RFC 8446) | Уровень | Кто генерирует | Первопричина в контексте Nginx |
| :--- | :--- | :--- | :--- | :--- |
| **0 / 0x00** | `close_notify` | Warning | Обе стороны | Штатное закрытие TLS-сессии перед разрывом TCP-соединения. |
| **10 / 0x0A** | `unexpected_message` | Fatal | Обе стороны | Нарушение порядка следования сообщений рукопожатия. |
| **20 / 0x14** | `bad_record_mac` | Fatal | Обе стороны | Ошибка целостности записи (неверный ключ или сбой симметричного шифрования). |
| **40 / 0x28** | `handshake_failure` | Fatal | Обе стороны | Сервер и клиент не смогли договориться (нет общих шифров, протоколов или сработал `ssl_reject_handshake`). |
| **42 / 0x2A** | `bad_certificate` | Fatal | Клиент/Nginx | Сертификат поврежден, содержит невалидную подпись или битые ASN.1 поля. |
| **43 / 0x2B** | `unsupported_certificate` | Fatal | Клиент/Nginx | Сертификат использует неподдерживаемый тип ключа (например, старый DSA). |
| **44 / 0x2C** | `certificate_revoked` | Fatal | Клиент | Сертификат сервера отозван согласно проверке OCSP или CRL. |
| **45 / 0x2D** | `certificate_expired` | Fatal | Клиент | Истек срок действия сертификата сервера (или системное время узла рассинхронизировано). |
| **46 / 0x2E** | `certificate_unknown` | Fatal | Клиент/Nginx | Общая ошибка верификации цепочки доверия в хранилище CA. |
| **48 / 0x30** | `unknown_ca` | Fatal | Клиент/Nginx | Цепочка не может быть сведена к доверенному Root CA (разорвана цепочка Intermediate CA). |
| **80 / 0x50** | `internal_error` | Fatal | Обе стороны | Внутренний сбой криптобиблиотеки (нехватка оперативной памяти, сбой kTLS). |
| **112 / 0x70** | `unrecognized_name` | Warning/Fatal | Nginx | Сервер сообщает, что переданное в SNI доменное имя не распознано. |
| **116 / 0x74** | `certificate_required` | Fatal | Nginx | Режим mTLS: Nginx потребовал клиентский сертификат (`ssl_verify_client on;`), но клиент его не предоставил. |

---

## Практические сценарии

### 1. Аварийная ротация просроченного сертификата без даунтайма

**Контекст:** Система мониторинга сигнализирует об истечении срока действия SSL-сертификата на веб-сервере Nginx. Требуется установить новые сертификаты, проверить их соответствие закрытому ключу и применить конфигурацию без разрыва текущих сессий.

```bash
# 1. Проверка текущего срока действия сертификата на локальном узле через сокет
echo | openssl s_client -connect 127.0.0.1:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates
# → notBefore=Jan 10 00:00:00 2025 GMT
# → notAfter=Apr 10 23:59:59 2025 GMT

# 2. Проверка соответствия публичного ключа сертификата и приватного ключа (проверка контрольных сумм модулей)
CERT_MOD=$(openssl x509 -noout -modulus -in /etc/ssl/certs/example.com.crt | openssl md5)
KEY_MOD=$(openssl rsa -noout -modulus -in /etc/ssl/private/example.com.key 2>/dev/null | openssl md5)
[ "$CERT_MOD" = "$KEY_MOD" ] && echo "Keys match" || echo "ERROR: Modulus mismatch!"
# → Keys match

# 3. Валидация цепочки сертификатов через доверенное хранилище системы
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/example.com.crt
# → /etc/ssl/certs/example.com.crt: OK

# 4. Проверка прав доступа к файлам сертификатов и закрытых ключей
ls -la /etc/ssl/private/example.com.key /etc/ssl/certs/example.com.crt
# → -rw-r----- 1 root www-data 1704 Oct 17 12:00 /etc/ssl/private/example.com.key
# → -rw-r--r-- 1 root root     3550 Oct 17 12:00 /etc/ssl/certs/example.com.crt

# 5. Верификация конфигурационных файлов Nginx на синтаксические ошибки
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 6. Применение изменений методом Graceful Reload (перечитывание сертификатов без остановки сервиса)
systemctl reload nginx

# 7. Контрольная верификация даты обновленного сертификата через TLS-рукопожатие
echo | openssl s_client -connect 127.0.0.1:443 -servername example.com 2>/dev/null | openssl x509 -noout -enddate
# → notAfter=Jan 15 23:59:59 2027 GMT
```

### 2. Локализация и устранение разорванной цепочки сертификатов (Incomplete Intermediate CA)

**Контекст:** Десктопные веб-браузеры открывают HTTPS-ресурс без ошибок (благодаря кэшированию Intermediate CA или механизму AIA-fetching), однако консольные утилиты (`curl`), мобильные приложения и микросервисы на Go/Java возвращают ошибку `unable to get local issuer certificate (20)`.

```bash
# 1. Воспроизведение ошибки через curl
curl -I https://example.com 2>&1 | grep -i "ssl"
# → curl: (60) SSL certificate problem: unable to get local issuer certificate

# 2. Анализ цепочки сертификатов, отдаваемой веб-сервером
openssl s_client -connect 127.0.0.1:443 -servername example.com -showcerts </dev/null 2>&1 | grep -E "s:|i:"
# →  0 s:CN = example.com
# →    i:C = US, O = Let's Encrypt, CN = R11
# (В выводе присутствует только узел 0; промежуточный центр R11 отсутствует!)

# 3. Извлечение URL-адреса промежуточного сертификата из расширения AIA конечного сертификата
openssl x509 -in /etc/ssl/certs/example.com.leaf.crt -noout -text | grep -A2 "Authority Information Access"
# → Authority Information Access:
# →     CA Issuers - URI:http://r11.i.lencr.org/

# 4. Загрузка недостающего промежуточного сертификата (в формате DER) и конвертация в PEM
curl -s http://r11.i.lencr.org/ -o /tmp/r11.der
openssl x509 -inform DER -in /tmp/r11.der -out /tmp/intermediate.pem

# 5. Сборка полного бандла (Full Chain): Сначала Leaf, затем Intermediate
cat /etc/ssl/certs/example.com.leaf.crt /tmp/intermediate.pem > /etc/ssl/certs/example.com.fullchain.crt

# 6. Проверка обновленного файла конфигурации и reload Nginx
sed -i 's|ssl_certificate .*|ssl_certificate /etc/ssl/certs/example.com.fullchain.crt;|' /etc/nginx/conf.d/example.com.conf
nginx -t && systemctl reload nginx
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 7. Финальная проверка: сервер отдает 2 сертификата, цепочка успешно валидируется
openssl s_client -connect 127.0.0.1:443 -servername example.com -CAfile /etc/ssl/certs/ca-certificates.crt </dev/null 2>&1 | grep "Verify return code"
# → Verify return code: 0 (ok)
```

### 3. Диагностика несовместимости шифронаборов и протоколов (`no shared cipher`)

**Контекст:** После обновления политик безопасности Nginx устаревший промышленный клиент или агент инвентаризации теряет связь с сервером. В журнале `/var/log/nginx/error.log` фиксируется ошибка: `SSL_do_handshake() failed: no shared cipher`.

```bash
# 1. Поиск записи об ошибке в системном журнале Nginx
grep "no shared cipher" /var/log/nginx/error.log | tail -n 2
# → 2026/10/17 14:15:22 [error] 4812#4812: *105 SSL_do_handshake() failed (SSL: error:0A0000C1:SSL routines::no shared cipher) while SSL handshaking, client: 192.168.10.45, server: 0.0.0.0:443

# 2. Определение активных шифров, сконфигурированных в Nginx
nginx -T 2>/dev/null | grep -E "ssl_protocols|ssl_ciphers" | head -n 4
# → ssl_protocols TLSv1.3;
# → ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;

# 3. Эмуляция запроса со стороны проблемного клиента (поддерживающего только TLS 1.2 и RSA-AES128-GCM)
openssl s_client -connect 127.0.0.1:443 -servername example.com -tls1_2 -cipher 'AES128-GCM-SHA256' </dev/null
# → 4097486848:error:0A000410:SSL routines:ssl3_read_bytes:sslv3 alert handshake failure:ssl/record/rec_layer_s3.c:1584:SSL alert number 40

# 4. Анализ списка доступных шифров OpenSSL на сервере (колонка $1 - имена шифров)
openssl ciphers -v 'HIGH:!aNULL:!kEDH' | awk '{print $1}' | grep "AES128-GCM"
# → ECDHE-ECDSA-AES128-GCM-SHA256
# → ECDHE-RSA-AES128-GCM-SHA256
# → AES128-GCM-SHA256

# 5. Добавление безопасного профиля обратной совместимости в nginx.conf
# Блок http / server:
# ssl_protocols TLSv1.2 TLSv1.3;
# ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';

# 6. Проверка синтаксиса и перезагрузка
nginx -t && systemctl reload nginx
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 7. Контрольный тест: успешное согласование TLS 1.2 с безопасным ECDHE-шифром
openssl s_client -connect 127.0.0.1:443 -servername example.com -tls1_2 </dev/null 2>&1 | grep -E "Protocol|Cipher"
# → Protocol  : TLSv1.2
# → Cipher    : ECDHE-RSA-AES256-GCM-SHA384
```

### 4. Диагностика зависаний TLS-сессий из-за MTU / PMTU Blackhole

**Контекст:** Сетевое соединение по HTTP (порт 80) и TCP ping проходят мгновенно, однако HTTPS-запросы к Nginx «зависают» после отправки `ClientHello`. Браузеры бесконечно ждут ответа, а утилита `curl -v` останавливается на строке `* TLSv1.3 (OUT), TLS handshake, Client hello (1):`.

```bash
# 1. Проявление симптома через verbose-вызов curl
curl -v -k https://192.168.1.100/ 2>&1 | head -n 12
# → *   Trying 192.168.1.100:443...
# → * Connected to 192.168.1.100 (192.168.1.100) port 443
# → * TLSv1.3 (OUT), TLS handshake, Client hello (1):
# (Зависание по таймауту 60 секунд)

# 2. Запуск захвата трафика на сервере для выявления retransmission пакетов
tcpdump -nn -i eth0 'tcp port 443' -c 10
# → IP 192.168.1.50.54321 > 192.168.1.100.443: Flags [P.], seq 1:518, ack 1 (ClientHello)
# → IP 192.168.1.100.443 > 192.168.1.50.54321: Flags [.], ack 518
# → IP 192.168.1.100.443 > 192.168.1.50.54321: Flags [P.], seq 1:2921, length 2920 (ServerHello + Cert)
# → IP 192.168.1.100.443 > 192.168.1.50.54321: Flags [P.], seq 1:2921, length 2920 (Retransmission!)
# (Сервер отправляет крупный сегмент 2920 байт, но подтверждение ACK от клиента не поступает)

# 3. Проверка текущего MTU на сетевом интерфейсе сервера
ip -br link show eth0
# → eth0             UP             1500 ...

# 4. Проверка прохождения ICMP сообщений Fragmentation Needed
sysctl net.ipv4.ip_no_pmtu_disc
# → net.ipv4.ip_no_pmtu_disc = 0

# 5. Оперативное устранение: принудительное ограничение TCP Maximum Segment Size (MSS) через nftables/iptables
iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -o eth0 -j TCPMSS --clamp-mss-to-pmtu
# или для явного ограничения размера:
iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -o eth0 -j TCPMSS --set-mss 1360

# 6. Контрольная верификация: повторный запрос завершается мгновенно
curl -I https://192.168.1.100/ --resolve example.com:443:192.168.1.100
# → HTTP/2 200
# → server: nginx
```

### 5. Сбои OCSP Stapling и таймауты внешних резолверов

**Контекст:** В журнале ошибок Nginx фиксируются сообщения: `ssl_stapling: no data` или `OCSP responder timed out`. Браузеры пользователей испытывают задержки до 2–5 секунд при первичном подключении.

```bash
# 1. Поиск сообщений OCSP в error.log
grep -i "stapling" /var/log/nginx/error.log | tail -n 2
# → 2026/10/17 15:02:11 [warn] 2104#2104: "ssl_stapling" ignored, no OCSP responder URL in the certificate
# → 2026/10/17 15:05:43 [error] 2104#2104: OCSP responder timed out (110: Connection timed out) while requesting certificate status

# 2. Проверка наличия OCSP URL в сертификате
openssl x509 -in /etc/ssl/certs/example.com.fullchain.crt -noout -ocsp_uri
# → http://ocsp.int-r11.letsencrypt.org

# 3. Ручной опрос OCSP-респондера с сервера Nginx
OCSP_URL=$(openssl x509 -in /etc/ssl/certs/example.com.fullchain.crt -noout -ocsp_uri)
openssl ocsp -issuer /tmp/intermediate.pem -cert /etc/ssl/certs/example.com.leaf.crt -url "$OCSP_URL" -header "Host" "ocsp.int-r11.letsencrypt.org" -text
# → Response verify OK
# → example.com.leaf.crt: good
# →         This Update: Oct 17 14:00:00 2026 GMT
# →         Next Update: Oct 24 14:00:00 2026 GMT

# 4. Проверка конфигурации директивы resolver в Nginx
nginx -T 2>/dev/null | grep -E "resolver |ssl_stapling"
# (Если директива resolver отсутствует, Nginx не может разрешить DNS-имя OCSP-респондера!)

# 5. Добавление локального системного DNS-резолвера и доверенного CA в конфигурацию (блок http)
# cat << 'EOF' > /etc/nginx/conf.d/ocsp_tuning.conf
# resolver 127.0.0.1 192.168.1.1 valid=300s ipv6=off;
# resolver_timeout 5s;
# ssl_stapling on;
# ssl_stapling_verify on;
# ssl_trusted_certificate /etc/ssl/certs/example.com.fullchain.crt;
# EOF

# 6. Проверка и перезагрузка Nginx
nginx -t && systemctl reload nginx

# 7. Контрольная проверка наличия OCSP-ответа в ServerHello
echo | openssl s_client -connect 127.0.0.1:443 -servername example.com -status 2>/dev/null | grep -A 4 "OCSP Response Data:"
# → OCSP Response Data:
# →     OCSP Response Status: successful (0x0)
# →     Cert Status: good
```

### 6. Диагностика сбоев HTTP/3 (QUIC) и сетевого транспорта UDP/443

**Контекст:** После включения поддержки протокола HTTP/3 клиенты продолжают подключаться по HTTP/2, либо подключения по UDP/443 обрываются по таймауту.

```bash
# 1. Проверка наличия модуля http_v3_module в установленном бинарнике Nginx
nginx -V 2>&1 | tr ' ' '\n' | grep 'with-http_v3_module'
# → --with-http_v3_module

# 2. Проверка прослушивания сокетов UDP на порту 443
ss -ulpn | grep :443
# → UNCONN 0      0            0.0.0.0:443        0.0.0.0:*    users:(("nginx",pid=3456,fd=8))

# 3. Проверка межсетевого экрана Linux (iptables / nftables) на пропуск входящего UDP-трафика
iptables -L INPUT -v -n | grep "dpt:443"
# →   125 15200 ACCEPT     udp  --  *      *       0.0.0.0/0            0.0.0.0/0            udp dpt:443

# 4. Проверка передачи HTTP-заголовка Alt-Svc в ответах HTTP/2
curl -I -k https://127.0.0.1/ -H "Host: example.com" 2>&1 | grep -i "alt-svc"
# → alt-svc: h3=":443"; ma=86400

# 5. Тестирование рукопожатия QUIC утилитой curl с поддержкой HTTP/3
curl --http3 -v -I https://example.com --resolve example.com:443:127.0.0.1 2>&1 | grep -E "HTTP/3|Connected"
# → * Connected to example.com (127.0.0.1) port 443
# → * Using HTTP/3 protocol
# → < HTTP/3 200
```

### 7. Диагностика ошибок Encrypted Client Hello (ECH) и DNS HTTPS/SVCB

**Контекст:** Клиенты с поддержкой ECH (Chrome 125+, Firefox 125+) получают ошибку `ERR_SSL_ECH_DECRYPTION_FAILED` при попытке подключения к защищенному домену.

```bash
# 1. Проверка активной директивы ssl_ech_file в конфигурации хоста
nginx -T 2>/dev/null | grep -B1 -A2 "ssl_ech"
# → server {
# →     server_name example.com;
# →     ssl_ech_file /etc/nginx/ssl/ech/example.com.ech;

# 2. Проверка содержимого файла ECH (должен содержать приватный ключ и метаданные ECHConfig)
head -n 2 /etc/nginx/ssl/ech/example.com.ech
# → -----BEGIN ECHCONFIG-----
# → AEX+DQBB5wAgACA...

# 3. Запрос публичной DNS-записи HTTPS (RFC 9460) через локальный резолвер dig
dig +short HTTPS example.com
# → 1 . alpn="h2,h3" ech="AEX+DQBB5wAgACAA4...="

# 4. Сверка контрольной суммы публичного ключа из DNS и локального ECHConfig
# (Несовпадение свидетельствует о незавершенной репликации DNS после плановой ротации ключа ECH)

# 5. Тестирование подключения с флагом ECH через openssl s_client (OpenSSL 3.5+)
openssl s_client -connect 127.0.0.1:443 -servername example.com -ech </dev/null 2>&1 | grep -i "ech"
# → ECH: accepted
```

---

## Операции и команды

### Диагностика рукопожатий через OpenSSL s_client

| Цель диагностики | Команда CLI | Ожидаемый результат / Маркер успеха |
| :--- | :--- | :--- |
| **Комплексная проверка TLS 1.3** | `openssl s_client -connect 127.0.0.1:443 -servername example.com -status -alpn h2` | `Protocol : TLSv1.3`, `OCSP response: successful (0x0)`, `ALPN protocol: h2` |
| **Проверка только TLS 1.2** | `openssl s_client -connect 127.0.0.1:443 -servername example.com -tls1_2` | `Protocol : TLSv1.2`, согласован безопасный ECDHE-шифр |
| **Проверка отказа в устаревшем TLS 1.0** | `openssl s_client -connect 127.0.0.1:443 -servername example.com -tls1` | Ошибка: `handshake failure` или `no protocols available` |
| **Дамп всех сертификатов цепочки** | `openssl s_client -connect 127.0.0.1:443 -servername example.com -showcerts` | Полный список сертификатов от 0 (Leaf) до N-1 (Intermediate) |
| **Строгая проверка через CAfile** | `openssl s_client -connect 127.0.0.1:443 -servername example.com -CAfile /etc/ssl/certs/ca-certificates.crt -verify_return_error` | `Verify return code: 0 (ok)` |
| **Проверка сессионных тикетов** | `openssl s_client -connect 127.0.0.1:443 -servername example.com -reconnect` | `Re-use session-id: YES` при повторном подключении |
| **Проверка fallback без SNI** | `openssl s_client -connect 127.0.0.1:443 -noservername` | Отклонение соединения (`ssl_reject_handshake`) или выдача дефолтного сертификата |

### Захват и анализ TLS-пакетов через tcpdump и tshark

Перехват сетевого трафика позволяет расследовать аномалии, не попадающие в журналы Nginx (сбросы соединений RST, MTU blackhole, отброшенные фаерволом пакеты):

```bash
# 1. Захват пакетов TLS ClientHello (код типа записи 0x16 = Handshake, смещение типа сообщения 0x01 = ClientHello)
tcpdump -nn -i any 'tcp port 443 and (tcp[((tcp[12:1] & 0xf0) >> 2):1] = 0x16) and (tcp[((tcp[12:1] & 0xf0) >> 2) + 5:1] = 0x01)' -c 5
# → IP 192.168.1.50.48120 > 192.168.1.100.443: Flags [P.], length 517

# 2. Захват пакетов с сообщениями TLS Alert (код типа записи 0x15 = Alert)
tcpdump -nn -i any 'tcp port 443 and (tcp[((tcp[12:1] & 0xf0) >> 2):1] = 0x15)' -vv -c 5
# → IP 192.168.1.100.443 > 192.168.1.50.48120: Flags [P.], length 7 (TLS Alert Fatal)

# 3. Декодирование расширений TLS SNI и версий протокола через tshark в реальном времени
tshark -i eth0 -f "tcp port 443" -Y "tls.handshake.type == 1" \
  -T fields -e ip.src -e tls.handshake.extensions_server_name -e tls.handshake.version
# → 192.168.1.50    example.com    0x0303

# 4. Анализ причин сброса TCP соединений (RST флаги) в процессе TLS-рукопожатия
tcpdump -nn -i eth0 'tcp port 443 and (tcp[tcpflags] & tcp-rst != 0)' -c 10
# → IP 192.168.1.100.443 > 192.168.1.50.48120: Flags [R.], seq 0, ack 518
```

### Комплексный локальный аудит через testssl.sh

Утилита **testssl.sh** — автономный скрипт командной строки для аудита TLS без отправки данных сторонним сервисам (Zero Cloud):

```bash
# 1. Быстрый локальный аудит протоколов и сертификата
testssl.sh --fast --warnings batch https://127.0.0.1:443/
# → Testing protocols via sockets:
# →  SSLv2      not offered (OK)
# →  SSLv3      not offered (OK)
# →  TLS 1      not offered (OK)
# →  TLS 1.1    not offered (OK)
# →  TLS 1.2    offered (OK)
# →  TLS 1.3    offered (OK)

# 2. Проверка сервера на распространенные уязвимости (Heartbleed, CCS Injection, Ticketbleed)
testssl.sh -U https://127.0.0.1:443/
# → Vulnerabilities:
# →  Heartbleed: not vulnerable (OK)
# →  CCS:        not vulnerable (OK)
# →  Ticketbleed: not vulnerable (OK)
# →  ROBOT:      not vulnerable (OK)

# 3. Полный аудит с формированием структурированного JSON-отчета для системного архива
testssl.sh --jsonfile /var/log/nginx/tls_audit_$(date +%F).json https://127.0.0.1:443/
```

### Мониторинг сокетов и системных буферов ядра через ss

```bash
# 1. Проверка слушающих TCP-сокетов с очередями Send-Q / Recv-Q
ss -tlnp '( sport = :443 )'
# → State   Recv-Q  Send-Q   Local Address:Port   Peer Address:Port  Process
# → LISTEN  0       511            0.0.0.0:443        0.0.0.0:*      users:(("nginx",pid=1234,fd=6))

# 2. Проверка слушающих сокетов UDP для протокола QUIC
ss -ulpn '( sport = :443 )'
# → State   Recv-Q  Send-Q   Local Address:Port   Peer Address:Port  Process
# → UNCONN  0       0              0.0.0.0:443        0.0.0.0:*      users:(("nginx",pid=1234,fd=7))

# 3. Детальная статистика активных TLS-соединений (RTT, потери пакетов, размер окна TCP)
ss -ti '( dport = :443 or sport = :443 )' | head -n 4
# → skmem:(r0,rb131072,t0,tb16384,f0,w0,o0,bl0,d0)
# → rtt:14.2/0.8 mss:1460 rcvspace:64240 ssthresh:10 cwnd:10
```

### Парсинг и аудит журналов Nginx

```bash
# 1. Статистика по используемым версиям протоколов TLS из журнала tls_audit.log
awk -F'proto=' '{print $2}' /var/log/nginx/tls_audit.log | awk '{print $1}' | sort | uniq -c | sort -rn
# → 48201 TLSv1.3
# →  3105 TLSv1.2

# 2. Подсчет распределения согласованных шифронаборов
awk -F'cipher=' '{print $2}' /var/log/nginx/tls_audit.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -n 5
# → 35120 TLS_AES_256_GCM_SHA384
# → 13081 TLS_AES_128_GCM_SHA256
# →  2100 ECDHE-RSA-AES256-GCM-SHA384
# →  1005 ECDHE-RSA-AES128-GCM-SHA256

# 3. Эффективность кэширования сессий (Session Reuse Rate)
awk -F'session_reused=' '{print $2}' /var/log/nginx/tls_audit.log | awk '{print $1}' | sort | uniq -c
# → 38100 r      # (resumed - сессия восстановлена без полного рукопожатия)
# → 13206 .      # (full handshake - выполнено полное асимметричное рукопожатие)
```

---

## Устранение неполадок

### Исчерпывающая матрица типовых ошибок TLS в Nginx

| Симптом / Текст ошибки в журнале `error.log` | Код OpenSSL / Alert | Первопричина | Метод локализации | Решение |
| :--- | :--- | :--- | :--- | :--- |
| `SSL_do_handshake() failed: no shared cipher` | `0x0A0000C1` / Alert 40 | Клиент и сервер не имеют общих шифронаборов (например, клиент умеет только CBC, а сервер требует GCM/CHACHA). | `openssl ciphers -v` на сервере; `tcpdump` для разбора `ClientHello`. | Включить безопасный набор шифров в `ssl_ciphers` или добавить TLS 1.2 в `ssl_protocols`. |
| `SSL_do_handshake() failed: alert handshake failure (40)` | Alert 40 (`handshake_failure`) | Клиент запросил SNI, который попал на `default_server` с `ssl_reject_handshake on;`, либо клиент не поддерживает SNI. | Проверить имя в запросе через `openssl s_client -servername <name>`. | Проверить сопоставление `server_name` и сертификата; настроить валидный fallback-хост. |
| `peer closed connection in SSL handshake (104: Connection reset by peer)` | TCP RST | Клиент разорвал TCP-соединение во время рукопожатия (не доверяет сертификату, таймаут или промежуточный DPI сбросил сессию). | Захват `tcpdump -nn -i any 'tcp port 443'`; проверка клиентских логов. | Проверить валидность цепочки сертификатов на сервере; проверить настройки MTU/PMTU. |
| `unable to get local issuer certificate` | OpenSSL verify error 20 | Разорвана цепочка сертификатов: Nginx отдает только Leaf-сертификат без Intermediate CA. | `openssl s_client -showcerts` показывает только 1 сертификат. | Собрать `fullchain.crt` (Leaf + Intermediate) и указать его в `ssl_certificate`. |
| `certificate has expired` | OpenSSL verify error 10 | Истек срок действия сертификата сервера (или сбиты системные часы на сервере/клиенте). | `openssl x509 -noout -dates -in cert.crt`; сверка системного времени `timedatectl`. | Обновить сертификат; синхронизировать системное время по NTP (`chronyd`/`systemd-timesyncd`). |
| `cannot load certificate ... BIO_new_file() failed (Permission denied)` | POSIX `EACCES` (13) | Рабочий процесс Nginx (пользователь `www-data`/`nginx`) не имеет прав на чтение файла сертификата или каталога. | `namei -l /etc/ssl/private/server.key`. | Выставить права `0640` на ключ, владельца `root:www-data`, права `0750` на родительские каталоги. |
| `cannot load certificate key ... key values mismatch` | OpenSSL error `0x0A080006` | Приватный ключ не соответствует открытому ключу в загруженном файле сертификата. | Сравнить модуль: `openssl x509 -noout -modulus` и `openssl rsa -noout -modulus`. | Перевыпустить сертификат с соответствующим ключом или восстановить ключ из резервной копии. |
| `ssl_stapling: no data` / `OCSP responder timed out` | Nginx core warn/error | Nginx не может связаться с сервером OCSP (заблокирован исходящий порт 80/53 или не задан `resolver`). | `grep resolver /etc/nginx/nginx.conf`; ручной опрос через `openssl ocsp`. | Добавить директиву `resolver 127.0.0.1 valid=300s;` в блок `http` и открыть исходящий HTTP к OCSP. |
| `ECH decryption failed` | ECH alert 121 | Рассинхронизация ключей: клиент зашифровал SNI ключом из DNS, отсутствующим в `ssl_ech_file`. | Проверить запись `dig +short HTTPS domain.com` и содержимое `ssl_ech_file`. | Обновить `ssl_ech_file` актуальными ключами или обновить DNS-запись HTTPS/SVCB. |
| `400 Bad Request (The plain HTTP request was sent to HTTPS port)` | Nginx HTTP status 497 | Клиент обратился по протоколу plain HTTP к порту, на котором Nginx ожидает TLS-рукопожатие. | Проверить адрес запроса: `curl http://domain.com:443/`. | Настроить обработку ошибки 497 через директиву `error_page 497 =301 https://$host:$server_port$request_uri;`. |
| `400 Bad Request (No required SSL certificate was sent)` | Nginx HTTP status 496 | Включен mTLS (`ssl_verify_client on;`), но клиент не передал персональный сертификат в Client Certificate. | Проверить конфигурацию `ssl_verify_client`; протестировать `curl --cert client.crt --key client.key`. | Предоставить клиенту корректный сертификат, подписанный доверенным центром из `ssl_client_certificate`. |
| `400 Bad Request (SSL certificate error)` | Nginx HTTP status 495 | Клиент передал невалидный mTLS-сертификат (просрочен, отозван по CRL или подписан неизвестным CA). | Проверить client cert через `openssl verify -CAfile /etc/nginx/ssl/client_ca.crt client.crt`. | Перевыпустить клиентский сертификат, обновить файл CRL (`ssl_crl`) или цепочку CA. |
| `425 Too Early` | HTTP status 425 | Nginx отклонил небезопасный запрос (POST/PUT/DELETE), отправленный клиентом в 0-RTT Early Data (защита от Replay). | Проверить `$ssl_early_data` в `access_log`. | Разрешать 0-RTT только для идемпотентных запросов (GET/HEAD) через проверку `$ssl_early_data`. |

### Безопасная точечная отладка в production через debug_connection

Глобальное включение уровня `debug` в `error_log` на высоконагруженном сервере приводит к генерации сотен мегабайт логов в секунду и деградации дисковой подсистемы. Nginx предоставляет механизм изоляции отладки для конкретного IP-адреса инженера SRE:

```nginx
# /etc/nginx/nginx.conf

events {
    worker_connections 2048;
    # Детальный отладочный лог будет писаться ТОЛЬКО для запросов с этого IP:
    debug_connection 192.168.1.55;
    debug_connection 10.10.0.0/24;
}

http {
    # Основной лог остается на безопасном уровне warn или notice:
    error_log /var/log/nginx/error.log warn;
    ...
}
```

После выполнения `nginx -t && systemctl reload nginx` все подключения с адреса `192.168.1.55` будут подробно логироваться со всеми внутренними состояниями OpenSSL в `/var/log/nginx/error.log`.

### Разбор структуры TLS Handshake в Nginx Debug Log

При активации `debug_connection` в журнале фиксируются следующие ключевые маркеры рукопожатия:

```text
2026/10/17 15:30:01 [debug] 4812#4812: *1 SSL server name: "example.com"
2026/10/17 15:30:01 [debug] 4812#4812: *1 SSL ALPN supported by client: h2, http/1.1
2026/10/17 15:30:01 [debug] 4812#4812: *1 SSL ALPN selected: h2
2026/10/17 15:30:01 [debug] 4812#4812: *1 SSL ciphers: TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-RSA-AES256-GCM-SHA384...
2026/10/17 15:30:01 [debug] 4812#4812: *1 SSL certificate: "/etc/ssl/certs/example.com.fullchain.crt"
2026/10/17 15:30:01 [debug] 4812#4812: *1 SSL verify depth: 1
2026/10/17 15:30:01 [debug] 4812#4812: *1 SSL handshake: done
```

Если рукопожатие прерывается, последняя строка указывает на точный шаг:
- `SSL_do_handshake() failed (SSL: error:0A000418:SSL routines::tlsv1 alert unrecognized name)` — клиент передал SNI, отвергнутый директивой `ssl_reject_handshake on`.
- `SSL_do_handshake() failed (SSL: error:0A0000C1:SSL routines::no shared cipher)` — отсутствие совместимых шифров.

### Обработка нестандартных HTTP-статусов Nginx (495, 496, 497)

Nginx транслирует внутренние ошибки TLS в специальные HTTP-коды. Для обеспечения прозрачности клиентам рекомендуется настраивать кастомные обработчики:

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate /etc/ssl/certs/api.example.com.fullchain.crt;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;

    # Автоматический редирект клиентов, обратившихся по HTTP на порт HTTPS
    error_page 497 =301 https://$host:$server_port$request_uri;

    # Информативные JSON-ответы при ошибках клиентских сертификатов (mTLS)
    error_page 495 @error_mtls_invalid;
    error_page 496 @error_mtls_missing;

    location @error_mtls_invalid {
        default_type application/json;
        return 400 '{"error": "invalid_client_certificate", "message": "Client certificate validation failed"}';
    }

    location @error_mtls_missing {
        default_type application/json;
        return 401 '{"error": "certificate_required", "message": "Mutual TLS requires a valid client certificate"}';
    }
}
```

---

## Рекомендации и лучшие практики

### Матрица совместимости клиентов (Baseline 2026)

| Категория клиентов | Минимальная версия | Поддерживаемые протоколы | Особенности согласования | Рекомендации по конфигурации Nginx |
| :--- | :--- | :--- | :--- | :--- |
| **Современные браузеры** | Chrome 125+, Firefox 125+, Edge 125+ | TLS 1.3, TLS 1.2, HTTP/3, ECH | Полная поддержка Hybrid PQC (X25519MLKEM768), ALPN (`h2`, `h3`). | Базовый профиль: TLS 1.3 + TLS 1.2 с AEAD-шифрами. |
| **Apple экосистема** | iOS 18+, macOS 15+ (Sequoia) | TLS 1.3, TLS 1.2, HTTP/3 | Нативная поддержка ECH через системный DNS-резолвер. | Требуются валидные DNS-записи HTTPS (RFC 9460). |
| **Legacy Android** | Android 8.0 – 11.0 | TLS 1.2 (TLS 1.3 частично) | Не поддерживают ECH и PQC; требуют классических RSA/ECDHE шифронаборов. | Обязательно сохранять `ECDHE-RSA-AES128-GCM-SHA256` в `ssl_ciphers`. |
| **CLI-утилиты** | curl 8.x+, git 2.40+, wget 1.24+ | TLS 1.3, TLS 1.2 | Жесткая проверка доверенной цепочки без AIA-fetching. | Обязательна полная цепочка (Full Chain) в `ssl_certificate`. |
| **Java Runtime** | OpenJDK 17+, OpenJDK 21+ | TLS 1.3, TLS 1.2 | Поддержка TLS 1.3 по умолчанию; строгая валидация длины ключей (DH >= 2048). | Избегать устаревших кривых и DHE-шифров ниже 2048 бит. |
| **Python / Go / Node** | Python 3.10+, Go 1.22+, Node.js 20+ | TLS 1.3, TLS 1.2 | Go нативно поддерживает TLS 1.3 и HTTP/2; Python использует системный OpenSSL. | Наличие ALPN `h2` обязательно для оптимальной производительности. |

> [!WARNING]
> Протоколы **TLS 1.0 и TLS 1.1 полностью признаны устаревшими (RFC 8996)** и отключены во всех современных дистрибутивах Linux и версиях OpenSSL 3.x. Включение TLS 1.0/1.1 не допускается стандартом PCI-DSS и отраслевыми регламентами безопасности.

### SRE Runbook реагирования на инциденты TLS

1. **Шаг 1: Первичная локализация (Срок < 2 минут):**
   - Выполнить проверку синтаксиса на проблемном сервере: `nginx -t`.
   - Проверить срок действия сертификата через внешний опрос: `openssl s_client -connect 127.0.0.1:443 -servername <domain> | openssl x509 -noout -dates`.
2. **Шаг 2: Анализ сетевого стека и сокетов (Срок < 5 минут):**
   - Проверить наличие слушающих сокетов: `ss -tlnpn | grep :443` и `ss -ulpn | grep :443`.
   - Убедиться в отсутствии дропов в правилах фаервола: `iptables -vnL INPUT`.
3. **Шаг 3: Проверка цепочки и закрытого ключа (Срок < 7 минут):**
   - Сверить модуль сертификата и ключа (`openssl x509 -modulus` == `openssl rsa -modulus`).
   - Убедиться, что в `ssl_certificate` прописан `fullchain.crt`, а не одиночный `cert.crt`.
4. **Шаг 4: Активация точечной отладки (Срок < 10 минут):**
   - В блоке `events` прописать `debug_connection <SRE_IP>;`.
   - Выполнить `systemctl reload nginx` и исследовать детальный лог рукопожатия.
5. **Шаг 5: Восстановление сервиса (Срок < 15 минут):**
   - Применить исправленные конфигурационные файлы или сертификаты.
   - Проверить через `nginx -t && systemctl reload nginx`.
   - Провести верификацию запросом `curl -Iv https://<domain>/`.

### On-prem Observability: Мониторинг сертификатов для Prometheus

Для отслеживания сроков действия SSL-сертификатов без внешних SaaS/Cloud-сервисов используется локальный скрипт генерации метрик для **Prometheus Node Exporter (Textfile Collector)**:

```bash
#!/usr/bin/env bash
# /usr/local/bin/ssl_cert_exporter.sh
# Скрипт генерации метрик срока действия локальных сертификатов Nginx
set -euo pipefail

TEXTFILE_DIR="/var/lib/node_exporter/textfile_collector"
TMP_FILE="${TEXTFILE_DIR}/ssl_certs.prom.tmp"
TARGET_FILE="${TEXTFILE_DIR}/ssl_certs.prom"

cat << 'EOF' > "$TMP_FILE"
# HELP ssl_certificate_expiry_timestamp_seconds Unix timestamp of SSL certificate expiration
# TYPE ssl_certificate_expiry_timestamp_seconds gauge
# HELP ssl_certificate_days_left Days left until SSL certificate expiration
# TYPE ssl_certificate_days_left gauge
EOF

NOW=$(date +%s)

for CERT_FILE in /etc/ssl/certs/*.fullchain.crt /etc/letsencrypt/live/*/fullchain.pem; do
    [ -f "$CERT_FILE" ] || continue
    DOMAIN=$(basename "$(dirname "$CERT_FILE")")
    [ "$DOMAIN" = "certs" ] && DOMAIN=$(basename "$CERT_FILE" .fullchain.crt)
    
    EXPIRY_DATE=$(openssl x509 -enddate -noout -in "$CERT_FILE" | cut -d= -f2)
    EXPIRY_TS=$(date -d "$EXPIRY_DATE" +%s)
    DAYS_LEFT=$(( (EXPIRY_TS - NOW) / 86400 ))

    echo "ssl_certificate_expiry_timestamp_seconds{domain=\"${DOMAIN}\",path=\"${CERT_FILE}\"} ${EXPIRY_TS}" >> "$TMP_FILE"
    echo "ssl_certificate_days_left{domain=\"${DOMAIN}\",path=\"${CERT_FILE}\"} ${DAYS_LEFT}" >> "$TMP_FILE"
done

mv "$TMP_FILE" "$TARGET_FILE"
```

Добавление задачи в системный планировщик `cron` (запуск раз в 6 часов):

```cron
# /etc/cron.d/ssl_cert_monitor
0 */6 * * * root /usr/local/bin/ssl_cert_exporter.sh > /dev/null 2>&1
```

### Правила алертинга Prometheus (Alertmanager)

Файл правил для локального сервера Prometheus (`/etc/prometheus/rules/ssl_alerts.yml`):

```yaml
groups:
  - name: ssl_certificate_alerts
    rules:
      - alert: SSLCertificateExpiringSoon
        expr: ssl_certificate_days_left <= 30
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "SSL сертификат домена {{ $labels.domain }} истекает менее чем через 30 дней"
          description: "Осталось дней: {{ $value }}. Проверьте службу автоматической ротации."

      - alert: SSLCertificateCriticalExpiring
        expr: ssl_certificate_days_left <= 7
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "КРИТИЧЕСКИЙ СРОК: SSL сертификат {{ $labels.domain }} истекает менее чем через 7 дней"
          description: "Осталось дней: {{ $value }}. Требуется ручная ротация сертификата!"

      - alert: NginxTLSHandshakeFailureRateHigh
        expr: rate(nginx_tls_handshake_failures_total[5m]) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Всплеск ошибок TLS-рукопожатий на сервере {{ $labels.instance }}"
          description: "Частота сбоев TLS handshake превышает 10 ошибок в секунду."
```

### Конфигурация логирования и ротация через logrotate

Конфигурация расширенного журнала аудита TLS в `/etc/nginx/conf.d/tls_audit_log.conf`:

```nginx
log_format tls_audit '$remote_addr [$time_local] "$request" '
                     'status=$status proto=$ssl_protocol cipher=$ssl_cipher '
                     'curves=$ssl_curves ech=$ssl_ech_status '
                     'session_reused=$ssl_session_reused hand_time=$ssl_handshake_time';

access_log /var/log/nginx/tls_audit.log tls_audit buffer=32k flush=5s;
```

Конфигурация ротации без разрыва соединений в `/etc/logrotate.d/nginx`:

```text
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        if [ -f /var/run/nginx.pid ]; then
            kill -USR1 $(cat /var/run/nginx.pid)
        fi
    endscript
}
```

> [!NOTE]
> Сигнал `USR1` указывает мастер-процессу Nginx переоткрыть дескрипторы всех файлов журналов без остановки или перезапуска рабочих процессов, исключая потерю входящих записей.

### Влияние диагностических инструментов на производительность

| Инструмент | Потребление CPU | Потребление памяти / Дисковый I/O | Рекомендации по эксплуатации |
| :--- | :--- | :--- | :--- |
| `error_log debug` (глобальный) | Высокое (+30–50% CPU) | Экстремальный I/O (до 100 МБ/с) | **Категорически запрещен на production!** Использовать только в lab/staging. |
| `events { debug_connection IP; }` | Минимальное (<1%) | Низкий (пишется только лог одного IP) | **Рекомендованный SRE-стандарт** для точечной отладки инцидентов на production. |
| `error_log info` | Низкое (+2–3% CPU) | Умеренный I/O (логгирование попыток handshake) | Допустим временно в production в период расследования инцидента. |
| `tcpdump / tshark` | Среднее (+5–15% CPU) | Зависит от фильтра (`-c` или буфер pcap) | Всегда ограничивать интерфейс (`-i eth0`), фильтр портов и лимит пакетов (`-c 100`). |
| `testssl.sh` | Низкое на сервере | 0 на сервере (нагрузка на тестовый узел) | Безопасен для локального тестирования в любое время. |
| `tls_audit.log` | Минимальное (<1% CPU) | Низкий (при использовании `buffer=32k flush=5s`) | Рекомендуется для постоянного аудита клиентской совместимости. |

---

## Дополнительная информация

### См. также

* **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура подсистемы TLS, криптография, ECH, PQC и жизненный цикл соединения.
* **[Глобальные параметры TLS в Nginx](./nginx_tls_global_parameters.md)** — настройка блока `http`: протоколы, шифронаборы, кэш сессий, kTLS и OCSP.
* **[Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md)** — настройка блоков `server`: привязка сертификатов, default_server, 0-RTT и ECH.
* **[Настройка Mutual TLS (mTLS) в Nginx](./nginx_mtls_configuration.md)** — регламент развертывания взаимной аутентификации, управление списками отзыва CRL и верификация клиентов.
* **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — общая методология анализа системных сбоев веб-сервера, анализ сигналов процессов и кодов 5xx.
* **[Диагностика SSL/TLS сертификатов](../../../Security/Tools/ssl_certificate_diagnostics.md)** — системные утилиты CLI для глубокой верификации ключей и сертификатов X.509.
* **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)** — фундаментальная теория криптографических примитивов, фаз рукопожатия и устройства симметричного шифрования.

### Стандарты и спецификации RFC

* **RFC 8446** — The Transport Layer Security (TLS) Protocol Version 1.3
* **RFC 5246** — The Transport Layer Security (TLS) Protocol Version 1.2
* **RFC 6066** — Transport Layer Security (TLS) Extensions: Extension Definitions (SNI, OCSP Stapling)
* **RFC 6960** — X.509 Internet Public Key Infrastructure Online Certificate Status Protocol - OCSP
* **RFC 9460** — Service Binding and Parameter Specification via the DNS (SVCB and HTTPS Resource Records)
* **RFC 7301** — Transport Layer Security (TLS) Application-Layer Protocol Negotiation Extension (ALPN)
* **RFC 8996** — Deprecating TLS 1.0 and TLS 1.1
* **RFC 9000** — QUIC: A UDP-Based Multiplexed and Secure Transport
