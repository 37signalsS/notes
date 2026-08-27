# whois — протокол и утилита

## Определения

**whois** — сетевой протокол прикладного уровня, работающий по модели «запрос-ответ» через TCP (порт **43**), и одноимённая утилита командной строки. Предназначен для получения регистрационных данных о владельцах доменных имён, IP-адресов и автономных систем (AS).

**RDAP (Registration Data Access Protocol)** — современный преемник WHOIS (RFC 7480-7485). В отличие от классического WHOIS, RDAP использует HTTP(S), возвращает структурированные данные в формате JSON, поддерживает интернационализацию (IDN) и механизмы аутентификации.

## Базовые концепции

### Формат протокола WHOIS

WHOIS — это текстовый строковый протокол (RFC 3912). Клиент устанавливает TCP-соединение с сервером на порту **43**, отправляет одну строку с запросом и получает один или несколько строковых ответов, после чего сервер закрывает соединение.

**Формат запроса:**
```
<объект>\r\n
```
Объектом может быть доменное имя, IP-адрес, AS-номер или хендл (уникальный идентификатор записи, например `NET-8-8-8-0`).

**Формат ответа:**
Сервер возвращает свободный текст с парами «ключ: значение» и комментариями, начинающимися с `%` или `#`. Полей с фиксированным форматом нет — каждая зона (TLD, RIR) определяет собственный набор полей.

**Пример низкоуровневого взаимодействия:**
```bash
# SMTP-подобный диалог через netcat (ручной запрос)
echo "example.com" | nc whois.verisign-grs.com 43
# → Server: whois.verisign-grs.com
# → Domain Name: EXAMPLE.COM
# → Registry Domain ID: 2336799_DOMAIN_COM-VRSN
# → ...
```

**Важно:** протокол не предусматривает аутентификацию клиента, шифрование или восстанавливаемость соединения. Это делает WHOIS уязвимым к прослушиванию и спуфингу.

### Типы запросов

| Тип запроса | Описание | Пример |
| :--- | :--- | :--- |
| **Domain query** | Запрос по доменному имени | `whois example.com` |
| **IP query** | Запрос по IP-адресу (определяет RIR автоматически) | `whois 8.8.8.8` |
| **ASN query** | Запрос по номеру автономной системы | `whois AS15169` |
| **Handle query** | Запрос по уникальному идентификатору записи | `whois NET-8-8-8-0` |
| **Server-specific** | Запрос к конкретному серверу | `whois -h whois.ripe.net 193.0.6.135` |

### Механизм работы и иерархия серверов

Протокол WHOIS не имеет единой централизованной базы. Данные распределены между региональными регистраторами (RIR) и аккредитованными регистраторами доменов.

1.  **IANA Root WHOIS:** Сервер `whois.iana.org` является точкой входа. Он содержит информацию о том, какой регистратор (Registry) отвечает за конкретную TLD (например, `.ru` или `.com`) или блок IP-адресов.
2.  **Referral Chain (Цепочка перенаправлений):**
    *   Клиент опрашивает корневой сервер.
    *   Корневой сервер возвращает адрес авторитативного сервера (например, `whois.ripe.net` для IP в Европе).
    *   Клиент (утилита) автоматически повторяет запрос к целевому серверу.
3.  **Thick vs Thin WHOIS:**
    *   **Thin (Тонкий):** Содержит только базовую информацию (регистратор, серверы имен). Для деталей требуется дополнительный запрос к серверу регистратора.
    *   **Thick (Толстый):** Содержит полные данные о владельце (регистранте) непосредственно в базе реестра.

### Типы информации в базе данных

| Поле | Описание |
| :--- | :--- |
| `Domain Name` | Полное доменное имя (FQDN). |
| `Registrar` | Организация-регистратор, через которую куплен домен. |
| `Creation Date` | Дата первой регистрации. |
| `Registry Expiry Date` | Дата окончания срока делегирования. |
| `Status` | Состояние домена (например, `clientTransferProhibited` — запрет переноса). |
| `Registrant` | Контактные данные владельца (часто скрыты через Privacy Protection или GDPR). |
| `AS Number` | Номер автономной системы (для сетевых объектов). |

### Ограничения и безопасность

*   **WHOIS Privacy:** Услуга скрытия реальных данных владельца (заменяются данными посредника).
*   **GDPR:** Европейский регламент, приведший к массовому скрытию персональных данных (email, телефон) из публичного доступа.
*   **Rate Limiting:** Регистраторы жестко ограничивают количество запросов с одного IP во избежание парсинга баз.
*   **Отсутствие шифрования:** Трафик WHOIS (порт 43) передается в открытом виде. Для защиты данных рекомендуется переходить на RDAP (через HTTPS).
*   **Неструктурированность:** Ответы WHOIS — это свободный текст. Парсинг требует написания регулярных выражений под каждого регистратора.

## Установка и настройка

### Linux

**Debian / Ubuntu:**
```bash
sudo apt update && sudo apt install whois
```

**RHEL / CentOS / Fedora:**
```bash
sudo yum install whois
# или для Fedora 36+:
sudo dnf install whois
```

**Arch Linux:**
```bash
sudo pacman -S whois
```

### macOS

```bash
# Через Homebrew
brew install whois
```

> **Примечание:** в macOS `whois` не входит в базовую поставку. После установки через Homebrew утилита доступна в PATH без дополнительных настроек.

### Windows

WHOIS не входит в стандартную поставку Windows. Варианты:

1. **WSL (Windows Subsystem for Linux):** установите дистрибутив Linux и используйте `apt install whois`.
2. **Whois от Sysinternals:** портативная утилита Microsoft (`whois.exe`), не требует установки.
3. **PowerShell + .NET:** создайте функцию-обёртку через `System.Net.Sockets.TcpClient` (см. пример в разделе «Интеграция с Python»).

### Проверка установки

```bash
whois --version
# → Version 5.5.17  (версия зависит от дистрибутива)

# Быстрый тест — запрос короткого домена
whois example.com | head -5
```

## Практические сценарии

### Диагностика доменов и IP

```bash
# Базовый запрос информации о домене
whois example.com

# Поиск информации об IP-адресе (автоматически определит RIR)
whois 8.8.8.8

# Запрос к конкретному WHOIS-серверу (например, для обхода ограничений клиента)
whois -h whois.ripe.net 193.0.6.135
```

### Полный пример вывода и解读 полей

```bash
whois google.com
```

**Ожидаемый вывод (с пояснением ключевых полей):**
```
   Domain Name: GOOGLE.COM
   # Полное доменное имя (FQDN).

   Registry Domain ID: 2138514_DOMAIN_COM-VRSN
   # Уникальный идентификатор записи в реестре Verisign.

   Registrar WHOIS Server: whois.markmonitor.com
   # Адрес WHOIS-сервера регистратора (для тонкого WHOIS).

   Registrar: MarkMonitor Inc.
   # Организация-регистратор, через которую зарегистрирован домен.

   Updated Date: 2024-08-12T07:02:20Z
   # Дата последнего обновления записи.

   Creation Date: 1997-09-15T04:00:00Z
   # Дата первичной регистрации домена.

   Registry Expiry Date: 2028-09-14T04:00:00Z
   # Дата окончания срока делегирования.

   Registrar Registration Expiration Date: 2028-09-14T04:00:00Z
   # То же значение (дублируется для тонкого WHOIS).

   Registrar: MarkMonitor Inc.
   Registrar IANA ID: 292
   Registrar Abuse Contact Email: abusecompliance@markmonitor.com
   Registrar Abuse Contact Phone: +1.2086851750

   Domain Status: clientDeleteProhibited
   # Статус домена: запрет удаления (защита от случайного/мошеннического удаления).
   # Типичные статусы:
   #   clientTransferProhibited — запрет трансфера
   #   clientUpdateProhibited — запрет обновления
   #   serverHold — домен приостановлен на уровне реестра

   Name Server: NS1.GOOGLE.COM
   Name Server: NS2.GOOGLE.COM
   Name Server: NS3.GOOGLE.COM
   Name Server: NS4.GOOGLE.COM
   # Делегирующие DNS-серверы (NS-записи).

   DNSSEC: unsigned
   # Статус DNSSEC: подпись не настроена.

   # WHOIS Privacy / GDPR:
   Registrant Name: REDACTED FOR PRIVACY
   Registrant Organization: REDACTED FOR PRIVACY
   Registrant Street: REDACTED FOR PRIVACY
   Registrant City: REDACTED FOR PRIVACY
   Registrant State/Province: CA
   Registrant Postal Code: REDACTED FOR PRIVACY
   Registrant Country: US
   # Контактные данные владельца скрыты (WHOIS Privacy или GDPR).
```

### Опции командной строки

| Опция | Описание | Пример |
| :--- | :--- | :--- |
| `-h <server>` | Запрос к указанному WHOIS-серверу | `whois -h whois.ripe.net 193.0.6.135` |
| `-p <port>` | Подключение к указанному порту (по умолчанию 43) | `whois -p 43 example.com` |
| `-r` | Отключение автоматических повторных запросов (без referral) | `whois -r example.com` |
| `-i` | Использовать `whois.iana.org` для определения сервера | `whois -i 8.8.8.8` |
| `-l` | Локальный реестр (не отправлять запрос серверу) | `whois -l example.com` |
| `-T <types>` | Фильтрация по типам объектов (через запятую) | `whois -T domain,registrar example.com` |
| `-q` | Тихий режим (без сообщений сервера) | `whois -q example.com` |

### Анализ автономных систем (AS)

Полезно для понимания принадлежности сети конкретному провайдеру или организации.

```bash
# Получение данных об автономной системе Google
whois AS15169
# → aut-num:        AS15169
# → org-name:       Google LLC
# → country:        US
# → ...

# Определение AS для конкретного IP
whois 8.8.8.8 | grep -iE "origin|aut-num|org-name"
# → origin:         AS15169
# → org-name:       Google LLC
```

### Проверка подозрительных ресурсов

**Сценарий:** Оценка возраста домена для выявления фишинга.

```bash
whois suspicious-bank-login.com | grep -iE "Creation Date|Expiry Date"
# → Creation Date: 2024-01-10T12:00:00Z
# → Expiry Date: 2025-01-10T12:00:00Z
```

*   **Признак риска:** Если домен создан несколько дней назад, но претендует на роль крупного сервиса — это вероятный фишинг.

**Дополнительные проверки:**
```bash
# Проверка статуса домена
whois suspicious-domain.com | grep -i "status"
# → Domain Status: ok

# Проверка registrar'а (подозрительные — дешёвые, с плохой репутацией)
whois suspicious-domain.com | grep -i "registrar"
# → Registrar: Some Cheap Registrar Inc.

# Проверка количества NS-серверов (у крупных сервисов обычно 2-4)
whois suspicious-domain.com | grep -i "name server"
```

### Массовый проверка доменов (скрипт)

```bash
#!/bin/bash
# Проверка списка доменов на предмет фишинга

DOMAINS="bank-secure-login.com sketchy-crypto.com fake-paypal.net"

for domain in $DOMAINS; do
    echo "=== Проверка: $domain ==="
    creation=$(whois "$domain" 2>/dev/null | grep -i "Creation Date" | head -1)
    registrar=$(whois "$domain" 2>/dev/null | grep -i "Registrar:" | head -1)
    
    if [ -z "$creation" ]; then
        echo "  Домен не найден или недоступен"
    else
        echo "  $creation"
        echo "  $registrar"
        
        # Проверка возраста (< 6 месяцев = подозрительно)
        created_year=$(echo "$creation" | grep -oE "[0-9]{4}" | head -1)
        current_year=$(date +%Y)
        if [ "$created_year" -ge "$current_year" ]; then
            echo "  ⚠ Домен создан в текущем году — проверьте вручную"
        fi
    fi
    echo ""
done
```

### Работа с RDAP через curl

Если требуется получить данные в формате JSON для автоматизации или если стандартный `whois` заблокирован.

```bash
# Запрос данных о домене .com (через Verisign RDAP)
curl -s https://rdap.verisign.com/com/v1/domain/example.com | jq .

# Запрос данных об IP-адресе (через RIPE RDAP)
curl -s https://rdap.ripe.net/ip/193.0.6.135 | jq .

# Фильтрация конкретных полей
curl -s https://rdap.verisign.com/com/v1/domain/example.com | jq '.ldhName, .events[] | select(.eventAction=="registration") | .eventDate'

# Проверка доступности RDAP-сервера для TLD
curl -s https://rdap.org/domain/example.com | jq '.links[0].href'
```

### Интеграция с Python

**Установка:**
```bash
pip install python-whois
```

**Пример использования:**
```python
import whois
from datetime import datetime

def check_domain(domain: str) -> dict:
    """Проверка домена через WHOIS."""
    w = whois.whois(domain)
    
    result = {
        "domain": w.domain_name,
        "registrar": w.registrar,
        "creation_date": w.creation_date,
        "expiration_date": w.expiration_date,
        "status": w.status,
        "name_servers": w.name_servers,
    }
    
    # Проверка возраста
    if isinstance(w.creation_date, datetime):
        age_days = (datetime.now() - w.creation_date).days
        result["age_days"] = age_days
        result["is_suspicious"] = age_days < 180  # Менее 6 месяцев
    
    return result

# Использование
if __name__ == "__main__":
    domain = "google.com"
    info = check_domain(domain)
    
    print(f"Домен: {info['domain']}")
    print(f"Регистратор: {info['registrar']}")
    print(f"Дата создания: {info['creation_date']}")
    print(f"Возраст (дней): {info.get('age_days', 'N/A')}")
    print(f"Статус: {info['status']}")
    print(f"NS-серверы: {', '.join(info['name_servers'] or [])}")
    if info.get('is_suspicious'):
        print("⚠ Домен подозрительно новый!")
```

**Парсинг raw WHOIS-ответа (без библиотек):**
```python
import subprocess
import re

def whois_raw(domain: str) -> dict:
    """Ручной парсинг WHOIS через subprocess."""
    result = subprocess.run(
        ["whois", domain],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    data = {}
    for line in result.stdout.splitlines():
        if ":" in line and not line.startswith(("%", "#", "//")):
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if key and value:
                # Некоторые поля повторяются — сохраняем список
                if key in data:
                    if isinstance(data[key], list):
                        data[key].append(value)
                    else:
                        data[key] = [data[key], value]
                else:
                    data[key] = value
    
    return data

# Использование
info = whois_raw("example.com")
print(info.get("creation_date"))
print(info.get("registrar"))
```

### Утилита mkpasswd

Исторически во многих дистрибутивах (Debian, Ubuntu) утилита `mkpasswd` поставляется в пакете `whois`. Она используется для генерации хешированных паролей.

```bash
# Генерация хеша пароля с алгоритмом yescrypt
mkpasswd -m yescrypt "my_password"
# → $y$j9T$v9M...

# Генерация с указанием алгоритма
mkpasswd -m sha-256 "my_password"
# → $5$...

# Генерация с солью
mkpasswd -m yescrypt -S "random_salt" "my_password"
```

## Типичные ошибки и решение

### Rate Limiting (Ограничение количества запросов)

**Симптом:** `whois` возвращает пустой ответ или ошибку `429 Too Many Requests` после нескольких последовательных запросов.

**Причина:** Регистраторы и RIR жестко ограничивают количество запросов с одного IP (обычно 50–100 запросов в час для доменных зон, до 1000 для IP-запросов в RIPE).

**Решение:**
```bash
# 1. Добавьте задержку между запросами
for domain in {a..z}.example.com; do
    whois "$domain" > /dev/null
    sleep 5  # 5 секунд между запросами
done

# 2. Используйте кеширование (сохраняйте результаты)
CACHE_DIR="$HOME/.whois_cache"
mkdir -p "$CACHE_DIR"

cached_whois() {
    local domain="$1"
    local cache_file="$CACHE_DIR/${domain}.txt"
    
    if [[ -f "$cache_file" ]] && [[ $(find "$cache_file" -mtime -1 2>/dev/null) ]]; then
        cat "$cache_file"
    else
        whois "$domain" | tee "$cache_file"
    fi
}

# 3. Используйте RDAP вместо WHOIS (меньше ограничений)
curl -s "https://rdap.org/domain/$domain" | jq .
```

### Таймауты и проблемы с сетью

**Симптом:** `whois` зависает или возвращает `whois: whois.verisign-grs.com: connection timed out; no servers could be reached`.

**Причина:** Блокировка порта 43 файрволом, проблемы с DNS-резолвингом WHOIS-сервера или его недоступность.

**Диагностика:**
```bash
# Проверка доступности WHOIS-сервера
nc -zv whois.verisign-grs.com 43
# → Connection to whois.verisign-grs.com 43 port [tcp/whois] succeeded!

# Проверка через telnet
telnet whois.verisign-grs.com 43

# Проверка DNS-резолвинга
dig whois.verisign-grs.com +short
# → 199.7.66.133
```

**Решение:**
```bash
# 1. Проверьте файрвол
sudo iptables -L -n | grep 43
# или
sudo ufw status | grep 43

# 2. Используйте RDAP через HTTPS (порт 443) — обычно не блокируется
curl -s https://rdap.verisign.com/com/v1/domain/example.com | jq .

# 3. Укажите альтернативный WHOIS-сервер
whois -h whois.verisign-grs.com example.com

# 4. Проверьте прокси (если используется)
export http_proxy="http://proxy:8080"
curl -s https://rdap.verisign.com/com/v1/domain/example.com | jq .
```

### Пустые ответы (GDPR / WHOIS Privacy)

**Симптом:** WHOIS-ответ не содержит контактных данных владельца (поля Registrant, Admin, Tech пусты или содержат `REDACTED FOR PRIVACY`).

**Причина:**
1. **WHOIS Privacy:** владелец домена активировал услугу скрытия данных (WhoisGuard, Domains By Proxy и т.д.).
2. **GDPR:** для доменных зон EU (`.de`, `.fr`, `.eu`) персональные данные скрыты по умолчанию с 2018 года.
3. **Thin WHOIS:** доменная зона (`.com`, `.net`) хранит только базовые данные; полные данные — на сервере регистратора.

**Решение:**
```bash
# 1. Проверьте registrar'а — у него может быть другой WHOIS-сервер
whois example.com | grep "Registrar WHOIS Server"
# → Registrar WHOIS Server: whois.godaddy.com

# 2. Запросите WHOIS через registrar'а
whois -h whois.godaddy.com example.com

# 3. Используйте RDAP — он может содержать больше структурированных данных
curl -s https://rdap.verisign.com/com/v1/domain/example.com | jq '.entities[] | select(.roles[]=="registrant")'

# 4. Проверьте ICANN WHOIS (последняя инстанция)
curl -s "https://lookup.icann.org/en/lookup?name=example.com" | grep -i "registrant"

# 5. Для критически важных случаев — обращитесь напрямую к регистратору
```

### Ошибки парсинга (неструктурированный вывод)

**Симптом:** скрипт или программа некорректно извлекает данные из WHOIS-ответа из-за различий в формате между разными регистраторами.

**Причина:** WHOIS не имеет стандартизированного формата. Каждый регистратор (Verisign, RIPE, AFRINIC) использует собственный стиль вывода.

**Решение:**
```bash
# 1. Используйте RDAP (JSON) вместо WHOIS — формат стандартизирован
curl -s https://rdap.verisign.com/com/v1/domain/example.com | jq '.events[] | select(.eventAction=="registration") | .eventDate'

# 2. Для WHOIS — ищите ключевые слова, а не позиции строк
whois example.com | grep -iE "^(Domain Name|Registrar|Creation Date|Expiry Date):"

# 3. Используйте готовые библиотеки (Python)
pip install python-whois
# Библиотека сама определяет формат и парсит данные

# 4. Создайте свой парсер с учётом вариаций
whois example.com | awk -F: '/^[Dd]omain [Nn]ame/ {print $2}' | tr -d ' '
```

### Домен не найден

**Симптом:** `whois example.com` возвращает `No match for "EXAMPLE.COM"`.

**Причины:**
1. Домен действительно не зарегистрирован.
2. Домен был удалён и находится в стадии `Pending Delete`.
3. Техническая проблема с WHOIS-сервером.

**Диагностика:**
```bash
# 1. Проверьте через RDAP (более надёжно)
curl -s https://rdap.verisign.com/com/v1/domain/example.com | jq '.errorCode'
# → 404 (если домен не найден)

# 2. Попробуйте другой WHOIS-сервер
whois -h whois.iana.org example.com

# 3. Проверьте статус через DNS
dig example.com +short
# → (пустой ответ = домен не делегирован)
```

### Ограничения по длине запроса

**Симптом:** WHOIS-клиент обрезает длинные запросы или возвращает ошибку.

**Причина:** Некоторые серверы ограничивают длину входного запроса (обычно 256–1024 байта).

**Решение:**
```bash
# Используйте короткие имена без FQDN
whois example          # вместо whois example.com
whois 8.8.8.8          # вместо whois 8.8.8.8.in-addr.arpa
```

## Дополнительная информация

### Региональные интернет-регистраторы (RIR)

| RIR | Регион обслуживания | WHOIS-сервер | RDAP-сервер |
| :--- | :--- | :--- | :--- |
| **RIPE NCC** | Европа, Ближний Восток, Центральная Азия | `whois.ripe.net` | `rdap.ripe.net` |
| **ARIN** | Северная Америка | `whois.arin.net` | `rdap.arin.net` |
| **APNIC** | Азиатско-Тихоокеанский регион | `whois.apnic.net` | `rdap.apnic.net` |
| **LACNIC** | Латинская Америка и Карибский бассейн | `whois.lacnic.net` | `rdap.lacnic.net` |
| **AFRINIC** | Африка | `whois.afrinic.net` | `rdap.afrinic.net` |

### Полезные RDAP-эндпоинты

| TLD | RDAP-сервер | URL-шаблон |
| :--- | :--- | :--- |
| `.com`, `.net` | Verisign | `https://rdap.verisign.com/com/v1/domain/{domain}` |
| `.org` | Public Interest Registry | `https://rdap.org/domain/{domain}` |
| `.ru` | Coordination Center for TLD .RU | `https://rdap.tld.ru/rdap/domain/{domain}` |
| `.de` | DENIC | `https://rdap.denic.de/domain/{domain}` |
| IP-адреса (RIPE) | RIPE NCC | `https://rdap.ripe.net/ip/{ip}` |
| IP-адреса (ARIN) | ARIN | `https://rdap.arin.net/ip/{ip}` |

### Автоматизация мониторинга доменов

**Сценарий:** Ежедневная проверка истечения срока доменов в организации.

```bash
#!/bin/bash
# domain_monitor.sh — проверка сроков истечения доменов

DOMAINS="example.com example.org example.net"
ALERT_DAYS=30

for domain in $DOMAINS; do
    expiry=$(whois "$domain" 2>/dev/null | grep -i "Registry Expiry Date" | head -1 | awk '{print $NF}')
    
    if [ -z "$expiry" ]; then
        echo "[$(date)] ОШИБКА: не удалось получить данные для $domain"
        continue
    fi
    
    # Конвертация в Unix timestamp
    expiry_ts=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$expiry" 2>/dev/null || date -d "$expiry" +%s 2>/dev/null)
    now_ts=$(date +%s)
    days_left=$(( (expiry_ts - now_ts) / 86400 ))
    
    if [ "$days_left" -le "$ALERT_DAYS" ]; then
        echo "[$(date)] ⚠ $domain истекает через $days_left дней ($expiry)"
        # Отправка уведомления (email, Slack, Telegram)
        # curl -X POST -H 'Content-type: application/json' --data "{\"text\":\"⚠ $domain истекает через $days_left дней\"}" $WEBHOOK_URL
    else
        echo "[$(date)] ✓ $domain — OK ($days_left дней)"
    fi
done
```

### Сравнение WHOIS и RDAP

| Критерий | WHOIS | RDAP |
| :--- | :--- | :--- |
| **Протокол** | TCP (порт 43) | HTTP/HTTPS (порт 80/443) |
| **Формат данных** | Свободный текст | JSON (RFC 7483) |
| **Структурированность** | Нет (парсинг через regex) | Да (строго типизированные поля) |
| **Шифрование** | Нет | Да (HTTPS) |
| **Аутентификация** | Нет | Да (Bearer token, OAuth2) |
| **Поддержка IDN** | Ограниченная | Полная (Unicode) |
| **Пагинация** | Нет | Да (для больших результатов) |
| **Стандартизация** | RFC 3912 (1994) | RFC 7480-7485 (2015) |
| **Актуальность** | Устаревает | Рекомендуется ICANN |

### См. также

- [Обзор протокола DNS](../Protocols/DNS/dns.md) — иерархия имен и разрешение.
- [Основные концепции DNS](../Protocols/DNS/dns_concepts.md) — RDAP/WHOIS, регистрация доменов.
- [Безопасность DNS](../Protocols/DNS/dns_security.md) — DNSSEC, DoH и DoT.
- [Диагностика SSL/TLS](../../Security/Tools/ssl_certificate_diagnostics.md) — проверка сертификатов.
