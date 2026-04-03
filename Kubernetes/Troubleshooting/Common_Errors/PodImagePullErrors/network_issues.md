# Pod Image Pull Errors: Сетевые проблемы

## Определения

**Сетевые проблемы (в контексте image pull)** — класс ошибок, при которых `kubelet` не может подключиться к registry из-за проблем с DNS, firewall, proxy, TLS-сертификатами или NetworkPolicy.

**Rate Limiting** — механизм ограничения количества запросов к registry (например, Docker Hub) для предотвращения злоупотреблений. Превышение лимита вызывает ошибку `toomanyrequests`.

**NetworkPolicy** — объект Kubernetes, контролирующий входящий (ingress) и исходящий (egress) трафик подов на основе меток, IP-диапазонов и портов.

---

## Основные концепции

### Классификация сетевых проблем

| Категория | Симптом | Корневая причина |
| :--- | :--- | :--- |
| **DNS** | `dial tcp: lookup registry.example.com: no such host` | Некорректный `/etc/resolv.conf`, DNS-сервер недоступен |
| **Firewall** | `connection timed out` | Порт 443/80 заблокирован на уровне сети |
| **Proxy** | `connection refused`, `proxy error` | Не настроены `HTTP_PROXY`/`HTTPS_PROXY` для kubelet/containerd |
| **TLS** | `x509: certificate signed by unknown authority` | Self-signed сертификат registry не добавлен в доверенные |
| **Rate Limit** | `toomanyrequests: pull rate limit exceeded` | Превышен лимит pull-запросов Docker Hub |
| **NetworkPolicy** | `dial tcp <ip>:443: i/o timeout` | Egress-правила блокируют трафик к registry |

### Влияние proxy на image pull

Kubelet и containerd используют собственные настройки proxy — переменные окружения системы не применяются автоматически:

```
kubelet/containerd
    ↓
Читает proxy из systemd unit drop-in
    ↓
Применяет HTTP_PROXY/HTTPS_PROXY при pull
    ↓
NO_PROXY исключает внутренний трафик (cluster.local, localhost)
```

### Docker Hub Rate Limits

| Тип аккаунта | Лимит pull | Период |
| :--- | :--- | :--- |
| **Anonymous** | 100 | 6 часов |
| **Authenticated (free)** | 200 | 6 часов |
| **Pro/Team** | Без ограничений | — |

Лимит считается по IP-адресу. Аутентификация через `imagePullSecrets` увеличивает лимит до 200 pull/6ч.

---

## Практические сценарии

### Сценарий 1: Диагностика DNS, Firewall и TLS

**Сообщение:**

```
dial tcp: lookup registry.example.com: no such host
connection timed out
x509: certificate signed by unknown authority
```

**Диагностика и решение:**

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **DNS** | `nslookup registry.example.com` с узла | Исправить `/etc/resolv.conf`, проверить DNS-сервер |
| **Firewall** | `curl -v telnet://registry.example.com:443` | Открыть порт 443, добавить в whitelist |
| **Proxy** | Проверить env vars kubelet/containerd | Настроить `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` |
| **Self-signed cert** | `curl -v https://registry.example.com/v2/` | Добавить CA cert в доверенные на всех узлах |

### Сценарий 2: Настройка proxy для kubelet

```ini
# /etc/systemd/system/kubelet.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:3128"
Environment="HTTPS_PROXY=http://proxy.example.com:3128"
Environment="NO_PROXY=localhost,127.0.0.1,.cluster.local"
```

**Применение изменений:**

```bash
systemctl daemon-reload
systemctl restart kubelet
```

### Сценарий 3: Настройка proxy для containerd

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".registry.mirrors."registry.example.com"]
  endpoint = ["http://proxy-registry.internal:5000"]
```

**Применение изменений:**

```bash
systemctl restart containerd
```

### Сценарий 4: Rate Limiting Docker Hub

**Сообщение:**

```
toomanyrequests: You have reached your pull rate limit.
```

**Решение:**

| Вариант | Описание |
| :--- | :--- |
| **Аутентификация** | Создать `imagePullSecrets` — увеличивает лимит до 200/6ч |
| **Локальный mirror** | Развернуть Harbor/Nexus как proxy-cache registry |
| **Переход на другой registry** | GCR, ECR, GHCR имеют лучшие лимиты |
| **Pre-pull образов** | Скачать образы на узлы заранее (cron, init-скрипт) |

### Сценарий 5: Проблемы с Network Policies

**Сообщение:**

```
connection timed out
dial tcp <ip>:443: i/o timeout
```

**Причина:** NetworkPolicy блокирует исходящий трафик подов к registry.

**Диагностика:**

```bash
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <policy-name>
```

**Решение — разрешение egress-трафика к registry:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-registry-access
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: <registry-ip>/32
    ports:
    - protocol: TCP
      port: 443
```

**Диагностика DNS из pod:**

```bash
kubectl run dns-test --image=busybox:1.28 --rm -it --restart=Never -- nslookup registry.example.com
```

---

## Дополнительная информация

### Связанные темы

- Определения и базовые концепции: [Definitions](./definitions.md)
- Пошаговая диагностика: [Diagnostics](./diagnostics.md)
- Air-gapped кластеры (нет доступа к интернету): [Air-gapped](./airgapped.md)
- Rate limiting Docker Hub: [Definitions](./definitions.md#rate-limiting-docker-hub)
- NetworkPolicy best practices: [NetworkPolicy Best Practices](../../../Networking/Network/NetworkPolicy/best_practices.md)
