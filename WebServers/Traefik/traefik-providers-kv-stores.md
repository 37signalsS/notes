# Провайдеры конфигурации: Consul, etcd, Redis, ZooKeeper

## Определения

**Provider** — источник **динамической** конфигурации (роутеры, сервисы, middleware), из которого Traefik читает данные: файлы, Docker/Kubernetes API, KV-хранилища (Consul, etcd, Redis, ZooKeeper), Nomad, Consul Catalog.

**KV Provider** — провайдер, читающий конфигурацию из распределённого key-value хранилища. Traefik **подписан** на изменения и применяет их в рантайме.

**Root Key** — корневой ключ в KV-хранилище, под которым лежит конфигурация Traefik (по умолчанию `traefik`).

**Static vs Dynamic** — провайдеры работают только с *динамической* частью (роутеры/сервисы/middlewares). Конфигурация самого Traefik (`providers.consul`, порты, entrypoints) задаётся статически: флагами CLI, файлом, переменными окружения или в самом KV-хранилище (через `providers.consul` в static).

## Базовые концепции

### Как это работает

1. В KV-хранилище создаётся дерево ключей под `rootKey/`:
   ```
   traefik/http/routers/app/rule=Host(`app.example.com`)
   traefik/http/routers/app/service=api@file   (или другой провайдер)
   traefik/http/routers/app/entryPoints[]=websecure
   traefik/http/services/api/loadBalancer/servers[]/url=http://1.2.3.4:80
   ```
2. Traefik (в составе провайдера) следит за изменениями (`watch` по умолчанию) и применяет дельту.
3. Схема - та же, что у File/Docker провайдеров, но в виде пар «ключ=значение».

Форматы значений: обычные строки (правила — одинарные кавычки), `[]` (список), вложенные ключи. Пример для Consul (consul KV):

```
consul kv put traefik/http/routers/app/rule "Host(\`app.example.com\`)"
consul kv put traefik/http/routers/app/service api@file
consul kv put traefik/http/services/api/loadBalancer/servers/0/url "http://1.2.3.4:80"
```

### Общие опции провайдеров KV

| Опция | Значение | По умолчанию |
| :--- | :--- | :--- |
| `rootKey` | Корневой ключ структуры | `traefik` |
| `endpoint(s)` | Адрес хранилища | `127.0.0.1:xxx` |
| `username` / `password` | Аутентификация (Consul: ACL token; etcd: basic auth) | — |
| `tls` (`ca`, `cert`, `key`, `insecureSkipVerify`, `serverName`) | TLS к хранилищу | — |
| `watch` | Слушать изменения | `true` |
| `defaultRule` | Правило для сервисов без явного `rule` (шаблон) | `Host(name)` |
| `token` | токен Consul ACL / etcd auth | — |
| `namespace` | (Nomad) | — |

### Провайдеры

**Consul**:

```yaml
providers:
  consul:
    endpoint: "127.0.0.1:8500"
    rootKey: traefik
    watch: true
```

**etcd**:

```yaml
providers:
  etcd:
    endpoints: ["http://127.0.0.1:2379"]
    rootKey: traefik
```

**Redis (v3 Redis 5+)**: ключи вида `traefik:<path>` (через `rootKey`), значение = JSON; с `providers.redis`.

**ZooKeeper**:

```yaml
providers:
  zookeeper:
    endpoint: "127.0.0.1:2181"
    rootKey: traefik
```

### Разница с Consul Catalog

`providers.consul` — это мини-провайдер KV (чтение роутеров/сервисов). `providers.consulCatalog` — провайдер «сообрази» про сервисы (L4 net), авто-построение трафика из зарегистрированных сервисов. Они не взаимозаменяемы: для маршрутизации поднимается KV-провайдер; для discovery сервисов с автоматическими роутерами — consulCatalog.

## Практические сценарии

### Сценарий 1: KV-конфиг всего сайта (Consul)

```bash
# Статика: providers.consul.endpoint=127.0.0.1:8500
consul kv put traefik/http/routers/frontend/rule "Host(\`front.example.com\`)"
consul kv put traefik/http/routers/frontend/entryPoints[] websecure
consul kv put traefik/http/routers/frontend/service frontal
consul kv put traefik/http/services/frontal/loadBalancer/servers/0/url "http://10.0.0.21:8080"
```

### Сценарий 2: etcd — базовый (с auth)

```bash
# Кластер etcd, endpoints, user/pass — см. статику
etcdctl --user rd --password x put traefik/http/routers/app/rule `Host(`app.example.com`)`
```

### Сценарий 3: Redis провайдер

Структура (ключи с путями и JSON-значениями):

```
redis-cli SET traefik.http.routers.app.rule "Host(\`app.example.com\`)"
redis-cli SET traefik.http.services.api.loadBalancer.servers.0.url "http://api:8080"
```

(В Redis провинность значений проще хранить как строки и расставлять точки — индексы тоже строки.)

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Роутеры не появились** | Неверный `rootKey` / префикс ключей | Проверьте точные имена ключей в KV; prefix `<rootKey>/` |
| **Провайдер падает при старте** | Недоступно хранилище, неверный endpoint/порт | Проверьте доступность, TLS, ACL | 
| **Дельты не применяются** | `watch: false` или нет прав | Включите `watch`; проверьте права ACL |
| **Конфликт с другим провайдером** | Два источника задают один name роутера | Удалите дубликаты; при необходимости разделите `rootKey` |

## Рекомендации

- KV-провайдеры — только для централизованного управления роутерами/сервисами в кластере или когда конфиг меняется часто.
- Защищайте хранилище: TLS, аутентификация (ACL-токены/пароли), ограниченные права на `rootKey` для Traefik.
- Схема в KV = та же, что в YAML; регулярно валидируйте наборы ключей скриптом `consul kv get`/`etcdctl get --prefix`.
- Держите `rootKey` читабельным и задокументированным в команде (сложный для производительности паттерн — длинные цепочки вложенных ключей).
- Для изменений вне провайдера — перезапустите/reload Traefik (зависит от `watch`), если надо применить сразу.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — разделы про провайдеры и статическую конфигурацию.
- [Consul KV store](../../Consul/consul_kv_store.md) — общая работа с KV Consul, ACL.
- [Файловая конфигурация Traefik (FIFO/templates)](./traefik_with_docker_compose.md) — альтернативный способ.
- [etcd: ключи и кластер](../../etcd/etcdctl_cheatsheet.md) — основы работы с etcd-ключами.