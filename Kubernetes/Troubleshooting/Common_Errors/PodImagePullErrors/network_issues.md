# Ошибки загрузки образов (Image Pull Errors): Сетевые проблемы

## Определения

**Сетевые проблемы (в контексте Image Pull)** — класс ошибок, при которых агент `kubelet` не может установить соединение с реестром образов (Registry) из-за некорректной настройки DNS, блокировок Firewall, отсутствия параметров Proxy, проблем с TLS-сертификатами или ограничений NetworkPolicy.

**Rate Limiting** — механизм ограничения частоты запросов к реестру (например, Docker Hub). При превышении лимита реестр возвращает ошибку `toomanyrequests`.

**NetworkPolicy** — объект Kubernetes, определяющий правила прохождения трафика между подами и внешними ресурсами. В контексте загрузки образов важны правила Egress (исходящий трафик).

---

## Основные концепции

### Классификация сетевых проблем

| Категория | Симптом в событиях (Events) | Корневая причина |
| :--- | :--- | :--- |
| **DNS** | `dial tcp: lookup registry.example.com: no such host` | Ошибка в `/etc/resolv.conf`, недоступность DNS-сервера |
| **Firewall** | `connection timed out` | Порт 443 заблокирован на сетевом оборудовании или узле |
| **Proxy** | `connection refused`, `proxy error` | Не настроены переменные `HTTP_PROXY` / `HTTPS_PROXY` для среды выполнения |
| **TLS** | `x509: certificate signed by unknown authority` | Self-signed сертификат реестра не добавлен в доверенные на узле |
| **Rate Limit** | `toomanyrequests: pull rate limit exceeded` | Превышен лимит анонимных скачиваний с Docker Hub |
| **NetworkPolicy** | `dial tcp <ip>:443: i/o timeout` | Правила Egress блокируют доступ пода к реестру |

### Настройки Proxy для среды выполнения

Важно учитывать, что `kubelet` и контейнерный рантайм (containerd/docker) игнорируют системные переменные окружения пользователя. Настройки должны быть заданы в конфигурации соответствующих системных служб.

---

## Практические сценарии

### Сценарий 1: Диагностика соединения с узла

Если в событиях пода наблюдаются таймауты или ошибки DNS, проверьте доступность реестра напрямую с проблемного узла:

```bash
# Проверка разрешения имени
nslookup registry.example.com
# → Server: 127.0.0.53, Address: 127.0.0.53#53, Non-authoritative answer: Name: registry.example.com...

# Проверка доступности порта реестра
curl -v telnet://registry.example.com:443
# → * Connected to registry.example.com (IP) port 443 (#0)

# Проверка TLS-сертификата
curl -v https://registry.example.com/v2/
# → HTTP/1.1 200 OK (или 401 Unauthorized, что подтверждает сетевую связность)
```

### Сценарий 2: Настройка Proxy для kubelet (Systemd)

Создайте drop-in файл для настройки прокси-сервера:

```ini
# /etc/systemd/system/kubelet.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:3128"
Environment="HTTPS_PROXY=http://proxy.example.com:3128"
Environment="NO_PROXY=localhost,127.0.0.1,.cluster.local"
```

Примените изменения:

```bash
systemctl daemon-reload
systemctl restart kubelet
# → (перезапуск службы kubelet)
```

### Сценарий 3: Настройка NetworkPolicy для доступа к реестру

Если в кластере используется политика "deny-all" по умолчанию, необходимо явно разрешить исходящий трафик к реестру:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-registry-egress
  namespace: my-namespace
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 1.2.3.4/32  # IP адрес вашего реестра
    ports:
    - protocol: TCP
      port: 443
```

Проверка применения политики:

```bash
kubectl describe networkpolicy allow-registry-egress -n my-namespace
# → Name: allow-registry-egress, Namespace: my-namespace, ... Egress rules: ...
```

---

## Дополнительная информация

### Связанные темы

- [Пошаговая диагностика](./diagnostics.md) — общий алгоритм поиска причин ошибок.
- [Air-gapped кластеры](./airgapped.md) — работа в полностью изолированных средах.
- [Best Practices: NetworkPolicy](../../../Networking/Network/NetworkPolicy/best_practices.md) — общие рекомендации по сетевой безопасности.
