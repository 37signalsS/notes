# nftables — GeoIP-фильтрация и интеграция с Threat Intelligence

## Определения

**GeoIP-фильтрация** — механизм блокировки или разрешения трафика на основе географического положения IP-адреса (страна, регион, ASN). В nftables реализуется через внешние утилиты, генерирующие sets из баз данных MaxMind GeoIP2.

**MaxMind GeoIP2** — коммерческая база данных, содержащая маппинг IP-адресов на географические данные (страна, город, координаты, ASN, ISP). Обновляется ежедневно. Существует бесплатная версия `GeoLite2`.

**GeoLite2** — бесплатная версия базы данных MaxMind с ограниченной точностью. Требует регистрации на maxmind.com для получения лицензионного ключа.

**ASN (Autonomous System Number)** — уникальный идентификатор автономной системы в глобальной маршрутизации. Используется для фильтрации трафика по провайдерам.

**Threat Intelligence Feed** — поток данных, содержащий списки вредоносных IP-адресов (C2-серверы, ботнеты, сканеры). Примеры: abuse.ch (URLhaus, ThreatFox), Spamhaus, FireHOL.

**Abuse.ch** — бесплатный проект, предоставляющий списки вредоносных IP-адресов и URL. Включает URLhaus (вредоносные URL), ThreatFox (IoC), Feodo Tracker (C2 Dridex).

## Основные концепции

### Архитектура GeoIP-фильтрации в nftables

nftables **не имеет встроенного** GeoIP-модуля (в отличие от старого `xt_geoip` для iptables). Фильтрация по геоданным реализуется через:

1. **Внешний скрипт** — загружает GeoIP-базу, извлекает IP-адреса по стране, генерирует nftables set.
2. **Именованный set** — хранит IP-адреса для конкретной страны/региона.
3. **Правило nftables** — проверяет принадлежность IP к set.

```
MaxMind GeoIP2 (.mmdb) → Скрипт (geoip2nft) → nft add element → set country_blocks
                                                         ↓
                                              nft list ruleset → set blackhole_countries
```

### Ограничения

1. **Точность** — GeoIP определяет только страну/регион, не город (бесплатная версия).
2. **VPN/Proxy** — пользователи через VPN могут иметь IP другой страны.
3. **Обновление** — база обновляется ежедневно; устаревшие данные могут блокировать легитимный трафик.
4. **Производительность** — большие sets (>100k IP) могут замедлять обработку.

### Паттерн использования

GeoIP-фильтрация — **не замена**, а **дополнение** к стандартным правилам файрвола. Рекомендуется комбинировать:
- GeoIP для блокировки трафика из «вражеских» стран
- Threat Intelligence для блокировки известных вредоносных IP
- Rate limiting для защиты от DDoS
- Stateful inspection для базовой фильтрации

## Предварительные требования

### Программные требования

| Компонент | Назначение | Установка |
|:---|:---|:---|
| **nftables** | Фильтрация | `apt install nftables` |
| **python3** | Скрипт конвертации | Системный |
| **python3-maxminddb** | Чтение .mmdb | `pip install maxminddb` |
| **GeoLite2 Country** | База данных | Регистрация на maxmind.com |
| **curl/wget** | Загрузка feeds | Системный |

## Практические сценарии

### 1. Базовая GeoIP-фильтрация (MaxMind GeoLite2)

**Шаг 1: Регистрация и скачивание базы**
```bash
# Регистрация на https://www.maxmind.com/en/geolite2/signup
# Скачивание лицензионного ключа: /etc/GeoIP.conf

# Установка базы
sudo mkdir -p /var/lib/GeoIP
sudo wget -O /var/lib/GeoIP/GeoLite2-Country.mmdb \
  "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&license_key=YOUR_KEY&suffix=tar.gz"
sudo tar -xzf /var/lib/GeoIP/GeoLite2-Country.mmdb.tar.gz -C /var/lib/GeoIP/
```

**Шаг 2: Скрипт генерации sets**
```python
#!/usr/bin/env python3
"""geoip2nft.py — генерация nftables sets из MaxMind GeoIP2."""
import maxminddb
import subprocess
import sys

# Конфигурация
MMDB_PATH = "/var/lib/GeoIP/GeoLite2-Country.mmdb"
COUNTRIES_BLOCK = ["CN", "RU", "KP", "IR"]  # Коды стран ISO

def get_ips_by_country(mmdb_path, country_code):
    """Извлечение всех IP-адресов для страны."""
    reader = maxminddb.open_database(mmdb_path)
    ips = []
    # Примечание: для production используйте предкомпилированные блоки
    #而非 перебора всех IP
    return ips

def generate_nft_set(country_code, ips):
    """Генерация nftables set для страны."""
    set_name = f"geoip_{country_code.lower()}"
    elements = ", ".join(ips[:1000])  # Ограничение для производительности
    return f"""
table inet filter {{
    set {set_name} {{
        type ipv4_addr
        flags interval
        elements = {{ {elements} }}
    }}
}}
"""

def update_nftables(country_code, ips):
    """Обновление set в nftables."""
    set_name = f"geoip_{country_code.lower()}"
    # Удаление старых элементов
    subprocess.run(["nft", "flush", "set", "inet", "filter", set_name],
                   capture_output=True)
    # Добавление новых
    for ip in ips:
        subprocess.run(["nft", "add", "element", "inet", "filter", set_name,
                       "{", ip, "}"], capture_output=True)

if __name__ == "__main__":
    for country in COUNTRIES_BLOCK:
        ips = get_ips_by_country(MMDB_PATH, country)
        print(f"Country {country}: {len(ips)} IPs")
        update_nftables(country, ips)
```

**Шаг 3: Правило nftables**
```bash
table inet filter {
    set geoip_cn {
        type ipv4_addr
        flags interval
    }

    set geoip_ru {
        type ipv4_addr
        flags interval
    }

    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # Блокировка трафика из определенных стран
        ip saddr @geoip_cn drop
        ip saddr @geoip_ru drop

        tcp dport { 22, 80, 443 } accept
    }
}
```

**Шаг 4: Автоматическое обновление (cron)**
```bash
# /etc/cron.d/geoip-update
0 3 * * * root /usr/local/bin/geoip2nft.py && nft -f /etc/nftables.conf
```

### 2. Фильтрация по ASN (провайдерам)

**Скрипт ASN-фильтрации:**
```python
#!/usr/bin/env python3
"""asn2nft.py — генерация nftables sets по ASN."""
import maxminddb
import subprocess

MMDB_PATH = "/var/lib/GeoIP/GeoLite2-ASN.mmdb"
ASN_BLOCK = [12345, 67890]  # ASN для блокировки

def get_ips_by_asn(mmdb_path, asn):
    """Извлечение IP-адресов по ASN."""
    reader = maxminddb.open_database(mmdb_path)
    # В реальном использовании: загрузка PREFIX LIST для ASN
    return []

def update_nft_asn(asn, ips):
    set_name = f"asn_{asn}"
    subprocess.run(["nft", "flush", "set", "inet", "filter", set_name],
                   capture_output=True)
    for ip in ips:
        subprocess.run(["nft", "add", "element", "inet", "filter", set_name,
                       "{", ip, "}"], capture_output=True)

if __name__ == "__main__":
    for asn in ASN_BLOCK:
        ips = get_ips_by_asn(MMDB_PATH, asn)
        print(f"ASN {asn}: {len(ips)} IPs")
        update_nft_asn(asn, ips)
```

**Правило nftables:**
```bash
table inet filter {
    set asn_12345 {
        type ipv4_addr
        flags interval
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # Блокировка по ASN
        ip saddr @asn_12345 drop

        # Остальные правила...
    }
}
```

### 3. Интеграция с Threat Intelligence feeds

**Скрипт загрузки feeds:**
```bash
#!/usr/bin/env bash
# update_threat_feeds.sh — загрузка threat intelligence в nftables sets

set -euo pipefail

SETS_DIR="/var/lib/nftables/feeds"
mkdir -p "$SETS_DIR"

# abuse.ch URLhaus (вредоносные URL/IP)
curl -s "https://urlhaus.abuse.ch/downloads/ip_recent/" | \
  grep -v "^#" | awk '{print $1}' | sort -u > "$SETS_DIR/urlhaus.txt"

# abuse.ch ThreatFox (IoC)
curl -s "https://threatfox.abuse.ch/export/csv/recent/" | \
  grep "^ioc_type_ip" | cut -d',' -f3 | sort -u > "$SETS_DIR/threatfox.txt"

# Feodo Tracker (C2 Dridex/Emotet)
curl -s "https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.txt" | \
  grep -v "^#" | grep -v "^$" | sort -u > "$SETS_DIR/feodo.txt"

# FireHOL (агрегированный список)
curl -s "https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level1.netset" | \
  grep -v "^#" | grep -v "^$" | sort -u > "$SETS_DIR/firehol_level1.txt"

# Генерация nftables sets
echo "table inet threat_intel {" > /etc/nftables/threat_feeds.nft

for feed in urlhaus threatfox feodo firehol_level1; do
    IPs=$(cat "$SETS_DIR/$feed.txt" | head -50000)  # Ограничение
    echo "    set $feed {" >> /etc/nftables/threat_feeds.nft
    echo "        type ipv4_addr" >> /etc/nftables/threat_feeds.nft
    echo "        flags interval" >> /etc/nftables/threat_feeds.nft
    echo "        elements = { $(echo $IPs | tr '\n' ', ') }" >> /etc/nftables/threat_feeds.nft
    echo "    }" >> /etc/nftables/threat_feeds.nft
done

echo "}" >> /etc/nftables/threat_feeds.nft

# Применение
nft -f /etc/nftables/threat_feeds.nft
```

**Правило nftables:**
```bash
table inet threat_intel {
    set urlhaus { type ipv4_addr; flags interval; }
    set threatfox { type ipv4_addr; flags interval; }
    set feodo { type ipv4_addr; flags interval; }
    set firehol_level1 { type ipv4_addr; flags interval; }

    chain input {
        type filter hook input priority -5; policy accept;

        # Блокировка вредоносных IP
        ip saddr @urlhaus drop
        ip saddr @threatfox drop
        ip saddr @feodo drop
        ip saddr @firehol_level1 drop
    }
}
```

### 4. Комбинированная фильтрация (GeoIP + Threat Intel + Rate Limiting)

```bash
#!/usr/sbin/nft -f
flush ruleset

# GeoIP sets
table inet filter {
    set blocked_countries {
        type ipv4_addr
        flags interval
    }

    # Threat Intelligence sets
    set threat_intel {
        type ipv4_addr
        flags interval
    }

    # Rate limiting
    set ssh_bruteforce {
        type ipv4_addr
        flags dynamic, timeout
        timeout 1h
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # 1. Established/related
        ct state established,related accept

        # 2. Invalid
        ct state invalid drop

        # 3. Loopback
        iif "lo" accept

        # 4. Threat Intelligence (приоритет выше)
        ip saddr @threat_intel drop

        # 5. GeoIP (приоритет выше)
        ip saddr @blocked_countries drop

        # 6. Rate limiting SSH
        tcp dport 22 ct state new \
            limit rate over 5/minute \
            add @ssh_bruteforce { ip saddr } \
            drop

        # 7. Allowed services
        tcp dport { 22, 80, 443 } accept

        # 8. ICMP
        icmp type echo-request limit rate 5/second accept

        # 9. Log drops
        log prefix "NFT_DROP: " limit rate 10/minute
    }
}
```

### 5. Обновление sets без перезагрузки

**Горячее обновление sets:**
```bash
#!/usr/bin/env bash
# hot_update.sh — обновление sets без影响 на работающие соединения

set -euo pipefail

# Обновление GeoIP
/usr/local/bin/geoip2nft.py

# Обновление Threat Intel
/usr/local/bin/update_threat_feeds.sh

# Применение (атомарно)
nft -f /etc/nftables/threat_feeds.nft

echo "Sets updated: $(nft list sets | grep -c 'set')"
```

### 6. Мониторинг GeoIP-блокировок

```bash
# Логирование GeoIP-блокировок
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Логирование GeoIP-блокировок
        ip saddr @blocked_countries log prefix "GEOIP_BLOCK: " limit rate 10/minute drop
    }
}

# Просмотр логов
journalctl -t nftables | grep "GEOIP_BLOCK"

# Статистика по странам
nft list set inet filter blocked_countries
```

## Валидация результатов

### Проверка sets

```bash
# Просмотр GeoIP set
sudo nft list set inet filter blocked_countries

# Просмотр Threat Intel set
sudo nft list set inet filter threat_intel

# Количество элементов
sudo nft list set inet filter blocked_countries | grep -c "element"
```

### Тестирование фильтрации

```bash
# С VPN-сервера в заблокированной стране
curl -v http://target-server.com
# → Connection timed out (blocked by GeoIP)

# С доверенного IP
curl -v http://target-server.com
# → HTTP/1.1 200 OK
```

### Проверка обновлений

```bash
# Время последнего обновления
ls -la /var/lib/nftables/feeds/
# → urlhaus.txt: Sep 15 03:00

# Cron-расписание
crontab -l | grep geoip
# → 0 3 * * * /usr/local/bin/geoip2nft.py
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Set пуст** | GeoIP-скрипт не работает | Проверьте логи: `journalctl -u geoip-update` |
| **Блокируется легитимный трафик** | VPN/Proxy пользователя | Добавьте исключения для доверенных IP |
| **Обновление не применяется** | Ошибка синтаксиса | Проверьте `nft --check -f` |
| **Производительность падает** | Слишком много элементов в set | Ограничьте sets 50k элементов, используйте `interval` |
| **Threat feed недоступен** | Блокировка URL | Используйте зеркала или кэширование |

## Best Practices

1. **Не полагайтесь только на GeoIP** — используйте как дополнение к основным правилам.

2. **Ограничивайте размер sets** — >50k элементов может замедлять обработку. Используйте `interval` для CIDR-блоков.

3. **Автоматизируйте обновления** — настройте cron для ежедневного обновления GeoIP и Threat feeds.

4. **Логируйте блокировки** — используйте `log prefix "GEOIP_BLOCK: "` для анализа ложных срабатываний.

5. **Тестируйте перед блокировкой** — временно переключите `drop` на `log` для проверки влияния.

6. **Версионируйте списки** — храните GeoIP-конфигурации и threat feeds в Git.

7. **Комбинируйте** — GeoIP + Threat Intel + Rate Limiting + Stateful Inspection = многослойная защита.

## См. также

- **[nftables — моделирование угроз](./threat_modeling.md)** — bogon-фильтрация, uRPF.
- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — sets, maps.
- **[MaxMind GeoIP2](https://www.maxmind.com/en/geoip2-databases)** — официальная документация.
- **[abuse.ch](https://abuse.ch)** — бесплатные threat intelligence feeds.
- **[FireHOL](https://github.com/firehol/blocklist-ipsets)** — агрегированные списки IP.
