# Pod Image Pull Errors: Сетевые проблемы

## 4. Сетевые проблемы

**Сообщение:**

```
dial tcp: lookup registry.example.com: no such host
connection timed out
x509: certificate signed by unknown authority
```

**Причины и решения:**

| Проблема | Диагностика | Решение |
|----------|-------------|---------|
| **DNS** | `nslookup registry.example.com` | Исправить DNS настройки узла |
| **Firewall** | `telnet registry.example.com 443` | Открыть порт, добавить whitelist |
| **Proxy** | Проверить env vars | Настроить `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` |
| **Self-signed cert** | `curl -v https://registry` | Добавить CA cert в доверенные на узлах |

### Настройка proxy для kubelet

```ini
# /etc/systemd/system/kubelet.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:3128"
Environment="HTTPS_PROXY=http://proxy.example.com:3128"
Environment="NO_PROXY=localhost,127.0.0.1,.cluster.local"
```

### Настройка для containerd

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".registry.mirrors."registry.example.com"]
  endpoint = ["http://proxy-registry.internal:5000"]
```

## 5. Rate Limiting (Docker Hub)

**Сообщение:**

```
toomanyrequests: You have reached your pull rate limit.
```

**Причина:** Docker Hub ограничивает количество скачиваний для анонимных и бесплатных аккаунтов.

**Решение:**

| Вариант | Описание |
|---------|----------|
| **Аутентификация** | `imagePullSecrets` увеличивает лимит |
| **Локальный mirror** | Развернуть Harbor/Nexus как proxy-cache |
| **Переход на другой registry** | GCR, ECR, GHCR имеют лучшие лимиты |
| **Pre-pull образы** | Скачать образы на узлы заранее |

## 6. Проблемы с Network Policies

**Сообщение:**

```
connection timed out
dial tcp <ip>:443: i/o timeout
```

**Причина:** Network Policy блокирует исходящий трафик к registry.

**Диагностика:**

```bash
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <policy-name>
```

**Решение:**

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

> **См. также:** [`../../../Security/network_policies.md`](../../../Security/network_policies.md), [`../../../Security/network_policies/Calico/index.md`](../../../Security/network_policies/Calico/index.md)
