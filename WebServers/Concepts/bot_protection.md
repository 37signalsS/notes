# Защита веб-серверов от ботов

## Определения

**Bot (Бот)** — автоматизированный клиент (скрипт, сканер, краулер), который отправляет HTTP-запросы без участия человека. Включает поисковых роботов (Googlebot), парсеры, сканеры уязвимостей, DDoS-инструменты.

**Bad Bot (Вредоносный бот)** — бот, который причиняет ущерб: скрапинг контента, brute-force атаки, сканирование уязвимостей, DDoS, спам в формах.

**Good Bot (Хороший бот)** — поисковый робот, мониторинг (UptimeRobot), партнёрские сервисы. Обычно идентифицируются по User-Agent и IP-диапазонам.

**Rate Limiting** — механизм ограничения количества запросов за единицу времени для защиты от ботов.

**CAPTCHA / reCAPTCHA** — механизм отличия человека от бота через тест, который легко решить человеку, но сложно боту.

**JS Challenge** — техника, при которой сервер возвращает JavaScript, который должен выполниться в браузере. Бот без JS-движка не пройдёт проверку.

**Bot Management** — комплексный подход к управлению ботами: идентификация, классификация, применение политик.

## Основные концепции

### Типы ботов

| Тип | Пример | Ущерб | Защита |
| :--- | :--- | :--- | :--- |
| **Поисковый робот** | Googlebot, Bingbot | Скрапинг, перегрузка | `robots.txt`, rate limiting по IP |
| **Сканер уязвимостей** | Nikto, SQLMap | Обнаружение дыр | WAF, rate limiting, JS challenge |
| **Brute-force бот** | Hydra, Medusa | Подбор паролей | Fail2ban, CAPTCHA, account lockout |
| **DDoS бот** | LOIC, HOIC | Перегрузка | Rate limiting, CDN, Anycast |
| **Скрапер контента** | curl, wget, Scrapy | Кража контента | Rate limiting, User-Agent блокировка |
| **Спам-бот** | Form filler | Спам в формах, комментарии | CAPTCHA, honeypot, reCAPTCHA |

### Идентификация ботов

| Метод | Механизм | Надёжность |
| :--- | :--- | :--- |
| **User-Agent** | Проверка `User-Agent` заголовка | Низкая (легко подделать) |
| **IP репутация** | Проверка IP в списках ботнетов | Средняя (требует обновления) |
| **JS Challenge** | Выполнение JS в браузере | Высокая (но блокирует доступibility) |
| **Behavioral** | Анализ паттернов запросов (скорость, порядок) | Высокая |
| **TLS Fingerprint** | Анализ JA3/JA4 fingerprint | Высокая |
| ** honeypot** | Скрытые поля в формах | Средняя |

### Rate Limiting против ботов

| Алгоритм | Механизм | Рекомендация |
| :--- | :--- | :--- |
| **Token Bucket** | Разрешает burst, ограничивает средний rate | Для API |
| **Sliding Window** | Окно скользит; более точный | Для аутентификации |
| **IP-based** | Ограничение по IP клиента | Базовый уровень |
| **User-based** | Ограничение по API key / JWT | Для зарегистрированных пользователей |

### CAPTCHA и альтернативы

| Тип | Механизм | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **reCAPTCHA v2** | Клик по checkbox | Простой для пользователя | Требует JS, Google |
| **reCAPTCHA v3** | Невидимый, scoring | Не мешает UX | Требует настройки порогов |
| **hCaptcha** | Альтернатива reCAPTCHA | Конфиденциальность | Меньше данных для обучения |
| **Turnstile** | Cloudflare CAPTCHA | Быстрый, без Google | Зависит от Cloudflare |
| **Honeypot** | Скрытые поля | Невидимый для пользователя | Менее надёжный |

## Практические сценарии

### Сценарий 1: Блокировка ботов по User-Agent и IP

```nginx
# Блокировка известных ботов
map $http_user_agent $is_bad_bot {
    default  0;
    ~*curl    1;
    ~*wget    1;
    ~*scrapy  1;
    ~*nikto   1;
    ~*sqlmap  1;
    ~*hydra   1;
    ~*medusa  1;
}

# Ограничение по IP
geo $is_bad_ip {
    default          0;
    192.0.2.0/24     1;  # известный ботнет
    198.51.100.0/24  1;
}

server {
    listen 80;
    server_name example.com;

    if ($is_bad_bot) { return 403; }
    if ($is_bad_ip)  { return 403; }

    location / {
        proxy_pass http://backend;
    }
}
```

**Валидация:**
- `curl -A "curl/7.68.0" http://example.com/` — `403 Forbidden`.
- `curl -A "Mozilla/5.0" http://example.com/` — `200 OK`.

### Сценарий 2: Rate Limiting для защиты от ботов

```nginx
# Ограничение: 10 запросов в секунду с burst 20
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

server {
    listen 80;
    server_name api.example.com;

    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://api_backend;
    }
}
```

**Валидация:**
- `ab -n 100 -c 25 http://api.example.com/` — после 20 burst запросов `429 Too Many Requests`.
- `for i in $(seq 1 30); do curl -s -o /dev/null -w "%{http_code}\n" http://api.example.com/; done` — первые 20 запросов `200`, остальные `429`.

### Сценарий 3: JS Challenge и honeypot

```nginx
# JS Challenge: возвращаем JS для подозрительных запросов
server {
    listen 80;
    server_name example.com;

    # Скрытое поле в формах (honeypot)
    location = /contact {
        if ($args ~* "url") { return 403; }  # honeypot-параметр
        proxy_pass http://backend;
    }
}
```

### Сценарий 4: Fail2ban для защиты от ботов

```ini
# /etc/fail2ban/jail.d/nginx-bots.conf
[nginx-badbots]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
maxretry = 2
bantime  = 86400
findtime = 600
action   = %(action_mwl)s

[nginx-botsearch]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
maxretry = 10
bantime  = 3600
findtime = 120
action   = %(action_mwl)s
```

**Валидация:**
- `fail2ban-client status nginx-badbots` — IP в списке забаненных.
- `iptables -L -n | grep DROP` — правила DROP для IP.

## Лучшие практики

1. **Не блокируйте поисковых роботов без необходимости:** Googlebot, Bingbot индексируют сайт. Блокировка вредит SEO.
2. **Используйте `robots.txt`:** указание правил для хороших ботов.
3. **Rate limiting на API:** всегда ограничивайте API, чтобы боты не могли делать бесконечные запросы.
4. **CAPTCHA на чувствительных endpoints:** логин, регистрация, форма обратной связи.
5. **Fail2ban / CrowdSec:** автоматическая блокировка IP при подозрительной активности.
6. **WAF с OWASP CRS:** ModSecurity/NAXSI блокируют известные паттерны атак.
7. **User-Agent + IP + Behavioral:** комбинация методов надёжнее любого отдельного.
8. **Не полагайтесь только на User-Agent:** его легко подделать.

## Граничные случаи и ограничения

1. **CDN и боты:** за CDN все клиенты имеют IP edge-сервера. Fail2ban заблокирует весь CDN. Анализируйте `X-Forwarded-For` за доверенным прокси.
2. **JavaScript-зависимость:** JS Challenge блокирует пользователей с отключённым JS. Используйте только как дополнительный слой.
3. **CAPTCHA и accessibility:** reCAPTCHA может быть недоступен для пользователей с ограниченными возможностями. Предусмотрите альтернативу.
4. **Поисковые роботы и crawl budget:** агрессивный rate limiting может уменьшить crawl budget Google. Настройте `Crawl-Delay` в `robots.txt`.
5. **Tor / VPN:** пользователи Tor/VPN имеют общие IP. Не блокируйте диапазоны Tor полностью; используйте challenge.

## Дополнительная информация

- **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — rate limiting, fail2ban, WAF.
- **[Rate Limiting и устойчивость HTTP-сервисов](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — алгоритмы rate limiting.
- **[Bot Management (OWASP)](https://owasp.org/www-project-bot-protection/)** — руководство по защите от ботов.
