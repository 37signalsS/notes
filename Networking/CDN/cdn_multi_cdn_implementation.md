# CDN — Реализация Multi-CDN

## Определения

- **Multi-CDN**: Архитектурный паттерн, при котором используются одновременно несколько CDN-провайдеров для доставки контента. Обеспечивает отказоустойчивость, оптимизацию стоимости и глобальное покрытие.
- **Weighted DNS (Взвешенная маршрутизация)**: Метод распределения трафика между CDN с заданными весами (например, 70% Cloudflare, 30% Fastly).
- **Cost Routing (Маршрутизация по стоимости)**: Направление трафика через наиболее дешёвый CDN для каждого региона или типа контента.
- **Failover (Переключение при отказе)**: Автоматическое переключение трафика на резервный CDN при отказе основного.
- **Health-Check DNS (DNS с проверкой здоровья)**: DNS-сервис, который проверяет доступность CDN-провайдеров и исключает неработающие из DNS-ответов.
- **Geographic Steering**: Маршрутизация трафика по географическому принципу (например, US → Cloudflare, Asia → Akamai).
- **Latency-Based Routing**: Маршрутизация на основе измерений задержки (RTT) от пользователя до CDN.
- **Origin Shield CDN**: CDN-провайдер, выполняющий функцию Origin Shield для других CDN (например, Fastly как Shield для Cloudflare).
- **CDN Orchestration**: Управление конфигурацией нескольких CDN из единого центра (Terraform, API, Control Plane).
- **Sticky Sessions (Sticky Routing)**: Привязка пользователя к конкретному CDN на время сессии (например, через cookies).

---

## Теория

### Зачем Multi-CDN?

**Проблемы одного CDN:**
- **Single Point of Failure**: При отказе CDN все пользователи недоступны.
- **Vendor Lock-in**: Зависимость от одного провайдера.
- **Стоимость**: Невозможность сравнения и выбора наиболее дешёвого варианта.
- **Покрытие**: Ни один CDN не покрывает 100% глобальных PoP идеально.

**Преимущества Multi-CDN:**
- **100% Uptime**: Если один CDN упал, трафик переключается на другой.
- **Cost Optimization**: Сравнение тарифов и маршрутизация через дешёвый CDN.
- **Geo-Optimization**: Выбор CDN с лучшим покрытием для каждого региона.
- **Performance**: Автоматический выбор CDN с наименьшей задержкой для пользователя.
- **Negotiation Leverage**: Возможность торга с провайдерами.

### Архитектурные модели

**Модель 1: DNS-Based Multi-CDN**
```
[Клиент] → DNS Resolver → Weighted A/CNAME → [CDN-1] → Origin
                                                 [CDN-2] → Origin
```
- DNS-сервис (Route53, NS1, DNSimple) распределяет трафик по CDN.
- Каждый CDN кэширует контент независимо.
- При отказе CDN DNS исключает его из ответов.

**Модель 2: Application-Based Multi-CDN**
```
[Клиент] → Application Logic → CDN-1 или CDN-2 → Origin
```
- Приложение само определяет, какой CDN использовать (на основе гео, latency, failover).
- Гибкость: можно выбирать CDN для каждого запроса.
- Сложность: требует разработки.

**Модель 3: CDN-As-Origin (CDN Chain)**
```
[Клиент] → CDN-1 (Edge) → CDN-2 (Shield) → Origin
```
- CDN-1 кэширует контент, CDN-2 выступает как Origin Shield.
- Уникальная архитектура: CDN-2 снижает нагрузку на Origin.

### DNS-провайдеры для Multi-CDN

| Провайдер | Гео-DNS | Weighted | Health Checks | GSLB | API |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AWS Route 53** | Да | Да | Да (HTTP/TCP/Calculated) | Да | REST |
| **NS1** | Да | Да | Да (HTTP/TCP/DNS) | Да | REST |
| **Cloudflare** | Да | Да | Да (как CDN) | Да | REST |
| **Akamai (Edge DNS)** | Да | Да | Да | Да | REST |
| **Google Cloud DNS** | Да | Да (Weighted) | Нет | Нет | REST |

### Стратегии распределения трафика

**Weighted Routing:**
```
CDN-1 (Cloudflare): 70% трафика (основной)
CDN-2 (Fastly):     30% трафика (резервный)
```

**Geo-Based Routing:**
```
US/EU → Cloudflare (основной, дешевле)
Asia  → Akamai (лучшее покрытие)
Other → Fastly (бэкап)
```

**Latency-Based Routing:**
```
RTT < 20ms  → Cloudflare (ближе)
RTT > 20ms  → Fastly (альтернатива)
```

**Failover Routing:**
```
Primary → Cloudflare (health check: HTTP 200 на /healthz)
Backup  → Fastly (включается при failure Cloudflare)
```

### Проблемы Multi-CDN

**Кэширование:**
- Каждый CDN кэширует контент независимо → двойной Egress к-Origin.
- Решение: использовать `stale-while-revalidate` и синхронизацию кэша между CDN.

**Инвалидация:**
- Purge должен быть отправлен во все CDN.
- Решение: единый API-эндпоинт для инвалидации во все CDN.

**SSL/TLS:**
- Каждый CDN использует свой сертификат.
- Решение: автоматическое обновление сертификатов через ACME.

**Мониторинг:**
- Нужен единый дашборд для всех CDN.
- Решение: агрегация метрик через Prometheus/Grafana.

---

## Практика

### Route 53: Weighted Routing

```bash
# Создание weighted routing policy
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "cdn.example.com",
          "Type": "CNAME",
          "SetIdentifier": "cloudflare",
          "Weight": 70,
          "TTL": 60,
          "ResourceRecords": [{"Value": "example.com.cdn.cloudflare.net"}]
        }
      },
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "cdn.example.com",
          "Type": "CNAME",
          "SetIdentifier": "fastly",
          "Weight": 30,
          "TTL": 60,
          "ResourceRecords": [{"Value": "example.com.edgekey.net"}]
        }
      }
    ]
  }'
```

### Route 53: Failover Routing

```bash
# Primary + Failover
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "cdn.example.com",
          "Type": "A",
          "SetIdentifier": "primary",
          "Failover": "PRIMARY",
          "TTL": 60,
          "AliasTarget": {
            "HostedZoneId": "Z35SXDOTRQ7X7K",
            "DNSName": "d1234567890.cloudfront.net",
            "EvaluateTargetHealth": true
          },
          "HealthCheckId": "health-check-id"
        }
      },
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "cdn.example.com",
          "Type": "CNAME",
          "SetIdentifier": "secondary",
          "Failover": "SECONDARY",
          "TTL": 60,
          "ResourceRecords": [{"Value": "example.com.cdn.cloudflare.net"}]
        }
      }
    ]
  }'
```

### Route 53: Health Check

```bash
# Создание health check
aws route53 create-health-check \
  --caller-reference "cdn-health-$(date +%s)" \
  --health-check-config '{
    "IPAddress": "104.16.132.229",
    "Port": 443,
    "Type": "HTTPS",
    "ResourcePath": "/healthz",
    "FullyQualifiedDomainName": "cdn.cloudflare.com",
    "RequestInterval": 10,
    "FailureThreshold": 3,
    "EnableSNI": true
  }'
# → HealthCheck ID: health-check-id
```

### NS1: Geo-Based Routing

```bash
# Создание geo-based записи через NS1 API
curl -X PUT "https://api.ns1.com/v1/zones/example.com/records/CNAME/cdn" \
  -H "X-NSONE-Key: {api_key}" \
  -H "Content-Type: application/json" \
  --data '{
    "zone": "example.com",
    "domain": "cdn.example.com",
    "type": "CNAME",
    "ttl": 60,
    "answers": [
      {
        "answer": ["example.com.cdn.cloudflare.net"],
        "meta": {
          "georegion": ["US", "EU"],
          "upstreams": ["cloudflare"]
        }
      },
      {
        "answer": ["example.com.edgekey.net"],
        "meta": {
          "georegion": ["ASIA"],
          "upstreams": ["akamai"]
        }
      }
    ],
    "filters": [
      {"filter": "georegion", "config": {}},
      {"filter": "failover", "config": {"failover": ["cloudflare", "akamai"]}}
    ]
  }'
```

### Terraform: Multi-CDN Configuration

```hcl
# main.tf — Route53 Multi-CDN
provider "aws" {
  region = "us-east-1"
}

# Cloudflare (Primary)
resource "aws_route53_record" "cdn_cloudflare" {
  zone_id = var.zone_id
  name    = "cdn.example.com"
  type    = "CNAME"
  ttl     = 60
  weighted_routing_policy {
    weight = 70
  }
  set_identifier = "cloudflare"
  records        = ["example.com.cdn.cloudflare.net"]
}

# Fastly (Secondary)
resource "aws_route53_record" "cdn_fastly" {
  zone_id = var.zone_id
  name    = "cdn.example.com"
  type    = "CNAME"
  ttl     = 60
  weighted_routing_policy {
    weight = 30
  }
  set_identifier = "fastly"
  records        = ["example.com.edgekey.net"]
}

# Health Check
resource "aws_route53_health_check" "cloudflare_health" {
  ip_address        = "104.16.132.229"
  port              = 443
  type              = "HTTPS"
  resource_path     = "/healthz"
  failure_threshold = 3
  request_interval  = 10
  enable_sni        = true
}
```

### Единый API для Purge

```python
# purge_all_cdns.py — инвалидация кэша во всех CDN одновременно
import requests
import json
from concurrent.futures import ThreadPoolExecutor

CLOUDFLARE_TOKEN = "{cf_token}"
CLOUDFLARE_ZONE = "{cf_zone}"
FASTLY_TOKEN = "{fastly_token}"
FASTLY_SERVICE = "{fastly_service}"

def purge_cloudflare(urls):
    """Purge URLs from Cloudflare."""
    resp = requests.post(
        f"https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE}/purge_cache",
        headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}"},
        json={"files": urls}
    )
    return {"cdn": "cloudflare", "status": resp.json()["success"]}

def purge_fastly(urls):
    """Purge URLs from Fastly."""
    results = []
    for url in urls:
        resp = requests.request(
            "PURGE", url,
            headers={"Fastly-Key": FASTLY_TOKEN}
        )
        results.append(resp.status_code == 200)
    return {"cdn": "fastly", "status": all(results)}

def purge_all(urls):
    """Purge URLs from all CDNs in parallel."""
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(purge_cloudflare, urls),
            executor.submit(purge_fastly, urls)
        ]
        results = [f.result() for f in futures]
    return results

# Пример использования
if __name__ == "__main__":
    urls_to_purge = [
        "https://example.com/index.html",
        "https://example.com/style.css",
        "https://example.com/api/products"
    ]
    results = purge_all(urls_to_purge)
    print(json.dumps(results, indent=2))
# → [{"cdn":"cloudflare","status":true},{"cdn":"fastly","status":true}]
```

### Мониторинг Multi-CDN

```bash
#!/bin/bash
# multi_cdn_monitor.sh — мониторинг всех CDN

# Функция проверки CDN
check_cdn() {
  local name=$1
  local url=$2

  START=$(date +%s%N)
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  END=$(date +%s%N)
  LATENCY=$(( (END - START) / 1000000 ))

  echo "$name: HTTP $HTTP_CODE, Latency: ${LATENCY}ms"
}

echo "=== Multi-CDN Health Check ==="
check_cdn "Cloudflare" "https://example.com.cdn.cloudflare.net/healthz"
check_cdn "Fastly" "https://example.com.edgekey.net/healthz"
check_cdn "CloudFront" "https://d1234567890.cloudfront.net/healthz"
echo ""

# Проверка DNS resolve
echo "=== DNS Resolution ==="
dig +short example.com | head -5
echo ""

# Проверка Cache Status
echo "=== Cache Status ==="
for cdn in "Cloudflare" "Fastly"; do
  curl -sI "https://example.com/" | grep -iE "cache-status|cf-ray|x-cache" | head -3
  echo "---"
done
```

---

## Дополнительная информация

### Сравнение Multi-CDN провайдеров

| Критерий | Cloudflare | Fastly | Akamai | CloudFront |
| :--- | :--- | :--- | :--- | :--- |
| **Стоимость** | $0.02/GB | $0.12/GB | $0.03-0.08/GB | $0.085/GB |
| **Инвалидация** | <200 мс | <150 мс | 5-10 сек | 5-15 мин |
| **Geo-DNS** | Да | Нет (через DNS-провайдер) | Да (Edge DNS) | Да (Route 53) |
| **Health Checks** | Встроенные | Встроенные | Встроенные | Route 53 |
| **Multi-CDN поддержка** | Да (как CDN) | Да (как CDN) | Да (как CDN) | Да (через Route 53) |
| **Edge Computing** | Workers | Compute | EdgeWorkers | Lambda@Edge |

### Типичные ошибки и их решение

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Double Egress** | Два CDN кэшируют один контент | Использовать единственный CDN для кэширования, второй — только как бэкап |
| **Stale Cache** | Конфликтующие версии контента в разных CDN | Использовать Surrogate Keys + единый API для Purge |
| **Split-Brain DNS** | Часть пользователей идёт на другой CDN | Уменьшить TTL DNS до 30-60 сек |
| **SSL Mismatch** | Ошибки SSL на одном из CDN | Автоматическое обновление сертификатов через ACME |

### Связанные темы

- **[Обзор CDN](cdn_overview.md)** — стратегии развертывания Multi-CDN.
- **[Оптимизация стоимости](cdn_cost_optimization.md)** — Cost Routing между CDN.
- **[Health Checks](cdn_origin_health_checks.md)** — проверка здоровья CDN.
- **[Логирование и Tracing](cdn_logging_and_tracing.md)** — агрегация метрик Multi-CDN.
