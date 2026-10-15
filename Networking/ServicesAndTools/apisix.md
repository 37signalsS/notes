# APISIX

**Актуально для:** Apache APISIX 3.x

Apache APISIX — это высокопроизводительный API-шлюз и веб-сервер на базе NGINX, который используется для управления API, маршрутизации трафика, аутентификации, ограничения скорости и других функций на уровне прокси. APISIX поддерживает динамическую конфигурацию через Admin API и интегрируется с Kubernetes через ingress-контроллер.

## Определения

- **Admin API** — RESTful API для управления конфигурацией APISIX (маршруты, upstream-ы, плагины, consumers). По умолчанию слушает порт 9180.
- **Control Plane API** — API для мониторинга и диагностики работы процесса APISIX (порт 9080).
- **Route (маршрут)** — правило маршрутизации, связывающее входящие HTTP-запросы с upstream-ом. Содержит `uri`, `upstream` и другие параметры.
- **Upstream** — определение бэкенд-сервиса (набор узлов), к которому маршруты отправляют запросы.
- **Consumer** — сущность, представляющая конечного пользователя API. Используется для аутентификации и применения политик доступа.
- **Plugin (плагин)** — расширение, добавляющее функциональность (аутентификация, rate limiting, JWT, JWT-аутентификация и др.).
- **ingress-apisix** — namespace, в котором разворачивается ingress-контроллер APISIX в Kubernetes.

## Архитектура и принцип работы

APISIX работает как обратный прокси на базе NGINX. Архитектура включает:

- **Data Plane** — обрабатывает клиентские запросы (порт 9080 для control plane API, порт 9080/9443 для прокси).
- **Admin API** — управляет конфигурацией (порт 9180 по умолчанию).
- **Хранилище конфигурации** — etcd (в продакшене) или in-memory (в dev-режиме).

Маршрутизация работает по правилам: клиент → APISIX (Data Plane) → Upstream (бэкенд-сервис). Конфигурация загружается из etcd и может обновляться динамически через Admin API или CLI-утилиту `apisix`.

## Практические сценарии

### Управление маршрутами

Маршрут связывает URI входящего запроса с upstream-ом. Создаётся через Admin API:

```bash
# Создать маршрут с round-robin upstream
curl -X PUT http://apisix-admin:9180/apisix/admin/routes/1 \
  -H "X-API-KEY: $ADMIN_KEY" \
  -d '{"uri":"/api/*","upstream":{"nodes":{"backend:8080":1},"type":"roundrobin"}}'
```

Просмотр всех маршрутов:

```bash
# Список маршрутов (форматированный вывод через jq)
curl -s http://apisix:9180/apisix/admin/routes \
  -H 'X-API-KEY: <key>' \
  | jq '.list[].value | {id:.id, uri:.uri, upstream:.upstream.nodes}'

# Список маршрутов (сырой вывод)
curl http://apisix-admin:9180/apisix/admin/routes \
  -H "X-API-KEY: $ADMIN_KEY"
```

Просмотр конкретного маршрута по ID:

```bash
curl -s http://apisix:9180/apisix/admin/routes/<id> \
  -H 'X-API-KEY: <key>' \
  | jq .
```

### Управление upstream-ами

Upstream определяет бэкенд-сервисы, к которым APISIX отправляет запросы:

```bash
# Список всех upstream с нодами (форматированный вывод)
curl -s http://apisix:9180/apisix/admin/upstreams \
  -H 'X-API-KEY: <key>' \
  | jq '.list[].value | {id:.id, nodes:.nodes}'

# Список upstream-ов (сырой вывод)
curl http://apisix-admin:9180/apisix/admin/upstreams \
  -H "X-API-KEY: $ADMIN_KEY"
```

### Плагины

Плагины добавляют функциональность к маршрутам и consumers. Список доступных плагинов:

```bash
# Список плагинов (форматированный вывод)
curl -s http://apisix:9180/apisix/admin/plugins/list \
  -H 'X-API-KEY: <key>' \
  | jq .

# Список плагинов (сырой вывод)
curl http://apisix-admin:9180/apisix/admin/plugins/list \
  -H "X-API-KEY: $ADMIN_KEY"
```

Включение плагина rate limiting (`limit-req`) на существующий маршрут:

```bash
curl -X PATCH http://apisix-admin:9180/apisix/admin/routes/1 \
  -H "X-API-KEY: $ADMIN_KEY" \
  -d '{"plugins":{"limit-req":{"rate":100,"burst":50,"key":"remote_addr"}}}'
```

### Аутентификация

Создание consumer с key-аутентификацией:

```bash
curl -X PUT http://apisix-admin:9180/apisix/admin/consumers/myuser \
  -H "X-API-KEY: $ADMIN_KEY" \
  -d '{"plugins":{"key-auth":{"key":"user-api-key"}}}'
```

Включение JWT-аутентификации на маршруте через Admin API:

```bash
curl -X PATCH http://apisix-admin:9180/apisix/admin/routes/1 \
  -H "X-API-KEY: $ADMIN_KEY" \
  -d '{"plugins":{"jwt-auth":{"header":"Authorization","query":"jwt"}}}'
```

Для включения JWT-аутентификации также можно добавить `jwt-auth` в секцию `plugins` конфигурации маршрута или consumer.

### Перезагрузка конфигурации

Горячая перезагрузка конфигурации из etcd без даунтайма:

```bash
# Через Admin API
curl -X PUT http://apisix:9180/apisix/admin/configs/reload \
  -H 'X-API-KEY: <key>'

# Через CLI
apisix reload
```

## Мониторинг и диагностика

Проверка здоровья процесса APISIX через Control Plane API:

```bash
curl -s http://apisix:9080/apisix/status | jq .
```

Проверка статуса подов APISIX в Kubernetes (namespace `ingress-apisix` по умолчанию):

```bash
kubectl get pods -n ingress-apisix
```

## Best Practices

- **Храните Admin API key в секретах Kubernetes**, а не в открытом виде в скриптах.
- **Используйте HTTPS** для Admin API в продакшене; по умолчанию Admin API доступен только локально.
- **Применяйте `apisix reload`** вместо перезапуска сервиса для нулевого простоя при обновлении конфигурации.
- **Ограничивайте доступ к Admin API** через сетевые политики (NetworkPolicy) и firewall-правила.
- **Регулярно проверяйте** `apisix status` и `kubectl get pods -n ingress-apisix` для мониторинга состояния кластера.

## Дополнительная информация

- [Документация Apache APISIX](https://apisix.apache.org/docs/apisix/)
- [APISIX Ingress Controller](https://apisix.apache.org/docs/ingress-controller/)
- Источник команд: [cheatsheet.antonnovikov.com/apisix](https://cheatsheet.antonnovikov.com/apisix/)