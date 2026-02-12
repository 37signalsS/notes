# Защита от DDoS атак и WAF

## Определения

**DDoS (Distributed Denial of Service)** — это распределенная атака типа "отказ в обслуживании", при которой множество скомпрометированных устройств (ботнет) одновременно отправляют запросы к целевому серверу или сети с целью исчерпания его ресурсов и вывода из строя.

**WAF (Web Application Firewall)** — это межсетевой экран прикладного уровня (L7), который фильтрует, мониторит и блокирует HTTP/HTTPS-трафик на основе набора правил, защищая веб-приложения от атак.

## Типы DDoS атак

### 1. Атаки на канальный уровень (L3/L4)

**Volumetric attacks (Объемные):**
- **UDP Flood:** Массовая отправка UDP-пакетов на случайные порты
- **ICMP Flood (Ping of Death):** Перегрузка через ICMP echo-request
- **DNS Amplification:** Использование открытых DNS-серверов для усиления трафика
- **NTP Amplification:** Аналогично DNS, используя NTP сервера

**Protocol attacks:**
- **SYN Flood:** Исчерпание таблицы соединений полуоткрытыми TCP-соединениями
- **ACK Flood:** Массовая отправка ACK-пакетов
- **Fragmentation attacks:** Атаки с использованием фрагментированных пакетов

### 2. Атаки на прикладной уровень (L7)

**Application layer attacks:**
- **HTTP Flood:** Массовые GET/POST запросы к веб-приложению
- **Slowloris:** Медленная отправка HTTP-заголовков для исчерпания соединений
- **Slow POST:** Медленная отправка тела запроса
- **RUDY (R-U-Dead-Yet):** Аналогично Slow POST
- **LOIC/HOIC:** Инструменты для массовых HTTP-запросов

**Resource exhaustion:**
- **Complex search queries:** Тяжелые запросы к базе данных
- **Login attacks:** Массовые попытки аутентификации
- **API abuse:** Злоупотребление API endpoints

## Методы защиты от DDoS

### 1. Инфраструктурная защита

**Rate Limiting (Ограничение скорости):**
```nginx
# Nginx rate limiting
limit_req_zone $binary_remote_addr zone=one:10m rate=10r/s;

server {
    location / {
        limit_req zone=one burst=20 nodelay;
    }
}
```

```bash
# iptables rate limiting
iptables -A INPUT -p tcp --dport 80 -m limit --limit 25/minute --limit-burst 100 -j ACCEPT
iptables -A INPUT -p tcp --dport 80 -j DROP
```

**Connection Limiting:**
```nginx
# Ограничение количества соединений с одного IP
limit_conn_zone $binary_remote_addr zone=addr:10m;

server {
    location / {
        limit_conn addr 10;
    }
}
```

**SYN Cookies:**
```bash
# Включение SYN cookies (защита от SYN flood)
sysctl -w net.ipv4.tcp_syncookies=1
```

### 2. Сетевая защита

**Blackholing (RTBH - Remotely Triggered Black Hole):**
- Анонс маршрута к атакуемому IP в null0 на уровне провайдера
- Полное отбрасывание трафика до целевого сервера
- Используется при массивных атаках для защиты инфраструктуры

**Traffic Scrubbing:**
- Перенаправление трафика через центры очистки
- Фильтрация легитимного и вредоносного трафика
- Возврат очищенного трафика через GRE/VPN

**Anycast:**
- Распределение трафика между множеством точек присутствия (PoP)
- Поглощение атаки за счет масштаба
- Автоматическое перенаправление при отказе

### 3. Облачная защита

**CDN-based protection:**
- CloudFlare, Akamai, AWS CloudFront, Fastly
- Поглощение трафика на уровне CDN
- Кэширование статики, защита origin-сервера

**Dedicated DDoS protection services:**
- AWS Shield (Standard/Advanced)
- Google Cloud Armor
- Azure DDoS Protection
- Imperva Incapsula

### 4. Application-level защита

**Challenge-Response:**
- CAPTCHA для подозрительных запросов
- JavaScript challenges (проверка браузера)
- Cookie-based challenges

**Behavioral analysis:**
- Анализ паттернов поведения
- Отличие ботов от реальных пользователей
- ML-based детекция аномалий

## Web Application Firewall (WAF)

### Функции WAF

1. **Защита от OWASP Top 10:**
   - SQL Injection
   - XSS (Cross-Site Scripting)
   - CSRF (Cross-Site Request Forgery)
   - LFI/RFI (Local/Remote File Inclusion)
   - Command Injection

2. **Фильтрация трафика:**
   - Проверка HTTP-заголовков
   - Валидация параметров запроса
   - Блокировка вредоносных payloads

3. **Virtual Patching:**
   - Быстрая защита от известных уязвимостей
   - Без изменения кода приложения

### Типы WAF

**1. Network-based WAF (Hardware):**
- Физические устройства в ЦОД
- Высокая производительность
- Высокая стоимость

**2. Host-based WAF (Software):**
- Установка на сервере
- ModSecurity для Apache/Nginx
- Бесплатные и коммерческие решения

**3. Cloud WAF:**
- SaaS-решения
- CloudFlare WAF
- AWS WAF
- Azure Application Gateway WAF

### Примеры WAF правил

**ModSecurity (CRS - Core Rule Set):**
```apache
# Защита от SQL Injection
SecRule REQUEST_COOKIES|REQUEST_COOKIES_NAMES|REQUEST_FILENAME|ARGS_NAMES|ARGS|XML:/* \
    "@rx (?i:(?:select\s*\*\s*from|(?:delete|drop|truncate)\s+table|union(?:\s+all)?\s*select|insert\s+into\s+.+?values))" \
    "id:942100,phase:2,deny,status:403,msg:'SQL Injection Attack Detected'"

# Защита от XSS
SecRule REQUEST_COOKIES|REQUEST_COOKIES_NAMES|REQUEST_FILENAME|ARGS_NAMES|ARGS|XML:/* \
    "@rx (?i:<script|javascript:|on\w+\s*=)" \
    "id:941100,phase:2,deny,status:403,msg:'XSS Attack Detected'"
```

**AWS WAF Rules:**
```json
{
  "Name": "SQLInjectionProtection",
  "Priority": 1,
  "Statement": {
    "SqliMatchStatement": {
      "FieldToMatch": {
        "Body": {}
      },
      "TextTransformations": [
        {
          "Priority": 0,
          "Type": "URL_DECODE"
        }
      ]
    }
  },
  "Action": {
    "Block": {}
  },
  "VisibilityConfig": {
    "SampledRequestsEnabled": true,
    "CloudWatchMetricsEnabled": true,
    "MetricName": "SQLInjectionProtection"
  }
}
```

## Архитектура защиты

### Layered Defense (Защита в глубину)

```
┌─────────────────────────────────────────────────────────────┐
│                    DDoS Protection                          │
│         (CloudFlare/AWS Shield/Imperva)                     │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                        WAF                                  │
│              (Application Layer Protection)                 │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    Load Balancer                            │
│              (Rate Limiting, Health Checks)                 │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    Application                              │
│          (Input Validation, Authentication)                 │
└─────────────────────────────────────────────────────────────┘
```

### Best Practices

1. **Defense in depth:** Многоуровневая защита
2. **Monitoring и alerting:** Отслеживание аномалий
3. **Incident response plan:** План реагирования на инциденты
4. **Regular testing:** Тестирование защиты (stress testing)
5. **Capacity planning:** Запас мощности для поглощения атак
6. **Geographic filtering:** Блокировка трафика из подозрительных регионов

### Метрики для мониторинга

- Requests per second (RPS)
- Bandwidth utilization
- Connection count per IP
- Error rate (4xx, 5xx)
- Response time (latency)
- Geographic distribution of traffic

## Практические сценарии

### Сценарий 1: Защита веб-приложения

```yaml
# Kubernetes + Ingress + ModSecurity
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: protected-app
  annotations:
    nginx.ingress.kubernetes.io/enable-modsecurity: "true"
    nginx.ingress.kubernetes.io/enable-owasp-core-rules: "true"
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        backend:
          service:
            name: app-service
            port:
              number: 80
```

### Сценарий 2: Rate limiting с fail2ban

```bash
# Настройка fail2ban для защиты от brute-force
# /etc/fail2ban/jail.local
[nginx-limit-req]
enabled = true
filter = nginx-limit-req
action = iptables-multiport[name=ReqLimit, port="http,https", protocol=tcp]
logpath = /var/log/nginx/error.log
findtime = 600
bantime = 7200
maxretry = 10
```

### Сценарий 3: CloudFlare + Origin protection

```nginx
# Nginx - разрешить только CloudFlare IP
allow 173.245.48.0/20;
allow 103.21.244.0/22;
# ... другие CloudFlare ranges
deny all;

# Проверка подлинности запроса от CloudFlare
set $cf_check "false";
if ($http_cf_connecting_ip != "") {
    set $cf_check "true";
}
if ($cf_check = "false") {
    return 403;
}
```

## Дополнительная информация

- [OWASP DDoS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html)
- [CloudFlare DDoS Protection](https://www.cloudflare.com/ddos/)
- [AWS Best Practices for DDoS Resiliency](https://docs.aws.amazon.com/whitepapers/latest/aws-best-practices-ddos-resiliency/welcome.html)
- [ModSecurity Documentation](https://modsecurity.org/)
