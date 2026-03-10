# DDoS (Distributed Denial of Service)

## Определения

**DDoS (Distributed Denial of Service)** — это распределенная атака типа "отказ в обслуживании", при которой множество скомпрометированных устройств (ботнет) одновременно отправляют запросы к целевому серверу или сети с целью исчерпания его ресурсов и вывода из строя.

## Основные концепции

### Типы DDoS атак

#### 1. Атаки на канальный уровень (L3/L4)

* **Volumetric attacks (Объемные):**
  * **UDP Flood:** Массовая отправка UDP-пакетов на случайные порты.
  * **ICMP Flood (Ping of Death):** Перегрузка через ICMP echo-request.
  * **DNS Amplification:** Использование открытых DNS-серверов для усиления трафика.
  * **NTP Amplification:** Аналогично DNS, используя NTP сервера.
* **Protocol attacks:**
  * **SYN Flood:** Исчерпание таблицы соединений полуоткрытыми TCP-соединениями.
  * **ACK Flood:** Массовая отправка ACK-пакетов.
  * **Fragmentation attacks:** Атаки с использованием фрагментированных пакетов.

#### 2. Атаки на прикладной уровень (L7)

* **Application layer attacks:**
  * **HTTP Flood:** Массовые GET/POST запросы к веб-приложению.
  * **Slowloris:** Медленная отправка HTTP-заголовков для исчерпания соединений.
  * **Slow POST:** Медленная отправка тела запроса.
  * **RUDY (R-U-Dead-Yet):** Аналогично Slow POST.
* **Resource exhaustion:**
  * **Complex search queries:** Тяжелые запросы к базе данных.
  * **Login attacks:** Массовые попытки аутентификации.
  * **API abuse:** Злоупотребление API endpoints.

### Архитектура защиты (Layered Defense)

```
┌─────────────────────────────────────────────────────────────┐
│                    DDoS Protection                          │
│         (CloudFlare/AWS Shield/Imperva)                     │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                        WAF                                  │
│       ([WAF](./waf.md) Application Layer Protection)        │
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

1. **Defense in depth:** Многоуровневая защита.
2. **Monitoring и alerting:** Отслеживание аномалий (RPS, bandwidth, error rate, latency).
3. **Incident response plan:** План реагирования на инциденты.
4. **Regular testing:** Тестирование защиты (stress testing).
5. **Capacity planning:** Запас мощности для поглощения атак.
6. **Geographic filtering:** Блокировка трафика из подозрительных регионов.

### Методы защиты

* **Инфраструктурная защита:** Rate Limiting, Connection Limiting, SYN Cookies.
* **Сетевая защита:** Blackholing (RTBH), Traffic Scrubbing, Anycast.
* **Облачная защита:** CDN-based (CloudFlare, Akamai), Dedicated services (AWS Shield, Google Cloud Armor).
* **Application-level защита:** Challenge-Response (CAPTCHA, JS challenges), Behavioral analysis.

## Практические сценарии

### Rate Limiting (Nginx)

```nginx
# Ограничение скорости запросов
limit_req_zone $binary_remote_addr zone=one:10m rate=10r/s;

server {
    location / {
        limit_req zone=one burst=20 nodelay;
    }
}
```

### Rate Limiting (iptables)

```bash
# Ограничение новых соединений
iptables -A INPUT -p tcp --dport 80 -m limit --limit 25/minute --limit-burst 100 -j ACCEPT
iptables -A INPUT -p tcp --dport 80 -j DROP
```

### Включение SYN Cookies

```bash
# Защита от SYN flood
sysctl -w net.ipv4.tcp_syncookies=1
```

### Rate limiting с fail2ban

```bash
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

### Защита Origin-сервера за CloudFlare

```nginx
# Разрешить запросы только от IP-адресов CloudFlare
allow 173.245.48.0/20;
allow 103.21.244.0/22;
# ... другие диапазоны CloudFlare
deny all;
```

## Дополнительная информация

* [OWASP DDoS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html)
* [CloudFlare DDoS Protection](https://www.cloudflare.com/ddos/)
* [Yandex Cloud DDoS Protection](https://yandex.cloud/ru/docs/ddos-protection/)
* Связанный файл: [Web Application Firewall (WAF)](./waf.md)

### См. также

* **[Защита от DoS-атак в Angie/Nginx](../../../WebServers/Angie/High_Load/dos_protection.md)** — практическое руководство по настройке rate limiting, GeoIP-блокировки и других методов на уровне веб-сервера
* **[Fail2Ban](../../../Linux/Security/Tools/Fail2Ban.md)** — автоматическая блокировка нарушителей на основе логов
