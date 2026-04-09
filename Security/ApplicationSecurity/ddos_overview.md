# DDoS (Distributed Denial of Service)

## Definitions

**DDoS (Distributed Denial of Service)** — распределённая атака типа «отказ в обслуживании», при которой множество скомпрометированных устройств (ботнет) одновременно отправляют запросы к целевому серверу или сети с целью исчерпания ресурсов и вывода из строя. Отличается от DoS тем, что атака идёт из множества географически распределённых источников, что значительно усложняет защиту.

> **Обзорный материал по DoS/DDoS (сетевой аспект):** [DoS/DDoS Overview](../../Networking/Concepts/dos_ddos_overview.md)

## Basic Concepts

### Классификация атак

Атаки классифицируются по уровням модели OSI, на которые они нацелены.

#### L3/L4 — Сетевой и транспортный уровень (Volumetric)

Атаки направлены на переполнение пропускной способности сети или ресурсов сетевого оборудования.

- **Объёмные атаки (Volumetric):**
  - **UDP Flood** — массовая отправка UDP-пакетов на случайные порты.
  - **ICMP Flood** — перегрузка через ICMP echo-request.
  - **DNS Amplification** — использование открытых DNS-серверов для усиления трафика.
  - **NTP Amplification** — аналогично DNS, через NTP-серверы.
- **Протокольные атаки (Protocol):**
  - **SYN Flood** — исчерпание таблицы соединений полуоткрытыми TCP-соединениями. Защита: [SYN Cookies](../../Networking/Concepts/dos_ddos_overview.md#продвинутые-методы-защиты-на-сервере) (`net.ipv4.tcp_syncookies=1`).
  - **ACK Flood** — массовая отправка ACK-пакетов.
  - **Fragmentation attacks** — атаки с использованием фрагментированных пакетов.
- **Цель:** Забить входящий канал вредоносным трафиком. Защита на конечном сервере (iptables) неэффективна — канал уже перегружен. Требуются специализированные сервисы очистки трафика (CloudFlare, Qrator, AWS Shield).

#### L7 — Уровень приложения

Атаки направлены на исчерпание ресурсов приложения (CPU, память, подключения к БД) запросами, имитирующими легитимные.

- **Application layer attacks:**
  - **HTTP Flood** — массовые GET/POST-запросы к веб-приложению.
  - **Slowloris** — медленная отправка HTTP-заголовков для исчерпания соединений.
  - **Slow POST / RUDY (R-U-Dead-Yet)** — медленная отправка тела запроса.
- **Resource exhaustion:**
  - **Complex search queries** — тяжёлые запросы к базе данных.
  - **Login attacks** — массовые попытки аутентификации.
  - **API abuse** — злоупотребление API-эндпоинтами.
- **Цель:** Заставить приложение выполнять ресурсоёмкие операции. Современные ботнеты мимикрируют под поведение реальных пользователей.

### Архитектура многоуровневой защиты (Layered Defense)

```
┌─────────────────────────────────────────────────────────────┐
│                    DDoS Protection                          │
│         (CloudFlare / AWS Shield / Imperva)                 │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                        WAF                                  │
│       ([WAF](./waf.md) — защита на уровне приложения)       │
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

### Методы защиты

| Уровень | Метод | Примеры |
|---|---|---|
| Инфраструктурный | Rate Limiting, Connection Limiting, SYN Cookies | Nginx `limit_req`, `tcp_syncookies` |
| Сетевой | Blackholing (RTBH), Traffic Scrubbing, Anycast | Провайдер, дата-центр |
| Облачный | CDN-based (CloudFlare, Akamai), Dedicated services | AWS Shield, Google Cloud Armor |
| Application-level | Challenge-Response (CAPTCHA, JS challenges), Behavioral analysis | WAF-правила |

### Best Practices

1. **Defense in depth** — многоуровневая защита.
2. **Monitoring и alerting** — отслеживание аномалий (RPS, bandwidth, error rate, latency).
3. **Incident response plan** — план реагирования на инциденты.
4. **Regular testing** — тестирование защиты (stress testing).
5. **Capacity planning** — запас мощности для поглощения атак.
6. **Geographic filtering** — блокировка трафика из подозрительных регионов.

> **Ключевой вывод:** Построить надёжную защиту от масштабных распределённых атак (особенно L7) силами одного сервера или локального файрвола практически невозможно. Необходимы специализированные внешние сервисы ([подробнее](../../Networking/Concepts/dos_ddos_overview.md)).

## Practical Scenarios

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
# ... другие диапазоны CloudFlare (https://www.cloudflare.com/ips/)
deny all;
```

См. также практическое руководство по [защите от DoS-атак в Angie/Nginx](../../WebServers/Angie/High_Load/dos_protection.md) и настройке [fail2ban](../../Linux/Security/Tools/fail2ban.md).

## Additional Information

### Связанные файлы

- [WAF](./waf.md) — Web Application Firewall для защиты на уровне приложения
- [DoS/DDoS Overview](../../Networking/Concepts/dos_ddos_overview.md) — обзор типов атак и методов противодействия (сетевой аспект)
- [Защита от DoS в Angie/Nginx](../../WebServers/Angie/High_Load/dos_protection.md) — rate limiting, GeoIP-блокировка, test cookie
- [fail2ban](../../Linux/Security/Tools/fail2ban.md) — автоматическая блокировка нарушителей по логам
- [Proxy](../../Networking/Concepts/proxy.md) — защита от DDoS через CDN/прокси-сервисы
