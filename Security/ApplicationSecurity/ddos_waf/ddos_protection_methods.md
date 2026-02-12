# Методы защиты от DDoS

## 1. Инфраструктурная защита

### Rate Limiting (Ограничение скорости)

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

### Connection Limiting

```nginx
# Ограничение количества соединений с одного IP
limit_conn_zone $binary_remote_addr zone=addr:10m;

server {
    location / {
        limit_conn addr 10;
    }
}
```

### SYN Cookies

```bash
# Включение SYN cookies (защита от SYN flood)
sysctl -w net.ipv4.tcp_syncookies=1
```

## 2. Сетевая защита

### Blackholing (RTBH - Remotely Triggered Black Hole)

- Анонс маршрута к атакуемому IP в null0 на уровне провайдера
- Полное отбрасывание трафика до целевого сервера
- Используется при массивных атаках для защиты инфраструктуры

### Traffic Scrubbing

- Перенаправление трафика через центры очистки
- Фильтрация легитимного и вредоносного трафика
- Возврат очищенного трафика через GRE/VPN

### Anycast

- Распределение трафика между множеством точек присутствия (PoP)
- Поглощение атаки за счет масштаба
- Автоматическое перенаправление при отказе

## 3. Облачная защита

### CDN-based protection

- CloudFlare, Akamai, AWS CloudFront, Fastly
- Поглощение трафика на уровне CDN
- Кэширование статики, защита origin-сервера

### Dedicated DDoS protection services

- AWS Shield (Standard/Advanced)
- Google Cloud Armor
- Azure DDoS Protection
- Imperva Incapsula

## 4. Application-level защита

### Challenge-Response

- CAPTCHA для подозрительных запросов
- JavaScript challenges (проверка браузера)
- Cookie-based challenges

### Behavioral analysis

- Анализ паттернов поведения
- Отличие ботов от реальных пользователей
- ML-based детекция аномалий
