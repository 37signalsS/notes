# A/B-тестирование в Kubernetes (A/B Testing)

## Определения

**A/B-тестирование (A/B Testing / Split Testing)** — стратегия прогрессивной поставки (Progressive Delivery), ориентированная на проверку бизнес-гипотез и UX-метрик путем параллельного запуска двух версий приложения и сравнения их эффективности на сегментированных группах пользователей. В отличие от Canary, где критерий принятия решения — технические метрики (ошибки, латентность), в A/B тестировании решение принимается по продуктовым показателям (конверсия, выручка, удержание).

- **Контрольная группа (Control Group / Version A)** — группа пользователей, работающая с текущей стабильной версией продукта (baseline).
- **Экспериментальная группа (Treatment Group / Version B)** — группа пользователей, получающая новую версию с тестируемым изменением.
- **Статистическая значимость (Statistical Significance)** — показатель того, что разница в результатах групп A и B не является случайной (проверяется через p-value < 0.05 или доверительный интервал, не пересекающий 0).
- **Сегментация трафика** — разделение входящего потока запросов на основе атрибутов пользователя (HTTP-заголовки, Cookie, User-Agent, IP-адрес, регион, ID пользователя).
- **Липкие сессии (Sticky Sessions)** — механизм, гарантирующий, что конкретный пользователь будет видеть одну и ту же версию приложения на протяжении всего эксперимента, исключая "прыгающий" интерфейс.
- **Feature Flag (Флаг функциональности)** — механизм управления видимостью новой логики внутри уже развернутой версии кода через конфигурацию, без перевыпуска артефакта. Дополняет инфраструктурную маршрутизацию, обеспечивая более тонкую сегментацию на уровне приложения.
- **OpenFeature** — открытый стандарт для управления флагами функциональности, предоставляющий единый API поверх разных бэкендов (Unleash, LaunchDarkly, Flagsmith).
- **Kill Switch (Аварийный выключатель)** — механизм мгновенного отключения эксперимента без деплоя и перезапуска приложения, обычно реализуемый через Feature Flag.
- **Session Affinity (Привязка сессии)** — механизм балансировщика или Service Mesh, который на основе Cookie или IP гарантирует, что повторные запросы одного пользователя попадают на ту же реплику.
- **Бизнес-метрики (Business Metrics)** — целевые показатели эксперимента: конверсия, средний чек, удержание, время на странице.
- **Guardrail-метрики (Технические метрики)** — SRE Golden Signals (латентность p99, error rate, saturation, трафик), которые не должны деградировать во время эксперимента.

## Основные концепции

### Архитектура A/B-тестирования

A/B-тестирование строится на двух независимых уровнях управления доступом к функционалу:

1. **Инфраструктурный уровень (L7 Routing):**
   - Управляется через **Gateway API**, **Service Mesh** (Istio, Cilium), **Ingress** (Nginx, HAProxy, Traefik) или балансировщики традиционной инфраструктуры.
   - Идеален для тестирования крупных изменений (новые версии сервисов, полная замена фронтенда, другой бэкенд).
   - Не требует изменения кода приложения для сегментации.
   - Сегментация происходит до того, как запрос достигает приложения.

2. **Прикладной уровень (Feature Flags):**
   - Управляется через системы управления флагами (например, **Unleash** — self-hosted OSS, **Flagsmith**, **LaunchDarkly**) и открытый стандарт **OpenFeature**.
   - Позволяет проводить множество независимых экспериментов внутри одного сервиса.
   - Максимально гибкая сегментация (по логике приложения, правам доступа, данным из БД, поведению пользователя).
   - Требует интеграции SDK в код приложения.

### Разделение ответственности: Сеть vs Код

| Критерий | L7 Routing | Feature Flags |
| :--- | :--- | :--- |
| **Скорость отката** | Средняя (требует обновления конфигурации балансировщика) | Высокая (Kill Switch через API флагов) |
| **Гибкость сегментации** | Ограничена HTTP-атрибутами (header, cookie, IP) | Полная (любые данные приложения, %) |
| **Влияние на производительность** | Нулевое (решается на уровне инфраструктуры) | Минимальное (проверка флага в коде) |
| **Сложность внедрения** | Требует настройки маршрутизации | Требует интеграции SDK |
| **Длительность эксперимента** | Дни-недели (зависит от инфраструктуры) | Недели-месяцы (независимо от релизов) |

### Проблема сосуществования версий

Длительность A/B-тестов (от нескольких дней до недель) накладывает жесткие требования на инфраструктуру:

- **Совместимость данных:** База данных должна поддерживать обе версии одновременно. Обязательно использование паттерна **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
- **Наблюдаемость:** Метрики (Prometheus/OpenTelemetry) должны быть обогащены тегами версии или идентификаторами эксперимента для разделения выборок.
- **Ресурсы:** Параллельный бег двух версий удваивает минимальные требования к вычислениям/памяти и квотам флота раннеров — планируйте ёмкость с запасом на период теста (см. [Управление парком раннеров](../runner-fleet-management.md)).
- **Обратная совместимость API:** Обе версии должны поддерживать старый контракт, иначе пользователи, попавшие на v2, столкнутся с ошибками при изменении v1.
- **Sticky Sessions:** Без гарантии липкости сессии пользователь будет "прыгать" между версиями при каждом запросе, делая метрики невалидными.

### A/B vs Canary: ключевые различия

| Характеристика | A/B Testing | Canary Deployment |
| :--- | :--- | :--- |
| **Цель** | Бизнес-валидация (конверсия, UX) | Техническая стабильность (ошибки, латентность) |
| **Длительность** | Дни / Недели | Минуты / Часы |
| **Аудитория** | Специфические сегменты (по атрибутам) | Случайный % трафика |
| **Решение об откате** | Ручное (продуктовое решение) или бизнес-гейтинг | Автоматическое (SRE Golden Signals) |
| **Сегментация** | По атрибутам (cookie, header, ID) | По весу (%) |
| **Sticky Sessions** | Обязательны | Опциональны |
| **Метрики** | Бизнес-метрики + Guardrail | Golden Signals + Error Budget |

### Роли и зоны ответственности

| Аспект | DevOps | SRE | Sysadmin |
| :--- | :--- | :--- | :--- |
| **Сегментация трафика** | Gateway API, Service Mesh (Istio/Cilium), веса в L7-балансировщике | Traffic splitting, cookie/header-based routing, session affinity | Nginx `map`, HAProxy ACL, Apache `mod_rewrite` |
| **Feature Flags** | Интеграция OpenFeature SDK в пайплайн, управление жизненным циклом флага | Kill Switch, гейтинг по бизнес-метрикам, автоматический откат | Развертывание Unleash/Flagsmith, управление окружениями |
| **Наблюдаемость** | Pipeline Observability, DORA-метрики, OpenTelemetry | Бизнес-метрики (конверсия, выручка), A/B-анализ, статистические тесты | node_exporter, journald, access-логи балансировщика |
| **Базы данных** | Миграции через CI/CD, Expand-Contract, обратная совместимость | Схемная миграция без даунтайма, репликация, откат без потери данных | Бэкапы, восстановление, репликация (PostgreSQL/MySQL) |

## Практические сценарии

### 1. A/B через Gateway API (Kubernetes)

Сегментация по значению Cookie с использованием `HTTPRoute`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: frontend-ab-test
spec:
  parentRefs:
  - name: internal-gateway
  hostnames: ["shop.example.com"]
  rules:
  - matches:
    - headers:
      - name: "cookie"
        value: ".*user_segment=beta.*"
        type: RegularExpression
    backendRefs:
    - name: frontend-v2
      port: 80
  - backendRefs:
    - name: frontend-v1
      port: 80
```

### 2. A/B через Nginx (map по cookie/заголовку)

```nginx
http {
    map $cookie_ab_test $ab_target {
        default      stable_app;
        "v2"         canary_app;
    }
    map $http_x_ab_test $ab_target_hdr {
        default      $ab_target;
        "v2"         canary_app;
    }

    upstream stable_app { server 10.0.1.10:8080; }
    upstream canary_app { server 10.0.1.20:8080; }

    server {
        listen 80;
        location / {
            proxy_pass http://$ab_target_hdr;
        }
    }
}
```

**Валидация:**
```bash
# → попадает на canary
curl --cookie "ab_test=v2" http://lb.local/
# → попадает на stable (контрольная группа)
curl http://lb.local/
```

### 3. A/B через HAProxy (ACL по заголовку/cookie)

```haproxy
frontend app_frontend
    bind *:80
    acl is_ab_test_v2 hdr_sub(cookie) ab_test=v2
    use_backend app_v2 if is_ab_test_v2
    default_backend app_v1

backend app_v1
    server app1 10.0.1.10:8080 check

backend app_v2
    server app2 10.0.1.20:8080 check
```

### 4. A/B через Apache mod_rewrite

```apache
RewriteEngine On
RewriteCond %{HTTP_COOKIE} ab_test=v2 [NC]
RewriteRule ^/(.*)$ http://app-v2.internal:8080/$1 [P,L]
ProxyPassReverse / http://app-v2.internal:8080/
```

### 5. Feature Flags на прикладном уровне (Unleash + OpenFeature)

Интеграция через OpenFeature SDK позволяет переключать логику без перезапуска подов:

```python
# Пример использования OpenFeature Python SDK
from openfeature import api

client = api.get_client()
show_new_checkout = client.get_boolean_value("new-checkout-flow", False)

if show_new_checkout:
    return render_v2()
else:
    return render_v1()
```

### 6. Атомарный откат в традиционной среде (systemd + symlink)

Для монолитов и приложений без балансировщика:

```bash
# Развертывание новой версии рядом со старой (immutable artifacts)
ln -sfn /opt/app/2.3.1 /opt/app/current
systemctl restart myapp

# Мгновенный откат (Kill Switch через симлинк)
ln -sfn /opt/app/2.3.0 /opt/app/current
systemctl restart myapp

# Живое изменение лимита ресурсов (In-Place Resize)
systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%
```

### 7. Автоматизация A/B через Ansible (Bare Metal/VM)

```yaml
- hosts: lb
  become: true
  tasks:
    - name: Deploy v2 artifacts
      unarchive:
        src: "/opt/apps/myapp/2.3.1.tar.gz"
        dest: "/opt/apps/myapp/2.3.1/"
        remote_src: yes

    - name: Switch traffic to v2 via Nginx map
      lineinfile:
        path: /etc/nginx/conf.d/ab_test.conf
        regexp: '^[[:space:]]*"v2".*canary_app;'
        line: '    "v2"         canary_app;'
      notify: reload nginx

  handlers:
    - name: reload nginx
      systemd:
        name: nginx
        state: reloaded
```

### 8. Автоматизация бизнес-метрик через Argo Rollouts

Argo Rollouts может выступать в роли "судьи", анализируя бизнес-показатели перед продвижением версии:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: conversion-rate-check
spec:
  metrics:
  - name: order-success-rate
    interval: 1h
    successCondition: result >= 0.15 # Ожидаемая конверсия > 15%
    provider:
      prometheus:
        address: http://prometheus.monitoring.svc.cluster.local:9090
        query: |
          sum(rate(order_created_total{version="{{args.version}}"}[1h]))
          /
          sum(rate(http_requests_total{version="{{args.version}}"}[1h]))
```

### 9. Быстрый откат и Kill-switch (runbook)

A/B должен отключаться за секунды, не дожидаясь конца теста:

- **Через флаг (preferred):** выключить `new-checkout-flow` в Unleash/OpenFeature → весь трафик возвращается на v1 без деплоя. Самый быстрый и безопасный путь.
- **Через маршрутизацию:** удалить/обновить конфигурацию балансировщика, убрав правило по Cookie — весь трафик пойдёт на стабильную версию.
- **Guardrail-автостоп:** добавить метрику-страж (error rate > порога) с `failureCondition`, чтобы система сама прервала эксперимент.

После остановки — зафиксировать метрики, провести blameless-постмортем; не перезапускать тест на той же когорте без правки гипотезы.

### 10. Метрики, статистическая значимость и guardrails

A/B — одновременно бизнес- и SRE-задача. Чтобы эксперимент не довёл прод к падению выручки и инфраструктуры, совмещайте два класса метрик:

- **Бизнес-метрики (целевые):** конверсия, выручка на пользователя, удержание — источник решения об успехе.
- **Guardrail-метрики (технические):** SRE Golden Signals — латентность p99, error rate (5xx), saturation, трафик. Если guardrail пробит, эксперимент останавливается автоматически, независимо от бизнес-метрик.

**Статистическая значимость:** разница считается значимой при p-value < 0.05 (или доверительном интервале, не пересекающем 0) и достаточном размере выборки. Для бинарных метрик (конверсия) размер выборки n оценивается по формуле для долей:

```
n ≈ (z_α/2 + z_β)^2 · (p1·(1-p1) + p2·(1-p2)) / (p2 - p1)^2
```

где p1/p2 — базовая и ожидаемая конверсии, z — квантили нормального распределения (1.96 для α=0.05). Утилиты: `statsmodels`/`scipy` (Python), онлайн A/B-калькуляторы; в пайплайне проверку удобно делать через AnalysisTemplate по Prometheus-запросу.

### 11. Валидация маршрутизации (практика SRE)

Проверка, что пользователь с нужным Cookie попадает на версию B:

```bash
# Запрос с сегментом beta — ожидаем ответ от frontend-v2
curl -s -i -H "Cookie: user_segment=beta" https://shop.example.com/ | head -1

# Контрольная группа (без cookie) — должна уйти на frontend-v1
curl -s -i https://shop.example.com/ | head -1

# Проверка фактического бэкенда через заголовок, проставленный приложением
curl -s -H "Cookie: user_segment=beta" https://shop.example.com/healthz | grep -i version
```

Если пользователь «прыгает» между версиями — нет Session Affinity / sticky sessions (см. Troubleshooting). Для Gateway API закрепление реализуется через `SessionPersistence` или на sidecar-прокси.

## Операции и команды

### Nginx — проверка A/B маршрутизации

```bash
# Проверка конфигурации
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Применение изменений (перезагрузка без потерь)
systemctl reload nginx
# → (служебный вывод systemd)

# Просмотр upstream и активных соединений
curl http://localhost/status  # (если включен stub_status)
# → Active connections: 42
# → server accepts handled requests: 12345 12345 56789
```

### HAProxy — оперативное управление ACL и весами

```bash
# Просмотр состояния серверов
echo "show stat" | socat /var/run/haproxy.sock stdio | grep app_servers
# → app1,FRONTEND,...,UP,...
# → app2,FRONTEND,...,UP,...

# Вывод узла в drain (остановка приема новых соединений)
echo "set server app_servers/app1 state drain" | socat /var/run/haproxy.sock stdio
# → (пустой вывод, статус меняется на DRY)

# Возврат узла в пул
echo "set server app_servers/app1 state ready" | socat /var/run/haproxy.sock stdio
# → status=UP

# Перезагрузка конфигурации без потери соединений
systemctl reload haproxy
# → (служебный вывод systemd)
```

### Gateway API — проверка весов трафика

```bash
# Просмотр HTTPRoute
kubectl get httproute frontend-ab-test -o yaml

# Проверка статуса родительского шлюза
kubectl get gateway internal-gateway

# Применение изменений
kubectl apply -f httproute-ab-test.yaml
# → httproute.gateway.networking.k8s.io/frontend-ab-test configured
```

### Istio / Envoy — проверка распределения трафика

```bash
# Просмотр виртуальных сервисов
istioctl proxy-config routes deployment/frontend-v1 --context prod

# Проверка кластеров и весов
istioctl proxy-config clusters deployment/frontend-v1 --context prod

# Проверка статуса прокси
istioctl proxy-status
# → myapp-v1-xxx    istio-gateway-xxx   SYNCED
```

### systemd — атомарная смена версии и управление ресурсами

```bash
# Проверка статуса сервиса
systemctl status myapp
# → Active: active (running) since ...

# Смена версии через symlink (immutable artifacts)
ln -sfn /opt/app/2.3.1 /opt/app/current
systemctl restart myapp

# Быстрый откат (Kill Switch)
ln -sfn /opt/app/2.3.0 /opt/app/current
systemctl restart myapp

# Живое изменение лимита ресурсов (In-Place Resize)
systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%
# → применяется мгновенно, без рестарта
```

### Ansible — деплой и переключение A/B

```bash
# Проверка конфигурации перед применением (dry-run)
ansible-playbook deploy.yml --check --diff
# → changed=0, unreachable=0, failed=0 (проверка пройдена)

# Применение плейбука с ограничением по тегу
ansible-playbook deploy.yml \
  --limit "tag_env_production:&tag_role_app" \
  --extra-vars "app_version=2.3.1"
# → playbook завершен, изменения применены
```

### Prometheus — запросы для A/B-анализа

```bash
# Относительный error rate (v2 vs v1)
curl -s "http://prometheus:9090/api/v1/query?query=\
sum(rate(http_requests_total{version=\"v2\",status=~\"5..\"}[5m]))\
/sum(rate(http_requests_total{version=\"v2\"}[5m]))"
# → результат < 0.01 (1%) при норме

# Latency P95 по версиям
curl -s "http://prometheus:9090/api/v1/query?query=\
histogram_quantile(0.95,sum(rate(http_request_duration_seconds_bucket[5m]))by(le,version))"
# → {"value":[...,"0.142"]} (P95 = 142 мс)
```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"Прыгающий" интерфейс** | Отсутствие Sticky Sessions или сброс Cookie. | Настроить Session Affinity на балансировщике или использовать хеширование ID пользователя в SDK. |
| **Отравление метрик (Metric Poisoning)** | Один пользователь попал в несколько конфликтующих экспериментов. | Использование "взаимоисключающих групп" (Exclusion Groups) в системе Feature Flags. |
| **SRM (Sample Ratio Mismatch)** | Распределение трафика (например, 50/50) не соответствует реальности. | Проверка корректности работы хэш-алгоритмов балансировщика. |
| **Пользователь "прыгает" между версиями** | Cookie не установлен или сбрасывается (SameSite, Secure, Domain). | Проверить атрибуты Cookie на стороне приложения и балансировщика. |
| **v2 не получает трафик (Nginx)** | `map` не срабатывает из-за опечатки в имени Cookie. | Включить `debug` логирование переменных Nginx или использовать `add_header X-Ab-Target $ab_target;` для отладки. |
| **v2 не получает трафик (HAProxy)** | ACL привязан к `$remote_addr` за NAT → все на stable. | Использовать ACL по заголовку или cookie вместо source IP. |
| **Оба сервиса получают трафик** | Нет явного `default_backend` или перекрытие правил. | Убедиться, что `default_backend` указан и правила не конфликтуют. |
| **Статистическая незначимость** | Выборка слишком мала или эксперимент слишком короткий. | Увеличить длительность эксперимента или использовать стратифицированную выборку. |
| **Обратная несовместимость БД** | v2 ожидает новую колонку, которой нет в схеме. | Применить паттерн Expand-Contract: добавить колонку (Expand), мигрировать данные, затем удалить старую (Contract). |
| **Ошибка 5xx только на v2** | Деградация новой версии под реальной нагрузкой. | Немедленный откат через Kill Switch, анализ логов, повторный деплой с фиксом. |
| **Latency v2 выше, чем v1** | Нет прогрева кэшей (JIT, connection pool) или неверная конфигурация. | Добавить warm-up период перед началом эксперимента, проверить конфигурацию пулов соединений. |
| **Конверсия v2 ниже, но latency выше** | Конфликт бизнес- и guardrail-метрик. | Остановить эксперимент, проанализировать причину деградации, не продвигать версию. |
| **Cookie не передается (HTTPS)** | Флаг `Secure` установлен, но тестирование идет по HTTP. | Использовать HTTPS для тестирования или временно отключить флаг `Secure` в dev-среде. |
| **Feature Flag не срабатывает** | SDK не инициализирован или конфиг флага не обновлен. | Проверить подключение к Unleash/Flagsmith, обновить конфигурацию флага, проверить логи SDK. |
| **Метрики не разделены по версиям** | Отсутствует лейбл `version` в Prometheus-экспозиции. | Добавить лейбл через переменную окружения `VERSION` или через relabeling в Prometheus. |
| **Saturation растет только на v2** | Утечка памяти или неоптимальная конфигурация в новой версии. | Проанализировать профиль памяти (pprof, async-profiler), проверить конфигурацию пулов. |
| **Эксперимент "зависает" без решения** | Нет автоматического гейтинга и оператор забывает про эксперимент. | Настроить TTL для эксперимента, автоматические напоминания, обязательный postmortem. |
| **DNS кэширует старые IP** | Клиенты используют DNS для маршрутизации и кэшируют TTL. | Перейти на L7-балансировщик (Nginx/HAProxy) для маршрутизации, снизить TTL только как крайняя мера. |
| **Clock Drift между узлами** | Время на серверах v1 и v2 расходится, ломая корреляцию логов. | Настроить chrony/NTP на всех узлах, проверить `chronyc tracking`. |
| **Config Drift на Bare Metal** | v2-узел "накопил" ручные изменения, отличается от v1. | Ежедневный `ansible-playbook --check --diff`, переход на Immutable Images. |
| **Graceful Shutdown не работает** | Приложение не перехватывает SIGTERM или ждет слишком долого. | Добавить обработчик сигнала в код, увеличить `TimeoutStopSec` до 60–120 с. |

## Лучшие практики

### Архитектура и проектирование

1. **Одна стратегия на эксперимент:** Не смешивайте L7 Routing и Feature Flags в одном эксперименте без явной необходимости. Каждый механизм имеет свою модель риска.
2. **Separation of Concerns:** Разделите три оси — доставку артефакта, управление трафиком и валидацию. Связка `CI → артефактори → реестр` не должна жестко зависеть от `балансировщик → веса`.
3. **Иммутабельность артефактов:** Никогда не используйте тег `:latest`. Обновление должно инициироваться сменой конкретной версии образа или хеша конфигурации.
4. **Expand and Contract:** При обновлении работают две версии приложения. База данных должна поддерживать обе схемы одновременно. Подробнее: **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
5. **Feature Flags отдельно от маршрутизации:** L7 Routing управляет *трафиком между версиями*, флаг — *видимостью функции внутри одной версии*. Разные оси риска.

### Надёжность и безопасность

6. **Sticky Sessions обязательны** для A/B тестирования — иначе пользователь будет "прыгать" между версиями, делая метрики невалидными.
7. **Kill Switch всегда доступен:** A/B должен отключаться за секунды через Feature Flag или переключение конфигурации балансировщика, без деплоя.
8. **Health-эндпоинт проверяет зависимости**, а не только `200 OK`. Иначе балансировщик пустит трафик в «живой, но мертвый» экземпляр.
9. **Graceful shutdown обязателен** — иначе активные запросы получат 502 при выводе узла из пула.
10. **Fail-Closed:** при недоступности мониторинга или ошибке «судьи» эксперимент останавливается, а не продолжается автоматически.

### Производительность и наблюдаемость

11. **Golden Signals в окне эксперимента:** После каждой волны фиксируются Error Rate, P95 Latency и Saturation. Продолжение эксперимента допустимо, только если Error Budget не исчерпан.
12. **Статистическая значимость:** разница считается значимой при p-value < 0.05 и достаточном размере выборки. Не принимайте решения на основе малого числа событий.
13. **Валидируйте маршрутизацию:** перед началом эксперимента проверьте, что сегментация работает корректно (`curl` с нужными Cookie/headers).
14. **Мониторьте shadow-пул отдельно:** метрики CPU/RAM/fd экспериментальной версии не должны смешиваться с baseline в дашбордах.
15. **Исключайте динамические поля из diff:** requestId, timestamp, nonce — иначе Comparison Engine будет генерировать False Positive при сравнении ответов версий.

### Организация процессов

16. **TTL для эксперимента:** эксперимент должен иметь автоматический срок завершения (например, 2 недели), по истечении которого трафик возвращается на baseline или принимается решение.
17. **Postmortem после каждого failed experiment** — без поиска виноватого, с action-items по предотвращению рецидива.
18. **Runbook на откат** — оператор должен за ≤5 минут выполнить откат по письменной инструкции.
19. **Ежедневный `ansible-playbook --check --diff`** для Bare Metal/VM — предотвращает Config Drift, который делает откат ненадежным.
20. **Атомарность операций:** L7-веса (HAProxy runtime API), симлинки (`ln -sfn`), VIP (VRRP) — все эти примитивы должны быть атомарными и проверяемыми.

## Граничные случаи и ограничения

- **Долгоживущие WebSocket/gRPC соединения:** при изменении веса маршрутизации активные каналы не должны обрываться. Настройте connection draining и graceful shutdown с увеличенными таймаутами.
- **Stateful-сервисы с сессиями в памяти:** A/B-тестирование для stateful-сервисов требует либо внешнего хранения сессий (Redis, Memcached), либо гарантии Session Affinity на уровне балансировщика.
- **Низкая нагрузка (ночные часы):** при недостаточном трафике эксперимент не наберет статистическую значимость. Используйте генератор синтетического трафика или отложите тест.
- **Когортные эффекты (Cohort Effects):** поведение пользователей меняется со временем (сезонность, дни недели). Используйте стратифицированную выборку или A/A-тест для калибровки baseline.
- **Ошибки множественного сравнения (Multiple Comparisons Problem):** при тестировании нескольких гипотез одновременно увеличивается вероятность ложного положительного результата. Применяйте поправку Бонферрони или Холма-Бонферрони.
- **Network Partitions / Split Brain:** при разделении сети балансировщики могут по-разному интерпретировать конфигурацию. Используйте Consensus-алгоритмы (etcd, Consul) для хранения состояния весов.
- **Bare Metal / VM: атомарность symlink на NFS:** `ln -sfn` на сетевой файловой системе не является атомарной операцией, возможна гонка. Перенесите артефакты на локальный диск или используйте lock-файл (`flock`) вокруг смены symlink.
- **Feature Flag-ы в distributed systems:** при отсутствии централизованного store флаги могут расходиться между инстансами. Используйте итоговый (eventual) консистентный store или кэширование с TTL.

## Дополнительная информация

### Сравнение с Canary Deployment

| Характеристика | Canary Deployment | A/B Testing |
| :--- | :--- | :--- |
| **Цель** | Техническая стабильность и безопасность | Проверка бизнес-гипотез и UX |
| **Аудитория** | Случайный % трафика (или внутренние пользователи) | Специфические бизнес-сегменты |
| **Метрики** | Ошибки, задержки, потребление ресурсов | Конверсия, клики, время на странице |
| **Управление** | Обычно через инфраструктуру (L7 Routing) | Обычно через код или SaaS-платформы |
| **Длительность** | Минуты / Часы | Дни / Недели |
| **Sticky Sessions** | Опциональны | Обязательны |
| **Decision Maker** | Автоматический (SRE Judge) | Продуктовая команда / бизнес-гейтинг |

Подробное сравнение: **[Канареечное развертывание](./canary_deployment.md)**.

### См. также

- **[Сравнение стратегий развертывания](./comparison.md)** — матрица выбора стратегий.
- **[Канареечное развертывание](./canary_deployment.md)** — Nginx/HAProxy/Traefik, Argo Rollouts, CI-автоматизация.
- **[Теневое развертывание](./shadow_deployment.md)** — GoReplay, Envoy, Nginx mirror, eBPF/tc mirred.
- **[Развертывание в традиционной инфраструктуре](./traditional_infrastructure.md)** — Bare Metal/VM, ZTP, Packer, Ansible, Immutable Infrastructure.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — пробы, архитектура отката, артефакты RCA.
- **[Мониторинг и оценка трафика при Canary](./canary_monitoring_and_gating.md)** — глубокий анализ метрик, PromQL и паттерн Baseline.
- **[Обзор Feature Toggles](../Testing/feature_toggles/overview.md)** — глубокое погружение в флаги.
- **[Gateway API: Маршрутизация](../../Kubernetes/Networking/gateway_api/routing_features.md)** — возможности L7.
- **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)** — обратно-совместимые миграции баз данных.
- **[OpenFeature SDK](https://openfeature.dev)** — открытый стандарт управления флагами.

## Интеграция с GitLab CI/CD

### Полный пайплайн A/B тестирования через Gateway API

```yaml
stages:
  - build
  - deploy_ab
  - verify
  - analyze

build_image:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_ab_variants:
  stage: deploy_ab
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/deployment-ab-v1.yaml
    - kubectl apply -f k8s/deployment-ab-v2.yaml
    - kubectl apply -f k8s/httproute-ab.yaml
  environment:
    name: ab-test
    url: https://app.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

verify_routing:
  stage: verify
  image: curlimages/curl:8.22.0
  needs:
    - deploy_ab_variants
  script:
    - |
      # Проверка, что вариант B получает трафик по cookie
      code=$(curl -s -o /dev/null -w "%{http_code}" -H "Cookie: ab_test=v2" https://app.example.com/healthz)
      [ "$code" = "200" ] || { echo "Variant B not reachable"; exit 1; }
      # Проверка контрольной группы
      code_ctrl=$(curl -s -o /dev/null -w "%{http_code}" https://app.example.com/healthz)
      [ "$code_ctrl" = "200" ] || { echo "Control group not reachable"; exit 1; }
  environment:
    name: ab-test

analyze_ab:
  stage: analyze
  image: curlimages/curl:8.22.0
  needs:
    - verify_routing
  script:
    - |
      # Проверка guardrail-метрик (технических)
      V2_ERRORS=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{version='v2',status=~'5..'}[5m]))/sum(rate(http_requests_total{version='v2'}[5m]))" | jq '.data.result[0].value[1]')
      V2_LATENCY=$(curl -s "http://prometheus:9090/api/v1/query?query=histogram_quantile(0.95,sum(rate(http_request_duration_seconds_bucket{version='v2'}[5m]))by(le))" | jq '.data.result[0].value[1]')
      echo "V2 errors: $V2_ERRORS, latency p95: $V2_LATENCY"
      if (( $(echo "$V2_ERRORS > 0.01" | bc -l) )); then
        echo "FAIL: V2 error rate exceeded threshold"
        exit 1
      fi
```

### A/B через HAProxy ACL (традиционная инфраструктура)

```yaml
ab_haproxy:
  stage: deploy_ab
  image: alpine:3.24
  before_script:
    - apk add --no-cache openssh-client socat
  script:
    - scp haproxy/ab.cfg deploy@lb:/etc/haproxy/haproxy.cfg
    - ssh deploy@lb "haproxy -c -f /etc/haproxy/haproxy.cfg && systemctl reload haproxy"
    - echo "show stat" | socat stdio /var/run/haproxy.sock | grep app_servers
  environment:
    name: ab-test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Откат A/B через Kill Switch

```yaml
kill_switch_ab:
  stage: rollback
  image: bitnami/kubectl:1.37
  script:
    # Удаляем variant B из маршрутизации — весь трафик идет на v1
    - kubectl patch httproute/ab-test --type=json -p='[
        {"op": "replace", "path": "/spec/rules/0/backendRefs/0/weight", "value": 100},
        {"op": "replace", "path": "/spec/rules/0/backendRefs/1/weight", "value": 0}
      ]'
    - kubectl scale deployment/ab-v2 --replicas=0
  environment:
    name: ab-test
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### A/B с Feature Flags (OpenFeature) в GitLab CI

```yaml
deploy_feature_flag:
  stage: deploy_ab
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/deployment-ab-v1.yaml
    # Флаг выключен — v2 код присутствует, но неактивен
    - kubectl set env deployment/ab-v1 NEW_CHECKOUT_FLAG=false
  environment:
    name: ab-test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

enable_flag_v2:
  stage: promote
  image: curlimages/curl:8.22.0
  needs:
    - deploy_feature_flag
  script:
    - curl -X POST https://unleash.internal/api/features/new-checkout/enable \
        -H "Authorization: Bearer $UNLEASH_API_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"strategies":[{"name":"gradualRolloutUserId","parameters":{"percentage":10}}]}'
  environment:
    name: ab-test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

## Совет по собеседованию

**Вопрос:** Почему A/B тестирование сложнее Canary-релиза с технической точки зрения?

**Ответ:** A/B тестирование требует гораздо более длительного сосуществования версий в Production. Это заставляет команду поддерживать обратную совместимость базы данных и API в течение недель, а не минут. Кроме того, требуется интеграция с системами бизнес-аналитики и обеспечение "липкости" сессий, что усложняет конфигурацию L7-маршрутизации.
