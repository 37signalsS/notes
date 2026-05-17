# NetworkPolicy: Лучшие Практики

## Определения

**Лучшие практики NetworkPolicy** — проверенные рекомендации по безопасному и эффективному внедрению сетевой изоляции в Kubernetes.

## Базовые Концепции

### Принцип минимальных привилегий

Следуйте принципу **минимальных привилегий**: разрешайте только тот трафик, который необходим для работы приложений.

## Практические Сценарии

### 1. Начинайте с Default Deny

Всегда начинайте с политики, которая блокирует весь трафик для неймспейса, а затем явно разрешайте необходимый:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress: []
```

*Подробнее: [Типовые политики](./definitions.md#типовые-политики-allow-all-и-deny-all)*

### 2. Разрешайте системный трафик

Всегда явно разрешайте Egress-трафик к DNS и API Server:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

### 3. Используйте NamespaceSelector

Для контроля доступа между неймспейсами используйте `namespaceSelector` — это надежнее, чем `ipBlock`:

- `namespaceSelector` работает с метками namespace
- `ipBlock` требует знания CIDR и не учитывает динамические изменения

### 4. Поддерживайте дисциплину меток

NetworkPolicy сильно зависят от корректных меток:

- Используйте согласованную схему именования меток
- Документируйте обязательные метки для каждого типа workload
- Автоматизируйте проверку наличия меток через Admission Controllers

### 5. Тестируйте связность

Используйте временные поды для проверки политик:

```bash
# Тестирование ingress
kubectl run test-curl --rm -it --image=curlimages/curl -- curl -v http://<service>:<port>

# Тестирование egress
kubectl run test-dig --rm -it --image=registry.k8s.io/dnsutils:1.3 -- dig <service>.<namespace>.svc.cluster.local

# Тестирование блокировки
kubectl run test-nc --rm -it --image=busybox -- nc -zv <target-ip> <port>
```

### 6. Виртуальный патчинг (Virtual Patching)

Сетевые политики (в особенности L7-Firewall, доступные в продвинутых CNI типа Cilium или в Service Mesh) можно использовать для «виртуального патчинга». Если в приложении найдена критическая уязвимость (например, RCE на конкретном эндпоинте), вы можете временно заблокировать этот маршрут с помощью сетевых политик, пожертвовав частью функционала, но предотвратив развитие атаки до выхода официального патча.

### 7. Используйте логирование

Некоторые CNI (например, Calico) позволяют логировать заблокированный трафик:

```yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: log-deny-all
spec:
  selector: all()
  types:
  - Ingress
  - Egress
  ingress:
  - action: Log
    protocol: TCP
  egress:
  - action: Log
    protocol: TCP
```

## Дополнительные Сведения

### Реализация CNI-плагинами

NetworkPolicy работает только при наличии CNI с поддержкой этой функциональности:

- **Calico, Cilium, Weave Net** — полная поддержка + расширения
- **Flannel** — не поддерживает NetworkPolicy
- **Kube-router, Antrea** — полная поддержка

*Подробнее: [Реализация CNI](./cni_implementation.md)*

### Визуализация и отладка

Для проверки политик рекомендуется использовать:

- [Orca Turfin](https://orca-tufin.com/) — визуализация YAML в графическое представление
- `kubectl get networkpolicy` — просмотр применённых политик
- `kubectl describe networkpolicy <name>` — детальная информация

*Подробнее: [Определения и структура](./definitions.md)*  
*Подробнее: [Логика правил](./rule_logic.md)*  
*Подробнее: [Практический сценарий](./practical_scenarios.md)*  
*Подробнее: [Реализация CNI](./cni_implementation.md)*
