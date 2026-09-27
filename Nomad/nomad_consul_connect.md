# Nomad — Consul Connect (Service Mesh)

## Определения

**Consul Connect** — компонент Consul, реализующий Service Mesh с автоматическим mTLS-шифрованием, авторизацией трафика через Intentions и маршрутизацией на уровне L7. Работает как в Kubernetes, так и с Nomad через sidecar-прокси Envoy.

**Sidecar Proxy (Envoy)** — прокси-сервер, запускаемый рядом с каждой задачей Nomad. Перехватывает весь входящий и исходящий трафик, обеспечивая шифрование, балансировку и политики без изменений кода приложения.

**Transparent Proxy** — режим, при котором трафик перехватывается на уровне ОС (iptables/eBPF) и автоматически направляется в Envoy, устраняя необходимость настройки приложениями.

**Intention** — политика авторизации в Consul Connect, определяющая, какие сервисы могут общаться друг с другом (L4/L7 правила).

**Mesh Gateway** — компонент для межкластерного трафика между сервисами в разных дата-центрах или кластерах.

## Основные концепции

### Архитектура Connect в Nomad

```
┌─────────────────────────────────────────────┐
│                Nomad Client                  │
│                                              │
│  ┌──────────┐    ┌──────────┐               │
│  │  Task A   │    │  Task B   │              │
│  │ (webapp)  │    │ (api)     │              │
│  └────┬─────┘    └────┬─────┘               │
│       │                │                     │
│  ┌────┴─────┐    ┌────┴─────┐               │
│  │  Envoy   │    │  Envoy   │               │
│  │ (sidecar)│◄──►│ (sidecar)│               │
│  └────┬─────┘    └────┬─────┘               │
│       │                │                     │
│       └───────┬────────┘                     │
│               │                              │
│         ┌─────┴─────┐                       │
│         │  Consul    │                       │
│         │  Agent     │                       │
│         └───────────┘                       │
└─────────────────────────────────────────────┘
```

### Сравнение: Nomad с Connect vs без Connect

| Критерий | Без Connect | С Connect |
| :--- | :--- | :--- |
| **Шифрование** | TLS на уровнеceptor | mTLS между каждой парой сервисов |
| **Авторизация** | ACL на уровне Nomad | Intentions между сервисами |
| **Балансировка** | На уровне Nomad service | L7-балансировка в Envoy |
| **Observability** | Базовые метрики | Distributed tracing, L7-метрики |
| **Маршрутизация** | DNS-based | Traffic splitting, mirroring |

### Жизненный цикл задачи Nomad с Connect

1. **Регистрация сервиса** — Nomad регистрирует задачу в Consul.
2. **Получение сертификатов** — Envoy запрашивает mTLS-сертификаты у Consul CA.
3. **Запуск sidecar** — Nomad запускает Envoy как отдельную задачу в группе.
4. **Перехват трафика** — Envoy перехватывает входящий/исходящий трафик.
5. **Проверка Intentions** — Consul проверяет политики авторизации.
6. **Маршрутизация** — Envoy направляет трафик к целевому сервису.

## Практические сценарии

### Сценарий 1: Базовая интеграция Connect с Nomad

**Предусловия:**
- Consul кластер с включённым Connect.
- Nomad кластер с включённым Consul integration.

**Конфигурация Nomad-джоба:**
```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "app" {
    count = 3

    network {
      port "http" { to = 8080 }
    }

    service {
      name = "webapp"
      port = "http"
      provider = "consul"

      connect {
        sidecar_service {
          proxy {
            upstreams {
              destination_name = "api"
              local_bind_port  = 9090
            }
          }
        }
      }
    }

    task "server" {
      driver = "docker"
      config {
        image = "registry/webapp:v2"
        ports = ["http"]
      }
    }
  }
}
```

**Валидация:**
```bash
nomad job run webapp.nomad.hcl

# Проверка регистрации в Consul
curl http://consul.service.consul:8500/v1/catalog/service/webapp

# Проверка Connect-сервисов
curl http://consul.service.consul:8500/v1/catalog/service/webapp?connect=true
```

### Сценарий 2: Intentions (авторизация трафика)

**Создание политик через Consul:**

```bash
# Разрешить webapp → api
consul intention create webapp api

# Запретить webapp → database
consul intention create -deny webapp database

# Просмотр intentions
consul intention list
```

**Более детальные правила (L7):**

```bash
# Разрешить только GET-запросы к /api/v1
consul intention create -allow webapp api \
  --http-method GET \
  --http-path /api/v1/*
```

### Сценарий 3: Transparent Proxy

Включение прозрачного проксирования для автоматического перехвата трафика:

```hcl
service {
  name = "webapp"
  port = "http"
  provider = "consul"

  connect {
    sidecar_service {
      proxy {
        transparent_proxy {
          outbound_listener_port = 15001
        }
      }
    }
  }
}
```

Приложения обращаются друг к другу по DNS-именам без знания о прокси:
```bash
# webapp обращается к api через DNS
curl http://api.service.consul:8080/data
# Трафик автоматически проходит через Envoy
```

### Сценарий 4: Mesh Gateway для multi-DC

```hcl
# Конфигурация Mesh Gateway в Nomad
service {
  name = "mesh-gateway"
  port = "443"
  provider = "consul"

  connect {
    sidecar_service {}
  }

  meta {
    gateway-kind = "mesh"
  }
}
```

```bash
# Создание peerings между DC
consul peering generate-token -peer=dc2
consul peering establish -peering-token=<token> -peer=dc2
```

### Сценарий 5: Traffic Splitting (Canary через Connect)

```hcl
# service-splitter в Consul (через API или Terraform)
# 90% трафика на v1, 10% на v2
```

```bash
# Через Consul API
curl --request PUT --data '{
  "Kind": "service-splitter",
  "Name": "api",
  "Splitter": {
    "Splits": [
      {
        "Weight": 90,
        "ServiceSubset": "v1"
      },
      {
        "Weight": 10,
        "ServiceSubset": "v2"
      }
    ]
  }
}' http://consul.service.consul:8500/v1/config/service-splitter/api
```

## Диагностика

```bash
# Проверка Connect-сервисов
consul catalog services -connect

# Проверка intentions
consul intention check webapp api

# Проверка сертификатов
consul connect ca list-roots

# Логи Envoy sidecar
nomad alloc logs <alloc-id> connect-proxy-service
```

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `connection refused` | Envoy не запущен или не настроен | Проверьте логи sidecar-задачи |
| `unauthorized` | Intention запрещает трафик | Проверьте `consul intention list` |
| `certificate error` | Неверная CA или срок действия | Обновите сертификаты: `consul connect ca set-config` |
| `upstream not found` | Сервис не зарегистрирован в Consul | Проверьте `consul catalog services` |

## Дополнительная информация

- [Consul Service Mesh (Connect)](../Consul/consul_service_mesh.md) — полная теория Connect.
- [Nomad — определения и базовые концепции](./definitions_and_concepts.md) — основы Nomad.
- [Nomad — Security Hardening](./nomad_security_hardening.md) — настройка mTLS.
